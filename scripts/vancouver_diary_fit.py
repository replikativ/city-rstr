"""Fit whole weekday diaries to Vancouver mode shares while retaining census strata."""
import argparse
from collections import Counter
from pathlib import Path
import shutil

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp, softmax

from scripts.artifacts import package, pointer, read, write_json
from scripts.vancouver_atlas import Weekday, sums
from scripts.vancouver_cityday import build as locate_weekday
from scripts.vancouver_city_transit import publish_riders
from scripts.vancouver_income_travel import BANDS, MODES, OBSERVED_2023, SOURCE_2023, roster_bands
from scripts.vancouver_mobility import mode_counts
from scripts.vancouver_street_walks import publish as index_streets

SEED = 20261122
PENALTY = 0.015
ACTIVITIES = ("paid-work", "study", "sleep")


def features(diary):
    counts = mode_counts(diary["episodes"])
    minutes = Counter()
    for _, duration, activity, _ in diary["episodes"]:
        minutes[activity] += duration
    return [*(counts[m] for m in MODES), *(minutes[a] / 60 for a in ACTIVITIES)]


def donor_probabilities(weekday, keys):
    result = {}
    for key in keys:
        indices, cdf = weekday.cdfs[key]
        result[key] = np.asarray(indices), np.diff(cdf, prepend=0) / cdf[-1]
    return result


def coupling(ids, prior, fitted):
    keep = dict(zip(ids,np.minimum(1,fitted/prior),strict=True))
    return ids,keep,np.cumsum(np.maximum(0,fitted-prior))


def draw(previous, pool, rng):
    ids,keep,replacement=pool
    if previous not in keep:
        raise ValueError("The original diary belongs to a different census stratum")
    if rng.random()<keep[previous]:
        return previous
    return int(ids[np.searchsorted(replacement,rng.random()*replacement[-1],side="right")])


def publish_atlas(root, directory, atlas, reassign):
    def stage(out):
        for da,area in atlas["das"].items():
            roster = read(directory/(da+".json"))
            reassign(da,roster)
            area["days"] = dict(Counter(p[7] for p in roster["people"]))
            write_json(out/(da+".json"),roster)
        atlas["city"] = sums(list(atlas["das"].values()))
        for area in atlas["areas"].values():
            area.update(sums([atlas["das"][da] for da in area["das"]]))
        shutil.copyfile(directory/"basemap.json",out/"basemap.json")
        write_json(out/"atlas.json",atlas)
    return package(root,"atlas",stage)


def fit_band(donors, weights, x, shares):
    pools = [(key, ids, prior, np.log(prior), x[ids], n / weights.total())
             for key, n in weights.items() for ids, prior in (donors[key],)]
    baseline = sum(w * (prior @ values) for _, _, prior, _, values, w in pools)
    target = baseline.copy()
    target[:5] = np.asarray(shares) * baseline[:5].sum() / sum(shares)

    def objective(tilt):
        loss = PENALTY * (tilt @ tilt) / 2 - target @ tilt
        gradient = PENALTY * tilt - target
        for _, _, _, log_prior, values, w in pools:
            logits = log_prior + values @ tilt
            normalizer = logsumexp(logits)
            loss += w * normalizer
            gradient += w * (np.exp(logits - normalizer) @ values)
        return loss, gradient

    fit = minimize(objective, np.zeros(x.shape[1]), jac=True, method="L-BFGS-B",
                   options={"gtol": 1e-8, "ftol": 1e-13})
    if not fit.success or np.linalg.norm(fit.jac, ord=np.inf) > 1e-5:
        raise ValueError("Whole-diary mode fit did not converge")
    projected = np.zeros_like(baseline)
    mixes = np.zeros((2, len(x)))
    sampling = {}
    for key, ids, prior, log_prior, values, w in pools:
        fitted = softmax(log_prior + values @ fit.x)
        projected += w * (fitted @ values)
        mixes[0, ids] += w * prior
        mixes[1, ids] += w * fitted
        sampling[key] = coupling(ids,prior,fitted)
    return sampling, dict(baseline=baseline.tolist(), fitted=projected.tolist(), target=target.tolist(),
                          effectiveDonors=(1 / np.sum(mixes**2, axis=1)).tolist())


def eligible(weekday, roster):
    bands = roster_bands(roster)
    for i, person in enumerate(roster["people"]):
        age, _, labour, _, school, *_ = person
        band = bands[i]
        if 3 <= age <= 13 and band < len(BANDS) and OBSERVED_2023[band] is not None:
            yield i, band, weekday.donor_key(age, labour, school), 2 if age == 3 else 5


def build(root, base, diary_path):
    directory = root / "atlas" / base
    atlas = read(directory / "atlas.json")
    diaries = [d for d in read(diary_path) if d["split"] == "fit"]
    weekday = Weekday(diaries)
    if weekday.templates != atlas["templates"]:
        raise ValueError("The fitted diary pool needs the exact atlas templates")
    x = np.asarray([features(diary) for diary in atlas["templates"]])
    weights = [Counter() for _ in BANDS]
    for da in atlas["das"]:
        roster = read(directory / (da + ".json"))
        for _, band, key, adult_fifths in eligible(weekday, roster):
            weights[band][key] += adult_fifths
    donors = donor_probabilities(weekday, set().union(*weights))

    sampling, reports = {}, {}
    for band, weights_by_key in enumerate(weights):
        if weights_by_key:
            sampling[band], reports[band] = fit_band(donors, weights_by_key, x, OBSERVED_2023[band])

    actual = {band: np.zeros((2, x.shape[1])) for band in reports}
    synthetic = Counter()

    def reassign(da,roster):
        people = roster["people"]
        rng = np.random.default_rng([SEED,int(da)])
        for i,band,key,adult_fifths in eligible(weekday,roster):
            old = people[i][7]
            new = draw(old,sampling[band][key],rng)
            people[i][7] = new
            synthetic[band] += old!=new
            actual[band][0] += adult_fifths*x[old]
            actual[band][1] += adult_fifths*x[new]

    fitted = publish_atlas(root,directory,atlas,reassign)
    for band, report in reports.items():
        report["assigned"] = dict(zip(("original", "fitted"), (actual[band]/weights[band].total()).tolist(), strict=True))
        report["adults"] = weights[band].total()/5
        report["changed"] = synthetic[band]
    data = dict(atlas=base, fittedAtlas=fitted, seed=SEED, penalty=PENALTY, source=SOURCE_2023,
                figure=55, units=[*MODES, *[a+" hours" for a in ACTIVITIES]], bands=BANDS, results=reports)
    print(fitted, f"{sum(synthetic.values()):,} resident diaries changed", flush=True)
    return data


def locate(root, archive, report, base_day):
    fitted = report["fittedAtlas"]
    original = root/"atlas"/report["atlas"]
    baseline = root/"cityday"/base_day
    streets = read(root/"streets"/"current.json")["version"]
    metadata = dict(kind=report.get("method","household-income"), baselineDay=base_day, baselineAtlas=report["atlas"],
                    fittedAtlas=fitted, source=report["source"], figure=report["figure"])

    def stage(out):
        locate_weekday(archive, root/"atlas"/fitted, out, paired=(original,baseline))
        day = read(out/"day.json")
        day["diaryFit"] = metadata
        write_json(out/"day.json", day)

    day = package(root, "cityday", stage, fitted)
    print("Paired city weekday", day, flush=True)
    versions = dict(atlas=fitted, day=day, streets=streets)
    index_streets(root, versions)
    return versions


def direct_schedule(root, archive, report, versions, base_day):
    family = root/"transit-riders"
    parents = (report["atlas"], base_day, versions["streets"])
    old = read(family/("_".join(parents)+".json"))
    if read(family/old["riders"]/"riders.json").get("transfers"):
        raise ValueError("The original timetable benchmark must use direct trips")
    fitted = publish_riders(archive, root, dict(versions, transit=old["transit"]))
    return schedule_evidence(root, old["riders"], fitted)


def schedule_evidence(root, original, fitted):
    family = root/"transit-riders"
    old, new = (read(family/release/"riders.json") for release in (original, fitted))
    if old["versions"]["transit"] != new["versions"]["transit"] or old["date"] != new["date"]:
        raise ValueError("The added timetable comparison uses different services")
    return dict(date=new["date"], timetable=new["versions"]["transit"],
                original=dict(riders=original, matched=old["matched"], bouts=old["total"]),
                fitted=dict(riders=fitted, matched=new["matched"], bouts=new["total"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("atlas")
    parser.add_argument("diaries", type=Path, help="Clojure atlas-diaries --income-comparison export")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--archive", type=Path, required=True, help="Spatial inputs used by the original weekday")
    parser.add_argument("--baseline-day", help="Original published weekday ID, defaulting to the current city weekday")
    args = parser.parse_args()
    current = read(args.root/"cityday"/"current.json")
    if args.baseline_day is None and current["atlas"] != args.atlas:
        parser.error("Pass the baseline weekday for the requested atlas")
    base_day = args.baseline_day or current["version"]
    report = build(args.root, args.atlas, args.diaries)
    versions = locate(args.root, args.archive, report, base_day)
    scheduled = direct_schedule(args.root, args.archive, report, versions, base_day)
    pointer(args.root/"diary-fit"/(versions["atlas"]+".json"), dict(report, locations=versions, scheduled=scheduled))

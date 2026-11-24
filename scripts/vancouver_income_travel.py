"""Compare daily travel modes by household income with the 2022 Vancouver survey."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from scripts.artifacts import package, pointer, read, write_json
from scripts.vancouver_household_market import household_income
from scripts.vancouver_mobility import PRIORITY, REPORT, mode_counts

SOURCE = "https://vancouver.ca/files/cov/2022-transportation-panel-survey.pdf"
SOURCE_2023 = "https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF"
CUTS = (25_000, 50_000, 75_000, 100_000, 150_000)
BANDS = ("Under $25,000", "$25,000–49,999", "$50,000–74,999", "$75,000–99,999", "$100,000–149,999", "$150,000 or more")
MODES = ("Auto driver", "Auto passenger", "Transit", "Walking", "Cycling", "Other / unspecified")
# Labels transcribed from Figure 54. The figure rounds percentages independently.
OBSERVED = ((22, 5, 44, 22, 8), (36, 4, 22, 33, 6), (35, 3, 21, 34, 7),
            (45, 7, 18, 24, 6), (48, 6, 10, 30, 5), (48, 8, 7, 28, 9))
# Figure 55 labels its second bracket $30,000–49,999.
OBSERVED_2023 = ((41, 7, 27, 18, 7), None, (39, 6, 22, 27, 6),
                 (35, 5, 20, 32, 8), (38, 9, 15, 30, 8), (45, 6, 10, 29, 10))


def comparable_shares(rows):
    return [[*row, None] if row is not None else None for row in rows]


def roster_bands(roster):
    people = roster["people"]
    unknown = len(BANDS)
    result = [unknown] * len(people)
    for start, size, _ in roster["homes"]:
        income = household_income(people[start:start+size])
        if income is not None:
            result[start:start+size] = [bisect_right(CUTS, income)] * size
    return result


def diary_pool_evidence(diaries):
    """Use individual income as household income only for people living alone."""
    groups = defaultdict(list)
    for diary in diaries:
        band = diary["incomeBand"]
        if diary["householdSize"] == 1 and band in range(1, 6):
            groups[band].append(diary)

    def summarize(group):
        weights = np.asarray([diary["weight"] for diary in group])
        modes = Counter()
        for diary, weight in zip(group, weights, strict=True):
            for mode, count in mode_counts(diary["episodes"]).items():
                modes[mode] += count*weight
        return dict(donors=len(group), effectiveDonors=float(weights.sum()**2 / (weights @ weights)) if len(group) else 0,
                    split=dict(Counter(diary["split"] for diary in group)),
                    weightedTrips=[float(modes[mode]) for mode in MODES])

    return dict(source="https://www150.statcan.gc.ca/n1/en/catalogue/452500012025001", geography="Urban British Columbia",
                minimumAge=15, period=2022, householdSize=1, weekday=True, totalDonors=len(diaries),
                bands=["Under $25,000", "$25,000–49,999", "$50,000–74,999", "$75,000–99,999", "$100,000 or more"],
                byIncome=[summarize(groups[band]) for band in range(1, 6)])


def publish(root, joint, evidence=None):
    parent = root / "joint-weekday" / joint
    report = read(parent / "report.json")
    inputs = dict(report["versions"], outings=report["outings"], outbound=report["workplaces"]["outbound"],
                  worksites=report["workplaces"]["worksites"], tracts=report["workplaces"]["tract-workplaces"])
    day = read(root / "cityday" / inputs["day"] / "day.json")
    atlas = root / "atlas" / inputs["atlas"]
    with tempfile.TemporaryDirectory(dir=root / "joint-weekday") as temporary:
        tmp = Path(temporary)
        bands, request, result = (tmp / name for name in ("bands.json", "inputs.json", "trips.json"))
        write_json(bands, [roster_bands(read(atlas / (da + ".json"))) for da in day["das"]])
        write_json(request, dict(inputs, priority=PRIORITY, surveyModes=REPORT, incomeBands=str(bands),
                                 knownBands=BANDS, incomeModes=MODES))
        subprocess.run(["node", "scripts/vancouver_joint_trips.mjs", root, request, result], check=True)
        extracted = read(result)
    scores = extracted["income"]
    original, combined = (np.asarray(scores[key], dtype=float) / 5 for key in ("original", "combined"))
    moved = np.asarray([extracted["adultModeDelta"].get(mode, 0)/5 for mode in MODES])
    added = combined.sum(axis=0) - original.sum(axis=0) - moved
    if not np.isfinite(combined).all() or np.any(combined < 0) or not np.allclose(added[:3], 0) or not np.allclose(added[4:], 0):
        raise ValueError("The model's income-by-mode totals disagree with the combined weekday")
    short = extracted["short"]
    shopping = added[3] - short["adultWalks"]
    if len(short["walks"]) != report["shortWalks"] or not -1e-6 <= shopping <= 2*report["shoppingOutings"]+1e-6:
        raise ValueError("The scorecard does not match the published short walks and shopping outings")
    data = dict(joint=joint, versions=inputs, survey={"year": 2022, "source": SOURCE, "figure": 54, "incomeQuestion": "B9"},
                bands=[*BANDS, "Income unresolved"], modes=MODES, observed=comparable_shares(OBSERVED),
                survey2023=dict(year=2023, source=SOURCE_2023, figure=55, shares=comparable_shares(OBSERVED_2023)),
                original=original.tolist(), combined=combined.tolist(), adults=(np.asarray(scores["adultFifths"])/5).tolist(),
                additionalWalking=round(float(added[3]), 1))
    if evidence is not None:
        data["diaryPool"] = diary_pool_evidence(read(evidence))
    name = "income-travel"
    release = package(root, name, lambda out: write_json(out / "report.json", data))
    pointer(root / name / (joint + ".json"), {"version": release})
    print(release, "classified adult trips", round(original[:-1].sum(), 1), round(combined[:-1].sum(), 1), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("joint", help="Published municipal combined weekday ID")
    parser.add_argument("--diary-evidence", type=Path, help="Clojure atlas-diaries --income-comparison export")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    args = parser.parse_args()
    publish(args.root, args.joint, args.diary_evidence)

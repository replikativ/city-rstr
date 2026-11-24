"""A fixed-workplace commuter population from Metro Vancouver into the City of Vancouver."""
import argparse
import csv
import json
import mmap
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_cityday import licensed_jobs, xy
from scripts.vancouver_downtown import MODES
from scripts.vancouver_region import package
from scripts.vancouver_visitors import donor_pool, intervals
from scripts.vancouver_walks import MOBILE

CITY = "5915022"
WORK = "Vancouver (CY), B.C."
SEED = 20261122
# City of Vancouver, 2020 Downtown Social Indicators Profile, "Share of the City".
DOWNTOWN_JOBS, OTHER_JOBS = 136625, 240820
# City transportation survey, Fall 2023, Table 22, usual workplace outside home.
WEEKDAY_ATTENDANCE = .64
MODE = {1: 4, 2: 0, 3: 7, 4: 7, 5: 1, 6: 5, 7: 6}
NAMES = {"5915046": "District of North Vancouver", "5915051": "City of North Vancouver",
         "5915001": "Township of Langley", "5915002": "City of Langley"}


def read(path):
    return json.loads(path.read_bytes())


def origins(path):
    result = {}
    outside = 0
    with path.open() as f:
        for line in f:
            row = json.loads(line)
            key = row["DGUID"][-7:]
            if row["work"] != WORK or key == CITY or not row["total"]:
                continue
            if not key.startswith("5915"):
                outside += row["total"]
                continue
            if key in result:
                raise ValueError("Duplicate workplace flow for " + key)
            result[key] = dict(name=NAMES.get(key, row["residence"]), stock=row["total"],
                               women=row["women"], men=row["men"])
    return result, outside


def profile_das(raw, cities):
    index = next(raw.glob("*Geo_starting_row_BritishColumbia.CSV"))
    ordered = []
    city = None
    with index.open(encoding="cp1252") as f:
        for row in csv.DictReader(f):
            key = row["Geo Code"]
            if key.startswith("2021A0005"):
                city = key[-7:]
            elif city in cities and key.startswith("2021S0512"):
                ordered.append((city, key))
    return ordered


def home_anchors(raw, cities):
    ordered = profile_das(raw, cities)
    profile = next(raw.glob("*_data_BritishColumbia.csv"))
    cells = []
    with profile.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        for city, key in ordered:
            needle = f'2021,"{key}",'.encode()
            start = mm.find(needle, mm.tell())
            if start < 0:
                raise ValueError("Missing DA " + key)
            mm.seek(start)
            population = int(next(csv.reader([mm.readline().decode("cp1252")]))[11])
            offset = mm.find(b',2600,"  Commute to a different census subdivision', mm.tell())
            if offset < 0:
                raise ValueError("Missing commute characteristic " + key)
            mm.seek(mm.rfind(b'\n', start, offset) + 1)
            row = next(csv.reader([mm.readline().decode("cp1252")]))
            if row[1] != key or row[8] != "2600":
                raise ValueError("Misaligned census profile at " + key)
            cells.append((key[-8:], city, population, int(row[11]) if row[11] else 0))
    with duckdb.connect() as db:
        db.execute("load spatial")
        db.execute("create table homes (da varchar, city varchar, pop bigint, commuters bigint)")
        db.executemany("insert into homes values (?,?,?,?)", cells)
        rows = db.execute("""with pts as (
            select h.*, st_transform(st_pointonsurface(geom), 'EPSG:3347', 'EPSG:4326', always_xy:=true) p
            from homes h join st_read(?) s on h.da=s.DAUID)
            select da,city,pop,commuters,st_x(p),st_y(p) from pts order by da""",
            [str(raw / "lda_000b21a_e.shp")]).fetchall()
    result = defaultdict(list)
    for da, city, pop, commuters, lon, lat in rows:
        result[city].append([da, *xy(lon, lat), pop, commuters])
    if len(rows) != len(ordered):
        raise ValueError("Missing DA geometry for commuter home placement")
    return result


def workplaces(raw, places):
    published = {tuple(p[:2]): i for i, p in enumerate(places) if p[3] == "Workplace" and p[2] >= 0}
    counts = defaultdict(int)
    for point, n in licensed_jobs(raw / "vancouver-ods").items():
        place = published.get(tuple(xy(*point)))
        if place is not None:
            counts[place] += n
    ids = sorted(counts)
    return np.array(ids), np.array([counts[i] for i in ids], dtype=float)


def workplace_weights(inside, licensed):
    weights = np.zeros(len(licensed), dtype=float)
    for mask, total in [(inside, DOWNTOWN_JOBS), (~inside, OTHER_JOBS)]:
        if not licensed[mask].sum():
            raise ValueError("No licensed workplace support in a calibration area")
        weights[mask] = licensed[mask] * total / licensed[mask].sum()
    return weights


def commute_donors(file):
    rows = []
    with file.open() as f:
        for r in csv.DictReader(f):
            if r["CMA"] != "933" or r["POWST"] != "5":
                continue
            dist, gender, mode, leave, duration = (int(r[k]) for k in ("DIST", "GENDER", "MODE", "PWLEAVE", "PWDUR"))
            if dist in range(1, 8) and mode in MODE and leave in range(1, 7) and duration in range(1, 6):
                rows.append([dist, gender, MODE[mode], leave, duration, int(r["AGEGRP"]), float(r["WEIGHT"])])
    if not rows:
        raise ValueError("No complete metropolitan cross-municipality commute donors")
    return np.asarray(rows)


def leave_band(t):
    h = (t // 60) % 24
    return h - 4 if 5 <= h <= 8 else 5 if 9 <= h < 16 else 6


def duration_band(minutes):
    return min(5, minutes // 15 + 1)


def shifts(diaries):
    # Use one complete home-to-work arrival and one last work departure per person.
    result = []
    work_spans = []
    for d in diaries:
        if d["role"] != "worker" or d["split"] != "fit":
            continue
        eps = d["episodes"]
        spans = intervals(eps, "paid-work")
        if not spans or spans[0][0] <= 240 or spans[-1][1] >= 1680:
            continue
        first, end = spans[0][0], spans[-1][1]
        i = next(i for i, ep in enumerate(eps) if ep[0] == first)
        j = i
        while j and eps[j - 1][3] in MOBILE:
            j -= 1
        if j < i and j and eps[j - 1][3] == "home":
            start = eps[j][0]
            result.append([start, first - start, end - first, d["weight"], len(work_spans)])
            work_spans.append([[a - first, b - first] for a, b in spans])
    return np.asarray(result), work_spans


def draw(rng, weights, n):
    return rng.choice(len(weights), size=n, p=weights / weights.sum())


def time_draws(rng, profiles, library):
    """Preserve both census time bands, using exact diary values within them."""
    n = len(profiles)
    starts = np.zeros(n, dtype=int)
    durations = np.zeros(n, dtype=int)
    templates = np.zeros(n, dtype=int)
    leave_codes = np.array([leave_band(int(v)) for v in library[:, 0]])
    dur_codes = np.array([duration_band(int(v)) for v in library[:, 1]])
    for leave, dur in np.unique(profiles[:, 3:5].astype(int), axis=0):
        ids = np.flatnonzero((profiles[:, 3] == leave) & (profiles[:, 4] == dur))
        joint = (leave_codes == leave) & (dur_codes == dur)
        clock_pool = library[joint] if joint.any() else library[leave_codes == leave]
        if not len(clock_pool):
            raise ValueError(f"Missing weekday departures in census band {leave}")
        samples = clock_pool[draw(rng, clock_pool[:, 3], len(ids))]
        starts[ids], templates[ids] = samples[:, 0], samples[:, 4]
        if joint.any():
            durations[ids] = samples[:, 1]
        else:
            pool = library[dur_codes == dur]
            if not len(pool):
                raise ValueError(f"Missing weekday journeys in census band {dur}")
            durations[ids] = pool[draw(rng, pool[:, 3], len(ids)), 1]
    return starts, durations, templates


def simulate(csd, control, homes, jobs, weights, zones, points, donors, library, attendance, downtown, *, destination=None):
    seed = [SEED, int(csd)]
    if destination is not None:
        seed.append(int(destination))
    rng = np.random.default_rng(seed)
    n = control["stock"]
    homes_weight = np.array([h[4] for h in homes], dtype=float)
    basis = "cross-municipality commuters"
    if not homes_weight.any():
        homes_weight = np.array([h[3] for h in homes], dtype=float)
        basis = "population"
    if not homes_weight.any():
        return None
    home = draw(rng, homes_weight, n)
    home_xy = np.array([h[1:3] for h in homes])[home]
    job = jobs[draw(rng, weights, n)]
    km = np.linalg.norm(home_xy - points[job], axis=1) / 1000
    dist = np.minimum(7, 1 + (km / 5).astype(int))
    # Flow totals and gender cells are independently rounded. Respect the flow total.
    gsum = control["women"] + control["men"]
    if gsum:
        n_women = round(n * control["women"] / gsum)
        gender = rng.permutation(np.r_[np.ones(n_women, dtype=int), np.full(n - n_women, 2)])
    else:
        gender = np.zeros(n, dtype=int)
    profiles = np.empty((n, donors.shape[1]))
    for b, g in np.unique(np.c_[dist, gender], axis=0):
        ids = np.flatnonzero((dist == b) & (gender == g))
        pool = donors[(donors[:, 0] == b) & (donors[:, 1] == g)] if g else donors[donors[:, 0] == b]
        if not len(pool):
            raise ValueError(f"No commute donors for distance {b} and gender {g}")
        profiles[ids] = pool[draw(rng, pool[:, -1], len(ids))]
    start, duration, template = time_draws(rng, profiles, library)
    span = library[template, 2].astype(int)
    if np.any(span + 2 * duration > 1440):
        raise ValueError("Commute tour exceeds a full weekday")
    arrive = start + duration
    depart = arrive + span
    attending = rng.random(n) < attendance
    in_core = zones[job] == downtown
    subset = attending & in_core
    mode = profiles[:, 2].astype(int)
    flows = np.zeros((24, 2, len(MODES)), dtype=int)
    for k, times in enumerate((arrive, depart)):
        np.add.at(flows, ((times[subset] // 60) % 24, k, mode[subset]), 1)
    if not np.all(flows.sum(axis=(0, 2)) == subset.sum()):
        raise ValueError("Unbalanced commuter tours")
    roster = np.column_stack([home, job, profiles[:, 1], profiles[:, 5], mode, start, duration, span, attending, template]).astype(int)
    return (dict(**control, basis=basis, attending=int(attending.sum()), downtownWorkers=int(in_core.sum()),
                 downtownAttending=int(subset.sum()), flows=flows.tolist()),
            dict(homes=[h[0] for h in homes], people=roster.tolist()))


def build(archive, atlas, day, diaries, out, backend, verify):
    raw = archive / "data/raw"
    places = read(day / "places.json")
    day_meta = read(day / "day.json")
    areas = day_meta["areas"]
    cities, outside = origins(archive / "data/derived/vancouver_commuting_flows.jsonl")
    homes = home_anchors(raw / "statcan", cities)
    jobs, weights = workplaces(raw, places)
    points = np.asarray([p[:2] for p in places])
    zones = np.asarray([p[2] for p in places])
    core = areas.index("Downtown")
    in_core = zones[jobs] == core
    raw_share = weights[in_core].sum() / weights.sum()
    weights = workplace_weights(in_core, weights)
    donors = commute_donors(raw / "statcan/pumf/data_donnees_2021_hier_v2.csv")
    library, work_spans = shifts(diaries)
    _, _, fit = donor_pool(diaries, "employees", "fit")
    _, _, holdout = donor_pool(diaries, "employees", "holdout")
    groups = {}
    unresolved = {}
    for csd, control in sorted(cities.items()):
        result = simulate(csd, control, homes[csd], jobs, weights, zones, points, donors, library,
                          WEEKDAY_ATTENDANCE, core)
        if result is None:
            unresolved[csd] = control
        else:
            groups[csd], roster = result
            write_json(out / (csd + ".json"), roster)
    report = dict(versions=dict(atlas=atlas.name, day=day.name), seed=SEED, groups=groups, modes=MODES,
                  unresolved=unresolved, beyondMetro=outside, fit=fit, holdout=holdout, shiftDiaries=len(library),
                  commuteDonors=len(donors), workplaceAnchors=len(jobs), attendance=WEEKDAY_ATTENDANCE,
                  licenceDowntownShare=float(raw_share), downtownJobShare=DOWNTOWN_JOBS/(DOWNTOWN_JOBS+OTHER_JOBS))
    report["totalStock"] = sum(c["stock"] for c in cities.values()) + outside
    from scripts.vancouver_commuter_presence import publish_presence
    report["workSpans"] = work_spans
    report["execution"] = publish_presence(out, groups, work_spans, zones, core, backend, verify)
    write_json(out / "commuters.json", report)
    return report


def publish(archive, root, backend="jvm", verify=False, day=None):
    day = day or read(root / "cityday/current.json")
    atlas_dir, day_dir = root / "atlas" / day["atlas"], root / "cityday" / day["version"]
    diaries = json.loads(subprocess.check_output(
        ["clojure", "-M", "-m", "city.vancouver.atlas-diaries", str(archive), "--attendance"]))
    version = package(root, "commuters", lambda out: build(archive, atlas_dir, day_dir, diaries, out, backend, verify))
    pointer = root / "commuters" / (day["atlas"] + "_" + day["version"] + ".json")
    with tempfile.TemporaryDirectory(dir=pointer.parent) as tmp:
        staged = Path(tmp) / "pointer"
        write_json(staged, {"version": version})
        staged.replace(pointer)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--backend", default="jvm")
    parser.add_argument("--verify-workers", action="store_true")
    args = parser.parse_args()
    print(publish(args.archive, args.data, args.backend, args.verify_workers))

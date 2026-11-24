"""Compare resident shopping arrivals and shop hours with independent travel and time-use surveys."""
import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import subprocess
import tempfile

from scripts.vancouver_atlas import write_json
from scripts.vancouver_cityday import compile_day
from scripts.vancouver_market import read, windows
from scripts.vancouver_mobility import travel_bouts
from scripts.vancouver_trip_demand import destination

MODES = ("walk", "bike", "car-driver")
SURVEYS = [
    {"year": 2019, "figure": "Figure 4-7", "source": "https://vancouver.ca/files/cov/2019-transportation-panel-survey.pdf",
     "shares": {"Auto driver": 38, "Auto passenger": 4, "Transit": 9, "Walking": 39, "Cycling": 10}},
    {"year": 2024, "figure": "Walking and Rolling", "source": "https://vancouver.ca/files/cov/2024-transportation-snapshot.pdf",
     "shares": {"Walking": 43}},
]


def clocks(diaries):
    """Survey-weighted occasions. Keep respondent-level support separate from repeat episodes."""
    counts = Counter()
    samples = defaultdict(list)
    for diary in diaries:
        pool = diary["pool"]
        counts[pool] += 1
        tpl = compile_day(diary["episodes"])
        for mode in MODES:
            stops = [(r[1], r[2]) for r in windows(diary, tpl, mode)]
            if stops:
                samples[pool, mode].append((diary["weight"], stops))
    result = {}
    for pool, people in counts.items():
        by_mode = {}
        for mode in MODES:
            group = samples[pool, mode]
            times = Counter()
            for weight, stops in group:
                for stop in stops:
                    times[stop] += weight
            mass = sum(times.values())
            squares = sum((w * len(s)) ** 2 for w, s in group)
            by_mode[mode] = dict(donors=len(group), occasions=sum(len(s) for _, s in group),
                                 effective=round(mass**2/squares, 1) if squares else 0,
                                 clock=[[start, dwell, w/mass] for (start, dwell), w in sorted(times.items())])
        result[pool] = dict(people=people, modes=by_mode)
    return result


def walk_arrivals(walks, atlas_dir, atlas, day):
    """Identify the first activity at the arrival slot of each reconstructed short walk."""
    by_da = defaultdict(list)
    for d, i, start, duration, a, b in walks["walks"]:
        by_da[d].append((i, start, duration, a, b))
    weights = Counter()
    for d, rows in by_da.items():
        da = day["das"][d]
        people = read(atlas_dir / (da + ".json"))["people"]
        for i, start, duration, a, b in rows:
            if i >= atlas["das"][da]["private"]:
                continue
            person = people[i]
            age = person[0]
            w = 5 if 4 <= age <= 13 else 2 if age == 3 else 0
            if not w:
                continue
            tpl = person[-1]
            parts = day["templates"][tpl]["parts"]
            arrival, = [p[0] for p in parts if p[2] == "stop" and p[3] == b]
            if not start <= arrival <= start + duration:
                raise ValueError("Reconstructed walk disagrees with its diary boundary")
            episodes = atlas["templates"][tpl]["episodes"]
            k = bisect_left(episodes, [arrival])
            if k == 0 or episodes[k][0] != arrival:
                raise ValueError("Missing original activity at reconstructed walk arrival")
            weights[destination(episodes[k-1], episodes[k])] += w
    if weights.total() != round(5 * walks["adultWalks"]):
        raise ValueError("Inferred purposes do not conserve adult walking trips")
    return weights["Shopping"]


def shopping_arrivals(cells, tours, templates):
    base = Counter()
    for zone, mode, purpose, fifths, *_ in cells:
        if purpose == "Shopping":
            base[mode] += fifths
    purposes = [{s: (m, destination(a, b)) for s, m, a, b in travel_bouts(d["episodes"])} for d in templates]
    added = Counter()
    seen = set()
    for d, i, tpl, _, _, legs, access in tours:
        for start, *_ in legs:
            key = (d, i, start)
            mode, purpose = purposes[tpl][start]
            if mode != "Auto driver" or key in seen:
                raise ValueError("Outing does not replace a unique recorded driver trip")
            seen.add(key)
            if purpose == "Shopping":
                added["ride"] += 5
                if access:
                    added["access"] += 5
    if added["ride"] > base["Auto driver"]:
        raise ValueError("Changed shopping arrivals exceed the original driver trips")
    return dict(fifths=dict(base), switchedFifths=dict(added))


def publish(root, archive):
    ptr = read(root / "cityday/current.json")
    atlas_id, day_id = ptr["atlas"], ptr["version"]
    street = read(root / "streets/current.json")["version"]
    cycling = read(root / "cycling" / (street + ".json"))["version"]
    tours = read(root / "cycle-tours" / ("_".join([atlas_id, day_id, street, cycling]) + ".json"))["version"]
    tdir = root / "cycle-tours" / tours
    versions = read(tdir / "report.json")["versions"]
    if any(versions[k] != v for k, v in dict(atlas=atlas_id, day=day_id, streets=street, cycling=cycling).items()):
        raise ValueError("Outings belong to another weekday")
    demand = read(root / "trip-demand" / versions["demand"] / "demand.json")
    adir = root / "atlas" / atlas_id
    atlas = read(adir / "atlas.json")
    day = read(root / "cityday" / day_id / "day.json")
    walkfile = root / "short-walks" / (day_id + "_" + street + ".json")
    walks = read(walkfile)
    if any(walks[k] != versions[k] for k in ("day", "atlas", "streets")) or any(demand[k] != versions[k] for k in ("day", "atlas")):
        raise ValueError("Trip and short-walk releases disagree")
    arrivals = shopping_arrivals(demand["cells"], read(tdir / "tours.json"), atlas["templates"])
    arrivals["inferredWalkFifths"] = walk_arrivals(walks, adir, atlas, day)
    with tempfile.TemporaryDirectory() as tmp:
        chains = Path(tmp) / "diaries.json"
        with chains.open("w") as stream:
            subprocess.run(["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.atlas-diaries", str(archive),
                            "--shopping-comparison"], stdout=stream, check=True)
        samples = clocks(read(chains))
    raw = archive / "data/raw/statcan/timeuse/Data_Données"
    receipts = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                [raw/"TU_ET_2022_Episode_PUMF.txt", raw/"TU_ET_2022_Main-Principal_PUMF.txt"]}
    result = dict(versions=dict(versions, tours=tours), shortWalks=hashlib.sha256(walkfile.read_bytes()).hexdigest(),
                  arrivals=arrivals, surveys=SURVEYS, samples=samples, timeUseFiles=receipts)
    output = root / "market" / ("evidence-" + tours + ".json")
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        path = Path(tmp) / "evidence.json"
        write_json(path, result)
        path.replace(output)
    print(output, arrivals, flush=True)
    print({k: {m: [a["donors"], a["occasions"]] for m, a in p["modes"].items()} for k, p in samples.items()})


if __name__ == "__main__":
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("archive", type=Path)
    args.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    opts = args.parse_args()
    publish(opts.root, opts.archive)

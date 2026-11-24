"""Build the Mount Pleasant walking replay from the archived Vancouver inventory."""
import argparse
import json
import math
import random
import re
import subprocess
import tempfile
from itertools import groupby
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import networkx as nx
from matplotlib.path import Path as Polygon
from openpyxl import load_workbook
from scipy.spatial import cKDTree

ORIGIN = (-123.105, 49.262)
METRES = (111195 * math.cos(math.radians(ORIGIN[1])), 111195)
AREA = "Mount Pleasant"
# Sites with unambiguous location, approach coverage and declared survey hours.
SURVEYS = {
    ("TMC_Ontario&10th", "2023-07-12"): "Ontario St & 10th Ave",
    ("TMC_OntarioSt&5thAv", "2023-07-12"): "Ontario St & 5th Ave",
    ("TMC_OntarioSt&IstAv", "2023-08-09"): "Ontario St & 1st Ave",
    ("TMC_Alberta&W12th", "2024-10-30"): "Alberta St & W 12th Ave",
}
RADIUS = 22
WALKABLE = set("residential living_street service unclassified pedestrian footway path steps "
               "primary secondary tertiary primary_link secondary_link tertiary_link track".split())
MOBILE = set("car-driver car-passenger walk transit air bike motorcycle taxi ridehail ferry "
             "travel-other travel-ns".split())


def project(lon, lat):
    return ((lon - ORIGIN[0]) * METRES[0], (ORIGIN[1] - lat) * METRES[1])


def clock_minute(value):
    h, m = map(int, value.split(":"))
    return h * 60 + m


def survey_windows(summary):
    col = summary.index("Count Time:")
    def times(cell):
        return [clock_minute(t) for t in re.findall(r"\d\d:\d\d", cell)]
    windows = []
    for a, b in zip(times(summary[col+1]), times(summary[col+3]), strict=True):
        if a >= b or a % 60 or b % 60 or (windows and a < windows[-1][1]):
            raise ValueError("Expected ordered whole-hour survey periods")
        if windows and a == windows[-1][1]:
            windows[-1][1] = b
        else:
            windows.append([a, b])
    return windows


def survey_counts(summary, rows):
    windows = survey_windows(summary)
    expected = {t for a, b in windows for t in range(a, b, 5)}
    cols = [i for i, name in enumerate(rows[9]) if name == "Peds"]
    if len(cols) != 4 or not expected:
        raise ValueError("Missing survey periods or pedestrian approaches")
    counts = {}
    for row in rows[10:]:
        minute = clock_minute(row[0])
        if minute not in expected:
            if any(row[c] not in (0, None) for c in cols):
                raise ValueError("Pedestrian counts outside declared survey periods")
            continue
        if minute in counts or any(type(row[c]) is not int or row[c] < 0 for c in cols):
            raise ValueError("Incomplete pedestrian observation")
        counts[minute] = sum(row[c] for c in cols)
    if counts.keys() != expected:
        raise ValueError("Five-minute rows do not cover declared survey periods")
    return windows, [counts[t] for t in sorted(counts)]


def verified_study(raw, study, name):
    receipt, = [f for f in (raw / "vancouver-arcgis").glob("*.receipt.edn")
                if study["attachment"] in f.read_text()]
    workbook = load_workbook(str(receipt).removesuffix(".receipt.edn"), read_only=True, data_only=True)
    try:
        rows = list(workbook["Ped and Passenger Vehicle"].values)
        summary = next(row for row in workbook["Summary"].values if "Count Time:" in row)
    finally:
        workbook.close()
    windows, observed = survey_counts(summary, rows)
    if (sum(observed) != study["total"] or rows[3][2] != study["site"]
            or datetime.strptime(rows[1][2], "%m/%d/%Y").date().isoformat() != study["date"]):
        raise ValueError("Pedestrian table and inventory disagree")
    return dict(name=name, date=study["date"], windows=windows, start=windows[0][0], end=windows[-1][1],
                bin=5, point=project(study["lon"], study["lat"]), observed=observed, events=[],
                source=re.search(r':url "([^"]+)"', receipt.read_text())[1], radius=RADIUS)


def boundary(raw):
    directory = raw / "vancouver-ods"
    receipt, = [p for p in directory.glob("*.geojson.receipt.edn") if ':dataset "local-area-boundary"' in p.read_text()]
    features = json.loads(Path(str(receipt).removesuffix(".receipt.edn")).read_text())["features"]
    area = next(f for f in features if f["properties"]["name"] == AREA)
    ring, = area["geometry"]["coordinates"]
    return [project(*p) for p in ring]


def street_network(raw, polygon):
    graph = nx.Graph()
    streets = []
    xmin, ymin, xmax, ymax = polygon.get_extents().extents
    ways = json.loads((raw / "osm-overpass/vancouver_highways.json").read_text())["elements"]
    for way in ways:
        tags = way["tags"]
        kind = tags.get("highway")
        if (kind not in WALKABLE or tags.get("area") == "yes"
                or tags.get("foot", tags.get("access")) in {"private", "no"}):
            continue
        ids = way["nodes"]
        points = [project(p["lon"], p["lat"]) for p in way["geometry"]]
        for node, point in zip(ids, points, strict=True):
            graph.add_node(node, xy=point)
        graph.add_weighted_edges_from((u, v, math.dist(a, b)) for u, v, a, b
                                      in zip(ids, ids[1:], points, points[1:]) if u != v)
        if (kind in {"primary", "secondary", "tertiary", "residential"}
                or any(xmin-800 <= x <= xmax+800 and ymin-800 <= y <= ymax+800 for x, y in points)):
            streets.append([kind, tags.get("name"), [[round(x), round(y)] for x, y in points]])
    # Routes starting in the largest component stay there. Query the original
    # adjacency directly, retaining its neighbour order for shortest-path ties.
    component = max(nx.connected_components(graph), key=len)
    ids = [node for node in graph if node in component]
    tree = cKDTree([graph.nodes[u]["xy"] for u in ids])
    return graph, streets, lambda point: ids[tree.query(point)[1]]


def destinations(raw):
    groups = defaultdict(list)
    seen = set()
    rules = {"store": r"store|shopping|market|bakery|florist|pharmacy",
             "restaurant": r"restaurant|cafe|coffee_shop|pub$|fast_food",
             "school": r"school|university|college", "outdoors": r"park$|beach|garden",
             "sports-venue": r"sports|fitness|gym", "culture": r"gallery|museum|theater|library",
             "worship": r"church|mosque|synagogue|temple", "clinic": r"clinic|hospital|doctor|dentist"}
    for receipt in sorted((raw / "overture-places").glob("*.receipt.edn")):
        if not re.search(r':local-area "(?!DA )[^"]+"', receipt.read_text()):
            continue
        with Path(str(receipt).removesuffix(".receipt.edn")).open() as f:
            for line in f:
                row = json.loads(line)
                if row["id"] in seen:
                    continue
                seen.add(row["id"])
                point = project(row["lon"], row["lat"])
                groups["business"].append(point)
                for loc, pattern in rules.items():
                    if re.search(pattern, row["category"] or ""):
                        groups[loc].append(point)
    return {k: cKDTree(v) for k, v in groups.items()}


def passing_minute(points, center, start, duration):
    """Time at the closest interior point of a leg passing through a site buffer."""
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    total = sum(lengths)
    if not total or min(math.dist(points[i], center) for i in [0, -1]) <= RADIUS:
        return None
    closest, at, elapsed = RADIUS, None, 0
    for a, b, length in zip(points, points[1:], lengths):
        if length:
            dx, dy = b[0]-a[0], b[1]-a[1]
            t = max(0, min(1, ((center[0]-a[0])*dx + (center[1]-a[1])*dy) / length**2))
            distance = math.hypot(a[0]+t*dx-center[0], a[1]+t*dy-center[1])
            if distance < closest:
                closest, at = distance, elapsed+t*length
        elapsed += length
    return None if at is None else start + duration*at/total


def can_reach_site(a, b, site, max_length):
    # Visiting any point in the buffer requires at least this much path length.
    return math.dist(a, site) + math.dist(site, b) <= max_length + 2 * RADIUS


def anchor_day(person, graph, snap, venues, rng, workplace=None):
    chain = person["chain"]
    home = snap(project(*person["home"]))
    xy = lambda n: graph.nodes[n]["xy"]
    last, previous_loc, work, anchored = home, None, {}, {}
    for i, (start, dur, act, loc) in enumerate(chain):
        if loc in MOBILE or loc in {"unknown", "elsewhere"}:
            previous_loc = None
            continue
        walked = i > 0 and chain[i-1][3] == "walk" and i-2 in anchored
        if loc == "home":
            last = home
        elif loc == previous_loc:
            pass
        elif loc == "work-or-school" and loc in work:
            last = work[loc]
        else:
            # Approximate a straight-line displacement from the diary's walking time.
            # A walk back home also constrains the preceding venue.
            origin = xy(last) if walked else xy(home)
            minutes = chain[i-1][1] if walked else None
            if minutes is None and i+2 < len(chain) and chain[i+1][3] == "walk" and chain[i+2][3] == "home":
                minutes = chain[i+1][1]
            distance = minutes * 60 if minutes is not None else rng.uniform(400, 5000)
            angle = rng.uniform(0, math.tau)
            target = (origin[0]+distance*math.cos(angle), origin[1]+distance*math.sin(angle))
            group = ("school" if act == "study" else "business") if loc == "work-or-school" else loc
            pool = venues.get(group)
            if workplace is not None and act == "paid-work" and loc == "work-or-school":
                target = workplace(target)
            elif pool is not None:
                target = pool.data[pool.query(target)[1]]
            last = snap(target)
            if loc == "work-or-school":
                work[loc] = last
        anchored[i], previous_loc = last, loc
    return anchored


def make_walks(person, graph, snap, venues, rng, stats, sites=None, anchored=None, windows=None):
    chain = person["chain"]
    if anchored is None:
        anchored = anchor_day(person, graph, snap, venues, rng)
    xy = lambda n: graph.nodes[n]["xy"]
    for i, last in anchored.items():
        if i-2 not in anchored or chain[i-1][3] != "walk":
            continue
        _, _, act, loc = chain[i]
        a, b = anchored[i-2], last
        if a == b:
            stats["same-node"] += 1
            continue
        start, dur = chain[i-1][:2]
        if windows and not any(start < end and start+dur > begin for begin, end in windows):
            continue
        max_length = 2.5 * 60 * dur
        if sites is not None and not any(can_reach_site(xy(a), xy(b), site, max_length) for site in sites):
            continue
        path = nx.astar_path(graph, a, b, heuristic=lambda n, end: math.dist(xy(n), xy(end)))
        points = [xy(n) for n in path]
        if sum(map(math.dist, points, points[1:])) > max_length:
            stats["over-speed-limit"] += 1
            continue
        yield dict(start=start, dur=dur, origin=chain[i-2][3], destination=loc,
                   activity=act, points=points)


def simulate_day(sample, seed, graph, snap, venues, polygon, studies, replay):
    sites = None if replay else [s["point"] for s in studies]
    people, stats = [], Counter()
    for person in sample:
        # Preserve the published seed's destination draws exactly.
        key = person["id"] if seed == 2023 else f"{seed}/{person['id']}"
        legs = list(make_walks(person, graph, snap, venues, random.Random(key), stats, sites))
        resident = person["area"] == AREA
        # Score every routed city leg, including those skirting the neighbourhood boundary.
        for leg in legs:
            xs, ys = zip(*leg["points"])
            left, right = min(xs) - RADIUS, max(xs) + RADIUS
            top, bottom = min(ys) - RADIUS, max(ys) + RADIUS
            for study in studies:
                x, y = study["point"]
                if not (left <= x <= right and top <= y <= bottom):
                    continue
                minute = passing_minute(leg["points"], study["point"], leg["start"], leg["dur"])
                if minute is not None and any(a <= minute < b for a, b in study["windows"]):
                    study["events"].append([minute, person["weight"], resident])
        if not replay or not any(polygon.contains_point(leg["points"][0]) or
                                 polygon.intersects_path(Polygon(leg["points"]), filled=False) for leg in legs):
            continue
        for leg in legs:
            leg["points"] = [[round(x), round(y)] for x, y in leg["points"]]
        people.append({**{k: person[k] for k in ("id", "age", "area", "weight")}, "legs": legs})
    return people, stats


def hourly_run(study, seed):
    hour = Counter()
    for minute, weight, _ in study["events"]:
        hour[int(minute // 60)] += weight
    return {"seed": seed, "hours": [hour[t // 60] for a, b in study["windows"] for t in range(a, b, 60)]}


def build(raw, derived, samples, seeds):
    ring = boundary(raw)
    polygon = Polygon(ring)
    counts = json.loads((derived / "vancouver_ped_counts_mp.json").read_text())["counts"]
    inventory = {(s["site"], s["date"]): s for s in counts}
    studies = [verified_study(raw, inventory[key], name) for key, name in SURVEYS.items()]
    graph, streets, snap = street_network(raw, polygon)
    venues = destinations(raw)
    days = groupby(map(json.loads, samples), key=lambda person: person["seed"])
    for i, (expected, (seed, sample)) in enumerate(zip(seeds, days, strict=True)):
        if expected != seed:
            raise ValueError("Unexpected sample order")
        day_studies = [dict(s, events=[]) for s in studies]
        people, stats = simulate_day(sample, seed, graph, snap, venues, polygon, day_studies, replay=i == 0)
        if i == 0:
            replay_people, replay_stats = people, stats
        for study, day in zip(studies, day_studies):
            if i == 0:
                study["events"] = sorted(day["events"])
                study["runs"] = []
            study["runs"].append(hourly_run(day, seed))
        print(f"Scored seed {seed}", flush=True)
    return dict(area=AREA, boundary=ring, streets=streets, people=replay_people, studies=studies,
                study=studies[0], exclusions=replay_stats)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, default=Path("public/data/vancouver/walks.json"))
    parser.add_argument("--seed", type=int, default=2023, help="First weekday seed, shown in the replay")
    parser.add_argument("--replicates", type=int, default=1, help="Number of consecutive weekday seeds")
    args = parser.parse_args()
    if args.replicates < 1:
        parser.error("--replicates must be positive")
    seeds = range(args.seed, args.seed + args.replicates)
    with tempfile.TemporaryFile(mode="w+") as sample:
        subprocess.run(["clojure", "-M", "-m", "city.vancouver.walk-sample", str(args.archive), *map(str, seeds)],
                       stdout=sample, check=True)
        sample.seek(0)
        result = build(args.archive/"data/raw", args.archive/"data/derived", sample, seeds)
    args.output.parent.mkdir(exist_ok=True, parents=True)
    with tempfile.NamedTemporaryFile(dir=args.output.parent, mode="w", delete=False) as f:
        json.dump(result, f, separators=(",", ":"), allow_nan=False)
    Path(f.name).chmod(0o644)
    Path(f.name).replace(args.output)
    for s in result["studies"]:
        print(s["name"], sum(s["observed"]), round(sum(e[1] for e in s["events"])), len(s["events"]))


if __name__ == "__main__":
    main()

"""Compare routed resident cycling trips with archived City of Vancouver bicycle counts."""
import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile

from openpyxl import load_workbook

from scripts.vancouver_atlas import write_json
from scripts.vancouver_region import package, read

SOURCE = "https://vancouver.ca/streets-transportation/traffic-count-data.aspx"
COUNTER_LOCATIONS = "https://vancouver.ca/files/cov/2025-873-release.pdf"
PROBES = [
    ("arbutus", "Arbutus St & W 10th Ave", "TMC_Arbutus&W10th", "2024-01-09",
     "tmc_arbutus_w10th", [7, 8, 16, 17], ["From North", "From East", "From South", "From West"],
     ["Left", "Right", "Thru", "Cross Walk"]),
    ("powell", "700 block of Powell St", "CSC_700PowellSt", "2024-01-31",
     "midblock_700_powell", list(range(4, 24)), ["From East", "From West"],
     ["North Sidewalk", "Bike Lane", "Road", "South Sidewalk"]),
]


# Chosen by geography after fixing the route cost. Both streets share exactly one
# graph node at each held-out junction. The remaining study sites have split junctions.
EXTRA = [
    ("ontario5", "Ontario St & 5th Ave", "TMC_OntarioSt&5thAv", "2023-07-12",
     "e5e174e666d017b3c2165baf0e686addd4217afe56384ca2a704465c6096a719", 5,
     ["Ontario Street", "East 5th Avenue"], "10002/attachments/11182"),
    ("prince", "Prince Edward St & E Broadway", "TMC_PrinceEdward&EBroadway", "2023-04-05",
     "832bb81973ea8d3c4d1fe63db0f205ff9008a70f385bce473746388c72c3ba7c", 60,
     ["Prince Edward Street", "East Broadway"], "10162/attachments/11342"),
]

# Daily averages transcribed from the City's Transportation Snapshots. The
# cross-sections are centred at the corresponding locations in FOI 2025-873.
# The first two screen values give the local along-path vector (east, south).
SUMMER = [
    ("pointgrey", "Point Grey Road at Volunteer Park", 2024, 3900,
     [-123.1687064, 49.27127679], [19, -10, 8], 12),
    ("davidlam", "Seawall at David Lam Park", 2023, 4500,
     [-123.12519, 49.2717], [47, -56, 8], 9),
    ("creekside", "Seawall at Creekside Community Centre", 2021, 4085,
     [-123.10597, 49.271984], [32, 1, 8], 9),
]


def screen_fraction(a, b, centre, screen, *, min_alignment=0):
    dx, dy, width = screen
    east, south = a[0]-centre[0], a[1]-centre[1]
    start = east*dx + south*dy
    end = (b[0]-centre[0])*dx + (b[1]-centre[1])*dy
    if (start < 0) == (end < 0) or abs(end-start) < min_alignment*math.dist(a, b):
        return None
    f = -start/(end-start)
    lateral = (south+f*(b[1]-a[1]))*dx - (east+f*(b[0]-a[0]))*dy
    if abs(lateral) <= width:
        return f, "From West" if start < 0 else "From East"
    return None


def observations(archive, extra=False):
    sites = []
    raw = archive/"data/raw"
    files = [(key, name, site, day, raw/"probes"/f"counts_vancouver_{prefix}_{day}.xlsx",
              hours, dirs, moves, 5 if key == "arbutus" else 60, None, SOURCE)
             for key, name, site, day, prefix, hours, dirs, moves in PROBES]
    if extra:
        for key, name, site, day, filename, step, roads, attachment in EXTRA:
            url = "https://maps.vancouver.ca/server/rest/services/GDH/Short_Term_Intersection_Movement_Counts/MapServer/33/"+attachment
            files.append((key, name, site, day, raw/"vancouver-arcgis"/(filename+".xlsx"), None,
                          PROBES[0][-2], PROBES[0][-1], step, roads, url))
    for key, name, site, day, file, hours, directions, movements, step, roads, source in files:
        expected = date.fromisoformat(day)
        seen, counts, approaches = set(), Counter(), Counter()
        weather = point = None
        book = load_workbook(file, read_only=True, data_only=True)
        try:
            if hours is None:
                from scripts.vancouver_walks import survey_windows
                summary = next(row for row in book["Summary"].values if "Count Time:" in row)
                hours = [h//60 for a,b in survey_windows(summary) for h in range(a,b,60)]
            rows = iter(book["Tabular Array"].values)
            header = next(rows)
            movement_label = "Position:" if key == "powell" else "Movement:"
            if list(header[7:13]) != ["Mode:", "Mode Group:", "Direction:", movement_label, "Time:", "Volume:"]:
                raise ValueError("Unexpected columns in " + file.name)
            for row in rows:
                if row[7] != "Bike":
                    continue
                if row[0].date() != expected or row[2] != site:
                    raise ValueError("Bicycle sheet has unexpected date or site")
                if key == "arbutus" and row[5] != "0700-0900&1600-1800":
                    raise ValueError("Unknown intersection count windows")
                if key == "powell":
                    lat, lon = map(float, row[6].split(","))
                    point = [lon, lat]
                weather = row[4]
                h, m = row[11].hour, row[11].minute
                if h not in hours:
                    continue
                cell = (h, m, row[9], row[10])
                if cell in seen or not isinstance(row[12], int) or row[12] < 0:
                    raise ValueError("Invalid bicycle count cell")
                seen.add(cell)
                counts[h] += row[12]
                approaches[row[9]] += row[12]
            totals = Counter()
            for row in book["Bike"].iter_rows(min_row=11, values_only=True):
                hour = int(row[0].split(":")[0])
                if hour in hours:
                    totals[hour] += sum(row[1:1+len(directions)*len(movements)])
            if counts != totals:
                raise ValueError("Tabular Array and the Bike sheet have different hourly totals")
        finally:
            book.close()
        if seen != {(h, m, d, movement) for h in hours for m in range(0, 60, step)
                    for d in directions for movement in movements}:
            raise ValueError("Incomplete coverage of published bicycle count intervals")
        sites.append(dict(key=key, name=name, date=day, weather=weather, hours=hours,
                          observed=[counts[h] for h in hours], approaches={d: approaches[d] for d in directions},
                          lonLat=point, file=file.name,
                          sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
        if roads:
            receipt = file.with_suffix(".xlsx.receipt.edn")
            if receipt.exists():
                acquired = receipt.read_text()
                sha = sites[-1]["sha256"]
                if f':url "{source}"' not in acquired or f':sha256 "{sha}"' not in acquired:
                    raise ValueError(f"City count workbook differs from its acquisition receipt: {file.name}")
            sites[-1].update(junction=roads, source=source)
    for key, name, year, daily, point, [dx, dy, width], page in SUMMER:
        length = math.hypot(dx, dy)
        sites.append(dict(key=key, name=name, date=f"Summer {year}", dailyAverage=daily,
                          lonLat=point, screen=[dx/length, dy/length, width], hours=list(range(4, 28)),
                          approaches=dict.fromkeys(["From East", "From West"], None),
                          source=f"https://vancouver.ca/files/cov/{year}-transportation-snapshot.pdf#page={page}",
                          locationSource=COUNTER_LOCATIONS))
    return sites


def add_junction_bounds(root, report, legs):
    """Count each diary leg once if a visit to the junction can fit a surveyed hour.

    Candidate legs include all trips whose endpoint distances to a survey site
    can fit the diary budget. The extra 44 m covers the entire Powell screen.
    """
    from scipy.sparse.csgraph import dijkstra
    from scripts.vancouver_cycling import FORWARD, REVERSE
    from scripts.vancouver_streets import access_graph
    v = report["versions"]
    net = read(root/"cycling"/v["cycling"]/"network.json")
    graph, snap = access_graph(net, FORWARD, REVERSE)
    reverse = graph.T.tocsr()
    places = read(root/"cityday"/v["day"]/"places.json")
    ids = sorted({p for _, a, b, *_ in legs for p in (a, b)})
    nodes, offsets = snap([places[p][:2] for p in ids], lowest_id_on_ties=True)
    anchors = dict(zip(ids, zip(nodes, offsets), strict=True))
    for j, site in enumerate(report["sites"]):
        if site["key"] == "powell" or "screen" in site:
            continue
        junction = [i for i, point in enumerate(net["nodes"]) if point == site["point"]]
        incoming = dijkstra(reverse, indices=junction, min_only=True)
        outgoing = dijkstra(graph, indices=junction, min_only=True)
        counts = Counter()
        for rule, a, b, start, duration, budget in legs:
            u, approach = anchors[a]
            w, exit_leg = anchors[b]
            speed = budget/duration
            earliest = start+(approach+incoming[u])/speed
            latest = start+duration-(outgoing[w]+exit_leg)/speed
            if earliest <= latest and any(earliest < (h+1)*60 and latest >= h*60 for h in site["hours"]):
                counts[rule] += 1
        for rule, run in report["runs"].items():
            result = run["sites"][j]
            if counts[rule] < sum(result["counts"]):
                raise ValueError("The junction bound excludes a counted cyclist")
            result["reachable"] = counts[rule]


def verify_routes(root, report, legs):
    """Independently reconstruct every potential site passage with directed Dijkstra trees."""
    from scipy.sparse.csgraph import dijkstra
    from scripts.vancouver_streets import access_graph
    from scripts.vancouver_cycling import FORWARD, REVERSE
    v, sites = report["versions"], report["sites"]
    net = read(root/"cycling"/v["cycling"]/"network.json")
    graph, snap = access_graph(net, FORWARD, REVERSE)
    weighted = None
    penalty = 1
    if v.get("bikeways"):
        import numpy as np
        profile = read(root/"bikeways"/v["bikeways"]/"profile.json")
        weighted = graph.copy()
        arcs = np.asarray(profile["arcs"], dtype=np.int64)
        n = graph.shape[0]
        row = np.repeat(np.arange(n), np.diff(graph.indptr))
        ids = row*n+graph.indices
        preferred = np.isin(ids, arcs[:,0]*n+arcs[:,1])
        factors = np.where(preferred, 1, profile["offBikewayCost"])
        penalty = profile["offBikewayCost"]
        if profile.get("uphillArcs"):
            uphill = np.asarray(profile["uphillArcs"], dtype=np.int64)
            uphill_ids = uphill[:,0]*n+uphill[:,1]
            edge = np.searchsorted(ids, uphill_ids)
            if np.any(edge >= len(ids)) or not np.array_equal(ids[edge], uphill_ids):
                raise ValueError("Grade profile contains inaccessible bicycle edges")
            costs = np.asarray(profile["uphillCosts"])
            factors[edge] += costs[uphill[:,2]]
            penalty += costs.max()
        weighted.data *= factors
    catalog = read(root/"cityday"/v["day"]/"places.json")
    ids = sorted({p for _, a, b, *_ in legs for p in (a, b)})
    nodes, offsets = snap([catalog[p][:2] for p in ids], lowest_id_on_ties=True)
    anchors = dict(zip(ids, zip(nodes, offsets), strict=True))
    groups, counts, approaches = defaultdict(list), Counter(), Counter()
    for row in legs:
        groups[anchors[row[1]][0]].append(row)
    for src, rows in groups.items():
        bound = max(r[-1] for r in rows)
        dist, prev = dijkstra(graph, indices=src, limit=bound, return_predecessors=True)
        weighted_prev = None
        if weighted is not None:
            _, weighted_prev = dijkstra(weighted, indices=src, limit=bound*penalty, return_predecessors=True)
        routes = {}

        def trace(dest, prefer):
            key = dest, prefer
            if key not in routes:
                pred = weighted_prev if prefer else prev
                j, sequence = dest, []
                while j != src and pred[j] >= 0:
                    i = pred[j]
                    sequence.append((net["nodes"][i], net["nodes"][j]))
                    j = i
                if j != src:
                    return math.inf, []
                along, hits = 0, {}
                for k, (a, b) in enumerate(reversed(sequence)):
                    metres = math.dist(a, b)
                    for site in sites:
                        x, y = site["point"]
                        name = site["key"]
                        if name in hits:
                            continue
                        screen = site.get("screen", (1, 0, 22) if name == "powell" else None)
                        if screen is None and k+1 < len(sequence) and b == [x,y]:
                            if abs(a[0]-x) > abs(a[1]-y):
                                side = "From East" if a[0] > x else "From West"
                            else:
                                side = "From South" if a[1] > y else "From North"
                            hits[name] = (site, along+metres, side)
                        if screen is not None:
                            hit = screen_fraction(a, b, (x, y), screen, min_alignment=0 if name == "powell" else .5)
                            if hit:
                                f, side = hit
                                hits[name] = (site, along+f*metres, side)
                    along += metres
                routes[key] = along, list(hits.values())
            return routes[key]

        for rule, a, b, start, duration, limit in rows:
            dest, tail = anchors[b]
            access = anchors[a][1]+tail
            if not 0 < dist[dest]+access <= limit:
                continue
            length, hits = trace(dest, weighted is not None)
            if weighted is not None and length+access > limit:
                length, hits = trace(dest, False)
            for site, along, side in hits:
                hour = int((start+duration*(anchors[a][1]+along)/(length+access))//60)
                if hour in site["hours"]:
                    counts[rule,site["key"],hour] += 1
                    approaches[rule,site["key"],side] += 1
    for rule, run in report["runs"].items():
        for s, result in zip(sites, run["sites"], strict=True):
            independent = [counts[rule,s["key"],h] for h in s["hours"]]
            if independent != result["counts"]:
                raise ValueError(f"Different hourly bicycle passages for {rule} at {s['name']}: {independent} vs {result['counts']}")
            if any(approaches[rule,s["key"],k] != n for k, n in result["approaches"].items()):
                raise ValueError(f"Different bicycle approaches for {rule} at {s['name']}")
    print(f"Checked all survey hours on {len(groups)} independent directed shortest-path trees.", flush=True)


def publish(archive, root, regional=False, clock=None, verify=False, market_run=None, bikeways=False,
            extra_sites=False, cycle_tours=False, combine_workplaces=False, hills=False):
    if cycle_tours and (regional or clock or market_run):
        raise ValueError("The published cycle outing scenario uses the original municipal weekday")
    if combine_workplaces and not cycle_tours:
        raise ValueError("Combining workplaces requires the cycle outing comparison")
    if not regional:
        extra_sites = extra_sites or all((archive/"data/raw/vancouver-arcgis"/(site[4]+".xlsx")).exists() for site in EXTRA)
    ptr = read(root/("current.json" if regional else "cityday/current.json"))
    saved = None
    if market_run:
        if regional or clock or len(market_run) != 64 or any(c not in "0123456789abcdef" for c in market_run):
            raise ValueError("An archived municipal market supplies its own extent and clock")
        saved = read(root/"market/archive"/market_run/"run.json")
        if saved["market"] != market_run or saved["city"] != "vancouver":
            raise ValueError("Archived market identity differs from its release")
        ptr, clock = saved, saved.get("clock")
    atlas, day = ptr["atlas"], ptr.get("day", ptr.get("version"))
    if clock == "household":
        clock = read(root/"household-clock"/(atlas+"_"+day+".json"))["version"]
    if clock:
        parent = read(root/"household-clock"/clock/"report.json")
        if saved and (parent["atlas"], parent["day"]) != (atlas, day):
            raise ValueError("Archived market and household clock have different parents")
        atlas, day = parent["atlas"], parent["day"]
        if regional and (atlas, day) != (ptr["atlas"], ptr["day"]):
            ptr = read(root/"releases"/(atlas+"_"+day+".json"))
    streets = ptr["streets"] if regional or saved else read(root/"streets/current.json")["version"]
    legs = read(root/"street-walks"/("_".join(filter(None, [atlas, day, clock]))+".json"))["version"]
    versions = dict(atlas=atlas, day=day, streets=streets, cycling=None, legs=legs, clock=clock)
    if saved:
        versions.update(saved.get("workplaceRuns") or {})
    elif not regional and not clock and (not cycle_tours or combine_workplaces):
        parent = atlas+"_"+day
        for family in ["outbound", "worksites", "tract-workplaces"]:
            pointer = root/family/(parent+".json")
            if not pointer.exists():
                break
            parent = read(pointer)["version"]
            versions[family] = parent
    if combine_workplaces and "outbound" not in versions:
        raise ValueError("Build municipal workplace assignments before combining them with cycle outings")
    fitted = {}
    if versions.get("outbound"):
        workplace = read(root/"outbound"/versions["outbound"]/"report.json")
        fitted = workplace.get("neighbourhoodFit") or {}
    cycling = fitted.get("cycling") or read(root/"cycling"/(streets+".json"))["version"]
    versions["cycling"] = cycling
    if cycle_tours:
        versions["tours"] = read(root/"cycle-tours"/("_".join([atlas, day, streets, cycling])+".json"))["version"]
    if bikeways or hills:
        versions["bikeways"] = read(root/"bikeways"/(cycling+("-hills" if hills else "")+".json"))["version"]
    def build(folder):
        audit = folder.parent/"candidate-legs.json"
        cmd = ["node", "scripts/vancouver_cycle_counts.mjs", str(root)]
        with (folder/"counts.json").open("w") as stream:
            subprocess.run(cmd+[str(audit)],
                           input=json.dumps(dict(versions=versions, sites=observations(archive, extra_sites), source=SOURCE)),
                           text=True, stdout=stream, check=True)
        report, legs = read(folder/"counts.json"), read(audit)
        add_junction_bounds(root, report, legs)
        if verify:
            verify_routes(root, report, legs)
        write_json(folder/"counts.json", report)
    version = package(root, "cycle-counts", build)
    report = read(root/"cycle-counts"/version/"counts.json")
    parent = root/"cycle-counts"
    work = versions.get("tract-workplaces") or versions.get("worksites") or versions.get("outbound")
    for work in ([work] if combine_workplaces else [None, work] if work else [None]):
        key = "_".join(filter(None, [atlas, day, cycling, clock, work, versions.get("tours"), versions.get("bikeways")]))
        with tempfile.TemporaryDirectory(dir=parent) as tmp:
            file = Path(tmp)/"pointer"
            write_json(file, dict(version=version))
            file.replace(parent/(key+".json"))
    for rule, run in report["runs"].items():
        print(rule, run["coverage"], [sum(s["counts"]) for s in run["sites"]], flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    p.add_argument("--region", action="store_true")
    p.add_argument("--clock")
    p.add_argument("--market-run", help="Replay the release recorded by a saved municipal market")
    p.add_argument("--verify", action="store_true")
    route = p.add_mutually_exclusive_group()
    route.add_argument("--bikeways", action="store_true", help="Prefer matched municipal bikeways within each diary time budget")
    route.add_argument("--hills", action="store_true", help="Prefer gentler routes and matched bikeways within the diary time budget")
    p.add_argument("--extra-sites", action="store_true", help="Include the municipal 2023 intersections in a regional build")
    p.add_argument("--cycle-tours", action="store_true", help="Score the original weekday and feasible discretionary cycling outings")
    p.add_argument("--combine-workplaces", action="store_true", help="Also apply census workplace and commute-mode assignments to the outing comparison")
    args = p.parse_args()
    publish(args.archive, args.data/"region" if args.region else args.data, args.region, args.clock, args.verify,
            args.market_run, args.bikeways, args.extra_sites, args.cycle_tours, args.combine_workplaces, args.hills)

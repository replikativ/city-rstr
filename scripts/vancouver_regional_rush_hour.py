"""Audit the regional weekday against Downtown travel observations.

Run each stage with python -m scripts.vancouver_regional_rush_hour STAGE,
then regenerate the evidence page with python -m scripts.preview_sources.
"""
import argparse
import csv
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path

import numpy as np

from scripts import vancouver_bridge_traffic as road
from scripts.vancouver_city_transit import DirectService, resident_trips
from scripts.vancouver_campus import access_routes
from scripts.vancouver_downtown import MODES, resident_flows, shared_minute_offset, station_counts
from scripts.vancouver_regional_inbound import commute_legs
from scripts.vancouver_regional_workplaces import TABLE, census_matrix
from scripts.vancouver_region import read


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


WORKPLACE_REPORT = "5bea5bc3322eb2bbae9f"


def workplace_report(region, run):
    fitted = read(region / "regional-workplaces" / WORKPLACE_REPORT / "report.json")
    if any(fitted["versions"][key] != run[key] for key in ("day", "atlas", "streets")):
        raise ValueError("Workplace comparison uses a different baseline")
    return fitted


def roads(region, run, probes):
    versions = {k: run[k] for k in ("atlas", "day", "streets")}
    bridges = road.BRIDGES[:3]
    source = probes / road.ARCHIVE
    sites = road.observations(source, bridges)
    network = read(region / "streets" / run["streets"] / "network.json")
    profile, routing = road.road_profile(region, run["streets"])
    places, incoming, _, workers = commute_legs(region, versions, run["regionalWorkers"], "Car driver")
    if sum(g["attending"] for g in workers["groups"].values()) != run["inbound"]:
        raise ValueError("Worker release and regional weekday disagree")
    residents = road.resident_legs(region, versions)
    fitted = workplace_report(region, run)
    if digest(region / "cityday" / fitted["day"] / "places.json") != workers["places"]:
        raise ValueError("The fitted workplace day uses different place identifiers")
    alternate = road.resident_legs(region, dict(versions, day=fitted["day"]))
    np.testing.assert_array_equal(residents[:, 3:], alternate[:, 3:])
    changed = np.any(residents[:, 1:3] != alternate[:, 1:3], axis=1)
    # Bits 1 and 4 represent baseline and fitted residents. Identical legs
    # can share one row and route. Incoming drivers (bit 2) enter both totals.
    residents[~changed, 0] = 5
    alternate = alternate[changed]
    alternate[:, 0] = 4
    incoming[:, 0] = 2
    legs = np.concatenate([residents, incoming, alternate])
    legs[:, 5] = -1  # No person-level examples are needed for this audit.
    coverage, searches = road.score(legs, places, network, sites, [], bridges=bridges, scenarios=3, profile=profile)
    return dict(source=road.SOURCE, sourceFile=source.name, sha256=digest(source), routing=routing,
                workplaceReport=WORKPLACE_REPORT, fittedDay=fitted["day"], changedDriverLegs=int(changed.sum()),
                coverage=coverage, searches=searches, sites=[
                    dict(name=s["name"], counters=s["counters"], resident=s["scenarios"][0]["counts"],
                         incoming=s["scenarios"][1]["counts"], fittedResident=s["scenarios"][2]["counts"]) for s in sites])


def inlet(region, run, probes):
    fitted = workplace_report(region, run)
    parents = {}

    def counts(family, day):
        versions = dict(atlas=run["atlas"], day=day, streets=run["streets"])
        root = region / family
        key = "_".join(versions.values()) + "_time.json"
        version = read(root / key)["version"]
        report = read(root / version / "counts.json")
        if report["versions"] != versions:
            raise ValueError(f"Bridge crossings use different inputs: {family}/{version}")
        parents[f"{family}/{day}"] = version
        return report

    baseline = counts("bridge-traffic", run["day"])
    alternative = counts("bridge-traffic", fitted["day"])
    incoming = counts("incoming-bridges", run["day"])
    if incoming["workerRelease"] != run["regionalWorkers"] or incoming["attending"] != run["inbound"]:
        raise ValueError("Incoming bridge counts use a different commuter cohort")
    if not baseline["routing"] == alternative["routing"] == incoming["routing"]:
        raise ValueError("Inconsistent driving speeds in the bridge comparison")
    for key, path in [("sourceDigest", probes / road.ARCHIVE),
                      ("ironworkersDigest", Path("data/mobility") / road.IRONWORKERS_FILE)]:
        if not baseline[key] == alternative[key] == digest(path):
            raise ValueError(f"Unmatched bridge counter archive: {path}")
    sites = []
    observations = [*road.observations(probes / road.ARCHIVE, road.REGIONAL_BRIDGES),
                    road.ironworkers_observations(Path("data/mobility") / road.IRONWORKERS_FILE)]
    for site, alt, observed in zip(baseline["sites"], alternative["sites"], observations, strict=True):
        if not (site["counters"] == alt["counters"] == observed["counters"]
                and site["key"] == alt["key"] == observed["key"]):
            raise ValueError("Unmatched bridge counter series")
        sites.append(dict(name=site["name"], counters=site["counters"], source=site.get("source", baseline["source"]),
                          resident=site["scenarios"][0]["counts"], fittedResident=alt["scenarios"][0]["counts"],
                          incoming=incoming["sites"][site["key"]]["counts"]))
    return dict(sites=sites, parents=parents, fittedDay=fitted["day"], routing=baseline["routing"],
                workplaceReport=WORKPLACE_REPORT, workerRelease=incoming["workerRelease"],
                vehicleCounterDigest=baseline["sourceDigest"], ironworkersDigest=baseline["ironworkersDigest"])


def demand(region, run):
    day = region / "cityday" / run["day"]
    atlas = region / "atlas" / run["atlas"]
    places = read(day / "places.json")
    result = resident_flows(day, atlas, places, workplace_ends=True)
    resident = np.array(result["counts"]).sum(axis=1)
    incoming = np.zeros_like(resident)
    shared_incoming = np.zeros_like(resident)
    workers = region / "incoming-workers" / run["regionalWorkers"]
    manifest = read(workers / "commuters.json")
    if manifest["places"] != digest(day / "places.json") or manifest["modes"] != MODES:
        raise ValueError("Worker destinations or mode ordering disagree")
    core = result["areas"].index("Downtown")
    ordinal = run["population"]
    for group in sorted(manifest["groups"]):
        for _, job, _, _, mode, leave, duration, span, attend, _ in read(workers / (group + ".json"))["people"]:
            if attend != 1:
                continue
            shift = shared_minute_offset(ordinal)
            ordinal += 1
            if places[job][2] == core:
                arrival, departure = leave + duration, leave + duration + span
                incoming[arrival // 60 % 24, 0, mode] += 1
                incoming[departure // 60 % 24, 1, mode] += 1
                shared_incoming[(arrival + shift) // 60 % 24, 0, mode] += 1
                shared_incoming[(departure + shift) // 60 % 24, 1, mode] += 1
    if ordinal != run["population"] + run["inbound"]:
        raise ValueError("External worker cohort differs from the published run")
    # Cross-check the modeled peak-hour totals on the shared diary clock while
    # retaining the rounded diary clock for the published evidence tables.
    shared_resident = np.array(resident_flows(day, atlas, places, shared_clock=True)["counts"]).sum(axis=1)
    overview = region.parents[1] / "overview"
    scene_id = read(overview / (run["release"] + ".json"))["scene"]
    scene = read(overview / (scene_id + ".json"))
    downtown = scene["areas"].index("Downtown")
    expected = np.zeros((24, 2), dtype=int)
    offset = scene["dayStart"] // 60
    excluded = {scene["areas"].index(label) for label in ("unresolved", "travelling")}
    for leave, arrive, origin, destination, count in scene["flows"]:
        if origin in excluded or destination in excluded:
            continue
        if origin != destination:
            if destination == downtown:
                expected[(arrive + offset) % 24, 0] += count
            if origin == downtown:
                expected[(leave + offset) % 24, 1] += count
    peak = [7, 8, 16, 17]
    np.testing.assert_array_equal(expected[peak], (shared_resident + shared_incoming).sum(axis=2)[peak])
    morning = result["morningDepartures"]
    assert sum(np.sum(v) for v in morning.values()) == resident[7:9, 1].sum()
    # The earlier workplace experiment retained its unmodified parent as "before".
    fitted = workplace_report(region, run)
    census = census_matrix(TABLE)
    np.testing.assert_array_equal(census, fitted["census"])
    if digest(TABLE) != fitted["sourceDigest"]:
        raise ValueError("Workplace matrix checksum mismatch")
    variant = region / "cityday" / fitted["day"]
    if digest(variant / "places.json") != manifest["places"]:
        raise ValueError("Cannot hold external workers fixed across these workplace assignments")
    alternative = resident_flows(variant, atlas, places)
    if alternative["areas"] != result["areas"]:
        raise ValueError("Workplace sensitivity has different geography")
    alternative_totals = np.array(alternative["counts"]).sum(axis=1) + incoming
    return dict(workplaceSensitivity=dict(day=fitted["day"], counts=alternative_totals.sum(axis=2).tolist()),
                morningDepartures=morning, areas=result["areas"], homeGroups=["Other resident", "Downtown resident"],
                workplaces=dict(municipalities=fitted["municipalities"], modeled=fitted["before"], fitted=fitted["after"], observed=census.tolist(),
                                source=fitted["source"], sourceDigest=fitted["sourceDigest"], report=WORKPLACE_REPORT),
                residentWorkplaceEnds=result["workplaceEnds"], modes=MODES, directions=["Arriving", "Departing"], resident=resident.tolist(), incoming=incoming.tolist())


def bicycles(region, run):
    versions = {k: run[k] for k in ("atlas", "day", "streets")}
    cycling = read(region / "cycling" / (run["streets"] + ".json"))["version"]
    key = "_".join([run["atlas"], run["day"], cycling])
    release = read(region / "cycle-counts" / (key + ".json"))["version"]
    report = read(region / "cycle-counts" / release / "counts.json")
    if any(report["versions"][k] != v for k, v in {**versions, "cycling": cycling}.items()) or report["versions"]["clock"]:
        raise ValueError("Cycle counts belong to a different weekday")
    return dict(cycleRelease=release, source=report["source"], coverage=report["runs"]["city"]["coverage"],
                sites=[dict(observation=s, modeled=m["counts"], approaches=m["approaches"])
                       for s, m in zip(report["sites"], report["runs"]["city"]["sites"], strict=True)])


def rail(region, run, probes):
    day = region / "cityday" / run["day"]
    trips, _ = resident_trips(region / "atlas" / run["atlas"], day)
    places, workers, _, _ = commute_legs(region, run, run["regionalWorkers"], "Public transit")
    base = read(region / "transit" / run["transit"] / "transit.json")
    # Same feed and service date, with regional rail and passenger access rules.
    schedule_id = "5688b19e3abeb58bd4a2"
    schedule = region / "transit" / schedule_id
    service = DirectService(schedule)
    manifest = service.route_manifest
    if any(base[k] != manifest[k] for k in ("date", "feed")):
        raise ValueError("Supplemental rail service is from another timetable")
    with zipfile.ZipFile(probes / "transit_translink_gtfs_static.zip") as z:
        types = {r["route_id"]: int(r["route_type"]) for r in csv.DictReader(io.TextIOWrapper(z.open("routes.txt"), encoding="utf-8-sig"))}
    pinned_rail = [r["id"] for r in base["routes"] if types[r["id"]] == 1]
    candidates = [[(start, duration, a, b) for _, _, start, duration, a, b in trips],
                  [(int(start), int(duration), int(a), int(b)) for _, a, b, start, duration, _, _ in workers]]
    endpoints = {p for group in candidates for _, _, a, b in group for p in (a, b)}
    access = access_routes(places, endpoints, service.stations, region / "streets" / run["streets"])
    match = service.matcher(access)
    table = probes / "transit_translink_tspr2025_skytrainavgalightsbrdgs_yearstationdaytypehourly.csv"
    result = dict(source="https://www.translink.ca/tspr", sourceFile=table.name, sha256=digest(table),
                  pinnedRailRoutes=pinned_rail, diagnosticTimetable=schedule_id, feed=base["feed"], date=base["date"])
    for cohort, group in zip(["resident", "incoming"], candidates, strict=True):
        rides = []
        for start, duration, a, b in group:
            if a in access and b in access and places[a][:2] != places[b][:2]:
                ride = match(start, duration, a, b)
                if ride:
                    rides.append([0, 0, start, duration, a, b, *ride])
        scored = station_counts(table, schedule, manifest, {"all": rides})
        result.update(observed=scored["observed"], stations=scored["stations"])
        result[cohort] = scored["matched"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["inlet", "roads", "demand", "bicycles", "rail"])
    parser.add_argument("output", type=Path, nargs="?", help="Defaults to the release-specific evidence file")
    parser.add_argument("--data", type=Path, default=Path("public/data"))
    parser.add_argument("--archive", type=Path, default=Path("../Simulations/city"))
    args = parser.parse_args()
    run, = [r for r in read(args.data / "runs/current.json") if r.get("regionalWorkers")]
    region = args.data / "vancouver/region"
    fn = {"inlet": inlet, "roads": roads, "rail": rail, "bicycles": bicycles, "demand": demand}[args.stage]
    params = [region, run] + ([args.archive / "data/raw/probes"] if args.stage in ("roads", "rail", "inlet") else [])
    result = dict(release=run["release"], **fn(*params))
    output = args.output or args.data / "vancouver/downtown-audit" / (run["release"] + "-" + args.stage + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=output.parent, delete=False) as out:
        json.dump(result, out, separators=(",", ":"))
    Path(out.name).chmod(0o644)
    Path(out.name).replace(output)


if __name__ == "__main__":
    main()

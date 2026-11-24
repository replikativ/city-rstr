"""Compare capacity-checked Downtown incoming commutes under fixed work shifts."""
import argparse
from bisect import bisect_right
from collections import Counter
import hashlib
from math import dist
from pathlib import Path
import re

from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_downtown import station_counts
from scripts.vancouver_downtown_transit_audit import downtown_window, incoming_inputs
from scripts.vancouver_incoming_duration_check import DISTANCE, DURATION, SOURCE, duration_margins, summarize
from scripts.vancouver_incoming_timing import as_booked, flex_window
from scripts.vancouver_outbound_transit import reservations
from scripts.vancouver_region import read
from scripts.vancouver_transit_commutes import pointer
from scripts.vancouver_transit_load import ANNUAL_TABLE, TABLE, BusSpaces, bus_capacity_profile, ride_legs
from scripts.vancouver_transit_reach import INF
from scripts.vancouver_transit_trace import JourneyTrace
from scripts.vancouver_work_transit import priority, transfer_inputs, window

STAGES = (0, 15, 30)


def keep_reservations(root, run, joint, incoming, booked, service, probes):
    outbound = root / "outbound-transit" / run["outboundTransit"]
    report = read(outbound / "report.json")
    if (report["joint"], report["incoming"], report["timetable"]) != (run["jointRun"], run["incomingTransit"], incoming["timetable"]):
        raise ValueError("External workplace bookings belong to a different weekday")
    profile = bus_capacity_profile(service.route_manifest, probes / TABLE, probes / ANNUAL_TABLE)
    if any(r["capacitySources"] != profile["sources"] for r in (report, incoming)):
        raise ValueError("The bus capacity proxies differ from the weekday")
    spaces = BusSpaces(profile["limits"])
    legs = reservations(root, joint, incoming)
    legs.extend(leg for row in booked.values() for leg in ride_legs(row[6:]))
    if len(legs) != report["reservedLegs"]:
        raise ValueError("The outbound layer reserved a different background")
    outgoing = [leg for da in report["areas"] for entry in read(outbound / f"{da}.json")
                for row in entry[3] for leg in ride_legs(row[6:])]
    spaces.preload(legs)
    spaces.preload(outgoing)
    verify_loads(spaces)
    return spaces


def verify_loads(spaces):
    if any(n > spaces.limits[route] for (route, _), loads in spaces.loads.items() for n in loads.values()):
        raise ValueError("An experimental booking exceeded a protected bus capacity")


def required_minutes(trace, row, maximum):
    def fits(extra):
        return trace.fits(*flex_window(row, extra))

    if not fits(maximum):
        return INF
    low, high = 0, maximum
    while low < high:
        middle = (low + high) // 2
        if fits(middle):
            high = middle
        else:
            low = middle + 1
    return low


def trial(trace, spaces, candidates, windows=STAGES):
    needed = {tuple(row[:3]): required_minutes(trace, row, windows[-1]) for row in candidates}
    recovered, stages = {}, []
    ordered = sorted(candidates, key=priority)
    for extra in windows:
        possible, denied = 0, 0
        for row in ordered:
            key = tuple(row[:3])
            minimum = needed[key]
            if key in recovered or minimum > extra:
                continue
            possible += 1
            option = trace.journey(*flex_window(row, minimum))
            if option is None:
                raise ValueError("An independently reachable window did not yield a journey")
            if not spaces.fits(option[2]):
                option = trace.journey(*flex_window(row, extra), available=spaces.available)
            if option is None:
                denied += 1
                continue
            spaces.reserve(option[2])
            recovered[key] = as_booked(row, option)
        stages.append((extra, possible, denied, dict(recovered)))
        print(f"{extra} extra minutes, {len(recovered):,} cumulative recovered trips", flush=True)
    verify_loads(spaces)
    return stages


def publish(data, release, archive, table):
    run = read(data / "runs" / f"{release}.json")
    root = data / "vancouver"
    if (run["release"], run["city"], run["coverage"]) != (release, "vancouver", "city"):
        raise ValueError("Choose a Vancouver municipal weekday")
    joint = read(root / "joint-weekday" / run["jointRun"] / "report.json")
    day = root / "cityday" / run["day"]
    places = read(day / "places.json")
    core = read(day / "day.json")["areas"].index("Downtown")
    incoming, _, _, groups, _, places, identities, _, booked = incoming_inputs(
        root, run["jointRun"], joint, run["incomingTransit"], places)
    probes = archive / "data/raw/probes"
    schedule = root / "transit" / incoming["timetable"]
    service = DirectService(schedule)
    spaces = keep_reservations(root, run, joint, incoming, booked, service, probes)
    selected = {key: (row, downtown_window(row, places, core)) for key, row in identities.items()
                if downtown_window(row, places, core)}
    pending = [row for key, (row, _) in selected.items() if key not in booked
               and places[row[4]][:2] != places[row[5]][:2]]
    street = root / "commuter-walk" / incoming["walking"]
    access, planner = transfer_inputs({window(row) for row in pending}, places, service, street, schedule)
    trace = JourneyTrace(service, access, planner.connections, incoming["boardingMargin"])
    candidates = [row for row in pending if row[4] in access and row[5] in access]
    stages = trial(trace, spaces, candidates)

    # The same inbound population, origin mix and distance bands are scored in every arm.
    margins = duration_margins(table, groups["groups"])
    population = {key: ((row[0], bisect_right(DISTANCE, dist(places[row[4]][:2], places[row[5]][:2]) / 1000) - 1), row[3])
                  for key, (row, _) in selected.items() if row[-1]}
    rail_table = probes / "transit_translink_tspr2025_skytrainavgalightsbrdgs_yearstationdaytypehourly.csv"
    benchmark = read(root / "downtown-audit" / f"{release}.json")
    rail_site = next(site for site in benchmark["sites"] if site["key"] == "downtownSkyTrain")
    if benchmark["parents"]["incomingTransit"] != run["incomingTransit"]:
        raise ValueError("The station benchmark uses different incoming commuters")

    def summarize_stage(extra, possible, denied, recovered):
        duration = summarize([(band, old, recovered[key][3] if key in recovered else old)
                              for key, (band, old) in population.items()], margins)
        recovered_inbound = [(band, old, recovered[key][3]) for key, (band, old) in population.items() if key in recovered]
        rail = station_counts(rail_table, schedule, service.route_manifest, {"new": recovered.values()})
        if rail["observed"] != incoming["rail"]["observed"] or rail["stations"] != rail_site["stations"]:
            raise ValueError("The experiment and published weekday use different station evidence")
        peaks = [[7, 9, "arriving"], [16, 18, "leaving"]]
        booked_by_slot = Counter(slot for key, (_, slot) in selected.items() if key in booked or key in recovered)
        peak_bookings = [sum(booked_by_slot[h, direction] for h in range(start, end)) for start, end, direction in peaks]
        station_counts_by_peak = [
            sum(rail["matched"][h][i] + rail_site["directions"][i]["hourly"]["modeled"][h] for h in range(start, end))
            for i, (start, end, _) in enumerate(peaks)]
        return dict(extraMinutes=extra, added=len(recovered), feasiblePending=possible, capacityDenied=denied,
                    downtownPeakBookings=peak_bookings, stationPeakCounts=station_counts_by_peak, duration=duration,
                    recoveredInbound=summarize(recovered_inbound, margins) if recovered_inbound else None)

    with table.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    evidence = dict(schema=1, release=release, incomingTransit=run["incomingTransit"],
                    parents=benchmark["parents"], durationSource=SOURCE, durationDigest=digest,
                    durationBands=DURATION, stationSource=rail_site["source"], eligible=len(selected),
                    initialBookings=sum(key in booked for key in selected),
                    observedStationPeakCounts=[rail_site["directions"][i]["windows"][i]["observed"] for i in range(2)],
                    scenarios=[summarize_stage(*stage) for stage in [(None, 0, 0, {}), *stages]])
    out = root / "downtown-audit" / f"{release}-booking.json"
    pointer(out, evidence)
    # Keep leg-level examples available to verify stop times and the fixed work boundary.
    proof = Path("target/downtown-transit-booking") / f"{release}.json"
    pointer(proof, {extra: [[list(key), identities[key], row] for key, row in recovered.items()]
                    for extra, _, _, recovered in stages})
    print(out, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("public/data"))
    parser.add_argument("--table", type=Path, default=Path("data/mobility/98100461-eng.zip"))
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{64}", args.release):
        parser.error("Choose a 64-character weekday ID")
    publish(args.data, args.release, args.archive, args.table)

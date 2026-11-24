"""Compare resident weekday trip demand with the North Shore surveys."""
import argparse
from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import subprocess
import tempfile

from scripts.vancouver_atlas import write_json
from scripts.vancouver_north_shore_zones import ZONE_NAMES, crosswalk, reference, workplace_groups
from scripts.vancouver_region import package, read
from scripts.vancouver_short_walks import gaps as stop_boundaries
from scripts.vancouver_trip_demand import destination, linked_trips

SURVEY = "https://docs.dnv.org/documents/FINAL_2023-North-Shore-Transportation-Survey.PDF"
SURVEY_DIGEST = "fea241ceae3da2b6f909e4f58203e95dc0ef2bb8ae8ba951a8db41ad6ae768a0"
SURVEY_ARCHIVE = Path("data/mobility/north-shore-transportation-survey-2023.pdf")
SURVEY_2025 = "https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Transportation-Plan/2025-North-Shore-Transportation-Survey-Report.pdf"
SURVEY_2025_DIGEST = "1899c623fc7e9cdd1d94fb1c655c33baa0be34bbaf3ca141ebbe2bedc8825be6"
SURVEY_2025_ARCHIVE = Path("data/mobility/north-shore-transportation-survey-2025.pdf")
NORTH_SHORE = "North Shore"
DOWNTOWN = "Downtown or West End"
VANCOUVER = "Rest of Vancouver or UBC"
OTHER_DESTINATION = "Beyond Vancouver and UBC"
EASTERN_DESTINATION = "Burnaby and New Westminster"

# Section 3.3 gives this hierarchy and places taxi, ride-hailing and motorcycles in Other.
SURVEY_PRIORITY = ("transit", "car-driver", "car-passenger", "taxi", "ridehail", "motorcycle",
                   "ferry", "air", "travel-other", "travel-ns", "bike", "walk")
SURVEY_MODES = {"car-driver": "Auto driver", "car-passenger": "Auto passenger", "transit": "Transit",
                "walk": "Walking", "bike": "Cycling"}
OTHER_MODE = "Other / unspecified"
MODES = [*SURVEY_MODES.values(), OTHER_MODE]
PURPOSES = ["Paid work", "Education", "Shopping and personal errands", "Dining", "Recreation",
            "Social", "Other or unclear", "Return home"]

# Table 4 population aged 15+, Table 8 counts in MODES order, and Table 7 shares
# in PURPOSES order. Sum usual work and work-related, shopping and personal
# business, and picking up or dropping off passengers and Other.
SURVEY_ROWS = {
    "City of North Vancouver": (52700, 157250, [87760, 8570, 16930, 37250, 4440, 2300],
                                 [18.0, 1.1, 17.5, 4.7, 8.4, 3.7, 8.5, 38.2]),
    "District of North Vancouver": (75400, 251460, [181970, 13580, 19980, 27140, 7120, 1680],
                                     [14.7, 1.6, 18.9, 3.4, 8.8, 3.6, 11.3, 37.8]),
    "West Vancouver": (40200, 116190, [87840, 9910, 9030, 8250, 740, 410],
                        [10.3, 2.4, 20.8, 2.8, 9.7, 3.9, 11.7, 38.2]),
}


def source_rows(wider=False):
    observations = {}
    for name, (population, total, modes, shares) in SURVEY_ROWS.items():
        observations[name] = dict(residents=population, trips=total, modes=dict(zip(MODES, modes, strict=True)),
                                  purposes={p: total * percent / 100 for p, percent in zip(PURPOSES, shares, strict=True)},
                                  hours={}, outbound={})
    # Section 3.1.2 reports only the two peak hours as numbers. Table 11
    # gives all-mode southbound trips leaving the North Shore by destination.
    observations[NORTH_SHORE] = dict(
        residents=168310, trips=524900,
        modes=dict(zip(MODES, [357570, 32070, 45930, 72640, 12300, 4390], strict=True)),
        purposes={p: round(sum(row["purposes"][p] for row in observations.values()), 2) for p in PURPOSES},
        hours={"8": 50600, "16": 51200},
        outbound={DOWNTOWN: 17870, VANCOUVER: 18160, OTHER_DESTINATION: 54580 - 17870 - 18160},
    )
    if wider:
        out = observations[NORTH_SHORE]["outbound"]
        uncovered = out.pop(OTHER_DESTINATION)
        out[EASTERN_DESTINATION] = 11540
        out["Other external destinations"] = uncovered - out[EASTERN_DESTINATION]
    return observations


def held_out_rows(wider=False):
    # Tables 21 and 27–30 have independently rounded totals, shares and modes.
    municipality = {
        "City of North Vancouver": (54800, 212600, [110800, 7700, 27200, 55900, 8500, 2800],
                                     [17, 1, 20, 5, 12, 4, 6, 37]),
        "District of North Vancouver": (75300, 311000, [188400, 18000, 28900, 64400, 9300, 2200],
                                         [13, 2, 18, 5, 15, 4, 8, 35]),
        "West Vancouver": (39100, 150100, [95900, 8900, 11600, 30200, 2000, 1800],
                            [20, 1, 17, 4, 16, 3, 5, 35]),
    }
    observations = {
        name: dict(residents=people, trips=total, modes=dict(zip(MODES, modes, strict=True)),
                   purposes={p: total * share / 100 for p, share in zip(PURPOSES, purposes, strict=True)},
                   hours={}, outbound={})
        for name, (people, total, modes, purposes) in municipality.items()
    }
    # Use the regional totals, which include more than the municipal rows.
    # Figure 29 and Table 26 omit Other mode and Return home totals respectively.
    # Figure 26 presents a chart without numerical hourly counts.
    outbound = {DOWNTOWN: 22000, VANCOUVER: 19100}
    if wider:
        outbound.update({EASTERN_DESTINATION: 12100, "Other external destinations": 2600 + 5300})
    else:
        outbound[OTHER_DESTINATION] = 12100 + 2600 + 5300
    observations[NORTH_SHORE] = dict(
        residents=174600, trips=698400,
        modes=dict(zip(MODES[:-1], [407200, 35600, 70500, 156400, 21000], strict=True)),
        purposes=dict(zip(PURPOSES[:-1], [78100 + 27100, 12500, 86900 + 42200, 32900, 97000, 23800, 48800], strict=True)),
        hours={}, outbound=outbound,
    )
    return observations


def survey_purpose(before, after, slot):
    proxy = destination(before, after)
    if proxy == "Shopping":
        return "Shopping and personal errands"
    if proxy != "Other or unclear" or after is None:
        return proxy
    activity, place = after[2:]
    if slot == "school" or (activity == "study" and place == "work-or-school"):
        return "Education"
    if place == "worship":
        return "Social"
    if place == "clinic" or (place in ("business", "store") and activity in ("housework", "housework-occasional", "personal-care")):
        return "Shopping and personal errands"
    return proxy


def trip_inputs(diary, template):
    slots = template["slots"]
    bouts = [[mode, survey_purpose(before, after, slots[b] if b >= 0 else None),
              start // 60 % 24, start + duration // 2, a, b, SURVEY_MODES.get(display, OTHER_MODE) == mode]
             for start, duration, mode, display, a, b, before, after in linked_trips(
                 diary, template, priority=SURVEY_PRIORITY, report=SURVEY_MODES)]
    gaps = [[a, b] for _, a, b, _, _ in stop_boundaries(template, diary)]
    return bouts, gaps


def model_rows(raw, outbound_destinations=(DOWNTOWN, VANCOUVER)):
    counts, examples = defaultdict(Counter), defaultdict(dict)
    for name, dimension, key, count, example in raw:
        if name == "Zones":
            continue
        key = tuple(key) if isinstance(key, list) else str(key)
        for geography in [name, NORTH_SHORE]:
            counts[geography, dimension][key] += count
            if example:
                examples[geography, dimension].setdefault(key, example)

    models = {}
    for name in [NORTH_SHORE, *SURVEY_ROWS]:
        row = {}
        for dimension, keys in (("modes", MODES), ("purposes", PURPOSES), ("hours", map(str, range(24))),
                                ("outbound", outbound_destinations)):
            cell = counts[name, dimension]
            row[dimension] = {k: [cell[k], examples[name, dimension].get(k)] for k in keys}
        trip_totals = [sum(n for n, _ in row[d].values()) for d in ("modes", "purposes", "hours")]
        coverage = counts[name, "coverage"]
        trips = trip_totals[0]
        if any(n != trips for n in trip_totals) or sum(n for label, n in coverage.items()
                                                       if label != "Unrecorded change of place") != trips:
            raise ValueError("North Shore trip totals do not reconcile by mode, purpose, time and coverage")
        outbound = {d: {m: counts[name, "outboundMode"][d, m] for m in MODES} for d in outbound_destinations}
        purpose_modes = {p: {m: counts[name, "purposeMode"][p, m] for m in MODES} for p in PURPOSES}
        if any(sum(modes.values()) != row["outbound"][d][0] for d, modes in outbound.items()):
            raise ValueError("North Shore outward demand does not reconcile by mode")
        if any(sum(modes.values()) != row["purposes"][p][0] for p, modes in purpose_modes.items()):
            raise ValueError("North Shore trip purposes do not reconcile by mode")
        models[name] = dict(row, residents=counts[name, "population"]["Residents"], trips=trips,
                            travelers=counts[name, "population"]["With recorded travel"],
                            coverage=coverage, outboundModes=outbound, purposeModes=purpose_modes)
    return models


def commute_zones(raw, areas, resident_count):
    result = reference(areas)
    residents, boundary, fallback = {}, {}, {}
    workplaces = defaultdict(dict)
    for label, dimension, key, count, example in raw:
        if label != "Zones":
            continue
        if dimension == "zoneWork":
            zone, workplace = key
            workplaces[workplace][zone] = [count, example]
        else:
            {"zonePopulation": residents, "zoneBoundary": boundary, "zoneFallback": fallback}[dimension][key] = count
    if sum(residents.values()) != resident_count or any(
            sum(cells.get(zone, [0])[0] for cells in workplaces.values()) > count
            for zone, count in residents.items()):
        raise ValueError("Survey zone population and commutes do not reconcile")
    for row in result["homeZones"]:
        zone = row["zone"]
        row.update(modelResidents=residents.get(zone, 0), nearBoundary=boundary.get(zone, 0),
                   fallback=fallback.get(zone, 0))
    for row in result["workplaces"]:
        cells = workplaces[row["key"]]
        row["model"] = [cells.get(zone, [0, None]) for zone in range(1, len(ZONE_NAMES) + 1)]
    result["unmappedResidents"] = residents.get(0, 0)
    result["unmappedWorkplaces"] = sum(x[0] for x in workplaces["Unmapped"].values())
    return result


def routed_gap_walks(root, roster, atlas, day, version, streets):
    path = root / "short-walks" / (version + "_" + streets + ".json")
    if not path.exists():
        return None
    data = read(path)
    if (data["atlas"], data["day"], data["streets"]) != (roster.name, version, streets):
        raise ValueError("Routed walks belong to a different regional weekday")
    groups = {da: name for name in SURVEY_ROWS for da in atlas["areas"][name]["das"]}
    by_area = defaultdict(list)
    for d, person, *_ in data["walks"]:
        da = day["das"][d]
        if da in groups and person < atlas["das"][da]["private"]:
            by_area[da].append(person)
    counts = Counter()
    for da, ids in by_area.items():
        people = read(roster / (da + ".json"))["people"]
        counts[groups[da]] += sum(3 <= people[i][0] <= 13 for i in ids)
    return {name: counts[name] for name in SURVEY_ROWS} | {NORTH_SHORE: counts.total()}


def verify_survey(path, digest):
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError(f"The archive differs from the North Shore survey reference at {path}")


def publish(root, atlas_version, days, survey, streets, survey_2025=None):
    verify_survey(survey, SURVEY_DIGEST)
    if survey_2025 is None and SURVEY_2025_ARCHIVE.exists():
        survey_2025 = SURVEY_2025_ARCHIVE
    if survey_2025 is not None:
        verify_survey(survey_2025, SURVEY_2025_DIGEST)
    roster = root / "atlas" / atlas_version
    atlas = read(roster / "atlas.json")
    for version in days:
        day_dir = root / "cityday" / version
        day = read(day_dir / "day.json")
        places = read(day_dir / "places.json")
        east = {"Burnaby", "New Westminster"}
        wider = bool(east & set(day["areas"]))
        observations = source_rows(wider)
        outbound = (DOWNTOWN, VANCOUVER, EASTERN_DESTINATION) if wider else (DOWNTOWN, VANCOUVER)
        areas = day["areas"]
        geography = [NORTH_SHORE if name in SURVEY_ROWS else DOWNTOWN if name in ("Downtown", "West End")
                     else EASTERN_DESTINATION if name in east else VANCOUVER for name in areas]
        bouts, gaps = zip(*(trip_inputs(d, t) for d, t in zip(atlas["templates"], day["templates"], strict=True)))
        zones = None
        if survey_2025 is not None:
            zones = crosswalk(survey_2025, atlas, roster, places, areas, SURVEY_ROWS)
            zones["workplaceGroups"] = workplace_groups(places, areas, zones["placeZones"], SURVEY_ROWS)
        with tempfile.TemporaryDirectory() as tmp:
            inputs, output = Path(tmp) / "inputs.json", Path(tmp) / "result.json"
            write_json(inputs, dict(municipalities=list(SURVEY_ROWS), trips=bouts, gaps=gaps,
                                    geography=[geography[p[2]] if p[2] >= 0 else None for p in places],
                                    zones=zones))
            subprocess.run(["clojure", "-J-Xmx1g", "-M", "-m", "city.vancouver.north-shore-demand",
                            roster, day_dir, inputs, output], check=True)
            counts = read(output)
            model = model_rows(counts, outbound)
        report = dict(atlas=atlas_version, day=version, observations=observations, model=model,
                      source=SURVEY, sourceDigest=SURVEY_DIGEST)
        if survey_2025 is not None:
            commute_check = commute_zones(counts, areas, model[NORTH_SHORE]["residents"])
            commute_check["usedInFit"] = day.get("workplaceFit") == SURVEY_2025_DIGEST
            report["heldOut2025"] = dict(source=SURVEY_2025, sourceDigest=SURVEY_2025_DIGEST,
                                         observations=held_out_rows(wider), commuteZones=commute_check)
        if wider:
            report["widerDestinations"] = True
        walks = routed_gap_walks(root, roster, atlas, day, version, streets)
        if walks is not None:
            for name, count in walks.items():
                if count > model[name]["coverage"].get("Unrecorded change of place", 0):
                    raise ValueError("The inferred walks exceed the unrecorded changes of place")
            report.update(gapWalks=walks, gapStreetRelease=streets)
        release = package(root, "north-shore-demand", lambda out: write_json(out / "report.json", report))
        folders = root / "north-shore-demand"
        with tempfile.TemporaryDirectory(dir=folders) as tmp:
            pointer = Path(tmp) / "pointer.json"
            index = {"version": release}
            if walks is not None:
                index["gapStreetRelease"] = streets
            write_json(pointer, index)
            pointer.replace(folders / (atlas_version + "_" + version + ".json"))
        print(version, release, model[NORTH_SHORE]["residents"], model[NORTH_SHORE]["trips"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--survey", type=Path, default=SURVEY_ARCHIVE)
    parser.add_argument("--survey-2025", type=Path, help="Path to the independently published 2025 survey PDF.")
    parser.add_argument("--day", action="append", help="Publish a named regional weekday. Repeat for multiple weekdays.")
    args = parser.parse_args()
    current = read(args.region / "current.json")
    publish(args.region, current["atlas"], args.day or [current["day"]], args.survey, current["streets"], args.survey_2025)

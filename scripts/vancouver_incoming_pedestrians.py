"""Count incoming workers' stop and transfer walks at the city's pedestrian surveys."""
import argparse
from functools import lru_cache
from pathlib import Path

from scripts.artifacts import pointer, read
from scripts.vancouver_walks import RADIUS, passing_minute


def itinerary_walks(row, access, egress, stop_times):
    """Use the same starts and durations as the scheduled passenger replay, in seconds."""
    if row[10]:
        yield "access", row[2]*60, row[10], access
    ride = row[6:]
    while len(ride) > 6:
        follow = ride[6]
        _, alight = stop_times(*ride[:4])
        seconds, _, walk = follow[4:7]
        if seconds:
            yield "transfer", alight, seconds, walk
        ride = [*follow[:4], 0, row[11], *follow[7:]]
    if row[11]:
        _, alight = stop_times(*ride[:4])
        yield "egress", alight, row[11], egress


def publish(root, release):
    incoming = root / "incoming-transit" / release
    report = read(incoming / "report.json")
    parent = read(root / "joint-weekday" / report["joint"] / "pedestrians.json")
    if parent["radius"] != RADIUS or parent["transit"]["riders"] != report["residentRiders"] or any(
        parent[k] != v for k, v in report["versions"].items()
    ):
        raise ValueError("Incoming transit and pedestrian observations use different weekday inputs")
    station_root = root / "transit" / report["timetable"]

    @lru_cache(maxsize=None)
    def route(key):
        return read(station_root / f"{key}.json")

    def stop_times(key, trip, board, alight):
        _, start, times, _ = route(key)["rides"][trip]
        return start+times[2*board+1], start+times[2*alight]

    modes = ("access", "transfer", "egress")
    sites = [dict(name=site["name"], hours=site["hours"], resident=site["joint"], observed=site["observed"],
                  **{mode: [0]*len(site["hours"]) for mode in modes}) for site in parent["sites"]]
    indexes = [{hour: i for i, hour in enumerate(s["hours"])} for s in sites]
    checked = 0
    for group, (_, count) in report["groups"].items():
        if not count:
            continue
        rows = read(incoming / f"{group}.json")
        paths = read(incoming / f"{group}-walks.json")
        for row, (person, minute, access, egress) in zip(rows, paths, strict=True):
            if row[:3] != [group, person, minute]:
                raise ValueError("Incoming walks and vehicle journeys are out of order")
            checked += 1
            for kind, start, duration, walk in itinerary_walks(row, access, egress, stop_times):
                for i, site in enumerate(parent["sites"]):
                    passing = passing_minute(walk, site["point"], start/60, duration/60)
                    hour = None if passing is None else int(passing//60)*60
                    if hour in indexes[i]:
                        sites[i][kind][indexes[i][hour]] += 1
    if checked != sum(count for _, count in report["groups"].values()):
        raise ValueError("The pedestrian scenario omitted incoming journeys")
    for site in sites:
        site["added"] = list(map(sum, zip(*(site[k] for k in modes), strict=True)))
    pointer(root / "incoming-pedestrians" / f"{release}.json",
            dict(joint=report["joint"], incoming=release, radius=RADIUS, journeys=checked, sites=sites))
    print(release, [(site["name"], sum(site["added"])) for site in sites], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    args = parser.parse_args()
    publish(args.root, args.release)

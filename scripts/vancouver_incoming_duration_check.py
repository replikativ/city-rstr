"""Standardize Census transit duration bands to the modeled origin and distance mix."""
import argparse
from bisect import bisect_right
from collections import Counter
import csv
import hashlib
from math import dist
from pathlib import Path
from zipfile import ZipFile

from scripts.vancouver_region import read
from scripts.vancouver_transit_commutes import pointer


DISTANCE = (0, 1, 3, 5, 7, 10, 15, 20, 25, 30, 35)
DURATION = (0, 15, 30, 45, 60)
SOURCE = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810046101"


def duration_margins(path, groups):
    """Read only the usual-workplace transit counts with departure time pooled."""
    groups = {"2021A0005"+group for group in groups}
    result = {}
    with ZipFile(path) as archive, archive.open("98100461.csv") as rows:
        header = next(csv.reader([next(rows).decode("utf-8-sig")]))
        duration = header.index("Commuting duration (7):Less than 15 minutes[2]")
        columns = [header.index(k) for k in ("DGUID", "Time leaving for work (7)", "Statistics (3)", "Main mode of commuting (11A)", "Coordinate")]
        # The public archive contains every Canadian CSD. Filter before decoding the CSV rows.
        lines = (line.decode("utf-8") for line in rows if b"2021A00055915" in line and b"Public transit" in line
                 and b"Total - Time leaving for work" in line)
        for row in csv.reader(lines):
            home, departure, statistic, mode, coordinate = (row[i] for i in columns)
            band = int(coordinate.split(".")[1])-2
            if home not in groups or departure != "Total - Time leaving for work" or statistic != "Count" or mode != "Public transit" or band < 0:
                continue
            key = home[-7:], band
            if key in result or band >= len(DISTANCE):
                raise ValueError("Duplicate or unexpected distance band in the Census table")
            cells = [row[duration+i:duration+i+2] for i in range(0, 12, 2)]
            valid = all(value and not symbol for value, symbol in cells)
            counts = tuple(int(value) for value, _ in cells[:-1]) if valid else ()
            result[key] = (counts, float(cells[-1][0])) if counts and sum(counts) else None
    return result


def summarize(rows, margins):
    eligible = len(rows)
    prior, revised, expected = [0]*5, [0]*5, [0.0]*5
    coverage = Counter()
    means = [0.0, 0.0, 0.0]
    for key, old, new in rows:
        sample = margins.get(key)
        if sample is None:
            continue
        counts, mean = sample
        support = sum(counts)
        prior[bisect_right(DURATION, old)-1] += 1
        revised[bisect_right(DURATION, new)-1] += 1
        expected = [n+count/support for n, count in zip(expected, counts, strict=True)]
        means = [a+b for a,b in zip(means, (old,new,mean), strict=True)]
        coverage[key[0]] += 1
    comparable = sum(coverage.values())
    if not comparable:
        raise ValueError("No modeled commutes are supported by published origin and distance cells")
    errors = [sum(abs(actual-n) for actual,n in zip(hist, expected, strict=True))*100/(5*comparable)
              for hist in (prior, revised)]
    return dict(eligible=eligible, compared=comparable, byOrigin=coverage, original=prior, replay=revised,
                observedExpected=expected, meanMinutes=[total/comparable for total in means], maePoints=errors)


def publish(root, table, release):
    report = read(root / "incoming-transit" / release / "report.json")
    timing = read(root / "incoming-timing-presence" / f"{release}.json")
    if timing["incoming"] != release or timing["workerRelease"] != report["workerRelease"]:
        raise ValueError("The travel clock belongs to a different cohort")
    folder = root / "commuters" / report["workerRelease"]
    workers = read(folder / "commuters.json")
    places = read(root / "cityday" / report["versions"]["day"] / "places.json")
    homes = read(root / "incoming-transit" / release / "homes.json")
    mode = workers["modes"].index("Public transit")
    margins = duration_margins(table, workers["groups"])
    rows, retimed = [], []
    offset = 0
    for group in sorted(workers["groups"]):
        cohort = read(folder / f"{group}.json")
        for person, (home, job, _, _, usual, start, duration, _, attends, _) in enumerate(cohort["people"]):
            if not attends or usual != mode:
                continue
            kilometres = dist(homes[offset+home][:2], places[job][:2])/1000
            key = group, bisect_right(DISTANCE, kilometres)-1
            override = timing["windows"].get(group, {}).get(str(person), [None, None])[0]
            revised = duration+(start-override if override is not None else 0)
            rows.append((key, duration, revised))
            if override is not None:
                retimed.append((key, duration, revised))
        offset += len(cohort["homes"])
    if offset != len(homes):
        raise ValueError("The commuter home addresses and origin groups did not reconcile")
    with table.open("rb") as archive:
        digest = hashlib.file_digest(archive, "sha256").hexdigest()
    data = dict(source=SOURCE, digest=digest, incoming=release, joint=report["joint"],
                distanceLowerKm=DISTANCE, durationLowerMinutes=DURATION,
                attendingTransit=summarize(rows, margins), retimedTowardWork=summarize(retimed, margins))
    pointer(root / "incoming-duration-check" / f"{release}.json", data)
    for label in ("attendingTransit", "retimedTowardWork"):
        row = data[label]
        print(label, row["eligible"], row["compared"], row["meanMinutes"], row["maePoints"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--table", type=Path, default=Path("data/mobility/98100461-eng.zip"))
    args = parser.parse_args()
    publish(args.root, args.table, args.release)

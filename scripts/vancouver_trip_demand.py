"""Publish release-bound resident trip counts for the municipal survey comparison."""
import argparse
from collections import Counter
from pathlib import Path
import subprocess
import tempfile

from scripts.vancouver_atlas import write_json
from scripts.vancouver_inbound import read
from scripts.vancouver_mobility import REPORT, SOURCE, SURVEY, travel_bouts
from scripts.vancouver_region import package
from scripts.vancouver_survey_zones import geography

# Table 16, in the published zone order. Rounding is retained.
MODES = ["Auto driver", "Auto passenger", "Transit", "Walking", "Cycling"]
SHARES = [[21, 6, 15, 52, 6], [23, 8, 15, 51, 3], [32, 6, 20, 36, 6],
          [44, 8, 15, 21, 12], [54, 3, 14, 23, 7], [38, 4, 18, 28, 12],
          [58, 9, 16, 12, 5], [44, 8, 22, 19, 7], [36, 7, 10, 34, 13]]
# Figure 36 gives citywide purpose shares. Table 16 gives mode shares by zone.
PURPOSES = {"Paid work": 15, "Shopping": 13, "Dining": 6, "Recreation": 9,
            "Social": 5, "Return home": 38, "Other or unclear": None}
# Section 1.3 population expansion and Figure 46 citywide purpose volumes
# and whole-number mode percentages, in MODES order.
SURVEY_ADULTS = 584_700
PURPOSE_MODE_ROWS = {
    "Paid work": [(197_800, [36, 4, 29, 17, 14]), (78_900, [47, 5, 21, 21, 6])],
    "Shopping": [(220_800, [40, 6, 10, 38, 6])],
    "Dining": [(101_200, [29, 9, 11, 47, 4])],
    "Recreation": [(152_900, [30, 7, 8, 42, 13])],
    "Social": [(86_700, [40, 12, 18, 26, 4])],
}


def survey_purpose_modes():
    purposes = {}
    for purpose, rows in PURPOSE_MODE_ROWS.items():
        trips = sum(volume for volume, _ in rows)
        mode_trips = {mode: sum(volume * shares[i] / 100 for volume, shares in rows)
                      for i, mode in enumerate(MODES)}
        purposes[purpose] = {"trips": trips, "modeTrips": mode_trips}
    return {"adults": SURVEY_ADULTS, "purposes": purposes}


def destination(before, after):
    if after is None:
        return "Other or unclear"
    activity, place = after[2:]
    if place == "home":
        return "Return home" if before and before[3] not in ("home", "unknown", "elsewhere") else "Other or unclear"
    if activity == "paid-work":
        return "Paid work"
    if activity == "shopping":
        return "Shopping"
    if place == "restaurant" and activity in ("eating", "socializing"):
        return "Dining"
    if activity in ("sports", "leisure-out"):
        return "Recreation"
    if activity == "socializing":
        return "Social"
    return "Other or unclear"


def linked_trips(diary, template, **mode_rules):
    trips = travel_bouts(diary["episodes"], **mode_rules)
    parts = [p for p in template["parts"] if p[2] != "stop"]
    for (start, mode, before, after), (s, duration, display, a, b) in zip(trips, parts, strict=True):
        if start != s:
            raise ValueError("Diary and spatial replay disagree on the travel start")
        yield start, duration, mode, display, a, b, before, after


def trip_terms(diary, template):
    return [[mode, destination(before, after), start + duration // 2, a, b,
             REPORT.get(display, "Other / unspecified") == mode]
            for start, duration, mode, display, a, b, before, after in linked_trips(diary, template)]


def publish(root, boundaries, day_id=None, atlas_id=None):
    ptr = read(root / "cityday/current.json")
    atlas = root / "atlas" / (atlas_id or ptr["atlas"])
    day = root / "cityday" / (day_id or ptr["version"])
    model, population = read(day / "day.json"), read(atlas / "atlas.json")
    geo = geography(boundaries, read(day / "places.json"))
    zones = [{"code": str(z["code"]), "name": z["name"], "shares": dict(zip(MODES, shares, strict=True))}
             for z, shares in zip(geo["zones"], SHARES, strict=True)]
    trips = [trip_terms(d, t) for d, t in zip(population["templates"], model["templates"], strict=True)]
    with tempfile.TemporaryDirectory() as tmp:
        inputs = Path(tmp) / "inputs.json"
        write_json(inputs, {"trips": trips, "zone": geo["zone"], "zones": zones})

        def build(folder):
            result = Path(tmp) / "counts.json"
            subprocess.run(["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.trip-demand",
                            atlas, day, inputs, result], check=True)
            data = read(result)
            # Independently verify every mode and the adult denominator against the
            # existing published municipal mobility audit before making the pointer visible.
            modes = Counter()
            for z, m, purpose, fifths, example, donors in data["cells"]:
                modes[m] += fifths
            audit = read(day / "mobility.json")["main"]
            if modes != {k: round(5 * v) for k, v in audit["modes"].items()} or sum(data["adults"].values()) != round(5 * audit["people"]):
                raise ValueError("Zonal counts do not conserve the published municipal weekday")
            write_json(folder / "demand.json", dict(data, city="vancouver", atlas=atlas.name, day=day.name,
                       zones=zones, cityShares=SURVEY["shares"], purposeShares=PURPOSES, source=SOURCE,
                       geography=geo["digest"], purposeModeSurvey=survey_purpose_modes()))

        version = package(root, "trip-demand", build)
    target = root / "trip-demand" / (atlas.name + "_" + day.name + ".json")
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        pointer = Path(tmp) / "pointer"
        write_json(pointer, {"version": version})
        pointer.replace(target)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--boundaries", type=Path, default=Path("data/mobility/taz-gvrd.geojson"))
    parser.add_argument("--day", help="Use a published weekday under the current atlas")
    args = parser.parse_args()
    print(publish(args.root, args.boundaries, args.day))

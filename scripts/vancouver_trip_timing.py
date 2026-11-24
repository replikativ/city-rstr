"""Compare a combined Vancouver weekday with the City's observed peak-period trip purposes."""
import argparse
from collections import Counter
from pathlib import Path
import subprocess
import tempfile

from scripts.vancouver_atlas import write_json
from scripts.vancouver_region import package, read
from scripts.vancouver_transit_commutes import pointer
from scripts.vancouver_trip_demand import destination, linked_trips

PURPOSES = ["Paid work", "Shopping", "Dining", "Recreation", "Social", "Return home", "Other or unclear"]
SHOPPING = PURPOSES.index("Shopping")
HOME = PURPOSES.index("Return home")
SOURCE = "https://vancouver.ca/files/cov/2025-transportation-survey-report.pdf"
SURVEY_ADULTS = 609_000  # Table 2, adults in private households
# Figures 19–21. Combine the two work purposes and sum the other published categories.
# Retain the survey rounding, including columns that add to 99% or 101%.
PERIODS = [
    ("am", "Morning peak", 420, 540, 260_000, [58, 2, 2, 8, 2, 7, 20]),
    ("pre-pm", "Afternoon before rush hour", 840, 960, 257_700, [8, 19, 4, 7, 4, 41, 18]),
    ("pm", "Afternoon peak", 960, 1080, 359_200, [2, 12, 6, 9, 6, 54, 11]),
]


def template_inputs(diary, template):
    trips = [[start, PURPOSES.index(destination(before, after))]
             for start, *_, before, after in linked_trips(diary, template)]
    episodes = diary["episodes"]
    at = {row[0]: i for i, row in enumerate(episodes)}
    gaps = []
    for left, right in zip(template["parts"], template["parts"][1:]):
        if left[2] == right[2] == "stop":
            i = at[right[0]]
            gaps.append([right[0], left[3], right[3], PURPOSES.index(destination(episodes[i - 1], episodes[i]))])
    return trips, gaps


def period_summary(counts, tours, das, period):
    key, label, start, end, survey_total, percentages = period
    lo, hi = start - 240, end - 240
    recorded, inferred, fitted = ([sum(row[lo:hi]) / 5 for row in counts[layer]]
                                  for layer in ("recorded", "inferred", "fitted"))
    combined = [r + w + s for r, w, s in zip(recorded, inferred, fitted, strict=True)]
    shopping_minutes = [sum(counts[layer][SHOPPING][i] for layer in ("recorded", "inferred", "fitted"))
                        for i in range(lo, hi)]
    peak = max(shopping_minutes)
    peak_minute = start + shopping_minutes.index(peak)
    examples = [row for row in tours if start <= row[2] and row[2] + row[3] // 2 < end and row[3] > 1]
    example = None
    if examples:
        d, i, leave, there, _ = min(examples, key=lambda row: (abs(row[2] - peak_minute), row[0], row[1]))
        example = [das[d], i, leave + there // 2]
    return dict(key=key, label=label, start=start, end=end, surveyTrips=survey_total, surveyShares=percentages,
                recorded=recorded, combined=combined, fittedShopping=fitted[SHOPPING], example=example,
                shoppingPeak=[peak_minute, peak / 5] if peak else None,
                shoppingDepartures=[count / 5 for count in shopping_minutes])


def publish(root, joint_id):
    joint_dir = root / "joint-weekday" / joint_id
    joint = read(joint_dir / "report.json")
    versions = joint["versions"]
    atlas_dir = root / "atlas" / versions["atlas"]
    day_dir = root / "cityday" / versions["day"]
    atlas, day = read(atlas_dir / "atlas.json"), read(day_dir / "day.json")
    short = read(joint_dir / "short-walks.json")
    tours_dir = root / "discretionary-outings" / joint["outings"]
    outings = read(tours_dir / "report.json")
    tours = read(tours_dir / "tours.json")
    if (any(short.get(k) != v or outings["versions"].get(k) != v for k, v in versions.items())
            or len(tours) != outings["attendance"] or len(tours) != joint["shoppingOutings"]
            or len(short["walks"]) != joint["shortWalks"]):
        raise ValueError("The combined day and its additions have inconsistent releases")
    shopping = [[d, i, start, there, dwell]
                for d, i, _, _, purpose, mode, start, there, dwell, *_ in tours
                if purpose == "Shopping" and mode == "walk"]
    if len(shopping) != len(tours):
        raise ValueError("Expected the fitted city shopping walks")
    inputs = [template_inputs(d, t) for d, t in zip(atlas["templates"], day["templates"], strict=True)]
    with tempfile.TemporaryDirectory() as tmp:
        request, output = (Path(tmp) / name for name in ("timing-inputs.json", "minute-counts.json"))
        write_json(request, dict(purposes=PURPOSES, shopping=SHOPPING, returnHome=HOME,
                                 diaries=[x[0] for x in inputs], gaps=[x[1] for x in inputs],
                                 shortWalks=short["walks"], shoppingWalks=shopping))
        subprocess.run(["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.trip-timing",
                        atlas_dir, day_dir, request, output], check=True)
        counts = read(output)
    demands = root / "trip-demand"
    demand_id = read(demands / f"{versions['atlas']}_{versions['day']}.json")["version"]
    demand = read(demands / demand_id / "demand.json")
    recorded = {purpose: sum(row) for purpose, row in zip(PURPOSES, counts["recorded"], strict=True)}
    reference = Counter()
    for _, _, purpose, fifths, *_ in demand["cells"]:
        reference[purpose] += fifths
    totals = {layer: sum(map(sum, counts[layer])) for layer in ("recorded", "inferred", "fitted")}
    if (recorded != reference or counts["adults"] != sum(demand["adults"].values())
            or totals["inferred"] != round(5 * short["adultWalks"])
            or totals["fitted"] != 10 * len(tours)):
        raise ValueError("The timing counts do not conserve the released adult trips")
    report = dict(schema=1, joint=joint_id, versions=versions, tripDemand=demand_id, outings=joint["outings"],
                  source=SOURCE, surveyAdults=SURVEY_ADULTS, modelAdults=counts["adults"] / 5, purposes=PURPOSES,
                  modelTotals={k: v / 5 for k, v in totals.items()},
                  periods=[period_summary(counts, shopping, day["das"], period) for period in PERIODS])

    def build(folder):
        write_json(folder / "report.json", report)

    version = package(root, "trip-timing", build)
    pointer(root / "trip-timing" / f"{joint_id}.json", {"version": version})
    print(version)
    for row in report["periods"]:
        print(row["key"], "recorded", row["recorded"], "combined", row["combined"], "peak", row["shoppingPeak"])
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("joint")
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    args = parser.parse_args()
    publish(args.root, args.joint)

"""Compare paired municipal diary releases with the 2025 home-zone survey."""
import argparse
from collections import defaultdict
from pathlib import Path

import numpy as np

from scripts.artifacts import pointer, read
from scripts.vancouver_trip_demand import MODES

SOURCE = "https://vancouver.ca/files/cov/2025-transportation-survey-report.pdf"
# Table 14, by home zone, in the trip-demand mode order.
OBSERVED = {
    "210": (23,7,18,46,6), "220": (23,5,15,52,5), "330": (33,7,17,33,10),
    "340": (42,8,19,24,7), "350": (56,9,12,18,4), "360": (34,6,23,31,7),
    "370": (59,8,17,13,3), "380": (44,6,21,24,5), "390": (39,6,14,30,11),
}
CITY = (40,7,18,29,6)
CITY_ADULTS = 609_034
CITY_TRIPS = 1_881_800


def zonal_counts(demand):
    counts = defaultdict(lambda: np.zeros(len(MODES)+1))
    index = {mode:i for i,mode in enumerate(MODES)}
    for zone,mode,_,fifths,*_ in demand["cells"]:
        counts[zone][index.get(mode,len(MODES))] += fifths/5
    return counts


def scores(original, alternatives):
    all_runs = [original,*alternatives]
    zones = {z["code"]:z["name"] for z in original["zones"]}
    if zones.keys()!=OBSERVED.keys() or any(
        (r["zones"],r["geography"],r["adults"]) != (original["zones"],original["geography"],original["adults"])
        for r in alternatives
    ):
        raise ValueError("The demand comparisons must use the same homes and survey boundaries")

    groups = []
    for demand in all_runs:
        counts = zonal_counts(demand)
        rows = []
        for code, target in OBSERVED.items():
            nums = counts[code]
            if nums[:-1].sum() <= 0:
                raise ValueError(f"No comparable trips in home zone {code}")
            shares = nums[:-1]*100/nums[:-1].sum()
            rows.append(dict(code=code,shares=shares.tolist(),unclassified=float(nums[-1])))
        abs_error = np.array([np.abs(np.array(row["shares"])-OBSERVED[row["code"]]) for row in rows])
        city = sum(counts.values())
        groups.append(dict(atlas=demand["atlas"],day=demand["day"],zones=rows,
                           meanError=float(abs_error.mean()),byMode=abs_error.mean(axis=0).tolist(),
                           cityShares=(city[:-1]*100/city[:-1].sum()).tolist(),
                           cityTrips=float(city[:-1].sum()),unclassified=float(city[-1]),
                           adults=sum(demand["adults"].values())/5))
    return dict(source=SOURCE,year=2025,table=14,modes=MODES,geography=original["geography"],
                surveyCity=dict(shares=CITY,adults=CITY_ADULTS,trips=CITY_TRIPS),
                zones=[dict(code=key,name=zones[key],observed=observed) for key,observed in OBSERVED.items()],runs=groups)


def publish(root, baseline, fitted, extra=()):
    family = root/"trip-demand"
    releases = [baseline,fitted,*extra]
    original,*alternatives = (read(family/release/"demand.json") for release in releases)
    report = scores(original,alternatives)
    report["demandReleases"] = releases
    pointer(root/"diary-fit"/(alternatives[0]["atlas"]+"_zone-check.json"),report)
    print([(r["atlas"],round(r["meanError"],2)) for r in report["runs"]],flush=True)
    return report


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline",help="Original trip-demand release")
    parser.add_argument("fitted",help="Income-fitted trip-demand release")
    parser.add_argument("extra",nargs="*",help="Additional trip-demand releases for the same households and homes")
    parser.add_argument("--root",type=Path,default=Path("public/data/vancouver"))
    args=parser.parse_args()
    publish(args.root,args.baseline,args.fitted,args.extra)

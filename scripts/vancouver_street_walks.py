"""Publish the complete roster's trip index for street-level replay."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from scripts.artifacts import package, read, write_json


def publish(root, versions, clock=None, census=False, *, atlas_root=None, day_root=None, clock_family="household-clock"):
    atlas, day = versions["atlas"], versions["day"]
    parent = "_".join(filter(None, [atlas, day, clock]))
    family = "street-walks"
    def build(out):
        subprocess.run(["clojure", "-J-Xmx1500m", "-M", "-m", "city.vancouver.street-walks",
                        (atlas_root or root/"atlas")/atlas, (day_root or root/"cityday")/day, out,
                        root/clock_family/clock/"clock.json" if clock else "-",
                        "census" if census and not clock else "diary"], check=True)
    version = package(root, family, build)
    with tempfile.TemporaryDirectory(dir=root/family) as tmp:
        f = Path(tmp)/"pointer"
        write_json(f, dict(version=version))
        f.replace(root/family/(parent+".json"))
    print(root, version, read(root/family/version/"walks.json"), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    p.add_argument("--region", action="store_true")
    p.add_argument("--clock", help="Household clock version, or 'household' for the current match")
    p.add_argument("--day", help="Publish another existing weekday for the current atlas")
    args = p.parse_args()
    root = args.data/"region" if args.region else args.data
    ptr = read(root/("current.json" if args.region else "cityday/current.json"))
    versions = dict(atlas=ptr["atlas"], day=args.day or ptr.get("day", ptr.get("version")))
    clock = args.clock
    if clock == "household":
        clock = read(root/"household-clock"/(versions["atlas"]+"_"+versions["day"]+".json"))["version"]
    if clock:
        versions = read(root/"household-clock"/clock/"report.json")
    publish(root, versions, clock, census=not args.region)

"""Compare both published weekdays with 2021 Census Profile time leaving for work."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from scripts.vancouver_atlas import write_json
from scripts.vancouver_census_geography import CITY, DA, profile_cells
from scripts.vancouver_population_check import read
from scripts.vancouver_region import NAMES, package


def household_times(index, atlas, das):
    from scripts.vancouver_outbound import household_profiles
    times, ambiguous = {}, 0
    for da in das:
        codes = []
        for start, _, profile, multiple in household_profiles(
                read(atlas / (da + ".json")), index, np.random.default_rng([20261124, int(da)])):
            if start != len(codes):
                raise ValueError("Nonconsecutive private household roster")
            codes.extend(profile)
            ambiguous += multiple
        times[da] = codes
    return dict(times=times, ambiguous=ambiguous)


def publish(root, archive, match=False, balance=True, fixed_lengths=True, scope="both", region_versions=None):
    runs = []
    requested = {CITY}
    municipalities = {name: "2021A0005" + csd for csd, name in NAMES.items()}
    for base in {"both": (root, root / "region"), "city": (root,), "region": (root / "region",)}[scope]:
        regional = base != root
        ptr = region_versions if regional and region_versions else read(base / ("current.json" if regional else "cityday/current.json"))
        atlas = base / "atlas" / ptr["atlas"]
        day = base / "cityday" / ptr["day" if regional else "version"]
        das = read(atlas / "atlas.json")["das"].keys()
        requested.update(DA + d for d in das)
        direct = municipalities if regional else {"All city residents": CITY}
        requested.update(direct.values())
        runs.append((base, atlas, day, das, direct))

    if match:
        from scripts.vancouver_outbound import donor_index
        index = donor_index(archive / "data/raw/statcan/pumf/data_donnees_2021_hier_v2.csv", "PWLEAVE")
        diaries = json.loads(subprocess.check_output(["clojure", "-M", "-m", "city.vancouver.atlas-diaries", archive]))

    ids = range(2617, 2624)
    cells = profile_cells(archive / "data/raw/statcan", requested, set(ids))
    def counts(key):
        row = cells[key]
        if row[2617] and all(row[i] is not None for i in ids):
            return [int(row[i]) for i in ids]

    for base, atlas, day, das, direct in runs:
        with tempfile.TemporaryDirectory() as tmp:
            reference = Path(tmp) / "reference.json"
            write_json(reference, dict(das={d: counts(DA + d) for d in das},
                                       direct={name: counts(key) for name, key in direct.items()}))
            name = "household-clock" if match else "departures"
            inputs = []
            if match:
                population = read(atlas / "atlas.json")
                if any(d["episodes"] != t["episodes"] for d, t in zip(diaries, population["templates"])) or len(diaries) + 3 != len(population["templates"]):
                    raise ValueError("Donor diary library differs from this population release")
                source = Path(tmp) / "households.json"
                write_json(source, {**household_times(index, atlas, das),
                                    "balance": balance, "fixedLengths": fixed_lengths, "diaries": [[d["role"], d["age"], d["weight"]] for d in diaries]})
                inputs = [source]

            def build(folder):
                namespace = "household-clock" if match else "departures"
                subprocess.run(["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver." + namespace,
                                atlas, day, reference, *inputs, folder if match else folder / "report.json"], check=True)
            version = package(base, name, build)
        if match:
            from scripts.vancouver_street_walks import publish as publish_walks
            publish_walks(base, dict(atlas=atlas.name, day=day.name), version)
        prefix = ("all_" if not balance else "") + ("longer_" if not fixed_lengths else "")
        target = base / name / (prefix + atlas.name + "_" + day.name + ".json")
        with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
            pointer = Path(tmp) / "pointer"
            write_json(pointer, dict(version=version))
            pointer.replace(target)
        print(base, version, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--match-households", action="store_true")
    parser.add_argument("--scope", choices=("city", "region", "both"), default="both")
    parser.add_argument("--all-matches", action="store_true", help="Build the unrestricted household match as a separate comparison")
    parser.add_argument("--allow-longer-trips", action="store_true", help="Publish the longer-duration sensitivity under a separate pointer")
    args = parser.parse_args()
    publish(args.root, args.archive, args.match_households or args.all_matches or args.allow_longer_trips,
            not args.all_matches, not args.allow_longer_trips, args.scope)

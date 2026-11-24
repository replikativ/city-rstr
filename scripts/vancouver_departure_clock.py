"""Publish an all-resident departure timing sensitivity with the original trip chains."""
import argparse
from collections import Counter
from pathlib import Path
import subprocess
import tempfile

from scripts.vancouver_atlas import write_json
from scripts.vancouver_market import archive_market, publish_market
from scripts.vancouver_region import package, read
from scripts.vancouver_street_walks import publish as publish_streets


def advertise(root, key, version):
    with tempfile.TemporaryDirectory(dir=root) as staging:
        pointer = Path(staging) / "pointer.json"
        write_json(pointer, {"version": version})
        pointer.replace(root / (key + ".json"))


def retime_hired(root, model, clock_dir, atlas, day, streets):
    family = root / "hired-rides"
    key = "_".join([atlas, day, streets])
    if not (family / (key + ".json")).exists():
        return
    parent = read(family / (key + ".json"))["version"]
    result = read(family / parent / "rides.json")
    result["versions"]["clock"] = clock_dir.name
    result["parentRides"] = parent
    rows = result["rows"]
    clock = read(clock_dir / "clock.json")
    times = {}
    for d, row in enumerate(clock["templates"], start=len(model["templates"])):
        times[d] = [p[0] for p in row["day"]["parts"]]
    changed = {d: {i: (old, new) for i, old, new in clock["changes"][da]}
               for d, da in enumerate(model["das"])}
    baseline = Counter((row[6], row[2]) for row in rows)
    ex = result["example"]
    for row in rows:
        d, i, start, duration, *rest = row
        if (pair := changed[d].get(i)) is None:
            continue
        old, new = pair
        for k, (minute, length, mode, _, _) in enumerate(model["templates"][old]["parts"]):
            if (minute, length) == (start, duration) and mode != "stop":
                shifted = times[new][k]
                if shifted // 60 != start // 60:
                    raise ValueError("A shifted hired ride changed its departure hour")
                row[2] = shifted
                if ex is not None and ex[:4] == [d, i, start, duration]:
                    ex[2] = shifted
                break
        else:
            raise ValueError("A shifted hired ride must match its original resident trip")
    shifted = Counter((row[6], row[2]) for row in rows)
    result["spread"] = {mode: {"at17": [baseline[mode, 1020], shifted[mode, 1020]],
                              "peakMinute": [max(n for (m, _), n in hist.items() if m == mode)
                                             for hist in [baseline, shifted]]}
                        for mode in ("taxi", "ridehail") if any(m == mode for m, _ in baseline)}
    version = package(root, "hired-rides", lambda out: write_json(out / "rides.json", result))
    advertise(family, key + "_" + clock_dir.name, version)
    print("Hired ride clock", version, result["spread"], flush=True)


def publish_clock_market(root, clock_dir, model, atlas, day, streets):
    parent = root / "market" / (day + "_" + streets + ".json")
    if not parent.exists():
        return
    market = read(parent)
    if (market["atlas"], market["day"], market["streets"]) != (atlas, day, streets):
        raise ValueError("The grocery catalogue and departure clock use different weekdays")
    schedule = read(clock_dir / "clock.json")
    templates = model["templates"] + [entry["day"] for entry in schedule["templates"]]
    residents = {(o[0], o[1]) for o in market["occasions"]}
    changes = {(d, i): (old, new) for d, da in enumerate(model["das"])
               for i, old, new in schedule["changes"][da] if (d, i) in residents}
    stop_timing = []
    for occasion in market["occasions"]:
        d, i, slot, start, dwell = occasion[:5]
        inbound, outbound, _, _, tpl = occasion[11:16]
        old, new = changes.get((d, i), (tpl, tpl))
        if old != tpl:
            raise ValueError("Grocery occasion and departure clock disagree on the resident diary")
        k = next(k for k, part in enumerate(templates[old]["parts"])
                 if part == [start, dwell, "stop", slot, slot])
        left, stop, right = templates[new]["parts"][k - 1:k + 2]
        arrive, leave = stop[0], stop[0] + stop[1]
        if old != new:
            episodes = schedule["templates"][new - len(model["templates"])]["diary"]["episodes"]
            if [start, dwell, "shopping", "store"] not in episodes:
                raise ValueError("A shifted grocery trip changed its shopping episode")
        if (stop[2:] != ["stop", slot, slot] or left[2] != "walk" or right[2] != "walk" or
                (left[1], right[1]) != (inbound, outbound) or left[0] + inbound != arrive or right[0] != leave or
                not arrive <= start < start + dwell <= leave):
            raise ValueError("A shifted grocery trip changed the shopping window or walking budgets")
        occasion[15] = new
        stop_timing.append(None if (arrive, leave) == (start, start + dwell) else [arrive, leave])
    parent_market = archive_market(root, parent, read(parent))
    market.update(clock=clock_dir.name, clockKind="spread-departures", parentMarket=parent_market, stopTiming=stop_timing)
    version = publish_market(root, market)
    print("Grocery clock", version, len(stop_timing), sum(t is not None for t in stop_timing), flush=True)


def publish(city_root, regional, day_id):
    root = city_root / "region" if regional else city_root
    pointer = read(root / ("current.json" if regional else "cityday/current.json"))
    atlas = pointer["atlas"]
    day = day_id or pointer.get("day", pointer.get("version"))
    streets = pointer.get("streets") or read(root / "streets/current.json")["version"]
    atlas_dir, day_dir = root / "atlas" / atlas, root / "cityday" / day

    def build(out):
        subprocess.run(["clojure", "-J-Xmx1800m", "-M", "-m", "city.vancouver.departure-clock",
                        atlas_dir, day_dir, out], check=True)

    family = "departure-clock"
    version = package(root, family, build)
    clock_dir = root / family / version
    print(root, version, read(clock_dir / "report.json"), flush=True)
    publish_streets(root, {"atlas": atlas, "day": day}, version, clock_family=family)
    model = read(day_dir / "day.json")
    retime_hired(root, model, clock_dir, atlas, day, streets)
    if not regional:
        publish_clock_market(root, clock_dir, model, atlas, day, streets)
    advertise(root / family, atlas + "_" + day, version)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--region", action="store_true")
    parser.add_argument("--day")
    args = parser.parse_args()
    publish(args.data, args.region, args.day)

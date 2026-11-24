"""Compare a published population footprint with the 2021 Census geographic hierarchy."""
import argparse
from collections import Counter
import csv
import hashlib
import io
import json
import mmap
from pathlib import Path
import tempfile
from zipfile import ZipFile


CITY = "2021A00055915022"
DA = "2021S0512"


def profile_index(raw):
    path = next(raw.glob("*Geo_starting_row_BritishColumbia.CSV"))
    with path.open(encoding="cp1252") as f:
        for row in csv.DictReader(f):
            yield row["Geo Code"]


def area_membership(raw, municipalities):
    areas = {}
    subdivision = None
    for code in profile_index(raw):
        if code.startswith("2021A0005"):
            subdivision = code[-7:]
        elif code.startswith(DA) and subdivision in municipalities:
            da = code[-8:]
            if da in areas:
                raise ValueError(f"Duplicate census area {da}")
            areas[da] = subdivision
    if set(areas.values()) != set(municipalities):
        raise ValueError("Missing census subdivision in profile index")
    return areas


def profile_cells(raw, keys, required, *, columns=None):
    order = [code for code in profile_index(raw) if code in keys]
    if set(order) != keys:
        raise ValueError("Requested geography missing from Census Profile index")
    profile = next(raw.glob("*_data_BritishColumbia.csv"))
    result = {}
    with profile.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        for key in order:
            needle = f'2021,"{key}",'.encode()
            offset = mm.find(needle, mm.tell())
            if offset < 0:
                raise ValueError(f"Missing census geography {key}")
            mm.seek(offset)
            cells = {}
            while len(cells) < len(required):
                line = mm.readline()
                if not line.startswith(needle):
                    raise ValueError(f"Incomplete census profile {key}")
                row = next(csv.reader([line.decode("cp1252")]))
                k = int(row[8])
                if k in required:
                    cells[k] = ([float(row[i]) if row[i] else None for i in columns] if columns is not None
                                else float(row[11]) if row[11] else None)
            result[key] = cells
    return result


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records(archive, member, encoding="utf-8-sig"):
    with ZipFile(archive) as z, z.open(member) as stream:
        yield from csv.DictReader(io.TextIOWrapper(stream, encoding=encoding, errors="strict"))


def compare(replay_ids, geographic, csd, *, profile_population=None):
    selected = set(replay_ids)
    centres = {}
    population = Counter()
    municipal = set()
    names = {}
    for r in records(geographic, "2021_92-151_X.csv", "latin-1"):
        da = r["DAUID_ADIDU"]
        if r["CSDUID_SDRIDU"] == csd:
            municipal.add(da)
        if da in selected or da in municipal:
            names[da] = r["CSDNAME_SDRNOM"]
            population[da] += int(r["DBPOP2021_IDPOP2021"])
            point = (float(r["DARPLONG_ADLONG"]), float(r["DARPLAT_ADLAT"]))
            if centres.setdefault(da, point) != point:
                raise ValueError(f"Inconsistent census representative points for {da}")
    if not municipal or not selected.issubset(centres) or len(replay_ids) != len(selected):
        raise ValueError("Invalid municipal code or atlas dissemination areas for the census geography")
    if profile_population is not None:
        for da in replay_ids:
            if population[da] != profile_population[da]:
                raise ValueError(f"Census Profile and geographic block population differ for {da}")
    ids = list(replay_ids) + sorted(municipal - selected)
    missing = {d: population[d] for d in sorted(municipal - selected)}
    adjacent = {d: population[d] for d in sorted(selected - municipal)}
    boundary = dict(inReplay=len(replay_ids), municipalPopulation=sum(population[d] for d in municipal),
                    municipal=[d in municipal for d in ids], missing=missing, adjacent=adjacent)
    boundary.update(municipality=csd, adjacentAreas={d: names[d] for d in adjacent},
                    source=digest(geographic), municipalAreas=len(municipal))
    return ids, [centres[da] for da in ids], boundary


def publish(atlas_dir, version, boundary):
    # This companion report can be regenerated for an existing immutable atlas.
    summary = {k: v for k, v in boundary.items() if k != "municipal"}
    summary["atlas"] = version
    with tempfile.TemporaryDirectory(dir=atlas_dir) as tmp:
        out = Path(tmp)/"boundary.json"
        out.write_text(json.dumps(summary, separators=(",", ":")))
        out.replace(atlas_dir/("boundary-"+version+".json"))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path("public/data/vancouver/atlas"))
    p.add_argument("--geography", type=Path, default=Path("data/mobility/2021_92-151_X.zip"))
    p.add_argument("--csd", default="5915022")
    opts = p.parse_args()
    version = json.loads((opts.root/"current.json").read_text())["version"]
    ids = json.loads((opts.root/version/"atlas.json").read_text())["das"]
    _, _, report = compare(ids, opts.geography, opts.csd)
    publish(opts.root, version, report)

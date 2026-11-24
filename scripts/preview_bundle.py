"""Assemble a static city preview from published runs and the compiled browser."""
import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

from scripts.preview_sources import PUBLIC

# City data releases use 20 hex digits and run/market manifests use 64.
VERSION = re.compile(rb"(?<![0-9a-f])(?:[0-9a-f]{64}|[0-9a-f]{20})(?![0-9a-f])")
PUBLIC_TYPES = {".json", ".geojson", ".bin", ".png", ".webp", ".jpg", ".pbf", ".gz", ".js", ".css", ".txt"}


def version_ids(data):
    return set(VERSION.findall(data))


def assets(public, data):
    """Resolve immutable release folders and composite lookup keys to a fixed point."""
    known = set()
    selected = {}
    families = defaultdict(list)
    for path in shell_files(public):
        rel = path.relative_to(public)
        if rel.parts[0] == "data" or any(part.startswith(".") for part in rel.parts) or not path.is_file():
            continue
        selected[rel] = path
        if path.suffix in {".js", ".html", ".json"}:
            known.update(version_ids(path.read_bytes()))
    for folder, dirs, files in os.walk(data):
        dirs[:] = sorted(name for name in dirs if not name.startswith((".", "tmp")))
        for name in sorted(files):
            path = Path(folder, name)
            if name.startswith(".") or path.suffix not in PUBLIC_TYPES:
                continue
            rel = path.relative_to(data)
            families[frozenset(version_ids(rel.as_posix().encode()))].append((Path("data") / rel, path))
    while True:
        ready = [key for key in families if key <= known]
        if not ready:
            return selected
        for key in ready:
            for rel, path in families.pop(key):
                selected[rel] = path
                # Per-area roster shards, coordinate arrays and tile data contain
                # no release links. Named JSON reports and pointers do.
                if path.suffix == ".json" and not path.stem.isdecimal():
                    known.update(version_ids(path.read_bytes()))


def shell_files(public):
    for child in sorted(public.iterdir()):
        if child.name != "data":
            if child.is_dir():
                yield from child.rglob("*")
            else:
                yield child


def check_roots(files, data):
    pinned = json.loads(files[Path("sources/weekday.json")].read_text())["runs"]
    catalog = json.loads((data / "runs/current.json").read_text())
    for entry in pinned:
        if not any(r["release"] == entry["release"] and r["city"] == entry["city"] for r in catalog):
            raise ValueError(f"Preview catalogue is missing the pinned {entry['city']} weekday")
    for run in catalog:
        release = run["release"]
        record = json.loads(files[Path("data/runs", release + ".json")].read_text())
        if record["release"] != release:
            raise ValueError(f"Run manifest mismatch for {release}")
        overview = Path("data/overview")
        def pointer(suffix):
            p = json.loads(files[overview / (release + suffix + ".json")].read_text())
            if p["release"] != release:
                raise ValueError(f"Overview pointer belongs to another release: {release}{suffix}")
            return p
        scene, traces, cases = pointer(""), pointer("-traces"), pointer("-cases")
        if len(traces["hours"]) != 24:
            raise ValueError(f"Incomplete local day for {release}")
        shards = {scene["scene"], traces["roads"], cases["cases"], *traces["hours"]}
        if run["city"] == "stuttgart":
            shards.add(traces["origins"])
        for digest, suffix in [(s, ".json") for s in shards] + [(scene[k], ".gz") for k in ("schedules", "agents")]:
            with files[overview / (digest + suffix)].open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise ValueError(f"Overview file changed: {digest}")
        if run["city"] == "stuttgart":
            for name, expected in record["files"].items():
                with files[Path("data/stuttgart", release, name)].open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                        raise ValueError(f"Stuttgart export changed: {name}")
        else:
            root = Path("data/vancouver")
            if run["coverage"] == "region":
                root /= "region"
            for family, key, name in [("atlas","atlas","atlas.json"),("cityday","day","day.json"),
                                      ("streets","streets","network.json"),("streets","streets","maplibre-gl.js"),
                                      ("streets","streets","maplibre-gl.css"),("streets","streets","LICENSE.txt")]:
                if root / family / run[key] / name not in files:
                    raise ValueError(f"Missing {family} for {release}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=PUBLIC / "data")
    parser.add_argument("--output", type=Path, default=Path("dist/city-previews"))
    parser.add_argument("--pinned-data", action="store_true",
                        help="Select and verify the exact data files recorded for the reviewed release")
    args = parser.parse_args()
    expected = {}
    if args.pinned_data:
        with gzip.open(PUBLIC.parent / "deploy/weekday-data.sha256.gz", "rt") as stream:
            for line in stream:
                digest, name = line.rstrip("\n").split("  ", 1)
                rel = Path(name)
                if (not re.fullmatch("[0-9a-f]{64}", digest) or rel.parts[:1] != ("data",)
                        or ".." in rel.parts or rel in expected):
                    parser.error(f"Invalid pinned data entry: {name}")
                expected[rel] = digest
        files = {path.relative_to(PUBLIC): path for path in shell_files(PUBLIC)
                 if path.is_file() and not any(p.startswith(".") for p in path.relative_to(PUBLIC).parts)}
        files.update({rel: args.data.joinpath(*rel.parts[1:]) for rel in expected})
    else:
        files = assets(PUBLIC, args.data)
    check_roots(files, args.data)
    for name in ("explorer.html", "lab/overview.css", "js/app/main.js", "js/experiments/saved.js", "js/vancouver/workplaces.js", "js/replay/replay.js"):
        if Path(name) not in files:
            parser.error(f"Compile the browser with npm run release first. Missing {name}")
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output) as tmp:
        stage = Path(tmp) / "city"
        stage.mkdir()
        manifest = stage / "SHA256SUMS"
        with manifest.open("w") as out:
            for rel, source in sorted(files.items()):
                dest = stage / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
                with dest.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if rel in expected and digest != expected[rel]:
                    raise ValueError(f"Data differs from reviewed release: {rel}")
                out.write(f"{digest}  {rel.as_posix()}\n")
        release = hashlib.sha256(manifest.read_bytes()).hexdigest()
        dest = args.output / release
        if not dest.exists():
            stage.rename(dest)
        link = Path(tmp) / "current"
        link.symlink_to(release)
        link.replace(args.output / "current")
        print(f"{dest} ({len(files)} files)")


if __name__ == "__main__":
    main()

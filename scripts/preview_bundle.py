"""Assemble a static city preview from published runs and the compiled browser."""
import argparse
import gzip
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

from html.parser import HTMLParser
from urllib.parse import urlsplit

from scripts.preview_sources import PUBLIC

class EvidenceLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {"src", "href"} and value and value.startswith("data/"):
                self.paths.add(Path(urlsplit(value).path))


def assets(public, data):
    # Ignored browser output directories can still contain retired builds.
    compiled = ("js/app/main.js", "js/experiments/saved.js", "js/replay/replay.js")
    files = {p.relative_to(public): p for child in public.iterdir() if child.name not in {"data", "js"}
             for p in (child.rglob("*") if child.is_dir() else [child]) if p.is_file()
             and not any(part.startswith(".") for part in p.relative_to(public).parts)}
    for name in compiled:
        path = public / name
        if not path.is_file():
            raise ValueError(f"Missing {name}. Compile the explorer with npm run release.")
        files[Path(name)] = path

    def include(rel, checksum=None):
        rel = Path(rel)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"Invalid data path: {rel}")
        path = data / rel
        if not path.is_file():
            raise ValueError(f"Missing published data: {rel}")
        if checksum:
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != checksum:
                    raise ValueError(f"Checksum mismatch: {rel}")
        files[Path("data") / rel] = path
        return path

    catalog = json.loads(include("runs/current.json").read_text())
    pinned = json.loads((public / "sources/weekday.json").read_text())["runs"]
    if not all(any(r["city"] == p["city"] and r["release"] == p["release"] for r in catalog) for p in pinned):
        raise ValueError("Catalogue is missing a cited weekday")
    for run in catalog:
        release = run["release"]
        if not re.fullmatch("[0-9a-f]{64}", release):
            raise ValueError(f"Invalid run ID: {release}")
        manifest = json.loads(include(f"runs/{release}.json").read_text())
        if (manifest["release"], manifest["city"]) != (release, run["city"]):
            raise ValueError(f"Invalid run manifest: {release}")

        def pointer(suffix):
            obj = json.loads(include(f"overview/{release}{suffix}.json").read_text())
            if obj["release"] != release:
                raise ValueError(f"Overview pointer belongs to another release: {release}{suffix}")
            return obj

        scene, traces, cases = pointer(""), pointer("-traces"), pointer("-cases")
        if len(traces["hours"]) != 24:
            raise ValueError(f"Incomplete day: {release}")
        shards = {scene["scene"], traces["roads"], cases["cases"], *traces["hours"]}
        if run["city"] == "stuttgart":
            shards.add(traces["origins"])
            for name, digest in manifest["files"].items():
                include(Path("stuttgart", release, name), digest)
        for ext, digests in (("json", shards), ("gz", {scene["schedules"], scene["agents"]})):
            for digest in digests:
                if not re.fullmatch("[0-9a-f]{64}", digest):
                    raise ValueError(f"Invalid overview checksum: {digest}")
                include(f"overview/{digest}.{ext}", digest)

    links = EvidenceLinks()
    for html in public.glob("*.html"):
        links.feed(html.read_text())
    for path in links.paths:
        include(path.relative_to("data"))
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=PUBLIC / "data")
    parser.add_argument("--output", type=Path, default=Path("dist/city-previews"))
    parser.add_argument("--pinned-data", action="store_true",
                        help="Select and verify the exact data files recorded for the reviewed release")
    args = parser.parse_args()
    files = assets(PUBLIC, args.data)
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
        actual = {rel for rel in files if rel.parts[0] == "data"}
        if actual != expected.keys():
            parser.error("Reviewed inventory differs from the explorer data dependencies")
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

"""Build the shared explorer's engine products for the published city catalogue."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT.parent / "Simulations/city")
    parser.add_argument("--data", type=Path, default=ROOT / "public/data")
    parser.add_argument("--release", help="Regenerate the engine product for one catalogue release")
    args = parser.parse_args()
    data = args.data.resolve()
    archive = args.archive.resolve()
    runs = json.loads((data / "runs/current.json").read_text())
    if args.release:
        runs = [r for r in runs if r["release"] == args.release]
        if not runs:
            parser.error("Unknown catalogue release")
    cp = subprocess.check_output(["clojure", "-Spath"], cwd=ROOT, text=True).strip()
    classpath = os.pathsep.join(str((ROOT / path).resolve()) for path in cp.split(os.pathsep))
    with tempfile.TemporaryDirectory(dir=data.parent.parent, prefix=".weekday-build-") as tmp:
        if any(r["city"] == "stuttgart" for r in runs):
            inputs = Path(tmp) / "data"
            inputs.mkdir()
            (inputs / "raw").symlink_to(archive / "data/raw")
            shutil.copytree(archive / "data/derived", inputs / "derived")
        for run in sorted(runs, key=lambda r: r["city"] == "stuttgart"):
            subprocess.run(["java", "-Xmx5g", "-XX:ActiveProcessorCount=5",
                            "--add-modules=jdk.incubator.vector", "--enable-native-access=ALL-UNNAMED",
                            "-cp", classpath, "clojure.main", "-m", "city.overview",
                            str(data), run["release"]], cwd=tmp, check=True)
    subprocess.run(["node", "scripts/overview_traces.mjs", str(data), str(archive),
                    *([args.release] if args.release else [])], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()

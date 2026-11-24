"""Serve the built public directory at the production mount point on loopback."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8191)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "public")
    args = parser.parse_args()
    public = args.directory.absolute()
    for name in ("runs.html", "js/app/main.js", "js/experiments/saved.js", "data/runs/current.json"):
        if not (public / name).is_file():
            parser.error(f"Missing preview asset: {public / name}")
    with TemporaryDirectory() as tmp:
        (Path(tmp) / "city").symlink_to(public, target_is_directory=True)
        handler = partial(SimpleHTTPRequestHandler, directory=tmp)
        with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
            print(f"http://127.0.0.1:{server.server_port}/city/", flush=True)
            server.serve_forever()


if __name__ == "__main__":
    main()

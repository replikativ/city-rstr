"""Read and publish the versioned files exchanged by offline city producers."""
import errno
import hashlib
import json
from pathlib import Path
import tempfile


def read(path):
    return json.loads(path.read_bytes())


def write_json(file, obj):
    file.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False),
                    encoding="utf-8")


def _package_digest(folder, seed):
    digest = hashlib.sha256(seed.encode())
    for file in sorted(folder.iterdir()):
        digest.update(file.name.encode())
        with file.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
    return digest.hexdigest()


def package(root, name, fn, seed=""):
    """Publish a flat directory using the existing seeded, 20-hex release ID."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        payload = Path(tmp) / "payload"
        payload.mkdir()
        fn(payload)
        digest = _package_digest(payload, seed)
        version = digest[:20]
        destination = folder / version
        if not destination.exists():
            try:
                payload.rename(destination)
                return version
            except OSError as exc:
                # Another producer can install the same immutable release first.
                if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY) or not destination.is_dir():
                    raise
        if _package_digest(destination, seed) != digest:
            raise ValueError(f"Published artifact differs at {destination}")
        return version


def pointer(path, info):
    """Switch a JSON pointer atomically on the same filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        pending = Path(tmp) / "pointer"
        write_json(pending, info)
        pending.replace(path)

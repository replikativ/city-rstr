import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from threading import Barrier
import unittest

from scripts.artifacts import package, pointer, read, write_json


class ArtifactTests(unittest.TestCase):
    def test_concurrent_publication_preserves_legacy_id_and_bytes(self):
        wait = Barrier(2)
        value = {"store": "Épicerie", "weights": [2.0, 1]}
        wire = '{"store":"Épicerie","weights":[2.0,1]}'.encode()
        expected = hashlib.sha256(b"seed" + b"a.json" + wire + b"z.txt" + b"end").hexdigest()[:20]

        def build(folder):
            (folder / "z.txt").write_bytes(b"end")
            write_json(folder / "a.json", value)
            wait.wait(timeout=10)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(package, root, "stores", build, "seed") for _ in range(2)]
                self.assertEqual([job.result() for job in futures], [expected, expected])
            payload = root / "stores" / expected / "a.json"
            self.assertEqual(payload.read_bytes(), wire)
            self.assertEqual(read(payload), value)
            current = root / "pointers" / "current.json"
            pointer(current, {"version": expected})
            with self.assertRaises(ValueError):
                pointer(current, {"invalid": float("nan")})
            self.assertEqual(current.read_bytes(), f'{{"version":"{expected}"}}'.encode())
            self.assertEqual(list(current.parent.iterdir()), [current])

    def test_failed_build_and_corrupt_previous_release(self):
        def build(folder):
            (folder / "part").write_bytes(b"content")

        def fail(folder):
            build(folder)
            raise RuntimeError("interrupted")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                package(root, "products", fail)
            folder = root / "products"
            self.assertEqual(list(folder.iterdir()), [])
            version = package(root, "products", build)
            (folder / version / "part").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "Published artifact differs"):
                package(root, "products", build)

import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
from tifffile import imwrite

from scripts.vancouver_terrain import Elevation, TILE, WORLD, composite, terrain_rgb, tile_centres


class TerrainTest(unittest.TestCase):
    def test_projected_pixel_centres_combine_valid_neighbours_and_fall_back(self):
        # GeoTIFF origin at the NW corner, with non-square pixels and a void.
        tags = [
            (33550, "d", 3, (10, 20, 0), False),
            (33922, "d", 6, (0, 0, 0, 100, 200, 0), False),
            (34735, "H", 16, (1, 1, 0, 3, 1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, 3857), False),
            (42113, "s", 0, "-32767", False),
        ]
        with tempfile.TemporaryDirectory() as directory:
            high, medium = (Path(directory) / (name + ".tif") for name in ("high", "medium"))
            imwrite(high, np.array([[10, -32767], [30, -32767]], dtype=np.float32), extratags=tags)
            imwrite(medium, np.full((2, 2), 90, dtype=np.float32), extratags=tags)
            heights, used = composite([Elevation(high), Elevation(medium)],
                                      np.array([105, 110, 115, 145]), np.array([190, 180, 190, 180]))
        np.testing.assert_array_equal(heights, [10, 20, 90, 0])
        np.testing.assert_array_equal(used, [1, 1, 2, 0])

    def test_tiles_have_uniform_global_pixel_spacing(self):
        z, x, y = 14, 2578, 5612
        west, north = tile_centres(z, x, y)
        east, _ = tile_centres(z, x + 1, y)
        _, south = tile_centres(z, x, y + 1)
        step = 2 * WORLD / (TILE * 2 ** z)
        self.assertTrue(math.isclose(east[0, 0] - west[0, -1], step, abs_tol=1e-7))
        self.assertTrue(math.isclose(north[-1, 0] - south[0, 0], step, abs_tol=1e-7))

    def test_rgb_round_trip_preserves_negative_and_positive_heights(self):
        values = np.array([-14.04, 0, 31.06, 1454.38])
        r, g, b = terrain_rgb(values).astype(int).T
        decoded = (65536 * r + 256 * g + b) * .1 - 10000
        np.testing.assert_allclose(decoded, values, atol=.05)


if __name__ == "__main__":
    unittest.main()

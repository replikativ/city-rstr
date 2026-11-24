import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from scripts.vancouver_commuter_presence import daily_segments, reference, schedule
from scripts.vancouver_inbound import (DOWNTOWN_JOBS, OTHER_JOBS, duration_band, leave_band,
                                      origins, shifts, time_draws, workplace_weights)


class IncomingWorkdayTest(unittest.TestCase):
    def test_disjoint_residence_scopes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "flows"
            base = dict(residence="Burnaby", work="Vancouver (CY), B.C.", men=4, women=6, total=10)
            rows = [dict(base, DGUID="2021A0005"+city) for city in ["5915025", "5915022", "5909052"]]
            rows.append(dict(rows[1], work="Burnaby (CY), B.C."))
            path.write_text("\n".join(map(json.dumps, rows)))
            selected, outside = origins(path)
        self.assertEqual(list(selected), ["5915025"])
        self.assertEqual(outside, 10)

    def test_workplace_control_retains_relative_address_weights(self):
        weights = workplace_weights(np.array([True, False, True]), np.array([2., 9., 6.]))
        self.assertAlmostEqual(weights[[0, 2]].sum(), DOWNTOWN_JOBS)
        self.assertEqual(weights[1], OTHER_JOBS)
        self.assertEqual(weights[2] / weights[0], 3)

    def test_worker_diary_preserves_absence_between_work_stops(self):
        episodes = [[240, 150, "sleep", "home"], [390, 30, "travel", "transit"],
                    [420, 180, "paid-work", "work-or-school"], [600, 60, "eating", "restaurant"],
                    [660, 240, "paid-work", "work-or-school"], [900, 780, "rest", "home"]]
        data = [dict(episodes=episodes, role="worker", split=split, weight=2) for split in ["fit", "holdout"]]
        library, spans = shifts(data)
        self.assertEqual(library.tolist(), [[390, 30, 480, 2, 0]])
        self.assertEqual(spans, [[[0, 180], [240, 480]]])

    def test_band_fallback_does_not_change_census_departure_or_duration(self):
        library = np.array([[430, 10, 400, 1, 0], [560, 100, 300, 1, 1]])
        profiles = np.array([[1, 1, 4, 3, 5, 4, 1]] * 7)
        starts, duration, template = time_draws(np.random.default_rng(5), profiles, library)
        self.assertTrue(all(leave_band(x) == 3 for x in starts))
        self.assertTrue(all(duration_band(x) == 5 for x in duration))
        self.assertTrue((template == 0).all())

    def test_overnight_return_and_break_against_direct_clock(self):
        row = [0, 0, 2, 6, 5, 1390, 35, 180, 1, 0]
        absent = row[:8] + [0, 0]
        spans = [[[0, 30], [90, 180]]]
        counts = reference(np.array([row, absent]), spans, 1, np.array([1]))
        actual = np.zeros((1440, 3), dtype=int)
        for a, b, k in schedule(row, spans, 0):
            actual[a:b, k] += 1
        np.testing.assert_array_equal(counts[:, 1], actual)
        self.assertEqual(actual.sum(axis=0).tolist(), [35, 120, 35])
        self.assertEqual(daily_segments(1439, 1), [(1439, 1440)])
        self.assertEqual(schedule(absent, spans, 0), ())

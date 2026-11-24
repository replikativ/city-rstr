import json
from pathlib import Path
import tempfile
import unittest

from scripts.vancouver_incoming_commutes import commute_windows
from scripts.vancouver_incoming_duration_check import summarize
from scripts.vancouver_incoming_drives import driving_legs
from scripts.vancouver_incoming_pedestrians import itinerary_walks
from scripts.vancouver_incoming_timing import as_booked, flex_window
from scripts.vancouver_incoming_timing_presence import extension
from scripts.vancouver_regional_inbound_transit import connection_options


class IncomingCommuteWindowsTest(unittest.TestCase):
    def test_keeps_each_attending_transit_workers_job_and_both_windows(self):
        report = {"modes": ["Public transit", "Car driver"], "groups": {"outer": {"stock": 3}}}
        roster = {
            "homes": ["first", "second"],
            "people": [[1, 0, 1, 5, 0, 470, 35, 480, 1, 0],
                       [0, 0, 2, 5, 0, 430, 25, 480, 0, 0],
                       [0, 0, 1, 5, 1, 480, 40, 480, 1, 0]],
        }
        places = [[0, 10, 0, "Workplace"]]
        anchors = {"second": (120, 40), "first": (20, 120)}
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "outer.json").write_text(json.dumps(roster))
            rows, homes = commute_windows(folder, anchors, places, report)
            adjusted, same_homes = commute_windows(folder, anchors, places, report, {"outer": {0: 0}})
        self.assertEqual(homes, [[20, 120, -1, "Home census area first"], [120, 40, -1, "Home census area second"]])
        self.assertEqual(rows, [("outer", 0, 470, 35, 2, 0, True), ("outer", 0, 985, 35, 0, 2, False)])
        self.assertEqual(adjusted, [("outer", 0, 470, 35, 1, 0, True), ("outer", 0, 985, 35, 0, 1, False)])
        self.assertEqual(same_homes, homes)

    def test_transfer_search_can_resume_without_revisiting_completed_windows(self):
        calls = []

        class Timetable:
            def journey(self, start, end, a, b):
                calls.append((start // 60, end // 60, a, b))
                return [a, b] if start == 420*60 else None

        rows = [(420, 450, 1, 2), (480, 510, 3, 4), (500, 540, 2, 3)]
        sources = ("weekday", "timetable", "streets")
        with tempfile.TemporaryDirectory() as temp:
            checkpoint = Path(temp) / "transfers.json"
            expected = connection_options(Timetable(), rows, 1, checkpoint, sources)
            partial = json.loads(checkpoint.read_text())
            partial["choices"] = partial["choices"][:2]
            checkpoint.write_text(json.dumps(partial))
            calls.clear()
            resumed = connection_options(Timetable(), rows, 1, checkpoint, sources)
            self.assertEqual(resumed, expected)
            self.assertEqual(calls, rows[2:])
            with self.assertRaises(ValueError):
                connection_options(Timetable(), rows, 1, checkpoint, ("new-weekday", *sources[1:]))
            calls.clear()
            reused = connection_options(Timetable(), rows, 1, None, sources,
                                        reuse={rows[0]: [1,2], rows[1]: None})
            self.assertEqual(reused, expected)
            self.assertEqual(calls, rows[2:])

    def test_longer_transit_windows_preserve_the_work_shift_boundaries(self):
        outward = ("outer", 0, 470, 35, 2, 0, True)
        returning = ("outer", 0, 985, 35, 0, 2, False)
        self.assertEqual(flex_window(outward, 15), (455, 505, 2, 0))
        self.assertEqual(flex_window(returning, 30), (985, 1050, 0, 2))
        self.assertEqual(as_booked(outward, (456, 499*60, ["route"]))[:6], ["outer", 0, 456, 49, 2, 0])
        self.assertEqual(as_booked(returning, (995, 1034*60+3, ["route"]))[:6], ["outer", 0, 985, 50, 0, 2])
        self.assertEqual(flex_window(("outer", 0, 250, 25, 2, 0, True), 30), (240, 275, 2, 0))
        self.assertEqual(flex_window(("outer", 0, 1655, 20, 0, 2, False), 30), (1655, 1680, 0, 2))
        worker = [0, 0, 1, 5, 0, 470, 35, 480, 1, 0]
        self.assertEqual(extension(["outer", 0, 456, 49, 2, 0], worker, 2, 30), (456, 470, 0))
        self.assertEqual(extension(["outer", 0, 985, 50, 0, 2], worker, 2, 30), (1020, 1035, 2))
        with self.assertRaises(ValueError):
            extension(["outer", 0, 456, 50, 2, 0], worker, 2, 30)

    def test_commuter_passage_uses_each_walk_at_its_scheduled_time(self):
        row = ["outer", 0, 420, 60, 1, 2, "A", 0, 0, 1, 60, 120,
               ["B", 0, 0, 1, 60, 240, [[2, 0], [3, 0]],
                ["C", 0, 0, 1, 60, 240, [[4, 0], [5, 0]]]]]
        access, egress = [[0, 0], [1, 0]], [[6, 0], [7, 0]]
        clock = {"A": (25500, 25700), "B": (26100, 26300), "C": (26700, 26900)}
        self.assertEqual(list(itinerary_walks(row, access, egress, lambda route, *_: clock[route])),
                         [("access", 25200, 60, access), ("transfer", 25700, 60, [[2, 0], [3, 0]]),
                          ("transfer", 26300, 60, [[4, 0], [5, 0]]), ("egress", 26900, 120, egress)])

    def test_commute_duration_reference_weights_geographic_cells_by_workers(self):
        rows = [(('a', 2), 12, 18), (('a', 2), 17, 26), (('b', 4), 50, 62), (('b', 5), 80, 99)]
        margins = {('a', 2): ((15, 5, 0, 0, 0), 17), ('b', 4): ((0, 0, 0, 10, 10), 55), ('b', 5): None}
        report = summarize(rows, margins)
        self.assertEqual((report['eligible'], report['compared']), (4, 3))
        self.assertEqual(report['observedExpected'], [1.5, .5, 0, .5, .5])
        self.assertEqual(report['meanMinutes'], [79/3, 106/3, 89/3])

    def test_driver_windows_reuse_a_home_root_in_both_directions(self):
        roster = {'outer': {'homes': ['old', 'new'], 'people': [[0, 3, 1, 5, 1, 480, 30, 480, 1, 0]]}}
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder/'outer.json').write_text('[[0,0,1]]')
            rows, end = driving_legs(roster, 5, folder, 1)
        self.assertEqual(end, 7)
        self.assertEqual(rows, [(0, 0, 480, 30, 5, 3, 6, 3, 1), (0, 0, 990, 30, 3, 5, 3, 6, 0)])

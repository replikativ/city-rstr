import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.artifacts import read
from scripts.vancouver_region import place_kinds, publish_versions
from scripts.vancouver_short_walks import gaps, interval
from scripts.vancouver_transit import active_services, seconds, stop_distances


class RegionalModelTest(unittest.TestCase):
    def test_first_reissue_keeps_the_preexisting_release_for_clock_links(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "current.json"
            current.write_text('{"atlas":"old","day":"one","streets":"roads","transit":"tt"}')
            before = read(current)
            after = dict(before, atlas="new", day="two")
            publish_versions(root, after)
            self.assertEqual(read(root/"releases/old_one.json"), before)
            self.assertEqual(read(root/"releases/new_two.json"), after)
            self.assertEqual(read(current), after)

    def test_private_home_candidates_and_unclassified_buildings(self):
        self.assertIn("home",place_kinds({"building":"apartments"}))
        self.assertEqual(place_kinds({"building":"yes"}),["home-proxy"])
        self.assertIn("home",place_kinds({"addr:housenumber":"520"}))
        self.assertNotIn("home",place_kinds({"addr:housenumber":"520","shop":"supermarket"}))
        self.assertNotIn("home-proxy",place_kinds({"building":"yes","amenity":"clinic"}))

    def test_walk_never_consumes_a_whole_diary_episode(self):
        episodes=[[240,60,"sleep","home"],[300,5,"eating","home"],[305,5,"recreation","outdoors"],[310,30,"eating","home"]]
        parts=[[240,65,"stop",0,0],[305,5,"stop",1,1],[310,30,"stop",2,2]]
        edges=list(gaps({"parts":parts},{"episodes":episodes}))
        self.assertEqual(edges,[(305,0,1,2,2),(310,1,2,2,14)])
        self.assertEqual(interval(305,2,2,320),(303,4))
        self.assertIsNone(interval(305,2,2,321))
        self.assertIsNone(interval(310,2,14,801))

    def test_service_day_exceptions_and_after_midnight(self):
        calendar=[dict(service_id="a",start_date="20260901",end_date="20260930",tuesday="1")]
        exceptions=[dict(service_id=k,date="20260915",exception_type=v) for k,v in [("a","2"),("b","1")]]
        self.assertEqual(active_services(calendar,exceptions,date(2026,9,15)),{"b"})
        self.assertEqual(seconds("25:20:00"),91200)

    def test_shape_projection_monotonic_and_offset_fallback(self):
        line=[[0,0],[100,0],[100,100]]
        self.assertEqual(stop_distances(line,[[0,1],[70,2],[103,30]]),[0,70,130])
        self.assertIsNone(stop_distances(line,[[0,0],[900,300]]))

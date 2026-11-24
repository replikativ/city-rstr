import unittest

from scripts.vancouver_cityday import compile_day
from scripts.vancouver_raster import half_ranks, work_tours


class WorkTourTest(unittest.TestCase):
    def test_paid_work_and_only_closed_home_tours(self):
        episodes=[[240,300,"sleep","home"],[540,30,"travel","walk"],[570,10,"travel","transit"],
                  [580,300,"paid-work","work-or-school"],[880,60,"eating","work-or-school"],
                  [940,30,"travel","transit"],[970,710,"leisure","home"]]
        def tours():
            return work_tours(compile_day(episodes),{"episodes":episodes})
        self.assertEqual(tours(),[2])
        episodes[-1][-1]="store"
        self.assertEqual(tours(),[])
        episodes[-1][-1]="home"
        episodes[3][2]="study"
        self.assertEqual(tours(),[])

    def test_draw_is_invariant_to_resident_order_and_sharding(self):
        ids=[0,8,22,110]
        ranks=half_ranks("59150680",ids)
        self.assertEqual(ranks.tolist(),[int(half_ranks("59150680",[i])[0]) for i in ids])
        self.assertEqual(ranks[::-1].tolist(),half_ranks("59150680",ids[::-1]).tolist())

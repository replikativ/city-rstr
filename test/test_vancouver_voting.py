import unittest
from unittest.mock import patch

import numpy as np

from scripts.vancouver_voting import (
    allocate_registrars, flexible_home_windows, paired_access, plan_detour, plan_voter,
    register, reschedule_housework, voting_clock,
)


class VotingTest(unittest.TestCase):
    def test_polling_stop_uses_directed_legs_and_preserves_departure(self):
        sites = [{"id": 200, "place": 7}]
        paths = {(3,200,"car-driver"):(12,None), (4,200,"car-driver"):(None,19)}
        self.assertEqual(plan_detour(4,[(3,600,630,640,"car-driver","job")],sites,paths,615),
                         ((200,7,"car-driver",612,12,19,621,None),[3,630,"job"]))
        self.assertIsNone(plan_detour(4,[(3,600,630,635,"car-driver","job")],sites,paths,615))
        self.assertIsNone(plan_detour(4,[(3,470,500,530,"car-driver","job")],sites,
                                      {(3,200,"car-driver"):(6,None), (4,200,"car-driver"):(None,19)},500))

    def test_polling_stop_replaces_old_motion_and_can_arrive_home_early(self):
        tour = [0,1,0,1,"walk",480,5,492,7,491,200,486,None,None,[2,505,"job"]]
        places = [[0,0,0,"Home"],[100,0,1,"Poll"],[150,0,1,"Job"]]
        with patch("scripts.vancouver_voting.verify_intervals") as verify:
            voting_clock([tour],places,np.zeros((1440,4)),["Home area","Poll area"],None,"jvm")
        _, changes, *_ = verify.call_args.args
        self.assertEqual(changes[480-240].tolist(),[0,0,0,0])
        self.assertEqual(changes[485-240].tolist(),[0,1,-1,0])
        self.assertEqual(changes[492-240].tolist(),[0,0,0,0])
        self.assertEqual(changes[499-240].tolist(),[1,0,-1,0])
        self.assertEqual(changes[505-240].tolist(),[0,0,0,0])

    def test_moves_whole_tasks_to_both_sides_of_the_same_polling_trip(self):
        tasks = [[530, 20, "housework"], [565, 10, "housework-occasional"]]
        windows = list(flexible_home_windows([(500, 600)], tasks, []))
        tour = [0, 1, 2, 3, "walk", 525, 10, 552, 14]
        self.assertEqual(reschedule_housework(tour, windows), [500, 600, [
            [530, 20, "housework", 505], [565, 10, "housework-occasional", 566],
        ]])

    def test_protected_time_cannot_be_used_to_move_housework(self):
        tasks = [[520, 20, "housework"], [610, 30, "housework"]]
        windows = list(flexible_home_windows([(500, 700)], tasks, [(550, 560), (625, 635)]))
        self.assertEqual(windows, [(500, 550, tasks[:1], [(500, 530), (520, 550)])])
        tour = [0, 1, 2, 3, "walk", 525, 10, 555, 10]
        with self.assertRaisesRegex(ValueError, "leaves too little time"):
            reschedule_housework(tour, windows)

    def test_chore_shift_limit_constrains_the_available_time(self):
        tasks = [[590, 20, "housework"]]
        windows = list(flexible_home_windows([(480, 750)], tasks, []))
        self.assertEqual(windows[0][3], [(480, 650), (550, 750)])

    def test_march_layout_retains_all_nine_staff(self):
        sites = (200, 24, 4, 9, 13)
        plans = {200: [1, 2, 3, 4], 24: [1, 2], 4: [1, 2], 9: [1], 13: [1]}
        self.assertEqual(allocate_registrars(sites, 9, plans), {200: 2, 4: 2, 24: 2, 9: 2, 13: 1})
        self.assertEqual(allocate_registrars(sites, 15, plans), dict.fromkeys(sites, 3))

    def test_registration_keeps_existing_commitments_and_reuses_unclaimed_slot(self):
        voters = [
            [0, 1, 10, 200, 11, "walk", 480, 4, 4, 485, None, 1],
            [0, 2, 12, 200, 11, "walk", 480, 4, 4, 500, None, 2],
            [0, 3, 13, 200, 11, "walk", 480, 5, 5, 500, None, 3],
        ]
        first, second, third = register(voters, staff=1)
        self.assertEqual(first[7:10], [485, 4, None])
        self.assertEqual((second[9], second[11]), (488, 483))
        self.assertEqual((third[9], third[11]), (490, 485))

    def test_both_legs_and_ballot_must_fit_before_accepting_site(self):
        routes = [(30, 1, "walk", 6, 10), (200, 2, "car-driver", 8, 8)]
        self.assertIsNone(plan_voter([(600, 620)], routes, {30, 200}, True, 610))
        plan = plan_voter([(600, 625)], routes, {30, 200}, True, 610)
        self.assertEqual(plan[:7], (30, 1, "walk", 609, 6, 10, 615))

    def test_matched_travel_counts_exclude_people_newly_reaching_a_poll(self):
        def visit(i, there, back):
            return [0, i, 4, 7, "walk", 480, there, 500, back]
        rows = {"hall": [visit(0, 12, 12), visit(1, 6, 5)],
                "centres": [visit(0, 10, 10), visit(1, 7, 5), visit(2, 5, 4)]}
        self.assertEqual(paired_access(rows), dict(both=2, gained=1, lost=0, shorter=1, same=0, longer=1))

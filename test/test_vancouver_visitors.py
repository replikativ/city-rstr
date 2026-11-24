import unittest
import numpy as np

from scripts.vancouver_visitors import COHORTS, donor_pool, intervals, visitors


class ExternalVisitorTest(unittest.TestCase):
    def test_physical_role_block_retains_break_and_midnight(self):
        eps=[[240,300,"study","home"],[540,100,"study","work-or-school"],[640,30,"eating","work-or-school"],
             [670,90,"study","work-or-school"],[760,800,"study","home"],[1560,120,"study","work-or-school"]]
        self.assertEqual(intervals(eps,"study"),[[540,760],[1560,1680]])
        self.assertEqual(intervals(eps,"paid-work"),[])

    def test_employed_students_and_home_only_diaries_remain_in_attendance_denominator(self):
        sample=[dict(split="fit",role="worker",enrolledAfterHighSchool=True,weight=w,
                     episodes=[[240,1440,"study",loc]]) for w,loc in [(3,"home"),(1,"work-or-school")]]
        days,_,support=donor_pool(sample,"students","fit")
        self.assertEqual(days,[[],[[240,1680]]])
        self.assertEqual(support["weekdayShare"],.25)

    def test_per_person_lunch_and_half_open_stays(self):
        eps=[[240,420,"sleep","home"],[660,30,"study","work-or-school"],
             [690,20,"travel","walk"],[710,130,"study","work-or-school"],[840,840,"sleep","home"]]
        diaries=[dict(split=split,role="student",enrolledAfterHighSchool=True,weight=1,episodes=eps)
                 for split in ("fit","holdout")]
        result=visitors(diaries,"students",[{"use":"Academic","area":123}],np.array([[True],[False]]),0)
        n=sum(round(COHORTS["students"][0]*.55*s) for s in COHORTS["students"][2].values())
        self.assertEqual(result["lunch"],[n,0])
        self.assertEqual([result["presence"][1][t-240] for t in [659,660,689,690,710,839,840]],[0,n,n,0,n,n,0])

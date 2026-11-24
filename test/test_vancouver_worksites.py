import unittest

import numpy as np
from scipy.sparse import csr_matrix

from scripts.vancouver_worksites import nearest_sites, solve


class WorksiteTest(unittest.TestCase):
    def test_nearest_site_accounts_for_both_connectors_and_unreachable_sites(self):
        graph = csr_matrix([[0,5,0,0],[5,0,5,0],[0,5,0,0],[0,0,0,0]])
        nodes = np.array([0,1,2,2,3])
        offsets = np.array([1,12,0,2,3])
        reach = nearest_sites(graph,nodes,offsets,[1,2],np.array([0,1,3,4]))
        np.testing.assert_array_equal(reach, [11,0,2,np.inf])

    def test_assignment_keeps_repeated_site_slots_and_can_exchange_three_workers(self):
        group = dict(siteSlots=[0,1,2,2], costs=[[6,1,None],[None,6,1],[1,None,6],[None,None,0]])
        permutation, = solve([group])
        self.assertEqual(sorted(permutation),list(range(4)))
        self.assertEqual([group['siteSlots'][p] for p in permutation],[1,2,0,2])

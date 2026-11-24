import numpy as np

from scripts.vancouver_block_homes import household_groups, plan_blocks, sample_by_area


def test_fit_moves_intact_households_and_unassigned_people():
    groups = household_groups(10, [(0, 1, 7), (1, 3, 8), (5, 1, 9), (8, 1, 10)])
    assert groups == {0: [4, 6, 7, 9], 1: [0, 5, 8], 3: [1]}
    sizes, counts = plan_blocks({size: len(members) for size, members in groups.items()}, [0, 3, 1], [4, 3, 3])
    assert counts[:, sizes > 0].sum(axis=1).tolist() == [0, 3, 1]
    assert (counts @ np.maximum(sizes, 1)).tolist() == [4, 3, 3]
    assert counts.sum(axis=0).tolist() == [4, 3, 1]


def test_inconsistent_block_people_leave_exact_occupied_dwelling_counts():
    # A census block can report an occupied dwelling and zero residents.
    sizes, counts = plan_blocks({1: 1, 2: 4}, [1, 4], [0, 9])
    assert counts.sum(axis=1).tolist() == [1, 4]
    assert (counts @ sizes).tolist() == [1, 8]


def test_animation_sample_uses_dense_area_indices_with_stable_roster_ids():
    day = {"das": ["59150001", "59150003"], "sample": [[1, 14, 2, [8], 100], [0, 8, 1, [7], 99]]}
    assert sample_by_area(day) == {"59150003": {14: 0}, "59150001": {8: 1}}

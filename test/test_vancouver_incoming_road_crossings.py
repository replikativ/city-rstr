import numpy as np

from scripts.vancouver_incoming_road_crossings import Cordon, PassageCounter


def count_passages(places, points, nodes, access, distance, screens):
    ring = np.array([[0, -10], [100, -10], [100, 10], [0, 10], [0, -10]])
    cordon = Cordon(ring, points, places)
    passages = PassageCounter(points, places, ["Burnaby"], cordon, screens, 2)
    # Both searches use the home node as the root. The return uses the reverse graph.
    legs = np.array([[0, 2, 466, 30, 0, 1, 0, 1, 1], [0, 2, 950, 30, 1, 0, 1, 0, 0]])
    cost = np.array([0, distance])
    for reverse in (False, True):
        passages(legs, [(int(reverse), 0, 1, 29, 0)], 0, reverse, cost, [-1, 0], nodes, access)
    return passages


def test_city_and_station_crossing_use_elapsed_road_time_in_each_direction():
    points = [[-50, 0], [50, 0]]
    passages = count_passages(points, points, [0, 1], [0, 0], 10,
                              {(0, 1): (1, 0, 0.6), (1, 0): (1, 1, 0.4)})
    assert passages.examples[0, 0, 0, 7] == ["Burnaby", 2, 471, [0, 0]]
    assert passages.examples[0, 0, 1, 15] == ["Burnaby", 2, 955, [0, 0]]
    assert passages.examples[1, 0, 0, 7] == ["Burnaby", 2, 472, [10, 0]]
    assert passages.examples[1, 0, 1, 15] == ["Burnaby", 2, 954, [10, 0]]
    assert passages.outcomes[0] == {"feasible": 2, "roadCrossing": 2}
    assert passages.counts.sum() == 4


def test_city_crossing_can_occur_on_the_workplace_connector():
    places = [[-50, 0], [20, 0]]
    points = [[-50, 0], [-10, 0]]
    passages = count_passages(places, points, [0, 1], [0, 3], 4, {})
    assert passages.examples[0, 0, 0, 7] == ["Burnaby", 2, 471, [0, 0]]
    assert passages.examples[0, 0, 1, 15] == ["Burnaby", 2, 952, [0, 0]]
    assert passages.outcomes[0] == {"feasible": 2, "connectorCrossing": 2}
    assert passages.counts.sum() == 2


def test_outbound_worker_leaves_the_city_before_work_and_enters_after():
    points = [[50, 0], [-50, 0]]
    ring = np.array([[0, -10], [100, -10], [100, 10], [0, 10], [0, -10]])
    cordon = Cordon(ring, points, points)
    passages = PassageCounter(points, points, ["Vancouver"], cordon, {}, 1, work_inside=False)
    legs = np.array([[0, 3, 450, 30, 0, 1, 0, 1, 1], [0, 3, 950, 30, 1, 0, 1, 0, 0]])
    for reverse in (False,True):
        passages(legs, [(int(reverse), 0, 1, 30, 0)], 0, reverse, [0,10], [-1,0], [0,1], [0,0])
    assert passages.examples[0, 0, 1, 7] == ["Vancouver", 3, 455, [0, 0]]
    assert passages.examples[0, 0, 0, 15] == ["Vancouver", 3, 955, [0, 0]]

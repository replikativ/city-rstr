import numpy as np
from scipy.sparse import csr_matrix

from scripts.vancouver_outbound_road_jobs import allocate, route_times


def test_external_job_requires_both_directions_of_the_full_diary():
    graph = csr_matrix([[0, 1, 4], [0, 0, 0], [5, 0, 0]])
    options = np.array([1, 2])
    profile = {"connectorKmh": 22.8, "connectorMetres": 500}
    legs = [[450, 10, 0, False, True, True], [960, 6, 0, True, False, True]]
    person = (0, 8, [1], legs)
    costs = route_times(graph, np.arange(3), np.zeros(3), profile, options, [person])
    rng = np.random.default_rng(1)
    assignments, target = allocate([person], options, ["One way", "Return"], {"One way": 90, "Return": 10}, costs, rng)
    assert assignments == [(person, 2, [4, 5])]
    assert target == {"One way": [90, 1, 0], "Return": [10, 0, 1]}


def test_short_return_keeps_the_whole_workplace_unresolved():
    graph = csr_matrix([[0, 2], [6, 0]])
    options = np.array([1])
    profile = {"connectorKmh": 22.8, "connectorMetres": 500}
    legs = [[450, 10, 0, False, True, True], [960, 5, 0, True, True, True]]
    person = (0, 8, [1], legs)
    costs = route_times(graph, np.arange(2), np.zeros(2), profile, options, [person])
    assignments, target = allocate([person], options, ["Tract"], {"Tract": 10}, costs, np.random.default_rng(1))
    assert assignments == []
    assert target == {"Tract": [10, 0, 0]}

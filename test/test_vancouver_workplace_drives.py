import math

import numpy as np

from scripts.vancouver_workplace_drives import score, summarize


def test_workplace_drives_can_detour_or_miss_the_window_in_one_direction():
    nodes = [[0, 0], [1000, 0], [2000, 0], [1000, 1000]]
    places = nodes + [[0, -600]]
    network = {"nodes": nodes, "ways": [[2, 0, [0, 1, 2]], [2, 0, [0, 3, 2]], [2, 0, [2, 0]]]}
    profile = {"kmh": [[60, 0]] * 3, "connectorKmh": 20, "connectorMetres": 500}
    hourly = {"hours": [7, 8], "corridors": [{"arcs": [[1, 2]], "factors": [1, 3]}]}
    routes = [[0, 0, 480, 3, 0, 1, 0, 2, 0], [0, 1, 480, 2, 0, 1, 0, 2, 0],
              [0, 2, 480, 2, 2, 0, 2, 0, 1], [0, 3, 420, 2, 0, 1, 0, 2, 0],
              [0, 4, 480, 5, 4, 2, 4, 2, 0]]

    rows, times, impediment, slowed = score(routes, places, network, profile, hourly)

    np.testing.assert_allclose(times, [[1, 2, math.sqrt(8)], [1, 2, np.inf], [2, 2, 2], [1, 2, 2],
                                      [np.inf, np.inf, np.inf]])
    assert slowed.tolist() == [True, True, False, False, False]
    assert impediment[-1].tolist() == ["connector", "connector"]
    audit = summarize(rows, times, impediment, slowed, ["DA"])
    assert audit["hourly"][8]["feasible"] == [3, 3, 2]
    assert audit["example"]["endpoints"] == [0, 2]

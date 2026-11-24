"""Recover a concrete forward timetable journey with up to two transfers."""
from numba import njit
import numpy as np

from scripts.vancouver_transit_reach import INF, Reach


@njit
def scan_trace(connections, runs, transfer_rows, transfer_links, platforms,
               origins, destinations, start, deadline, margin, blocked):
    ready = np.full((3, platforms), INF, dtype=np.int32)
    reached = np.full_like(ready, INF)
    ready_from = np.full_like(ready, -1)
    arrival_edge = np.full_like(ready, -1)
    aboard = np.full((3, runs), -1, dtype=np.int32)
    board_edge = np.full((3, len(connections)), -1, dtype=np.int32)
    predecessor = np.full_like(board_edge, -1)
    for stop, seconds in origins:
        ready[0, stop] = min(ready[0, stop], start + seconds + margin)
    for j, (dep, arr, origin, target, run, can_board, can_alight) in enumerate(connections):
        if blocked[j]:
            aboard[:, run] = -1
            continue
        if arr > deadline:
            continue
        for k in range(3):
            if aboard[k, run] < 0 and can_board and ready[k, origin] <= dep:
                aboard[k, run] = j
                predecessor[k, j] = ready_from[k, origin]
            if aboard[k, run] < 0 or not can_alight or arr >= reached[k, target]:
                continue
            reached[k, target] = arr
            arrival_edge[k, target] = j
            board_edge[k, j] = aboard[k, run]
            if k < 2:
                for n in range(transfer_rows[target], transfer_rows[target + 1]):
                    stop, seconds = transfer_links[n]
                    if arr + seconds < ready[k + 1, stop]:
                        ready[k + 1, stop] = arr + seconds
                        ready_from[k + 1, stop] = j
    best, level, edge, egress = deadline + 1, -1, -1, -1
    for k in range(3):
        for stop, seconds in destinations:
            arrival = reached[k, stop] + seconds
            if arrival < best:
                best, level, edge, egress = arrival, k, arrival_edge[k, stop], seconds
    path = np.full((3, 2), -1, dtype=np.int32)
    for k in range(level, -1, -1):
        board = board_edge[k, edge]
        path[k, 0] = board
        path[k, 1] = edge
        edge = predecessor[k, board]
    return path, best, egress


class JourneyTrace(Reach):
    def __init__(self, service, access, transfers, margin):
        super().__init__(service, access, transfers, margin)
        self.footpaths = transfers

    def journey(self, start, end, a, b, available=None):
        forward = self.connections[0]
        begin = np.searchsorted(forward[:, 0], start * 60)
        finish = np.searchsorted(forward[:, 0], end * 60, side="right")
        edges = forward[begin:finish]
        segments = self.segments[begin:finish]
        blocked = np.zeros(len(edges), dtype=np.bool_)
        if available:
            blocked[:] = [not available(*self.vehicles[run], int(pos), int(pos) + 1)
                          for run, pos in zip(edges[:, 4], segments, strict=True)]
        traced, arrival, egress = scan_trace(edges, self.runs, *self.transfers[0], len(self.platforms),
                                             self.access[a], self.access[b], start * 60, end * 60, self.margin, blocked)
        pairs = [(int(board), int(alight)) for board, alight in traced if board >= 0]
        if not pairs:
            return None
        legs = [[*self.vehicles[edges[board, 4]], int(segments[board]), int(segments[alight]) + 1]
                for board, alight in pairs]
        if len({tuple(leg[:2]) for leg in legs}) != len(legs):
            raise ValueError("A recovered itinerary boards the same vehicle twice")
        steps = []
        for i, (_, alight) in enumerate(pairs[:-1]):
            onward, _ = pairs[i + 1]
            origin = self.stop_ids[edges[alight, 3]]
            destination = self.stop_ids[edges[onward, 2]]
            path = self.footpaths[destination][origin]
            steps.append([*legs[i + 1], path.seconds, path.required, path.points])
        for i in range(len(steps) - 1, 0, -1):
            steps[i - 1].append(steps[i])
        first = pairs[0][0]
        walk = min(int(seconds) for stop, seconds in self.access[a] if stop == edges[first, 2])
        ready = int(edges[first, 0]) - walk - self.margin
        itinerary = [*legs[0], walk, int(egress), *steps[:1]]
        return ready // 60, int(arrival), itinerary

"""Match a dated transit journey with walkable connections between vehicles."""
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
import math

import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.artifacts import read
from scripts.vancouver_campus import WALK_METRES_PER_SECOND
from scripts.vancouver_streets import walk_graph

MAX_TRANSFER_METRES = 250


@dataclass(frozen=True)
class Footpath:
    seconds: int
    required: int
    points: list


def walk_transfers(service, rules, street_network, margin):
    """Use stops with the same ID and advertised stop pairs connected by streets."""
    platforms = service.platforms
    stations = service.stations
    if not platforms:
        raise ValueError("A transfer timetable needs GTFS stop IDs")
    pairs = {(a, b): (kind, minimum) for a, b, kind, minimum in rules if a in platforms and b in platforms}
    for name in platforms:
        pairs.setdefault((name, name), (0, 0))

    network = read(street_network)
    graph, snap = walk_graph(network)
    nodes, offsets = snap(stations, lowest_id_on_ties=True)
    destinations = defaultdict(list)
    for (a, b), (kind, minimum) in pairs.items():
        x, y = platforms[a], platforms[b]
        if kind != 3 and math.dist(stations[x], stations[y]) <= MAX_TRANSFER_METRES:
            destinations[x].append((a, b, y, minimum))

    connections = defaultdict(dict)
    for origin, options in sorted(destinations.items()):
        start = int(nodes[origin])
        pending = any(origin != j for _, _, j, _ in options)
        if pending and offsets[origin] <= MAX_TRANSFER_METRES:
            lengths, previous = dijkstra(graph, indices=start,
                                         limit=MAX_TRANSFER_METRES - offsets[origin],
                                         return_predecessors=True)
        else:
            lengths = previous = None
        for a, b, dest, minimum in options:
            if origin == dest:
                connections[b][a] = Footpath(0, max(margin, minimum), [stations[origin]])
                continue
            if lengths is None:
                continue
            end = int(nodes[dest])
            distance = lengths[end] + offsets[origin] + offsets[dest]
            if distance > MAX_TRANSFER_METRES:
                continue
            path = [end]
            while path[-1] != start:
                path.append(int(previous[path[-1]]))
            coords = [stations[origin], *(network["nodes"][j] for j in reversed(path)), stations[dest]]
            points = [list(p) for i, p in enumerate(coords) if i == 0 or tuple(p) != tuple(coords[i-1])]
            seconds = math.ceil(distance / WALK_METRES_PER_SECOND)
            connections[b][a] = Footpath(seconds, max(margin + seconds, minimum), points)
    return connections


@dataclass(frozen=True)
class LastRide:
    cutoff: int
    arrival: int
    egress: int
    path: Footpath
    vehicle: tuple

    def priority(self):
        return (-self.cutoff, self.arrival, self.egress + self.path.seconds, self.vehicle)


@dataclass(frozen=True)
class FirstRide:
    ready: int
    access: int
    path: Footpath
    vehicle: tuple

    def priority(self):
        return (self.ready, self.access + self.path.seconds, self.vehicle)


def keep_distinct(labels, label, limit):
    if len(labels) == limit and label.priority() >= labels[-1].priority():
        return
    for i, prior in enumerate(labels):
        if prior.vehicle[:2] == label.vehicle[:2]:
            if label.priority() >= prior.priority():
                return
            labels.pop(i)
            break
    labels.append(label)
    labels.sort(key=lambda item: item.priority())
    del labels[limit:]


class OneTransfer:
    def __init__(self, service, access, connections, margin):
        self.service = service
        self.positions = service.accessible_positions(access)
        self.connections = connections
        self.margin = margin
        self.board = []
        self.alight = []
        for mask in service.access_rules:
            self.board.append(tuple(i for i, flags in enumerate(mask[:-1]) if flags & 1))
            self.alight.append(tuple(i for i, flags in enumerate(mask) if i and flags & 2))

    @lru_cache(maxsize=8)
    def tails(self, deadline, destination):
        return self.build_tails(deadline, destination)

    def build_tails(self, deadline, destination, available=None, first_alights=None, distinct=None):
        """Latest feasible time to alight from the first vehicle at each platform."""
        service = self.service
        limit = distinct or (2 if available is not None else 1)
        latest = defaultdict(list)
        for pid, alights in self.positions(destination, False).items():
            if not service.mapped[pid]:
                continue
            route, _, _, _ = service.patterns[pid]
            platforms = service.pattern_platforms[pid]
            for alight, _, egress in alights:
                for board in self.board[pid]:
                    if board >= alight:
                        break
                    if platforms[board] == platforms[alight]:
                        continue
                    paths = self.connections.get(platforms[board])
                    if paths and first_alights is not None:
                        paths = {stop: path for stop, path in paths.items() if stop in first_alights}
                    if not paths:
                        continue
                    excluded = []
                    for _ in range(limit):
                        chosen = service.ride_before(pid, board, alight, deadline - egress, available, also_excluded=excluded)
                        if chosen is None:
                            break
                        dep, neg_arr, trip = chosen
                        excluded.append((route, trip))
                        vehicle = route, trip, board, alight
                        for stop, path in paths.items():
                            label = LastRide(dep - path.required, -neg_arr + egress, egress, path, vehicle)
                            keep_distinct(latest[stop], label, limit)
        return latest

    def latest(self, deadline, origin, destination, available=None, *, earliest_minute=None):
        service = self.service
        origin_positions = self.positions(origin, True)
        if available is None:
            tails = self.tails(deadline, destination)
        else:
            # Reservations can change between queries. Rebuild only the
            # onward labels the origin could reach on a first vehicle.
            first_alights = set()
            for pid, boards in origin_positions.items():
                if service.mapped[pid]:
                    first_board = min(pos for pos, _, _ in boards)
                    first_alights.update(service.pattern_platforms[pid][i] for i in self.alight[pid] if i > first_board)
            tails = self.build_tails(deadline, destination, available, first_alights)
        winner = best = None
        for pid, boards in origin_positions.items():
            if not service.mapped[pid]:
                continue
            route, _, _, _ = service.patterns[pid]
            platforms = service.pattern_platforms[pid]
            stops = [(i, tail) for i in self.alight[pid] for tail in tails.get(platforms[i], ())]
            for board, _, access in boards:
                ready = None if earliest_minute is None else earliest_minute * 60 + access + self.margin
                for alight, tail in stops:
                    if (alight <= board or platforms[alight] == platforms[board]
                            or ready is not None and tail.cutoff <= ready):
                        continue
                    excluded = tail.vehicle[:2] if available is not None else None
                    chosen = service.ride_before(pid, board, alight, tail.cutoff, available, excluded)
                    if chosen is None:
                        continue
                    dep, _, trip = chosen
                    if (route, trip) == tail.vehicle[:2] or ready is not None and dep < ready:
                        continue
                    minute = (dep - access - self.margin) // 60
                    key = (-minute, tail.arrival, access + tail.egress + tail.path.seconds,
                           route, trip, board, alight, tail.vehicle)
                    if best is None or key < best:
                        best = key
                        first = [route, trip, board, alight, access, tail.egress]
                        second = [*tail.vehicle, tail.path.seconds, tail.path.required, tail.path.points]
                        winner = minute, tail.arrival, [*first, second]
        return winner


class TwoTransfers:
    """Join a feasible first and last ride at a scheduled middle vehicle."""

    def __init__(self, planner):
        self.planner = planner
        self.service = planner.service
        self.outward = defaultdict(list)
        for board, stops in planner.connections.items():
            for alight, path in stops.items():
                self.outward[alight].append((board, path))
        self.mid_boards = defaultdict(list)
        self.mid_alights = defaultdict(list)
        for pid, platforms in enumerate(self.service.pattern_platforms):
            if not self.service.mapped[pid]:
                continue
            for pos in planner.board[pid]:
                self.mid_boards[platforms[pos]].append((pid, pos))
            for pos in planner.alight[pid]:
                self.mid_alights[platforms[pos]].append((pid, pos))

    def first_legs(self, start, origin, available=None):
        by_platform = defaultdict(list)
        service = self.service
        for pid, boards in self.planner.positions(origin, True).items():
            if not service.mapped[pid]:
                continue
            platforms = service.pattern_platforms[pid]
            route = service.patterns[pid][0]
            for board, _, access in boards:
                ready = start + access + self.planner.margin
                for alight in self.planner.alight[pid]:
                    links = self.outward.get(platforms[alight])
                    if alight <= board or platforms[alight] == platforms[board] or not links:
                        continue
                    excluded = []
                    for _ in range(3):
                        ride = service.ride_after(pid, board, alight, ready, available, excluded)
                        if ride is None:
                            break
                        arrival, trip = ride
                        excluded.append((route, trip))
                        for stop, path in links:
                            label = FirstRide(arrival + path.required, access, path, (route, trip, board, alight))
                            keep_distinct(by_platform[stop], label, 3)
        return self.project(by_platform, self.mid_boards)

    @staticmethod
    def project(labels, index):
        patterns = defaultdict(list)
        for stop, pool in labels.items():
            for pid, pos in index.get(stop, ()):
                patterns[pid].append((pos, pool))
        return patterns

    @lru_cache(maxsize=16)
    def first_cached(self, start, origin):
        return self.first_legs(start, origin)

    @lru_cache(maxsize=12)
    def last_cached(self, deadline, destination):
        return self.project(self.planner.build_tails(deadline, destination, distinct=3), self.mid_alights)

    def journey(self, start, deadline, origin, destination, available=None):
        first = self.first_cached(start, origin) if available is None else self.first_legs(start, origin, available)
        last = self.last_cached(deadline, destination) if available is None else self.project(
            self.planner.build_tails(deadline, destination, available, distinct=3), self.mid_alights)
        best = winner = None
        for pid in first.keys() & last.keys():
            platforms = self.service.pattern_platforms[pid]
            route = self.service.patterns[pid][0]
            for board, heads in first[pid]:
                for alight, tails in last[pid]:
                    if alight <= board or platforms[alight] == platforms[board] or heads[0].ready > tails[0].cutoff:
                        continue
                    for head in heads:
                        for tail in tails:
                            if head.ready > tail.cutoff or head.vehicle[:2] == tail.vehicle[:2]:
                                continue
                            middle = self.service.ride_after(pid, board, alight, head.ready, available,
                                                            (head.vehicle[:2], tail.vehicle[:2]))
                            if middle is None or middle[0] > tail.cutoff:
                                continue
                            _, run = middle
                            vehicle = route, run, board, alight
                            walking = head.access + head.path.seconds + tail.path.seconds + tail.egress
                            key = (tail.arrival, walking, head.vehicle, vehicle, tail.vehicle)
                            if best is None or key < best:
                                best = key
                                third = [*tail.vehicle, tail.path.seconds, tail.path.required, tail.path.points]
                                second = [*vehicle, head.path.seconds, head.path.required, head.path.points, third]
                                winner = [*head.vehicle, head.access, tail.egress, second]
        return winner

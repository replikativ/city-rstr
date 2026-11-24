"""Bulk door-to-door feasibility bounds on the dated transit timetable."""
from collections import defaultdict

from numba import njit
import numpy as np


INF = 2_000_000_000


@njit
def scan(connections, trips, transfer_rows, transfer_links, platforms, boards, walk,
         start, deadline, rides, initial_margin):
    # Each row in ready and reached is a distinct boarding count. Staying on
    # the same run carries its label through stops without boarding again.
    ready = np.full((rides, platforms), INF, dtype=np.int32)
    reached = np.full((rides, platforms), INF, dtype=np.int32)
    aboard = np.zeros((rides, trips), dtype=np.bool_)
    for i in range(len(boards)):
        stop = boards[i]
        ready[0, stop] = min(ready[0, stop], start + walk[i] + initial_margin)
    first = np.searchsorted(connections[:, 0], start)
    end = np.searchsorted(connections[:, 0], deadline, side="right")
    for j in range(first, end):
        dep, arr, origin, target, run, can_board, can_alight = connections[j]
        if arr > deadline:
            continue
        for k in range(rides):
            if can_board and ready[k, origin] <= dep:
                aboard[k, run] = True
            if not aboard[k, run] or not can_alight or arr >= reached[k, target]:
                continue
            reached[k, target] = arr
            if k + 1 < rides:
                for n in range(transfer_rows[target], transfer_rows[target + 1]):
                    stop, seconds = transfer_links[n]
                    ready[k+1, stop] = min(ready[k+1, stop], arr + seconds)
    return reached


@njit
def door_labels(times, rows, access, final_margin):
    answer = np.full(len(rows)-1, INF, dtype=np.int32)
    for i in range(len(answer)):
        for j in range(rows[i], rows[i+1]):
            stop, walk = access[j]
            answer[i] = min(answer[i], times[stop] + walk + final_margin)
    return answer


def edges(rows):
    return (np.asarray(np.cumsum([0, *map(len,rows)]),dtype=np.int32),
            np.asarray([item for row in rows for item in row],dtype=np.int32).reshape(-1,2))


class Reach:
    def __init__(self, service, access, transfers, margin):
        self.margin = margin
        self.platforms = {stop:i for i,stop in enumerate(sorted(service.platforms))}
        self.stop_ids = list(self.platforms)
        physical = defaultdict(list)
        for stop,id_ in self.platforms.items():
            physical[service.platforms[stop]].append(id_)
        self.access = {p: np.asarray(sorted((id_,walk) for stop,walk in legs.items() for id_ in physical[stop]),
                                     dtype=np.int32).reshape(-1,2) for p,legs in access.items()}
        forward, reverse = ([[] for _ in self.platforms] for _ in range(2))
        for b,row in transfers.items():
            for a,path in row.items():
                ia,ib = self.platforms[a],self.platforms[b]
                forward[ia].append((ib,path.required))
                reverse[ib].append((ia,path.required))
        self.transfers = [edges(forward),edges(reverse)]
        blocks, run_index = [], 0
        self.vehicles = []
        for pid,(route,_,ids,times) in enumerate(service.patterns):
            if not service.mapped[pid]:
                continue
            stops = [self.platforms[p] for p in service.pattern_platforms[pid]]
            rules = service.access_rules[pid]
            shape = len(times),len(stops)-1
            columns = (times[:,1:-2:2], times[:,2::2], stops[:-1],stops[1:],
                       np.arange(run_index,run_index+len(times))[:,None],
                       [r&1 for r in rules[:-1]], [bool(r&2) for r in rules[1:]], np.arange(shape[1]))
            blocks.append(np.stack([np.broadcast_to(col,shape).ravel() for col in columns],axis=1).astype(np.int32))
            self.vehicles.extend((route, int(run)) for run in ids)
            run_index += len(times)
        self.runs = run_index
        arr = np.concatenate(blocks)
        # Traversing arrivals backward is an increasing clock after negation.
        # Physical board and alight rules exchange roles in that scan.
        back = arr[:,[1,0,3,2,4,6,5,7]].copy()
        back[:,:2] *= -1
        back[:,7] *= -1
        forward_order = np.lexsort((arr[:,7], arr[:,0]))
        self.segments = arr[forward_order,7]
        self.connections = [np.ascontiguousarray(arr[forward_order,:7]),
                            np.ascontiguousarray(back[np.lexsort((back[:,7], back[:,0])),:7])]

    def destinations(self, places):
        return edges([self.access.get(place,()) for place in places])

    def fits(self, start, end, origin, destination):
        """The final walk must fit the window as well as the last ride."""
        return self.query(origin, start, end - start, False, self.destinations([destination]))[0] <= end * 60

    def query(self, anchor, start, duration, reverse, destinations, rides=3):
        """Return earliest door arrival, or the negated latest departure in reverse."""
        access = self.access.get(anchor)
        if access is None:
            return np.full(len(destinations[0])-1,INF,dtype=np.int32)
        a,b = (-(start+duration)*60,-start*60) if reverse else (start*60,(start+duration)*60)
        reached = scan(self.connections[reverse],self.runs,*self.transfers[reverse],len(self.platforms),
                       access[:,0],access[:,1],a,b,rides,0 if reverse else self.margin)
        result = door_labels(reached.min(axis=0),*destinations,self.margin if reverse else 0)
        return result

"""Test longer transit travel windows around an incoming worker's fixed shift."""
from collections import Counter

from scripts.vancouver_regional_inbound_transit import connection_options, reserve_incoming
from scripts.vancouver_transit_commutes import BOARDING_MARGIN_SECONDS
from scripts.vancouver_work_transit import priority, transfer_inputs, window


EXTRA_MINUTES = (15, 30)
DAY_START, DAY_END = 240, 1680


def flex_window(row, extra):
    start, end, a, b = window(row)
    if row[-1]:
        return max(min(DAY_START, start), start-extra), end, a, b
    return start, min(max(DAY_END, end), end+extra), a, b


def as_booked(row, option):
    """Extend towards home only by the time required by the selected service."""
    start, end, a, b = window(row)
    latest, arrival, ride = option
    if row[-1]:
        start = min(start, latest)
    else:
        end = max(end, (arrival+59)//60)
    return [*row[:2], start, end-start, a, b, *ride]


class TimingSearch:
    def __init__(self, service, access, planner, available=None):
        self.direct = service.latest_departure(access, BOARDING_MARGIN_SECONDS, available)
        self.planner = planner
        self.available = available

    def journey(self, start, deadline, origin, destination):
        earliest = start//60
        direct = self.direct(deadline, origin, destination)
        transfer = self.planner.latest(deadline, origin, destination, self.available, earliest_minute=earliest)
        return min((option for option in (direct, transfer) if option and option[0] >= earliest),
                   key=lambda option: (-option[0], option[1], len(option[2])), default=None)


def add_timing_slack(rows, places, service, streets, schedule, spaces, baseline, prior, *, workers, checkpoint):
    identities, booked = reserve_incoming(rows, spaces, baseline, prior)
    original = set(booked)
    pending = [row for key, row in identities.items() if key not in booked and places[row[4]][:2] != places[row[5]][:2]]
    pending.sort(key=priority)
    windows = {flex_window(row, extra) for row in pending for extra in (EXTRA_MINUTES[-1:] if row[-1] else EXTRA_MINUTES)}
    access, planner = transfer_inputs(windows, places, service, streets, schedule)
    windows = sorted((w for w in windows if w[2] in access and w[3] in access), key=lambda w: (w[3], w[1], w[2], w[0]))
    print(f"Checking {len(windows):,} distinct windows for extra commute time", flush=True)
    choices = connection_options(TimingSearch(service, access, planner), windows, workers, checkpoint,
                                 ("commute-timing", baseline.name, schedule.name, streets.name, EXTRA_MINUTES))
    limited = TimingSearch(service, access, planner, spaces.available)
    coverage = Counter(key[:2] for key in booked)
    both_before = sum(n == 2 for n in coverage.values())
    outcomes = Counter({k: n for k,n in prior["outcomes"].items() if k not in {"schedule", "capacity", "rerouted", "scheduleOrCapacity"}})
    stages = []
    for extra in EXTRA_MINUTES:
        fitted, possible = Counter(), Counter()
        for row in pending:
            key = tuple(row[:3])
            if key in booked:
                continue
            bound = flex_window(row, extra)
            option = choices.get(flex_window(row, EXTRA_MINUTES[-1]) if row[-1] else bound)
            if not option or option[0] < bound[0]:
                continue
            direction = "towardWork" if row[-1] else "fromWork"
            possible[direction] += 1
            if not spaces.fits(option[2]):
                start, end, a, b = bound
                option = limited.journey(start*60, end*60, a, b)
                if option is None:
                    continue
            booked[key] = as_booked(row, option)
            spaces.reserve(option[2])
            coverage[key[:2]] += 1
            fitted[direction] += 1
            outcomes[direction] += 1
            outcomes["transfer" if len(option[2]) > 6 else "direct"] += 1
        stages.append(dict(extraMinutes=extra, feasible=dict(possible), booked=dict(fitted),
                           bothDirections=sum(n == 2 for n in coverage.values())))
    outcomes["scheduleOrCapacity"] = len(rows) - len(booked) - outcomes["access"] - outcomes["sameCoordinates"]
    assigned = [(row, identities[key][-1]) for key, row in booked.items()]
    evidence = dict(version=baseline.name, retained=len(original), added=len(booked)-len(original),
                    pairedBefore=both_before, stages=stages)
    return sorted(assigned, key=lambda item: item[0][:3]), dict(outcomes), evidence, [booked[k] for k in sorted(booked.keys()-original)]

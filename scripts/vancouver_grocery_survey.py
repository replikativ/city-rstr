"""Estimate the grocery share of weekday store purchases in the 2010 Canadian GSS."""
from collections import defaultdict
import hashlib
from itertools import groupby
from pathlib import Path
from zipfile import ZipFile

import numpy as np

# Appendix G of the Cycle 24 User Guide. In-person retail goods, including fuel;
# omit online purchases, purchase research, services, takeout and ambiguous codes.
GOODS = {b"301.0", b"302.1", b"302.4", b"302.9", b"310.1", b"380.1", b"380.3"}
TRAVEL = set(range(12, 22))
MODES = {12: "car-driver", 14: "walk", 17: "bike"}
SOURCE = "https://www150.statcan.gc.ca/n1/pub/45-25-0001/index-eng.htm"


def occasions(episodes):
    """Isolated retail dwell, with two pure legs of the same mode and fixed non-store anchors."""
    groups = []
    for _, rows in groupby(episodes, key=lambda e: "travel" if e[0] in TRAVEL else e[0]):
        groups.append(list(rows))
    for a, incoming, stop, onward, b in zip(groups, groups[1:], groups[2:], groups[3:], groups[4:]):
        place, act, weight, start, dwell = stop[0]
        if len(stop) != 1 or place not in (6, 7) or act not in GOODS:
            continue
        if any(x[0] in TRAVEL | {6, 7, 97, 98, 99} for x in (a[0], b[0])):
            continue
        mode = incoming[0][0]
        if mode in MODES and all(e[0] == mode for e in incoming + onward):
            yield MODES[mode], place == 6 and act == b"301.0", weight, start, dwell


def read_survey(archive):
    people = {}
    samples = defaultdict(list)
    with ZipFile(archive) as z:
        # Positions are one-based in Statistics Canada's SAS layouts in this same file.
        with z.open("PUMF/Data_Données/C24PUMFM.DAT") as stream:
            for row in stream:
                if row[75:76] == b"1" and row[78:79] == b"1":  # larger urban centres, weekday
                    people[int(row[:5])] = "bc" if int(row[72:74]) == 59 else "otherUrban"
        with z.open("PUMF/Data_Données/C24EPISODE_withno_bootstrap.DAT") as stream:
            for person, rows in groupby(stream, key=lambda row: int(row[:5])):
                if person not in people:
                    continue
                diary = [(int(r[45:47]), r[20:25].strip(), float(r[7:17]), int(r[33:37]), int(r[41:45]))
                         for r in rows]
                for mode, grocery, weight, start, dwell in occasions(diary):
                    samples[people[person], mode].append((person, grocery, weight, start, dwell))
        contributors = {r[0] for rows in samples.values() for r in rows}
        replicates = {}
        with z.open("PUMF/Data_Données/C24EPISODE_bootstrap.DAT") as stream:
            for row in stream:
                person = int(row[:5])
                if person in contributors:
                    weights = np.frombuffer(row[5:5005], dtype="S10").astype(float)
                    if len(weights) != 500 or person in replicates:
                        raise ValueError("Invalid GSS episode bootstrap weights")
                    replicates[person] = weights
    def summary(rows):
        by_person, times = defaultdict(float), defaultdict(float)
        rep_goods, rep_total = np.zeros(500), np.zeros(500)
        for person, grocery, w, start, dwell in rows:
            by_person[person] += w
            rep_total += replicates[person]
            if grocery:
                times[start, dwell] += w
                rep_goods += replicates[person]
        total = sum(by_person.values())
        mass = sum(times.values())
        grocery_donors = len({r[0] for r in rows if r[1]})
        share = mass / total if total else None
        # Cycle 24 mean bootstrap: 500 replicates, Fay adjustment 25 (Guide, Appendix B).
        se = (25 * np.mean((rep_goods / rep_total - share)**2))**.5 if total and np.all(rep_total > 0) else None
        reliable = grocery_donors >= 15 and share and se is not None and se / share <= .333
        interval = [max(0, share - 1.96*se), min(1, share + 1.96*se)] if reliable else None
        return dict(donors=len(by_person), stops=len(rows), groceryStops=sum(r[1] for r in rows),
                    groceryDonors=grocery_donors,
                    effective=round(total**2 / sum(w*w for w in by_person.values()), 1) if total else 0,
                    share=share if reliable else None, interval=interval,
                    clock=[[s, d, w/mass] for (s,d), w in sorted(times.items())] if reliable else [])
    return dict(source=SOURCE, sha256=hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
                pools={p: {m: summary(samples[p,m]) for m in MODES.values()} |
                       {"active": summary(samples[p,"walk"] + samples[p,"bike"])}
                       for p in ("bc", "otherUrban")})

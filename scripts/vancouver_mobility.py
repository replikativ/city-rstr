"""Compare private-household resident weekdays with the independent 2023 City transportation survey."""
from collections import Counter
from itertools import groupby

from scripts.vancouver_walks import MOBILE

SOURCE="https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF"
# Fall 2023 survey. Figures 31 and 41 (footnote 27) and the 45–49 group in Figure 33.
SURVEY={"rate":3.0,"age45to49":3.9,"shares":{"Auto driver":39.9,"Auto passenger":6.7,
        "Transit":16.7,"Walking":28.8,"Cycling":7.9}}
PRIORITY=("transit","car-driver","car-passenger","bike","taxi","ridehail","motorcycle",
          "ferry","air","travel-other","travel-ns","walk")
REPORT={"transit":"Transit","car-driver":"Auto driver","motorcycle":"Auto driver","car-passenger":"Auto passenger",
        "taxi":"Auto passenger","ridehail":"Auto passenger","bike":"Cycling","walk":"Walking"}


def travel_bouts(episodes, *, priority=PRIORITY, report=REPORT):
    """One primary mode per uninterrupted travel bout, with its adjacent diary episodes."""
    at = 0
    for moving, items in groupby(episodes, key=lambda e: e[3] in MOBILE):
        group = list(items)
        end = at + len(group)
        if moving:
            modes = {e[3] for e in group}
            primary = next(x for x in priority if x in modes)
            yield (group[0][0], report.get(primary, "Other / unspecified"),
                   episodes[at - 1] if at else None, episodes[end] if end < len(episodes) else None)
        at = end


def mode_counts(episodes):
    return Counter(mode for _, mode, _, _ in travel_bouts(episodes))


def summarize(weights,counts):
    people=sum(weights.values());modes=Counter()
    for t,n in weights.items():
        for mode,count in counts[t].items():
            modes[mode]+=n*count
    total=sum(modes.values())
    return dict(people=people,trips=total,rate=total/people if people else None,modes=dict(modes))


class MobilityAudit:
    def __init__(self, diaries):
        self.counts=[mode_counts(d["episodes"]) for d in diaries]
        self.age20=Counter()
        self.teens=Counter()
        self.age45=Counter()
        self.masked=0

    def add(self, residents, private):
        for p in residents[:private]:
            age=p[0]
            if 4<=age<=13:
                self.age20[p[-1]]+=1
                if age==9:self.age45[p[-1]]+=1
            elif age==3:self.teens[p[-1]]+=1
            elif age==88:self.masked+=1

    def report(self):
        weighted=self.age20.copy()
        for t,n in self.teens.items():weighted[t]+=.4*n
        return dict(source=SOURCE,survey=SURVEY,main=summarize(weighted,self.counts),
                    age20plus=summarize(self.age20,self.counts),age45to49=summarize(self.age45,self.counts),
                    unknownPrivateAge=self.masked)

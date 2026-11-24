"""Publish aggregate evidence from the 2025 Vancouver by-election ballot markings."""
import argparse
from collections import Counter
import csv
import hashlib
from pathlib import Path

from scripts.vancouver_transit_commutes import pointer

SOURCE = "https://webtransfer.vancouver.ca/OpenData/csv/2025MunicipalBy-ElectionAnonymousBallotMarking.csv"
RESULTS = "https://council.vancouver.ca/20250415/documents/r9.pdf"
# The declared Council totals and Appendix A of the official result.
OFFICIAL_VOTES = dict(zip(range(100, 113),
    [459, 433, 404, 352, 8915, 33732, 652, 9267, 34448, 17352, 11581, 276, 15045], strict=True))
OFFICIAL_BALLOTS = {"General": 54_854, "Advance": 7_678, "Mail": 5_430}
MAX_MARKS = 2


def summarize(rows):
    title, contest, labels, parties = (next(rows, []) for _ in range(4))
    if not title or title[0] != "City of Vancouver 2025 ByElection" or parties[:3] != [
        "CountingGroup", "PrecinctPortion", "BallotType"
    ]:
        raise ValueError("Expected the City's 2025 Vancouver by-election ballot file")
    names = {}
    for label, party in zip(labels[3:], parties[3:], strict=True):
        code, name = label.split(" ", 1)
        names[int(code)] = {"name": name, "party": party}
    if (len(names) != len(labels)-3 or names.keys() != OFFICIAL_VOTES.keys()
            or contest[3:] != ["COUNCILLOR (Vote For=2)"] * len(names)):
        raise ValueError("Expected all 13 candidates for the two-seat Council contest")

    counts = {group: Counter() for group in OFFICIAL_BALLOTS}
    votes = Counter()
    pairs = {group: Counter() for group in OFFICIAL_BALLOTS}
    for line, row in enumerate(rows, start=5):
        if len(row) != len(labels) or row[0] not in counts or any(mark not in ("0", "1") for mark in row[3:]):
            raise ValueError(f"Invalid ballot at CSV line {line}")
        chosen = tuple(code for code, mark in zip(names, row[3:], strict=True) if mark == "1")
        if len(chosen) > MAX_MARKS:
            raise ValueError(f"Unexpected recorded overvote at CSV line {line}")
        group = row[0]
        counts[group][len(chosen)] += 1
        votes.update(chosen)
        if len(chosen) == MAX_MARKS:
            pairs[group][tuple(sorted(chosen))] += 1

    if {group: counts[group].total() for group in counts} != OFFICIAL_BALLOTS or votes != OFFICIAL_VOTES:
        raise ValueError("CSV does not reconcile with the official ballot and candidate totals")

    def group_summary(mark_counts, pair_counts):
        if pair_counts.total() != mark_counts[MAX_MARKS]:
            raise ValueError("Pair counts do not reconcile with two-mark ballots")
        return dict(ballots=mark_counts.total(), marks=[mark_counts[i] for i in range(MAX_MARKS+1)],
                    pairs=[[a, b, count] for (a, b), count in
                           sorted(pair_counts.items(), key=lambda pair: (-pair[1], pair[0]))])

    return dict(schema=1, election="2025 Vancouver municipal by-election", source=SOURCE, official=RESULTS,
                candidates={code: dict(item, votes=votes[code]) for code, item in names.items()},
                all=group_summary(sum(counts.values(), Counter()), sum(pairs.values(), Counter())),
                groups={group: group_summary(counts[group], pairs[group]) for group in counts})


def publish(csv_path, output):
    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        report = summarize(csv.reader(source))
    report["sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    pointer(output, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, nargs="?",
                        default=Path("data/civic") / SOURCE.rsplit("/", 1)[-1])
    parser.add_argument("--output", type=Path, default=Path("public/data/vancouver/voting/ballots-2025.json"))
    args = parser.parse_args()
    report = publish(args.csv, args.output)
    print(report["all"]["ballots"], "ballots", report["all"]["marks"], "by recorded mark count",
          report["groups"]["Advance"]["marks"], "advance")

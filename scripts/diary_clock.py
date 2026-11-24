"""Read the shared Clojure weekday clock once per offline producer process."""
from functools import cache
import json
from pathlib import Path
import subprocess


@cache
def phase_period():
    repo = Path(__file__).resolve().parents[1]
    return tuple(json.loads(subprocess.check_output(
        ["clojure", "-J-XX:-UsePerfData", "-M", "-m", "city.vancouver.diary-clock"], cwd=repo)))

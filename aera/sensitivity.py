"""How the feasible share changes with the non-inferiority tolerance, from stored run files.

    python -m aera.sensitivity
Reads only the stored run files (each scenario row carries the BSM1 default's shares), so nothing is simulated.
A run with no scored scenarios (for example an LLM that never submitted) counts as infeasible at every tolerance.
"""
import json
from collections import defaultdict
from . import benchmark as bench
from .leaderboard import ROOT

TOLERANCES = (0.0, 0.005, 0.01, 0.02, 0.05)

def feasible_at(run, tolerance):
    if not run["scenarios"]:
        return False
    for row in run["scenarios"].values():
        for limit in bench.LIMIT_NAMES:
            if row["share_over_limit"][limit] > row["reference_share_over_limit"][limit] + tolerance:
                return False
        if row["low_do_share"] > bench.LOW_DO_LIMIT:
            return False
    return True

def table():
    runs = [json.loads(p.read_text()) for p in sorted((ROOT / "runs").glob("*.json")) if "stage2" not in p.name]
    by = defaultdict(list)
    for r in runs:
        by[r["tuner"]].append(r)
    return {t: {tol: sum(feasible_at(r, tol) for r in rs) / len(rs) for tol in TOLERANCES} for t, rs in by.items()}

def markdown(data):
    head = "| Tuner | " + " | ".join(f"{t:g}" for t in TOLERANCES) + " |"
    rows = [head, "| --- |" + " --- |" * len(TOLERANCES)]
    for tuner, v in sorted(data.items()):
        rows.append(f"| {tuner} | " + " | ".join(f"{100 * v[t]:.0f}%" for t in TOLERANCES) + " |")
    return "\n".join(rows)

if __name__ == "__main__":
    print(markdown(table()))

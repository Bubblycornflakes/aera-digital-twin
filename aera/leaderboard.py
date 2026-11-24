"""Aggregate results/runs/*.json into results/leaderboard.json and a markdown table.

    python -m aera.leaderboard
To add a result, run your tuner with aera.run_benchmark and open a pull request with the new run files.
"""
import json
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent / "results"

def wilson(k, n, z=1.96):
    """95% Wilson score interval for a proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(float(max(0.0, centre - half)), 3), round(float(min(1.0, centre + half)), 3))

def build(runs_dir=None):
    runs = [json.loads(p.read_text()) for p in sorted((Path(runs_dir) if runs_dir else ROOT / "runs").glob("*.json"))]
    groups = defaultdict(list)
    for r in runs:
        groups[r["tuner"]].append(r)
    rows = []
    for tuner, rs in groups.items():
        feasible = [r for r in rs if r["feasible"]]
        failed = defaultdict(int)
        for r in rs:
            for f in r["failures"]:
                failed[f"{f['scenario']}:{f['rule']}"] += 1
        rows.append(dict(tuner=tuner, runs=len(rs), feasible_rate=round(len(feasible) / len(rs), 3),
                         feasible_ci=wilson(len(feasible), len(rs)),
                         mean_saving_feasible_pct=round(float(np.mean([r["saving_pct"] for r in feasible])), 2) if feasible else None,
                         mean_trials=round(float(np.mean([r["trials"] for r in rs])), 1),
                         common_failures=sorted(failed.items(), key=lambda kv: (-kv[1], kv[0]))[:3]))
    # Pooled energy is not comparable across plants, so rank by feasible share, then saving against the default.
    rows.sort(key=lambda r: (-r["feasible_rate"], -(r["mean_saving_feasible_pct"] if r["mean_saving_feasible_pct"] is not None else -1e9), r["tuner"]))
    return rows

def markdown(rows, failures=True):
    head = ["Tuner", "Runs", "Feasible (95% interval)", "Saving vs BSM1 default, feasible runs"] + (["Most common failures"] if failures else [])
    out = ["| " + " | ".join(head) + " |", "|" + " --- |" * len(head)]
    for r in rows:
        fail = ", ".join(f"{k} ({v})" for k, v in r["common_failures"]) or "none"
        saving = f'{r["mean_saving_feasible_pct"]}%' if r["mean_saving_feasible_pct"] is not None else "n/a"
        lo, hi = r["feasible_ci"]
        cells = [r["tuner"], str(r["runs"]), f'{r["feasible_rate"]:.0%} ({lo:.0%} to {hi:.0%})', saving] + ([fail] if failures else [])
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", help="a folder of run files (default results/runs; use results/private_runs for the private set)")
    ap.add_argument("--out", help="where to write the JSON (default results/leaderboard.json)")
    a = ap.parse_args()
    rows = build(a.runs)
    (Path(a.out) if a.out else ROOT / "leaderboard.json").write_text(json.dumps(rows, indent=1))
    print(markdown(rows))

"""Re-score stored runs with the current held-out scenarios and model, keeping each run's answer and trial history.

    python -m aera.rescore                 # every file in results/runs
Use this after changing the held-out set, the plant or the scoring, so old answers are judged by the same rules as new
ones. Training histories are not recomputed (they were produced by the earlier model version and are marked as such).
"""
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from . import benchmark as bench, bsm1_dynamic as dyn, private_set
from .run_benchmark import PRIVATE_RUNS as PRIVATE, RUNS

def one(path):
    run = json.loads(open(path).read())
    if not run.get("answer"):                       # no submission: nothing to score
        return path.name, "skipped (no answer)"
    result = bench.score(bench.PLANTS[run["plant"]], run["answer"], stage=run.get("stage", 1))
    run.update(feasible=result["feasible"], aeration_energy_kwh_d=result["aeration_energy_kwh_d"],
               reference_energy_kwh_d=result["reference_energy_kwh_d"], saving_pct=result["saving_pct"],
               scenarios_failed=result["scenarios_failed"], failures=result["failures"], scenarios=result["scenarios"],
               scored_model_version=dyn.MODEL_VERSION, scored_fingerprint=dyn.fingerprint())
    path.write_text(json.dumps(run, indent=1))
    return path.name, "feasible" if run["feasible"] else "infeasible"

def one_private(args):
    """Score one stored answer on the private set (same plant it was tuned on) and write the result under results/private_runs."""
    path, held_out = args
    run = json.loads(path.read_text())
    if not run.get("answer") or run["plant"] not in bench.PLANTS:
        return path.name, "skipped"
    scenarios, _, label = private_set.load(held_out)
    result = bench.score(bench.PLANTS[run["plant"]], run["answer"], scenarios=scenarios, stage=run.get("stage", 1))
    run.update(held_out_set=label, feasible=result["feasible"], aeration_energy_kwh_d=result["aeration_energy_kwh_d"],
               reference_energy_kwh_d=result["reference_energy_kwh_d"], saving_pct=result["saving_pct"], scenarios_failed=result["scenarios_failed"],
               failures=result["failures"], scenarios=result["scenarios"], scored_fingerprint=dyn.fingerprint())
    run.pop("scored_model_version", None)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    (PRIVATE / path.name).write_text(json.dumps(run, indent=1))
    return path.name, "feasible" if run["feasible"] else "infeasible"

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--held-out", help="score every stored answer on this private set instead; results go to results/private_runs")
    args = ap.parse_args(argv)
    paths = sorted(RUNS.glob("*.json"))
    if args.held_out:
        dyn.standard_start()
        with ProcessPoolExecutor(min(8, os.cpu_count() or 1)) as pool:
            for name, status in pool.map(one_private, [(p, args.held_out) for p in paths]):
                print(name, status, flush=True)
        return
    dyn.standard_start()                            # create it once before the workers start
    with ProcessPoolExecutor(min(8, os.cpu_count() or 1)) as pool:
        for name, status in pool.map(one, paths):
            print(name, status, flush=True)

if __name__ == "__main__":
    sys.exit(main())

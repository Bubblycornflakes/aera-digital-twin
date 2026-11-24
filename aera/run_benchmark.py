"""Run tuners on the AeroBench plants and write one JSON file per run to results/runs/.

    python -m aera.run_benchmark                       # all reference tuners, all plants
    python -m aera.run_benchmark --tuner mymodule:fn   # your own tuner (signature: fn(env) -> params)
"""
import argparse
import inspect
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from . import benchmark as bench, bsm1_dynamic as dyn, private_set, tuners

RUNS = Path(__file__).resolve().parent.parent / "results" / "runs"

PRIVATE_RUNS = Path(__file__).resolve().parent.parent / "results" / "private_runs"

def one(job):
    spec, plant_name, seed, budget, label, stage, held_out = job
    scenarios, extra_plants, set_label = (None, {}, "public") if held_out is None else private_set.load(held_out)
    plants = {**bench.PLANTS, **extra_plants}
    tuner = tuners.load_tuner(spec)
    if "seed" in inspect.signature(tuner).parameters:
        fn = lambda env: tuner(env, seed=seed)
    else:
        fn = tuner
    started = time.time()
    result = bench.run_tuner(fn, plants[plant_name], budget, stage=stage, scenarios=scenarios)
    sc = result["score"]
    record = dict(tuner=label, plant=plant_name, seed=seed, budget=budget, stage=stage, held_out_set=set_label,
                  model_version=dyn.MODEL_VERSION, fingerprint=dyn.fingerprint(), trials=result["trials"], answer=result["answer"],
                  feasible=sc["feasible"], aeration_energy_kwh_d=sc["aeration_energy_kwh_d"],
                  reference_energy_kwh_d=sc["reference_energy_kwh_d"], saving_pct=sc["saving_pct"],
                  scenarios_failed=sc["scenarios_failed"], failures=sc["failures"], scenarios=sc["scenarios"],
                  history=[dict(params=h["params"], energy=h["aeration_energy_kwh_d"], feasible=h["feasible"],
                                violation=h["violation"]) for h in result["history"]],
                  seconds=round(time.time() - started))
    folder = RUNS if held_out is None else PRIVATE_RUNS      # private results are kept apart and are not committed
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{label}__{plant_name}__{seed}.json").write_text(json.dumps(record, indent=1))
    return record

def make_jobs(specs, plants, seeds, budget, stage, held_out=None):
    jobs = []
    for spec in specs:
        label = spec.replace(":", "_").replace(".", "_") + ("_stage2" if stage == 2 else "")
        takes_seed = "seed" in inspect.signature(tuners.load_tuner(spec)).parameters
        use = range(seeds) if takes_seed else [0]            # a tuner without a seed parameter is deterministic
        jobs += [(spec, p, sd, budget, label, stage, held_out) for p in plants for sd in use]
    return jobs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tuner", action="append", help="built-in name or module:function (repeatable)")
    ap.add_argument("--plants", nargs="*", default=None, help="plant names (default: the public plants; a private set can also name its own plants, such as private_plant_1)")
    ap.add_argument("--held-out", help="a private set file made by python -m aera.private_set generate; results go to results/private_runs")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--budget", type=int, default=40)
    ap.add_argument("--stage", type=int, choices=(1, 2), default=1, help="2 adds the ammonia cascade parameters")
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    args = ap.parse_args()
    plants = args.plants or list(bench.PLANTS)
    jobs = make_jobs(args.tuner or list(tuners.TUNERS), plants, args.seeds, args.budget, args.stage, args.held_out)
    bench.CACHE.mkdir(parents=True, exist_ok=True)
    # Workers may compute the same default controller reference at the same time; the cache writes are atomic, so the
    # only cost is duplicated simulation.
    with ProcessPoolExecutor(args.workers) as pool:
        for rec in pool.map(one, jobs):
            print(rec["tuner"], rec["plant"], rec["seed"], "feasible" if rec["feasible"] else "infeasible",
                  rec["aeration_energy_kwh_d"], f'{rec["saving_pct"]}%', f'{rec["seconds"]}s', flush=True)

if __name__ == "__main__":
    main()

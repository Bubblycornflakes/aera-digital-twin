"""Convert Inspect AI eval logs of aerobench_task.py into results/runs/*.json so LLM runs join the leaderboard.

    python -m aera.import_inspect results/logs/*.eval
Each sample becomes one run labelled llm_<model>. `nudges` records how often the harness had to re-prompt the model.
"""
import json
import re
import sys
from pathlib import Path
from inspect_ai.log import read_eval_log
from .aerobench import TRIAL_BUDGET
from .run_benchmark import RUNS

def label(model):
    return "llm_" + re.sub(r"[^A-Za-z0-9]+", "_", model).strip("_")

def text_of(content):
    """Message content is a string, or a list of parts in newer Inspect versions."""
    if isinstance(content, str):
        return content
    return "".join(getattr(part, "text", "") or "" for part in content)

def trials(sample):
    out = []
    for m in sample.messages:
        if m.role != "tool":
            continue
        try:
            t = json.loads(text_of(m.content))
            out.append(dict(params=t["params"], energy=t["aeration_energy_kwh_d"], feasible=t["feasible"],
                            violation=round(sum(f["excess"] for f in t["failures"]), 5)))
        except (ValueError, KeyError, TypeError):
            continue          # an error string such as "Trial budget exhausted"
    return out

def convert(log):
    records = []
    for s in log.samples or []:
        score = s.scores["held_out"]
        v = score.value
        name = f"{label(log.eval.model)}__{s.id}__{s.epoch}__{str(log.eval.run_id)[:8]}"   # a second log never overwrites
        base = dict(tuner=label(log.eval.model), plant=s.id, seed=s.epoch, budget=TRIAL_BUDGET, stage=1,
                    trials=int(v["trials_used"]), nudges=int(v.get("nudges", 0)), history=trials(s), seconds=0)
        if v["submitted"]:
            r = score.metadata["score"]
            rec = dict(base, answer=r["params"], feasible=r["feasible"], aeration_energy_kwh_d=r["aeration_energy_kwh_d"],
                       reference_energy_kwh_d=r["reference_energy_kwh_d"], saving_pct=r["saving_pct"],
                       scenarios_failed=r["scenarios_failed"], failures=r["failures"], scenarios=r["scenarios"])
        else:                                        # no submission: infeasible, nothing to score
            rec = dict(base, answer={}, feasible=False, aeration_energy_kwh_d=0.0, reference_energy_kwh_d=0.0, saving_pct=0.0,
                       scenarios_failed=[], failures=[dict(scenario="all", rule="no_submission", share=0, reference=0, excess=0)],
                       scenarios={})
        records.append((name, rec))
    return records

def main(paths):
    RUNS.mkdir(parents=True, exist_ok=True)
    for path in paths:
        for name, rec in convert(read_eval_log(path)):
            (RUNS / f"{name}.json").write_text(json.dumps(rec, indent=1))
            print("wrote", name, "feasible" if rec["feasible"] else "infeasible")

if __name__ == "__main__":
    main(sys.argv[1:])

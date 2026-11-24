"""AeroBench v2: tune the BSM1 reactor 5 DO controller from simulation trials, scored on unseen scenarios.

Design: docs/AEROBENCH_DESIGN.md. A tuner is any callable `tuner(env) -> params` that may call
`env.trial(params)` up to `env.budget` times on the training scenario and returns final parameters.
Final parameters are scored on held-out scenarios. Feasibility comes before energy.

Integrity: the budget is enforced by `Environment`, and the Inspect task exposes only `run_trial` and `submit_gains`
to a model. A Python tuner runs in the same process as the scorer and is trusted: nothing here stops a tuner that
imports `evaluate_scenario` or `score` directly. Results from tuners you did not run yourself are self-reported.
"""
import functools
import hashlib
import json
import math
import os
import threading
from dataclasses import dataclass, replace
from pathlib import Path
import numpy as np
from . import bsm1_dynamic as dyn

CACHE = Path(__file__).resolve().parent.parent / "results" / "cache"
TOLERANCE = 0.005      # share of time a limit may be exceeded beyond the BSM1 default controller (about 3 samples)
LOW_DO_LIMIT = 0.01    # nitrous oxide risk rule chosen by the author: true DO below 0.5 g/m3 for at most 1% of the time
PENALTY = 1e5          # makes any violation outweigh any energy difference during search

DEFAULT = dict(so_ref=2.0, k_do=25.0, ti_do=0.002, kla_max=360.0)
BOUNDS = dyn.BOUNDS
STAGES = {1: dict(bounds=dyn.BOUNDS, default=dict(DEFAULT)),
          2: dict(bounds=dyn.BOUNDS2, default=dict(DEFAULT, nh_gain=0.0, nh_ref=1.0))}
LIMIT_NAMES = tuple(dyn.LIMITS)

# Daily nitrogen load is about 582 kg N/d; digestate return liquor is typically 15 to 25% of it (Fux and Siegrist). 20% = 116 kg.
LIQUOR_KG = 116.0
TRAIN = {"dry": dyn.Scenario(weather="dry")}
# Held-out scenarios use the sensor noise file rotated by 3 days, so none of them reuses the training noise. The two
# dry weather scenarios still share the dry influent file with training; only the pulse or fault differs.
NOISE_SHIFT = 3.0
HELD_OUT = {
    "rain": dyn.Scenario(weather="rain", noise_shift=NOISE_SHIFT),
    "storm": dyn.Scenario(weather="storm", noise_shift=NOISE_SHIFT),
    "dry_return_liquor": dyn.Scenario(weather="dry", return_liquor_kg=LIQUOR_KG, noise_shift=NOISE_SHIFT),
    "dry_sensor_fault": dyn.Scenario(weather="dry", noise_scale=2.0, do_bias=0.3, lag_scale=5.0, noise_shift=NOISE_SHIFT),
    "rain_liquor_and_fault": dyn.Scenario(weather="rain", return_liquor_kg=LIQUOR_KG, noise_scale=2.0, do_bias=-0.3,
                                          noise_shift=NOISE_SHIFT),
}

@dataclass(frozen=True)
class Plant:
    name: str
    alpha_scale: float = 1.0   # oxygen transfer (fouling)
    mu_a_scale: float = 1.0    # nitrifier growth rate

PLANTS = {p.name: p for p in (Plant("benchmark"), Plant("fouled_diffusers", alpha_scale=0.75),
                              Plant("slow_nitrifiers", mu_a_scale=0.8))}

class BudgetExceeded(RuntimeError):
    pass

def clip_params(params, stage=1):
    """Fill missing parameters from the default and clip to the bounds. Non-finite values are rejected."""
    bounds, out = STAGES[stage]["bounds"], dict(STAGES[stage]["default"])
    for k, v in params.items():
        if k in bounds:
            v = float(v)
            if not math.isfinite(v):
                raise ValueError(f"parameter {k} is not finite: {v}")
            out[k] = v
    return {k: float(np.clip(out[k], *bounds[k])) for k in bounds}

def scenario_for(plant, scenario):
    return replace(scenario, alpha_scale=plant.alpha_scale, mu_a_scale=plant.mu_a_scale)

@functools.cache
def _fingerprint():
    return dyn.fingerprint()

def _key(params, scenario, mode):
    """Cache key: controller, scenario, solver mode and the model fingerprint (version, solver modes, start state)."""
    blob = json.dumps([{k: round(v, 9) for k, v in sorted(params.items())}, scenario.__dict__, mode, _fingerprint()],
                      sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]

def failed_indices(reason):
    """Stand-in for a simulation that did not converge: counts as infeasible and very expensive, never cached."""
    share = {k: 1.0 for k in dyn.LIMITS}
    return dict(eqi=1e9, aeration_energy_kwh_d=1e5, share_over_limit=share, low_do_share=1.0, average={}, p95={},
                trajectory=dict(day=[], so5=[], kla5=[], snh5=[]), seconds=0.0, solver_failed=reason)

def evaluate_scenario(params, scenario, mode="fast", use_cache=True):
    """Indices and a coarse trajectory for one controller on one scenario (cached on disk).
    params may include the stage 2 cascade keys nh_gain and nh_ref."""
    params = clip_params(params, 2 if "nh_gain" in params else 1)
    path = CACHE / f"{_key(params, scenario, mode)}.json"
    if use_cache and path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass  # another worker is writing it; recompute
    try:
        result = dyn.run(dyn.Controller(**params), scenario, mode=mode)
    except RuntimeError as error:             # the stiff solver can fail for extreme gains
        return failed_indices(str(error)[:200])
    out = dyn.indices(result)
    s = result["samples"]
    s = s[s[:, 0] >= 7 - 1e-9][::8]       # every 2 h from day 7
    out["trajectory"] = dict(day=s[:, 0].round(4).tolist(), so5=s[:, 2 + 52 + 7].round(3).tolist(),
                             kla5=s[:, 2 + dyn.I_KA + 1].round(2).tolist(), snh5=s[:, 2 + 52 + 9].round(3).tolist())
    out["seconds"] = round(result["seconds"], 1)
    if use_cache:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(out))
        os.replace(tmp, path)
    return out

def check(candidate, reference):
    """Non-inferiority to the BSM1 default controller on the same scenario, per effluent limit, plus the DO rule."""
    failures = []
    for limit in LIMIT_NAMES:
        share, ref = candidate["share_over_limit"][limit], reference["share_over_limit"][limit]
        if share > ref + TOLERANCE:
            failures.append(dict(rule=limit, share=round(share, 4), reference=round(ref, 4), excess=round(share - ref - TOLERANCE, 4)))
    if candidate["low_do_share"] > LOW_DO_LIMIT:
        failures.append(dict(rule="low_do", share=round(candidate["low_do_share"], 4), reference=LOW_DO_LIMIT,
                             excess=round(candidate["low_do_share"] - LOW_DO_LIMIT, 4)))
    return dict(feasible=not failures, failures=failures, violation=round(sum(f["excess"] for f in failures), 5))

def fitness(trial):
    """Lower is better: aeration energy plus a penalty large enough that violations always dominate."""
    return trial["aeration_energy_kwh_d"] + PENALTY * trial["violation"]

class Environment:
    """What a tuner sees: a trial budget on the training scenario. Held-out scenarios are not offered.

    Thread safe: concurrent trial() calls reserve budget before simulating, so the budget cannot be overshot.
    `budget` is read-only and `history` is a copy. This guards against accidents, not against a tuner that is
    determined to cheat (see the module docstring)."""
    def __init__(self, plant, budget=40, mode="fast", stage=1, history=None):
        self.plant, self.mode, self.stage = plant, mode, stage
        self._budget = int(budget)
        self._history = history if history is not None else []
        self._extra = 0          # trials charged for work done outside trial() (for example a step test)
        self._pending = 0        # trials reserved and still simulating
        self._lock = threading.Lock()
        self._bounds = {k: tuple(v) for k, v in STAGES[stage]["bounds"].items()}
        self._default = dict(STAGES[stage]["default"])

    budget = property(lambda self: self._budget)
    bounds = property(lambda self: dict(self._bounds))
    default = property(lambda self: dict(self._default))
    history = property(lambda self: tuple(self._history))

    @property
    def used(self):
        return len(self._history) + self._extra

    def history_list(self):
        return list(self._history)

    def charge(self, n):
        with self._lock:
            if self.used + self._pending + n > self._budget:
                raise BudgetExceeded("trial budget exhausted")
            self._extra += n

    def trial(self, params):
        """Run the training scenario. Returns metrics, feasibility against the BSM1 default, and a trajectory.
        A simulation that does not converge counts as a (very bad, infeasible) trial and uses budget."""
        params = clip_params(params, self.stage)          # raises ValueError for non-finite values, before charging
        with self._lock:
            if self.used + self._pending >= self._budget:
                raise BudgetExceeded("trial budget exhausted")
            self._pending += 1
        try:
            sc = scenario_for(self.plant, TRAIN["dry"])
            cand = evaluate_scenario(params, sc, self.mode)
            ref = evaluate_scenario(DEFAULT, sc, self.mode)
            verdict = check(cand, ref)
            out = dict(params=params, aeration_energy_kwh_d=cand["aeration_energy_kwh_d"], eqi=cand["eqi"],
                       share_over_limit=cand["share_over_limit"], low_do_share=cand["low_do_share"],
                       average=cand["average"], trajectory=cand["trajectory"], **verdict,
                       reference=dict(aeration_energy_kwh_d=ref["aeration_energy_kwh_d"],
                                      share_over_limit=ref["share_over_limit"]))
            if "solver_failed" in cand:
                out["solver_failed"] = cand["solver_failed"]
        finally:
            with self._lock:
                self._pending -= 1
        with self._lock:
            out["trials_left"] = self._budget - self.used - 1
            self._history.append(out)
        return out

    def best(self):
        return min(self._history, key=fitness)["params"] if self._history else dict(self._default)

def score(plant, params, mode="full", scenarios=HELD_OUT, stage=1):
    """Held-out score for one plant. Feasible only if every scenario passes."""
    params = clip_params(params, stage)
    rows = {}
    for name, sc in scenarios.items():
        sc = scenario_for(plant, sc)
        cand, ref = evaluate_scenario(params, sc, mode), evaluate_scenario(DEFAULT, sc, mode)
        verdict = check(cand, ref)
        rows[name] = dict(aeration_energy_kwh_d=cand["aeration_energy_kwh_d"], eqi=cand["eqi"],
                          reference_energy_kwh_d=ref["aeration_energy_kwh_d"], reference_eqi=ref["eqi"],
                          share_over_limit=cand["share_over_limit"], low_do_share=cand["low_do_share"],
                          reference_share_over_limit=ref["share_over_limit"], **verdict)
    energy = float(np.mean([r["aeration_energy_kwh_d"] for r in rows.values()]))
    ref_energy = float(np.mean([r["reference_energy_kwh_d"] for r in rows.values()]))
    failures = [dict(scenario=n, **f) for n, r in rows.items() for f in r["failures"]]
    return dict(plant=plant.name, params=params, feasible=not failures, failures=failures, scenarios=rows,
                aeration_energy_kwh_d=round(energy, 1), reference_energy_kwh_d=round(ref_energy, 1),
                saving_pct=round(100 * (ref_energy - energy) / ref_energy, 2),
                scenarios_failed=sorted({f["scenario"] for f in failures}))

def run_tuner(tuner, plant, budget=40, mode="fast", stage=1, scenarios=None):
    """Run a tuner under the trial budget and score its answer on held-out scenarios (the public set unless `scenarios` is given)."""
    env = Environment(plant, budget, mode, stage)
    try:
        answer = tuner(env)
    except BudgetExceeded:
        answer = env.best()
    answer = clip_params(answer if answer else env.best(), stage)
    return dict(trials=env.used, answer=answer, history=env.history_list(),
                score=score(plant, answer, stage=stage, **({} if scenarios is None else dict(scenarios=scenarios))))

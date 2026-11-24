"""Regression tests for defects found in review. None needs the BSM1 archive unless marked."""
import ast
import threading
import time
from pathlib import Path
import numpy as np
import pytest
from aera import benchmark as bench, bsm1_dynamic as dyn, leaderboard, run_benchmark, sensitivity, tuners
from .fakes import fake_evaluate

PKG = Path(__file__).resolve().parent.parent / "aera"
PLANT = bench.PLANTS["benchmark"]

def test_no_module_defines_a_name_twice():
    for file in PKG.glob("*.py"):
        names = [n.name for n in ast.parse(file.read_text()).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        assert len(names) == len(set(names)), f"{file.name} defines {sorted({n for n in names if names.count(n) > 1})} twice"

def test_fopdt_recovers_a_known_system_and_zn_gains_use_the_right_terms():
    K, L, T, step = 2.0, 0.003, 0.01, 10.0
    grid = np.linspace(0, 0.1, 2001)
    resp = step * K * np.where(grid > L, 1 - np.exp(-(grid - L) / T), 0.0)
    fit = tuners.fopdt(grid, resp, step)
    assert fit["gain"] == pytest.approx(K, rel=0.01)
    assert fit["tau"] == pytest.approx(T, rel=0.08) and fit["dead"] == pytest.approx(L, rel=0.2)
    kc = 0.9 * fit["tau"] / (fit["gain"] * fit["dead"])
    assert kc == pytest.approx(0.9 * T / (K * L), rel=0.25)       # Kc = 0.9 T / (K L), not 0.9 L / (K T)
    assert kc > 1.0                                               # the swapped version would give 0.14

def test_cache_key_depends_on_fingerprint_scenario_and_params(monkeypatch):
    sc = bench.scenario_for(PLANT, bench.HELD_OUT["rain"])
    monkeypatch.setattr(bench, "_fingerprint", lambda: "a")
    k1 = bench._key(bench.DEFAULT, sc, "full")
    assert k1 == bench._key(dict(bench.DEFAULT), sc, "full")
    monkeypatch.setattr(bench, "_fingerprint", lambda: "b")
    assert bench._key(bench.DEFAULT, sc, "full") != k1
    monkeypatch.setattr(bench, "_fingerprint", lambda: "a")
    assert bench._key(bench.DEFAULT, sc, "fast") != k1
    assert bench._key(dict(bench.DEFAULT, so_ref=2.1), sc, "full") != k1
    shifted = bench.scenario_for(PLANT, dyn.Scenario(weather="rain", noise_shift=3.0))
    assert bench._key(bench.DEFAULT, shifted, "full") != bench._key(bench.DEFAULT, bench.scenario_for(PLANT, dyn.Scenario(weather="rain")), "full")

def fake_run_factory(calls):
    def fake_run(ctrl, scenario, mode="fast", **kw):
        calls.append(ctrl)
        t = np.arange(0, 14, 1 / 96)
        samples = np.zeros((len(t), 2 + dyn.NSTATE))
        samples[:, 0] = t
        samples[:, 1] = 18446.0
        return dict(samples=samples, seconds=0.0)
    return fake_run

def test_results_cache_hits_and_goes_stale_when_the_model_changes(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(bench, "CACHE", tmp_path)
    monkeypatch.setattr(bench, "_fingerprint", lambda: "v1")
    monkeypatch.setattr(dyn, "run", fake_run_factory(calls))
    monkeypatch.setattr(dyn, "indices", lambda r: dict(eqi=1.0, aeration_energy_kwh_d=3000.0, share_over_limit={k: 0.0 for k in dyn.LIMITS},
                                                       low_do_share=0.0, average={}, p95={}))
    sc = bench.scenario_for(PLANT, bench.TRAIN["dry"])
    bench.evaluate_scenario(bench.DEFAULT, sc, "fast")
    bench.evaluate_scenario(bench.DEFAULT, sc, "fast")
    assert len(calls) == 1 and len(list(tmp_path.glob("*.json"))) == 1       # second call is a cache hit
    monkeypatch.setattr(bench, "_fingerprint", lambda: "v2")                 # model or start state changed
    bench.evaluate_scenario(bench.DEFAULT, sc, "fast")
    assert len(calls) == 2

def test_solver_failure_is_an_expensive_infeasible_trial_that_uses_budget_and_is_not_cached(monkeypatch, tmp_path):
    def fake_run(ctrl, scenario, mode="fast", **kw):
        if ctrl.so_ref == 2.0 and ctrl.k_do == 25.0:
            return fake_run_factory([])(ctrl, scenario)
        raise RuntimeError("BSM1 closed loop failed: step size too small")
    monkeypatch.setattr(bench, "CACHE", tmp_path)
    monkeypatch.setattr(bench, "_fingerprint", lambda: "v1")
    monkeypatch.setattr(dyn, "run", fake_run)
    monkeypatch.setattr(dyn, "indices", lambda r: dict(eqi=1.0, aeration_energy_kwh_d=3000.0, share_over_limit={k: 0.0 for k in dyn.LIMITS},
                                                       low_do_share=0.0, average={}, p95={}))
    env = bench.Environment(PLANT, budget=2)
    out = env.trial(dict(k_do=500.0, ti_do=0.0005))
    assert not out["feasible"] and "solver_failed" in out and env.used == 1
    assert bench.fitness(out) > bench.fitness(env.trial(bench.DEFAULT))       # a failed run never looks best
    assert len(list(tmp_path.glob("*.json"))) == 1                            # only the converged reference is cached

def test_non_finite_parameters_are_rejected_without_charging_budget():
    with pytest.raises(ValueError):
        bench.clip_params(dict(so_ref=float("nan")))
    with pytest.raises(ValueError):
        bench.clip_params(dict(k_do=float("inf")))
    env = bench.Environment(PLANT, budget=2)
    with pytest.raises(ValueError):
        env.trial(dict(so_ref=float("nan")))
    assert env.used == 0

def test_budget_cannot_be_overshot_by_concurrent_trials(monkeypatch):
    def slow(*a, **k):
        time.sleep(0.05)
        return fake_evaluate(*a, **k)
    monkeypatch.setattr(bench, "evaluate_scenario", slow)
    env = bench.Environment(PLANT, budget=3)
    results = []
    def worker(i):
        try:
            env.trial(dict(so_ref=1.5 + 0.1 * i))
            results.append("ok")
        except bench.BudgetExceeded:
            results.append("refused")
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 3 and results.count("refused") == 7 and env.used == 3

def test_budget_history_and_bounds_cannot_be_changed_by_accident(monkeypatch):
    monkeypatch.setattr(bench, "evaluate_scenario", fake_evaluate)
    env = bench.Environment(PLANT, budget=2)
    env.trial({})
    with pytest.raises(AttributeError):
        env.budget = 10 ** 6
    assert isinstance(env.history, tuple)
    env.bounds["so_ref"] = (0, 1000)
    env.default["so_ref"] = 99
    assert env.bounds["so_ref"] == bench.BOUNDS["so_ref"] and env.default["so_ref"] == 2.0
    assert env.used == 1

def test_every_held_out_scenario_uses_rotated_noise_and_training_does_not():
    assert bench.TRAIN["dry"].noise_shift == 0.0
    assert all(sc.noise_shift == bench.NOISE_SHIFT != 0 for sc in bench.HELD_OUT.values())

@pytest.mark.skipif(not (dyn.ARCHIVE / "sensornoise.mat").exists(), reason="BSM1 archive not extracted")
def test_noise_shift_rotates_the_file_without_changing_its_statistics():
    t, so, no = dyn.sensor_noise()
    t2, so2, no2 = dyn.sensor_noise(3.0)
    assert np.array_equal(t, t2) and len(so2) == len(so) and not np.array_equal(so, so2)
    assert np.array_equal(so2[:3 * 1440], so[3 * 1440:6 * 1440])
    assert np.sort(so[:-1]).tolist() == np.sort(so2[:-1]).tolist()
    assert np.array_equal(dyn.sensor_noise(0.0)[1], so)

def test_unsubmitted_runs_are_infeasible_in_the_sensitivity_table():
    assert sensitivity.feasible_at(dict(plant="benchmark", scenarios={}), 0.0) is False

def test_sensitivity_uses_only_the_run_file_and_the_tolerance():
    shares = lambda n, s: {"total_n": n, "total_cod": 0.0, "snh": s, "tss": 0.0, "bod5": 0.0}
    run = dict(scenarios=dict(rain=dict(share_over_limit=shares(0.195, 0.17), reference_share_over_limit=shares(0.18, 0.17),
                                         low_do_share=0.0)))
    assert not sensitivity.feasible_at(run, 0.0) and not sensitivity.feasible_at(run, 0.01)
    assert sensitivity.feasible_at(run, 0.02) and sensitivity.feasible_at(run, 0.05)
    run["scenarios"]["rain"]["low_do_share"] = 0.05
    assert not sensitivity.feasible_at(run, 0.05)                     # the DO rule does not relax with the tolerance

def test_wilson_interval_and_ranking_ignore_pooled_energy(tmp_path, monkeypatch):
    assert leaderboard.wilson(0, 3)[0] == 0.0 and 0.4 < leaderboard.wilson(0, 3)[1] < 0.6
    lo, hi = leaderboard.wilson(2, 9)
    assert 0.05 < lo < 0.22 < hi < 0.6
    assert leaderboard.wilson(0, 0) == (0.0, 0.0)
    import json
    (tmp_path / "runs").mkdir()
    def rec(tuner, feasible, energy, saving):
        return dict(tuner=tuner, feasible=feasible, aeration_energy_kwh_d=energy, saving_pct=saving, trials=40,
                    failures=[] if feasible else [dict(scenario="storm", rule="snh")])
    for i, r in enumerate([rec("cheap_plant", True, 3000, 0.0), rec("dear_plant", True, 4200, 1.0)]):
        (tmp_path / "runs" / f"{i}.json").write_text(json.dumps(r))
    monkeypatch.setattr(leaderboard, "ROOT", tmp_path)
    assert [r["tuner"] for r in leaderboard.build()] == ["dear_plant", "cheap_plant"]     # ranked by saving, not raw kWh

def test_import_reads_list_content_and_skips_error_strings():
    from aera import import_inspect
    class Part:
        text = '{"params": {}}'
    assert import_inspect.text_of([Part(), Part()]) == '{"params": {}}{"params": {}}'
    assert import_inspect.text_of("plain") == "plain"

def test_deterministic_tuners_get_one_seed_stochastic_ones_get_all():
    jobs = run_benchmark.make_jobs(["bsm1_default", "random_search", "examples.hill_climber:hill_climber"], ["benchmark"], 3, 40, 1)
    seeds = {}
    for spec, plant, seed, budget, label, stage, held_out in jobs:
        seeds.setdefault(spec, []).append(seed)
    assert seeds["bsm1_default"] == [0] and seeds["random_search"] == [0, 1, 2] and seeds["examples.hill_climber:hill_climber"] == [0, 1, 2]
    assert run_benchmark.make_jobs(["ziegler_nichols"], ["benchmark", "fouled_diffusers"], 3, 40, 2)[0][4] == "ziegler_nichols_stage2"
    assert all(job[6] is None for job in jobs) and run_benchmark.make_jobs(["bsm1_default"], ["benchmark"], 1, 40, 1, "set.json")[0][6] == "set.json"

def numerical_jacobian(rhs, y, t):
    base = rhs(t, y)
    J = np.zeros((len(y), len(y)))
    for j in range(len(y)):
        h = 1e-6 * max(1.0, abs(y[j]))
        yy = y.copy()
        yy[j] += h
        J[:, j] = (rhs(t, yy) - base) / h
    return J

@pytest.mark.parametrize("controller", [dyn.Controller(), dyn.Controller(nh_gain=0.8, nh_ref=1.5)])
def test_jacobian_sparsity_covers_every_true_dependency(controller):
    y = dyn.stabilise(controller, **dyn.MODES["full"])
    rhs = dyn.make_rhs(controller, lambda t: (dyn.Q0, dyn.plant.RAW), None, dyn.Scenario())
    J = numerical_jacobian(rhs, y, 0.3)
    significant = np.abs(J) > 1e-7 * (1 + np.abs(J).max(axis=1, keepdims=True))
    pattern = dyn.jacobian_pattern().toarray()
    assert not (significant & ~pattern).any(), np.argwhere(significant & ~pattern)[:5]
    from scipy.optimize._numdiff import group_columns
    assert group_columns(pattern).max() + 1 < 60

def test_every_stored_run_carries_what_the_docs_need():
    import json
    runs = sorted((Path(__file__).resolve().parent.parent / "results" / "runs").glob("*.json"))
    assert len(runs) >= 40
    for path in runs:
        r = json.loads(path.read_text())
        if r["scenarios"]:
            assert all("reference_share_over_limit" in row for row in r["scenarios"].values()), path.name
        assert r.get("scored_model_version") or r["tuner"] == "ziegler_nichols" or "model_version" in r, path.name

def test_doc_tables_match_the_results_files():
    from aera import update_docs
    assert update_docs.main(check=True) == [], "run: python -m aera.update_docs"

import json
import pytest
from pathlib import Path
from aera import benchmark as bench, bsm1_dynamic as dyn, leaderboard, tuners
from aera.bsm1_dynamic import ARCHIVE
from .fakes import fake_evaluate

_real = bench.evaluate_scenario
bench._real_evaluate_scenario = _real
needs_archive_bench = pytest.mark.skipif(not (ARCHIVE / "dryinfluent.mat").exists(), reason="BSM1 archive not extracted")

@pytest.fixture(autouse=True)
def fake_simulator(monkeypatch):
    monkeypatch.setattr(bench, "evaluate_scenario", fake_evaluate)

PLANT = bench.PLANTS["benchmark"]

def indices(**over):
    base = dict(share_over_limit=dict(total_n=0.18, total_cod=0.0, snh=0.17, tss=0.0, bod5=0.0), low_do_share=0.0)
    base.update(over)
    return base

def test_non_inferiority_rule():
    ref = indices()
    assert bench.check(indices(), ref)["feasible"]
    within = indices(share_over_limit=dict(total_n=0.18 + bench.TOLERANCE, total_cod=0.0, snh=0.17, tss=0.0, bod5=0.0))
    assert bench.check(within, ref)["feasible"]
    worse = indices(share_over_limit=dict(total_n=0.25, total_cod=0.0, snh=0.17, tss=0.0, bod5=0.0))
    verdict = bench.check(worse, ref)
    assert not verdict["feasible"] and verdict["failures"][0]["rule"] == "total_n" and verdict["violation"] > 0
    newly_violated = indices(share_over_limit=dict(total_n=0.18, total_cod=0.0, snh=0.17, tss=0.05, bod5=0.0))
    assert [f["rule"] for f in bench.check(newly_violated, ref)["failures"]] == ["tss"]
    assert [f["rule"] for f in bench.check(indices(low_do_share=0.05), ref)["failures"]] == ["low_do"]

def test_trial_budget_and_best():
    env = bench.Environment(PLANT, budget=3)
    for so in (1.0, 2.0, 3.0):
        env.trial(dict(so_ref=so))
    with pytest.raises(bench.BudgetExceeded):
        env.trial(dict(so_ref=2.5))
    assert env.used == 3
    assert env.best()["so_ref"] == pytest.approx(2.0)   # lower energy than 3.0, and 1.0 is infeasible

def test_charge_counts_against_budget():
    env = bench.Environment(PLANT, budget=3)
    env.charge(2)
    env.trial({})
    with pytest.raises(bench.BudgetExceeded):
        env.trial({})

def test_training_scenario_is_not_held_out():
    assert all(sc != bench.TRAIN["dry"] for sc in bench.HELD_OUT.values())
    assert bench.TRAIN["dry"].noise_scale == 1.0 and bench.TRAIN["dry"].return_liquor_kg == 0

def test_environment_never_exposes_held_out_scenarios():
    env = bench.Environment(PLANT)
    out = env.trial({})
    assert set(out) >= {"params", "aeration_energy_kwh_d", "feasible", "failures", "trajectory", "trials_left"}
    assert not hasattr(env, "scenarios") and "rain" not in json.dumps(out)

def test_params_are_clipped_to_bounds():
    p = bench.clip_params(dict(so_ref=99, k_do=-5, ti_do=1.0, kla_max=1e9, junk=1))
    assert p["so_ref"] == 5.0 and p["k_do"] == 1.0 and p["ti_do"] == 0.02 and p["kla_max"] == 360.0 and "junk" not in p

def test_score_flags_failing_scenarios():
    good = bench.score(PLANT, bench.DEFAULT)
    assert good["feasible"] and good["saving_pct"] == 0 and not good["failures"]
    bad = bench.score(PLANT, dict(so_ref=0.6))
    assert not bad["feasible"] and bad["scenarios_failed"]
    assert all({"scenario", "rule", "share", "reference", "excess"} <= set(f) for f in bad["failures"])

@pytest.mark.parametrize("name", ["bsm1_default", "random_search", "differential_evolution", "bayesian_optimisation"])
def test_tuners_respect_budget_and_bounds(name):
    result = bench.run_tuner(tuners.TUNERS[name], PLANT, budget=16)
    assert result["trials"] <= 16
    for k, (lo, hi) in bench.BOUNDS.items():
        assert lo <= result["answer"][k] <= hi

@pytest.mark.parametrize("name", ["random_search", "differential_evolution", "bayesian_optimisation"])
def test_stochastic_tuners_are_reproducible(name):
    a = bench.run_tuner(lambda e: tuners.TUNERS[name](e, seed=3), PLANT, budget=12)["answer"]
    b = bench.run_tuner(lambda e: tuners.TUNERS[name](e, seed=3), PLANT, budget=12)["answer"]
    assert a == b

def test_search_beats_random_on_a_smooth_problem():
    random_best = bench.run_tuner(lambda e: tuners.random_search(e, seed=1), PLANT, budget=24)
    bayes_best = bench.run_tuner(lambda e: tuners.bayesian(e, seed=1), PLANT, budget=24)
    assert bench.fitness(bayes_best["history"][-1]) is not None
    assert min(bench.fitness(h) for h in bayes_best["history"]) <= min(bench.fitness(h) for h in random_best["history"]) * 1.05

def test_encode_decode_roundtrip():
    for stage in (1, 2):
        bounds = bench.STAGES[stage]["bounds"]
        p = dict(so_ref=3.1, k_do=40.0, ti_do=0.004, kla_max=250.0, nh_gain=0.7, nh_ref=2.0)
        p = {k: p[k] for k in bounds}
        assert tuners.decode(tuners.encode(p, bounds), bounds) == pytest.approx(p)

def test_load_tuner_by_module_path():
    assert tuners.load_tuner("aera.tuners:random_search") is tuners.random_search
    assert tuners.load_tuner("bsm1_default") is tuners.default_controller

def test_leaderboard_aggregates(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    def rec(tuner, feasible, energy):
        return dict(tuner=tuner, feasible=feasible, aeration_energy_kwh_d=energy, saving_pct=1.0, trials=40,
                    failures=[] if feasible else [dict(scenario="storm", rule="snh")])
    for i, r in enumerate([rec("a", True, 3600), rec("a", False, 3500), rec("b", True, 3650)]):
        (runs / f"{i}.json").write_text(json.dumps(r))
    monkeypatch.setattr(leaderboard, "ROOT", tmp_path)
    rows = leaderboard.build()
    assert [r["tuner"] for r in rows] == ["b", "a"] and rows[1]["feasible_rate"] == 0.5
    assert rows[1]["common_failures"] == [("storm:snh", 1)]
    assert "| b | 1 | 100% (" in leaderboard.markdown(rows) and "kWh/d" not in leaderboard.markdown(rows)

@pytest.mark.skipif(not (ARCHIVE / "dryinfluent.mat").exists(), reason="BSM1 archive not extracted")
def test_step_test_gives_physical_values():
    st = tuners.step_test(PLANT)
    assert st["gain"] > 0 and 0 < st["dead"] < 0.05 and 0 < st["tau"] < 0.05

def test_stage_two_adds_cascade_parameters_and_keeps_default_equivalent():
    assert set(bench.STAGES[2]["bounds"]) == set(bench.BOUNDS) | {"nh_gain", "nh_ref"}
    assert bench.STAGES[2]["default"]["nh_gain"] == 0.0     # cascade off reproduces stage 1
    env = bench.Environment(PLANT, budget=4, stage=2)
    out = env.trial(dict(env.default, nh_gain=0.5))
    assert out["params"]["nh_gain"] == 0.5 and "nh_gain" in env.bounds
    result = bench.run_tuner(lambda e: tuners.random_search(e, seed=0), PLANT, budget=6, stage=2)
    assert set(result["answer"]) == set(bench.STAGES[2]["bounds"]) and result["trials"] == 6

def test_report_renders_and_escapes(tmp_path, monkeypatch):
    from aera import report
    run = dict(tuner="<b>x</b>", plant="benchmark", seed=0, trials=2, feasible=False, aeration_energy_kwh_d=3600.0,
               reference_energy_kwh_d=3700.0, saving_pct=2.7, answer=dict(so_ref=2.0), 
               scenarios=dict(storm=dict(aeration_energy_kwh_d=3600.0, reference_energy_kwh_d=3700.0, feasible=False,
                                         failures=[dict(rule="snh")])),
               history=[dict(energy=3600.0, feasible=True), dict(energy=3500.0, feasible=False)])
    rows = [dict(tuner="<b>x</b>", runs=1, feasible_rate=0.0, feasible_ci=(0.0, 0.79), mean_saving_feasible_pct=None,
                 common_failures=[("storm:snh", 1)])]
    page = report.render(rows, [run])
    assert "<b>x</b>" not in page and "&lt;b&gt;x&lt;/b&gt;" in page and "<svg" in page and "storm" in page

def test_reproduction_table_flags_differences():
    from aera import reproduction
    from aera.reference_values import PUBLISHED as P
    idx = dict(aeration_energy_kwh_d=P["aeration_energy_kwh_d"] * 1.01, eqi=P["eqi"], average=dict(snh=P["snh_avg"], total_n=P["total_n_avg"],
               tss=P["tss_avg"], cod=P["cod_avg"], bod5=P["bod5_avg"]),
               share_over_limit=dict(total_n=P["over_total_n"], snh=P["over_snh"]), p95=dict(snh=P["p95_snh"], total_n=P["p95_total_n"]))
    table = reproduction.rows(idx, dict(qintr=P["qintr_steady"]))
    text = reproduction.markdown(table, "full")
    assert "+1.0%" in text and "Largest relative difference" in text and len(table) == 12

def test_example_plugin_tuner_runs_under_budget():
    from examples.hill_climber import hill_climber
    result = bench.run_tuner(hill_climber, PLANT, budget=10)
    assert result["trials"] == 10
    assert result["history"][0]["params"] == pytest.approx(bench.DEFAULT)   # starts from the BSM1 default
    assert bench.fitness(min(result["history"], key=bench.fitness)) <= bench.fitness(result["history"][0])

# ---------- private held-out set ----------
import json as _json
from aera import private_set, rescore, run_benchmark

def test_a_private_set_is_deterministic_and_differs_by_seed():
    a, b, c = private_set.generate("seed-number-one-0000"), private_set.generate("seed-number-one-0000"), private_set.generate("seed-number-two-0000")
    assert a == b and a != c and a["commitment"] == private_set.commitment("seed-number-one-0000") != c["commitment"]
    assert private_set.label(a) == private_set.label(b) != private_set.label(c)

def test_a_private_set_stays_inside_documented_ranges_and_covers_every_weather_file():
    for seed in ("alpha-seed-0000000", "beta-seed-00000000", "gamma-seed-0000000"):
        spec = private_set.generate(seed)
        assert len(spec["scenarios"]) == 6 and len(spec["plants"]) == 3
        assert {s["weather"] for s in spec["scenarios"].values()} == {"dry", "rain", "storm"}
        for s in spec["scenarios"].values():
            lo, hi = private_set.RANGES["noise_scale"]
            assert s["noise_scale"] == 1.0 or lo <= s["noise_scale"] <= hi
            assert 0 <= s["noise_shift"] <= 13 and -0.5 <= s["do_bias"] <= 0.5 and 1.0 <= s["lag_scale"] <= 8.0
            if s["return_liquor_kg"]:
                assert 60 <= s["return_liquor_kg"] <= 200
                first = int(round((s["return_liquor_day"] + 8 / 24) * 96))
                assert 7 * 96 <= first and first + 24 <= 1344              # the pulse lies inside the weather file, in the scored week
        for p in spec["plants"].values():
            assert 0.6 <= p["alpha_scale"] <= 1.05 and 0.7 <= p["mu_a_scale"] <= 1.15

def test_commit_reveal_verification(tmp_path):
    path = tmp_path / "set.json"
    path.write_text(_json.dumps(private_set.generate("a-long-secret-seed-1")))
    assert private_set.verify("a-long-secret-seed-1", path) and not private_set.verify("a-different-seed-22", path)
    tampered = _json.loads(path.read_text())
    tampered["scenarios"]["private_1"]["do_bias"] = 0.49
    path.write_text(_json.dumps(tampered))
    assert not private_set.verify("a-long-secret-seed-1", path)

def test_the_command_line_refuses_a_guessable_seed_and_roundtrips(tmp_path, capsys):
    seed = tmp_path / "seed.txt"
    seed.write_text("short")
    assert private_set.main(["generate", "--seed-file", str(seed), "--out", str(tmp_path / "s.json")]) == 2 and "too short" in capsys.readouterr().err
    seed.write_text("0123456789abcdef0123")
    assert private_set.main(["generate", "--seed-file", str(seed), "--out", str(tmp_path / "s.json")]) == 0 and private_set.commitment("0123456789abcdef0123") in capsys.readouterr().out
    assert private_set.main(["verify", "--seed-file", str(seed), "--set", str(tmp_path / "s.json")]) == 0
    seed.write_text("ffffffffffffffffffff")
    assert private_set.main(["verify", "--seed-file", str(seed), "--set", str(tmp_path / "s.json")]) == 1

def test_load_builds_scenarios_and_plants_for_scoring(tmp_path):
    path = tmp_path / "set.json"
    path.write_text(_json.dumps(private_set.generate("load-test-seed-0000")))
    scenarios, plants, label = private_set.load(path)
    assert set(scenarios) == {f"private_{i}" for i in range(1, 7)} and set(plants) == {f"private_plant_{i}" for i in range(1, 4)}
    assert all(isinstance(s, dyn.Scenario) for s in scenarios.values()) and label.startswith("private:")
    bad = _json.loads(path.read_text()); bad["version"] = 99
    path.write_text(_json.dumps(bad))
    with pytest.raises(ValueError, match="unsupported"):
        private_set.load(path)

def test_scoring_on_a_private_set_uses_its_scenarios_not_the_public_ones(tmp_path):
    path = tmp_path / "set.json"
    path.write_text(_json.dumps(private_set.generate("scoring-seed-0000000")))
    scenarios, _, _ = private_set.load(path)
    r = bench.score(PLANT, bench.DEFAULT, scenarios=scenarios)
    assert set(r["scenarios"]) == set(scenarios) and not set(r["scenarios"]) & set(bench.HELD_OUT) and r["feasible"]

def test_running_a_tuner_against_a_private_set_labels_and_separates_the_results(tmp_path, monkeypatch):
    path = tmp_path / "set.json"
    path.write_text(_json.dumps(private_set.generate("runner-seed-00000000")))
    monkeypatch.setattr(run_benchmark, "PRIVATE_RUNS", tmp_path / "private_runs")
    monkeypatch.setattr(run_benchmark, "RUNS", tmp_path / "public_runs")
    monkeypatch.setattr(run_benchmark.dyn, "fingerprint", lambda: "test-fingerprint")          # the real one needs the benchmark archive
    rec = run_benchmark.one(("bsm1_default", "benchmark", 0, 4, "bsm1_default", 1, str(path)))
    assert rec["held_out_set"].startswith("private:") and set(rec["scenarios"]) == {f"private_{i}" for i in range(1, 7)}
    assert len(list((tmp_path / "private_runs").glob("*.json"))) == 1 and not (tmp_path / "public_runs").exists()
    public = run_benchmark.one(("bsm1_default", "benchmark", 0, 4, "bsm1_default", 1, None))
    assert public["held_out_set"] == "public" and (tmp_path / "public_runs").exists()

def test_rescoring_stored_answers_on_a_private_set_writes_only_to_the_private_folder(tmp_path, monkeypatch):
    path = tmp_path / "set.json"
    path.write_text(_json.dumps(private_set.generate("rescore-seed-0000000")))
    runs, private = tmp_path / "runs", tmp_path / "private_runs"
    runs.mkdir()
    (runs / "x__benchmark__0.json").write_text(_json.dumps(dict(tuner="x", plant="benchmark", answer=dict(so_ref=2.0), stage=1)))
    (runs / "y__benchmark__0.json").write_text(_json.dumps(dict(tuner="y", plant="benchmark", answer={}, stage=1)))
    monkeypatch.setattr(rescore, "PRIVATE", private)
    monkeypatch.setattr(bench.dyn, "fingerprint", lambda: "fp")
    assert rescore.one_private((runs / "x__benchmark__0.json", str(path)))[1] == "feasible"
    assert rescore.one_private((runs / "y__benchmark__0.json", str(path)))[1] == "skipped"
    out = _json.loads((private / "x__benchmark__0.json").read_text())
    assert out["held_out_set"].startswith("private:") and "private_1" in out["scenarios"] and "rain" not in out["scenarios"]
    assert _json.loads((runs / "x__benchmark__0.json").read_text()).get("held_out_set") is None              # the public file is untouched

def test_the_leaderboard_can_aggregate_any_runs_folder(tmp_path):
    from aera import leaderboard
    folder = tmp_path / "private_runs"
    folder.mkdir()
    for i, ok in enumerate((True, False)):
        (folder / f"{i}.json").write_text(_json.dumps(dict(tuner="t", feasible=ok, aeration_energy_kwh_d=3700.0, saving_pct=0.0, trials=40,
                                                         failures=[] if ok else [dict(scenario="private_1", rule="snh")])))
    rows = leaderboard.build(folder)
    assert rows[0]["runs"] == 2 and rows[0]["feasible_rate"] == 0.5 and rows[0]["common_failures"] == [("private_1:snh", 1)]

def test_private_material_is_git_ignored():
    text = (Path(__file__).resolve().parent.parent / ".gitignore").read_text()
    for pattern in ("results/private_runs/", "private_set*.json", "*seed*.txt"):
        assert pattern in text

@needs_archive_bench
def test_every_generated_private_scenario_actually_runs():
    """A real simulation of the default controller on each scenario of a generated set: none may crash, and the default is feasible against itself."""
    from tests.fakes import fake_evaluate  # noqa: F401  (not used: this test runs the real simulator)
    spec = private_set.generate("simulation-check-seed")
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "set.json"
        path.write_text(_json.dumps(spec))
        scenarios, plants, _ = private_set.load(path)
        monkey = pytest.MonkeyPatch()
        monkey.setattr(bench, "evaluate_scenario", bench.__dict__["_real_evaluate_scenario"])
        try:
            r = bench.score(next(iter(plants.values())), bench.DEFAULT, mode="fast", scenarios=scenarios)
        finally:
            monkey.undo()
    assert r["feasible"] and len(r["scenarios"]) == 6 and all(row["aeration_energy_kwh_d"] > 1000 for row in r["scenarios"].values())

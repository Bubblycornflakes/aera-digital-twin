import json
import pytest
from inspect_ai import eval as inspect_eval
from inspect_ai.model import ModelOutput, get_model
from aera import benchmark as bench
from aera.aerobench import TRIAL_BUDGET, aerobench
from .fakes import fake_evaluate

GOOD = dict(so_ref=2.6, k_do=30.0, ti_do=0.003, kla_max=360.0)

@pytest.fixture(autouse=True)
def fake_simulator(monkeypatch):
    monkeypatch.setattr(bench, "evaluate_scenario", fake_evaluate)

def scripted(calls, replies=1):
    """Per plant: the scripted tool calls, then `replies` plain text replies (one is enough if the script submits;
    a script that never submits is nudged 15 times and needs 16)."""
    outputs = []
    for _ in bench.PLANTS:
        for name, args in calls:
            outputs.append(ModelOutput.for_tool_call("mockllm/model", name, args))
        outputs += [ModelOutput.from_content("mockllm/model", "Done.") for _ in range(replies)]
    return get_model("mockllm/model", custom_outputs=outputs)

def run_eval(calls, tmp_path, replies=1):
    return inspect_eval(aerobench(), model=scripted(calls, replies), log_dir=str(tmp_path), display="none", max_samples=1)[0]

def test_submission_is_scored_on_held_out_scenarios(tmp_path):
    log = run_eval([("run_trial", GOOD), ("submit_gains", GOOD)], tmp_path)
    assert log.status == "success" and len(log.samples) == len(bench.PLANTS)
    for sample in log.samples:
        expected = bench.score(bench.PLANTS[sample.id], GOOD)
        value = sample.scores["held_out"].value
        assert value["submitted"] == 1 and value["trials_used"] == 1
        assert value["feasible"] == int(expected["feasible"])
        assert value["energy_kwh_day"] == expected["aeration_energy_kwh_d"]

def test_missing_submission_scores_zero(tmp_path):
    log = run_eval([("run_trial", GOOD)], tmp_path, replies=16)
    for sample in log.samples:
        v = sample.scores["held_out"].value
        assert v["submitted"] == 0 and v["feasible"] == 0

def test_infeasible_submission_reports_failures(tmp_path):
    bad = dict(GOOD, so_ref=0.6)
    log = run_eval([("submit_gains", bad)], tmp_path)
    for sample in log.samples:
        score = sample.scores["held_out"]
        assert score.value["feasible"] == 0
        assert json.loads(score.explanation)["failures"]

def test_trial_budget_enforced(tmp_path):
    log = run_eval([("run_trial", GOOD)] * (TRIAL_BUDGET + 1) + [("submit_gains", GOOD)], tmp_path)
    for sample in log.samples:
        assert sample.scores["held_out"].value["trials_used"] == TRIAL_BUDGET
        assert sum("exhausted" in str(m.content) for m in sample.messages if m.role == "tool") == 1

def test_trial_results_hide_held_out_scenarios(tmp_path):
    log = run_eval([("run_trial", GOOD), ("submit_gains", GOOD)], tmp_path)
    tool_text = " ".join(str(m.content) for s in log.samples for m in s.messages if m.role == "tool")
    for name in bench.HELD_OUT:
        assert name not in tool_text

def test_prompt_has_no_template_braces():
    from aera.aerobench import PROMPT
    assert "{" not in PROMPT and "}" not in PROMPT
    for key, (lo, hi) in bench.BOUNDS.items():
        assert key in PROMPT and str(lo) in PROMPT and str(hi) in PROMPT

def test_model_that_stops_without_a_tool_call_is_nudged(tmp_path):
    outputs = []
    for _ in bench.PLANTS:
        outputs += [ModelOutput.from_content("mockllm/model", "I will think about it."),
                    ModelOutput.for_tool_call("mockllm/model", "submit_gains", GOOD),
                    ModelOutput.from_content("mockllm/model", "Done.")]
    model = get_model("mockllm/model", custom_outputs=outputs)
    log = inspect_eval(aerobench(), model=model, log_dir=str(tmp_path), display="none", max_samples=1)[0]
    for sample in log.samples:
        v = sample.scores["held_out"].value
        assert v["submitted"] == 1 and v["nudges"] == 1
        assert any("Continue. Call run_trial" in str(m.content) for m in sample.messages if m.role == "user")

def test_nudging_is_capped(tmp_path):
    outputs = [ModelOutput.from_content("mockllm/model", "thinking") for _ in range(60)]
    model = get_model("mockllm/model", custom_outputs=outputs)
    log = inspect_eval(aerobench(), model=model, log_dir=str(tmp_path), display="none", max_samples=1, limit=1)[0]
    v = log.samples[0].scores["held_out"].value
    assert v["submitted"] == 0 and v["nudges"] == 15

def test_inspect_log_converts_to_leaderboard_run(tmp_path, monkeypatch):
    from inspect_ai.log import read_eval_log
    from aera import import_inspect, leaderboard
    log_path = tmp_path / "logs"
    log = run_eval([("run_trial", GOOD), ("submit_gains", GOOD)], log_path)
    records = dict(import_inspect.convert(read_eval_log(log.location)))
    assert len(records) == len(bench.PLANTS)
    rec = next(iter(records.values()))
    assert rec["tuner"].startswith("llm_") and rec["trials"] == 1 and rec["history"][0]["params"]["so_ref"] == GOOD["so_ref"]
    assert {"feasible", "scenarios", "failures", "answer", "saving_pct"} <= set(rec)
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(import_inspect, "RUNS", runs)
    monkeypatch.setattr(leaderboard, "ROOT", tmp_path)
    import_inspect.main([log.location])
    assert len(list(runs.glob("*.json"))) == len(bench.PLANTS)
    assert leaderboard.build()[0]["tuner"].startswith("llm_")

def test_missing_submission_imports_as_infeasible(tmp_path):
    from inspect_ai.log import read_eval_log
    from aera import import_inspect
    log = run_eval([("run_trial", GOOD)], tmp_path / "logs", replies=16)
    for _, rec in import_inspect.convert(read_eval_log(log.location)):
        assert not rec["feasible"] and rec["failures"][0]["rule"] == "no_submission"

def test_prompt_states_the_tolerance():
    from aera.aerobench import PROMPT
    assert "0.5 percentage points" in PROMPT

def test_invalid_parameters_use_no_trial_and_cannot_be_submitted(tmp_path):
    nan = dict(GOOD, so_ref=float("nan"))
    log = run_eval([("run_trial", nan), ("submit_gains", nan)], tmp_path, replies=16)
    for sample in log.samples:
        v = sample.scores["held_out"].value
        assert v["trials_used"] == 0 and v["submitted"] == 0
        tool_text = " ".join(str(m.content) for m in sample.messages if m.role == "tool")
        assert "Invalid parameters" in tool_text

"""Tests for the site tools (import, consents, appraisal, guardrails, audit, shadow mode)."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from aera import bsm1_dynamic as dyn
from aera.site import appraisal, audit, characterise, cli, config as cfg, consent, demo, guardrails, importer, replay, report, shadow

needs_archive = pytest.mark.skipif(not (dyn.ARCHIVE / "dryinfluent.mat").exists(), reason="BSM1 archive not extracted")

def make_config(tmp_path, rows, extra_tags=None, flow_unit="m3/h", design=30000, **data):
    """Write a small CSV and return a loaded SiteConfig for it."""
    (tmp_path / "d.csv").write_text(rows)
    tags = {"influent_flow": dict(column="Q", unit=flow_unit), "influent_nh4": dict(column="N", unit="mg/l")}
    tags.update(extra_tags or {})
    raw = dict(site=dict(name="t", design_flow_m3_d=design), data=dict(file="d.csv", tags=tags, **data), validation=dict(min_days=0.1))
    return cfg.SiteConfig.model_validate(raw)

def csv_from(times, flow=1250.0, nh4=30.0):
    """Realistic CSV text: values vary a little from row to row, because a constant value is (rightly) treated as a stuck sensor."""
    lines = ["Timestamp,Q,N"] + [f"{t},{flow + 3 * np.sin(i):.3f},{nh4 + np.cos(i):.3f}" for i, t in enumerate(times)]
    return "\n".join(lines)

def local_strings(start_utc, n):
    utc = pd.Timestamp(start_utc, tz="UTC") + pd.to_timedelta(np.arange(n) * 15, unit="min")
    return [x.strftime("%d/%m/%Y %H:%M") for x in utc.tz_convert("Europe/London")]

# ---------- configuration ----------
def write_toml(tmp_path, text):
    path = tmp_path / "site.toml"
    path.write_text(text)
    return path

GOOD = """
[site]
design_flow_m3_d = 30000
[data]
file = "d.csv"
[data.tags.influent_flow]
column = "Q"
unit = "Ml/d"
[data.tags.influent_nh4]
column = "N"
unit = "mg/l"
"""

def test_a_minimal_configuration_loads_with_sensible_defaults(tmp_path):
    c = cfg.load(write_toml(tmp_path, GOOD))
    assert c.site.timezone == "Europe/London" and c.control.do_setpoint == 2.0 and c.tariff.flat_gbp_per_kwh == 0.25
    assert cfg.unit_factor("influent_flow", "Ml/d") == 1000.0

@pytest.mark.parametrize("text, expect", [
    (GOOD.replace('[data.tags.influent_nh4]\ncolumn = "N"\nunit = "mg/l"', ""), "influent_nh4"),
    (GOOD.replace('unit = "Ml/d"', 'unit = "gallons"'), "not supported"),
    (GOOD + '\n[data.tags.pressure]\ncolumn = "P"\nunit = "bar"', "unknown tag"),
    (GOOD + '\n[[consent]]\nname = "x"\ntag = "effluent_nh4"\nkind = "absolute"\nlimit = 5', "not listed under [data.tags]"),
    (GOOD + '\n[data.tags.effluent_nh4]\ncolumn = "E"\nunit = "mg/l"\n[[consent]]\nname = "x"\ntag = "effluent_nh4"\nkind = "lut"\nlimit = 5', "look-up table"),
    (GOOD.replace("30000", "5"), "greater than 100"),
    ("[site\nbroken", "not valid TOML"),
])
def test_configuration_errors_say_what_to_change(tmp_path, text, expect):
    with pytest.raises(cfg.ConfigError) as error:
        cfg.load(write_toml(tmp_path, text))
    assert expect in str(error.value)

def test_missing_configuration_file_points_to_init(tmp_path):
    with pytest.raises(cfg.ConfigError, match="site init|aera.site init"):
        cfg.load(tmp_path / "nope.toml")

# ---------- importer ----------
def test_autumn_clock_change_is_resolved_not_dropped(tmp_path):
    # Local midnight 25 Oct 2026 BST is 23:00 UTC on the 24th. The clocks go back at 02:00 BST, so local 01:00-01:59 occurs twice.
    times = local_strings("2026-10-24 23:00", 16)             # 4 hours of UTC time
    assert len(set(times)) == 12                                # 01:00-01:45 appear twice in the text
    data = importer.load(make_config(tmp_path, csv_from(times)), tmp_path)
    assert len(data.table) == 16 and data.table.index.is_monotonic_increasing and data.table["influent_flow"].notna().all()
    assert any("autumn clock change" in n for n in data.report["notes"]) and not data.report["issues"]

def test_spring_clock_change_has_no_missing_hour_error(tmp_path):
    times = local_strings("2026-03-29 00:00", 16)               # 00:00 UTC is 00:00 GMT; 01:00 UTC becomes 02:00 BST
    data = importer.load(make_config(tmp_path, csv_from(times)), tmp_path)
    assert len(data.table) == 16 and data.table["influent_flow"].notna().all()
    assert data.table.index[1] - data.table.index[0] == pd.Timedelta("15min")

def test_units_are_converted_and_a_unit_mistake_is_flagged(tmp_path):
    times = local_strings("2026-06-01 00:00", 8)
    rows = "Timestamp,Q,N\n" + "\n".join(f"{t},{1.25 + 0.003 * np.sin(i):.4f},{30 + np.cos(i):.3f}" for i, t in enumerate(times))
    ok = importer.load(make_config(tmp_path, rows, flow_unit="Ml/d"), tmp_path)                 # 1.25 Ml/d = 1250 m3/d
    assert ok.table["influent_flow"].iloc[0] == pytest.approx(1250.0, rel=1e-6)
    assert ok.report["flow_to_design_ratio"] == pytest.approx(1250 / 30000, abs=0.002)
    assert any("times the design flow" in i for i in ok.report["issues"])                          # 0.04 of the design flow: units suspect
    per_hour = importer.load(make_config(tmp_path, csv_from(times, flow=1250.0), flow_unit="m3/h"), tmp_path)
    assert per_hour.table["influent_flow"].iloc[0] == pytest.approx(1250 * 24, rel=1e-6)           # 1250 m3/h = 30000 m3/d
    assert not any("times the design flow" in i for i in per_hour.report["issues"])

def test_bad_values_are_removed_counted_and_never_silent(tmp_path):
    times = local_strings("2026-06-01 00:00", 40)
    lines = csv_from(times).split("\n")
    cut = lambda i, q=None, n=None: lines.__setitem__(i, ",".join([lines[i].split(",")[0], q or lines[i].split(",")[1], n or lines[i].split(",")[2]]))
    cut(3, q="-999")                                               # logger error value
    cut(5, n="N/A")                                                # text
    cut(7, n="9999")                                               # beyond physical range
    data = importer.load(make_config(tmp_path, "\n".join(lines), design=30000), tmp_path)
    flow, nh4 = data.report["tags"]["influent_flow"], data.report["tags"]["influent_nh4"]
    assert flow["out_of_range"] == 1 and nh4["not_numeric"] == 1 and nh4["out_of_range"] == 1
    text = " ".join(data.report["issues"])
    assert "non-numeric" in text and "outside the physical range" in text
    assert data.table["influent_flow"].notna().all()               # single bad points are filled, not left as holes

def test_stuck_sensor_runs_and_long_gaps_are_reported_and_split_the_window(tmp_path):
    n = 4 * 24 * 3
    times = local_strings("2026-06-01 00:00", n)
    lines = csv_from(times).split("\n")
    for i in range(1 + 100, 1 + 140):                              # 10 hours with no flow value at all
        lines[i] = lines[i].split(",")[0] + ",," + lines[i].split(",")[2]
    conf = make_config(tmp_path, "\n".join(lines))
    data = importer.load(conf, tmp_path)
    assert len(data.windows) == 2                                  # the long gap separates two usable periods
    assert any("longest gap" in i for i in data.report["issues"])

def test_flat_lined_sensor_is_removed(tmp_path):
    times = local_strings("2026-06-01 00:00", 96)
    rows = [f"{t},{1250 + 3 * np.sin(i)},{35.0 if 20 <= i < 60 else 30 + np.sin(i)}" for i, t in enumerate(times)]
    data = importer.load(make_config(tmp_path, "Timestamp,Q,N\n" + "\n".join(rows)), tmp_path)
    assert data.report["tags"]["influent_nh4"]["flatline"] == 40

def test_duplicate_rows_are_dropped_and_counted(tmp_path):
    times = local_strings("2026-06-01 00:00", 12)
    text = csv_from(times + [times[3]])
    data = importer.load(make_config(tmp_path, text), tmp_path)
    assert any("duplicate timestamp" in i for i in data.report["issues"])

def test_unreadable_files_give_friendly_errors(tmp_path):
    conf = make_config(tmp_path, "Timestamp,Q,N\nnot a date,1,2\n")
    with pytest.raises(cfg.ConfigError, match="No rows with a readable timestamp"):
        importer.load(conf, tmp_path)
    (tmp_path / "d.csv").write_text("When,Q,N\n01/06/2026 00:00,1,2\n")
    with pytest.raises(cfg.ConfigError, match="Timestamp column 'Timestamp' is not in the file"):
        importer.load(conf, tmp_path)
    bad = cfg.SiteConfig.model_validate(dict(site=dict(design_flow_m3_d=30000), data=dict(file="missing.csv", tags=dict(
        influent_flow=dict(column="Q", unit="m3/d"), influent_nh4=dict(column="N", unit="mg/l")))))
    with pytest.raises(cfg.ConfigError, match="Data file not found"):
        importer.load(bad, tmp_path)

def test_raw_data_file_is_never_modified(tmp_path):
    times = local_strings("2026-06-01 00:00", 24)
    conf = make_config(tmp_path, csv_from(times))
    before = (tmp_path / "d.csv").read_bytes()
    importer.load(conf, tmp_path)
    assert (tmp_path / "d.csv").read_bytes() == before

# ---------- influent characterisation ----------
def test_influent_characterisation_honours_measured_cod_and_ammonium():
    feed = characterise.asm1_feed(np.array([20.0, 45.0]), np.array([300.0, 600.0]))
    assert feed[:, 9] == pytest.approx([20.0, 45.0])
    assert characterise.total_cod(feed) == pytest.approx([300.0, 600.0])
    assert (feed[:, [7, 8]] == 0).all() and (feed[:, 12] == 7.0).all()
    assert feed[1, 10] == pytest.approx(2 * feed[0, 10])           # organic nitrogen scales with COD

def test_without_cod_it_is_assumed_to_scale_with_ammonium():
    feed = characterise.asm1_feed(np.array([31.56]))
    assert characterise.total_cod(feed)[0] == pytest.approx(characterise.COD_REF)

# ---------- consents ----------
def spec(**kw):
    base = dict(name="x", tag="effluent_nh4", kind="absolute", limit=5.0)
    base.update(kw)
    return cfg.ConsentSpec(**base)

def days(values):
    return pd.Series(values, index=pd.date_range("2026-06-01", periods=len(values), freq="D"))

def test_absolute_consent():
    assert consent.check(spec(), days([1, 2, 4.9]))["status"] == "within"
    assert consent.check(spec(), days([1, 2, 5.1]))["status"] == "exceeds"

def test_percentile_consent_with_upper_tier():
    values = [1.0] * 94 + [5.5] * 6                                 # the 95th percentile is 5.5
    assert consent.check(spec(kind="percentile", limit=5.0), days(values))["status"] == "exceeds"
    assert consent.check(spec(kind="percentile", limit=6.0), days(values))["status"] == "within"
    r = consent.check(spec(kind="percentile", limit=6.0, upper_tier=5.0), days(values))
    assert r["status"] == "exceeds" and "upper tier" in r["detail"]

def test_annual_mean_and_sampling_frequency():
    assert consent.check(spec(kind="annual_mean", limit=3.0), days([2, 3, 3]))["status"] == "within"
    r = consent.check(spec(kind="absolute", limit=5.0, sample_every_days=7), days([9, 1, 1, 1, 1, 1, 1, 1, 1]))
    assert r["samples"] == 2 and r["status"] == "exceeds"           # days 0 and 7 are sampled, day 0 is 9
    worst = consent.check(spec(kind="absolute", limit=5.0, sample_every_days=7), days([1, 9, 9, 9, 9, 9, 9, 1]))
    assert worst["status"] == "exceeds" and "worst of 7 sampling phases" in worst["detail"]       # some sampling phase hits a 9

def test_look_up_table_consent():
    table = [(8, 1), (13, 2), (20, 3)]
    assert consent.lut_allowed(table, 5) == 0 and consent.lut_allowed(table, 8) == 1 and consent.lut_allowed(table, 19) == 2
    assert consent.check(spec(kind="lut", limit=5.0, lut=table), days([6, 1, 1, 1, 1, 1, 1, 1]))["status"] == "within"        # 1 of 8 allowed
    assert consent.check(spec(kind="lut", limit=5.0, lut=table), days([6, 6, 1, 1, 1, 1, 1, 1]))["status"] == "exceeds"

# ---------- appraisal ----------
def frame(kwh_d, n=96 * 2, start="2026-06-01 00:00"):
    idx = pd.date_range(start, periods=n, freq="15min", tz="UTC")
    return pd.DataFrame(dict(aeration_kwh_d=np.full(n, float(kwh_d)), flow=np.full(n, 1000.0)), index=idx)

def conf_with(tmp_path, **extra):
    c = make_config(tmp_path, "Timestamp,Q,N\n")
    return c.model_copy(update=extra)

def test_cost_and_carbon_arithmetic(tmp_path):
    c = conf_with(tmp_path)
    a = appraisal.appraise(frame(2400), None, c)                    # 2 days at 2400 kWh/d
    assert a["energy_kwh"] == pytest.approx(4800) and a["cost_gbp"] == pytest.approx(4800 * 0.25)
    assert a["carbon_t"] == pytest.approx(4800 * 0.13096 / 1000, rel=1e-3) and not a["calibrated"]
    assert a["annualised"]["energy_kwh"] == pytest.approx(2400 * 365, rel=1e-3)
    cal = appraisal.appraise(frame(2400), 1.5, c)
    assert cal["energy_kwh"] == pytest.approx(7200) and cal["calibrated"]
    assert a["cost_gbp_range"][0] < a["cost_gbp"] < a["cost_gbp_range"][1]

def test_time_of_use_bands_use_local_clock_time_across_bst(tmp_path):
    tariff = cfg.Tariff(flat_gbp_per_kwh=0.2, bands=[cfg.Band(start_hour=0, end_hour=7, gbp_per_kwh=0.1)])
    summer = pd.date_range("2026-07-01 00:00", periods=96, freq="15min", tz="UTC")        # BST: local = UTC + 1
    price = appraisal.price_series(summer, tariff, "Europe/London")
    assert price[0] == 0.1 and price[4 * 6 - 1] == 0.1 and price[4 * 6] == 0.2             # 00:00 UTC is 01:00 local; the cheap band ends at 07:00 local = 06:00 UTC
    winter = pd.date_range("2026-01-15 00:00", periods=96, freq="15min", tz="UTC")
    pw = appraisal.price_series(winter, tariff, "Europe/London")
    assert pw[4 * 7 - 1] == 0.1 and pw[4 * 7] == 0.2

def test_comparison_sign_convention(tmp_path):
    c = conf_with(tmp_path)
    d = appraisal.compare(appraisal.appraise(frame(2400), None, c), appraisal.appraise(frame(2280), None, c))
    assert d["energy_pct"] == -5.0 and d["cost_gbp"] < 0 and d["carbon_t"] < 0

# ---------- audit ----------
def test_audit_chain_detects_edits_and_deletions(tmp_path):
    path = tmp_path / "audit.jsonl"
    for i in range(4):
        audit.append(path, "step", dict(i=i))
    assert audit.verify(path)[0]
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[1].replace('"i": 1', '"i": 9').replace('"i":1', '"i":9'), lines[2], lines[3]]) + "\n")
    ok, message = audit.verify(path)
    assert not ok and "entry 2" in message
    path.write_text("\n".join([lines[0], lines[2], lines[3]]) + "\n")                       # a deleted entry
    assert not audit.verify(path)[0]
    path.write_text("\n".join(lines[:3]) + "\n")                                            # truncation of the last entry is not detectable here, but the rest is intact
    assert audit.verify(path)[0]

def replayed_report(tmp_path, status="ready_for_operator_review"):
    """A report.json with a matching replay entry in the audit record, as shadow.run leaves them."""
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(dict(recommendation=dict(status=status))))
    trail = tmp_path / "audit.jsonl"
    audit.append(trail, "replay", dict(report="report.json", report_sha256=audit.file_hash(report_path)))
    return report_path, trail

def test_approval_records_the_report_hash_and_status_and_changes_nothing(tmp_path):
    report_path, trail = replayed_report(tmp_path)
    entry = audit.approve(trail, report_path, "A. Engineer", "Reviewed, go ahead with step one")
    assert entry["details"]["report_sha256"] == audit.file_hash(report_path) and entry["details"]["recommendation_status"] == "ready_for_operator_review"
    assert "never changes a plant setting" in entry["details"]["effect"] and audit.verify(trail)[0]

def test_approval_refuses_a_report_that_is_not_ready_unless_an_override_reason_is_recorded(tmp_path):
    report_path, trail = replayed_report(tmp_path, "research_only")
    with pytest.raises(ValueError, match="not 'ready for operator review'"):
        audit.approve(trail, report_path, "A", "n")
    entry = audit.approve(trail, report_path, "A", "n", override_reason="Learning exercise, no change planned")
    assert entry["details"]["override_reason"] == "Learning exercise, no change planned" and entry["details"]["recommendation_status"] == "research_only"

def test_approval_refuses_a_changed_or_unknown_report(tmp_path):
    report_path, trail = replayed_report(tmp_path)
    report_path.write_text(json.dumps(dict(recommendation=dict(status="ready_for_operator_review"), edited=True)))
    with pytest.raises(ValueError, match="has been changed"):
        audit.approve(trail, report_path, "A", "n")
    other = tmp_path / "other.json"
    other.write_text("{}")
    with pytest.raises(ValueError, match="no replay of this report"):
        audit.approve(trail, other, "A", "n")

def test_a_kept_head_hash_detects_removed_entries_that_the_chain_alone_cannot(tmp_path):
    path = tmp_path / "audit.jsonl"
    for i in range(4):
        audit.append(path, "step", dict(i=i))
    head = audit.head(path)
    assert audit.verify(path, head)[0]
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:3]) + "\n")                    # the last entry was cut off
    assert audit.verify(path)[0]                                      # the chain alone cannot tell
    ok, message = audit.verify(path, head)
    assert not ok and "removed" in message
    assert "cannot be detected" in audit.verify(path)[1]

# ---------- guardrails ----------
def guard_config(tmp_path):
    return make_config(tmp_path, "Timestamp,Q,N\n")

within = lambda v=1.0: [dict(name="n", tag="effluent_nh4", status="within", value=v)]
exceeds = lambda v=7.0: [dict(name="n", tag="effluent_nh4", status="exceeds", value=v)]
checked = lambda status, **extra: dict(status=status, indicators={"effluent_nh4": dict(ok=True), "aeration_energy": dict(ok=True), **extra})

def test_staged_plan_steps_are_small_and_reach_the_target():
    assert guardrails.staged_plan(2.0, 1.2, 0.5) == [1.6, 1.2]
    assert guardrails.staged_plan(2.0, 2.0, 0.5) == []
    assert guardrails.staged_plan(2.0, 3.0, 0.5) == [2.5, 3.0]

@pytest.mark.parametrize("status, base, cand, so_ref, expected", [
    ("validated", within(), within(), 1.7, guardrails.READY),
    ("partly_validated", within(), within(), 1.7, guardrails.RESEARCH),
    ("not_validated", within(), within(), 1.7, guardrails.RESEARCH),
    ("cannot_validate", within(), within(), 1.7, guardrails.RESEARCH),
    ("validated", within(), exceeds(), 1.7, guardrails.REJECTED),
    ("validated", within(), within(), 0.4, guardrails.REJECTED),
    ("validated", exceeds(7.0), exceeds(7.0), 1.7, guardrails.READY),            # already exceeding and no worse
    ("validated", exceeds(7.0), exceeds(9.0), 1.7, guardrails.REJECTED),         # already exceeding and made worse
])
def test_recommendation_status(tmp_path, status, base, cand, so_ref, expected):
    r = guardrails.review(guard_config(tmp_path), dict(so_ref=so_ref), checked(status), base, cand, 0.0, 0.0)
    assert r["status"] == expected and r["advisory_only"] and "does not read from or write to" in r["statement"]
    assert (r["staged_setpoints"] != []) == (expected == guardrails.READY and so_ref != 2.0)           # steps appear only for a ready recommendation

def test_more_low_do_time_than_today_blocks_the_recommendation(tmp_path):
    r = guardrails.review(guard_config(tmp_path), dict(so_ref=1.7), checked("validated"), within(), within(), 0.0, 0.08)
    assert r["status"] == guardrails.REJECTED and r["staged_setpoints"] == []

@pytest.mark.parametrize("settings", [dict(k_do=1e6), dict(ti_do=1e-9), dict(k_do=0.1)])
def test_controller_settings_outside_the_tested_ranges_are_rejected(tmp_path, settings):
    r = guardrails.review(guard_config(tmp_path), dict(so_ref=2.0, **settings), checked("validated"), within(), within(), 0.0, 0.0)
    assert r["status"] == guardrails.REJECTED and "Controller settings" in r["reason"]

def test_a_consent_never_checked_against_a_recording_blocks_ready(tmp_path):
    tss = [dict(name="TSS", tag="effluent_tss", status="within", value=10.0)]
    r = guardrails.review(guard_config(tmp_path), dict(so_ref=1.7), checked("validated"), within() + tss, within() + tss, 0.0, 0.0)
    assert r["status"] == guardrails.RESEARCH and r["consents_without_a_check"] == ["effluent_tss"] and "never checked" in r["reason"]
    ok = guardrails.review(guard_config(tmp_path), dict(so_ref=1.7), checked("validated", effluent_tss=dict(ok=True)), within() + tss, within() + tss, 0.0, 0.0)
    assert ok["status"] == guardrails.READY
    failed = guardrails.review(guard_config(tmp_path), dict(so_ref=1.7), checked("validated", effluent_tss=dict(ok=False)), within() + tss, within() + tss, 0.0, 0.0)
    assert failed["status"] == guardrails.RESEARCH

# ---------- validation gate ----------
def fake_inputs(index, observed):
    return replay.Inputs(index, np.full(len(index), 1000.0), np.full(len(index), 30.0), np.zeros((len(index), 13)), 1.0, 1.0, observed)

def model_frame(index, nh4, kwh, do):
    return pd.DataFrame(dict(effluent_nh4=nh4, aeration_kwh_d=kwh, do_aerobic=do, flow=np.full(len(index), 1000.0)), index=index)

def test_validation_gate_outcomes(tmp_path):
    idx = pd.date_range("2026-06-01", periods=96 * 10, freq="15min", tz="UTC")
    rng = np.random.default_rng(1)
    day = np.repeat(np.arange(10), 96)
    nh4 = 2 + np.sin(day) + rng.normal(0, .05, len(idx))
    kwh = 3000 + 200 * np.cos(day)
    do = np.full(len(idx), 2.0)
    base = model_frame(idx, nh4, kwh, do)
    conf = guard_config(tmp_path)
    obs = pd.DataFrame(dict(effluent_nh4=nh4 * 1.02, blower_power=kwh / 24 * 1.4, do_aerobic=do + 0.05), index=idx)
    good = replay.validate(base, fake_inputs(idx, obs), conf)
    assert good["status"] == "validated" and good["indicators"]["aeration_energy"]["calibration_factor"] == pytest.approx(1.4, rel=0.01)
    assert good["indicators"]["do_aerobic"]["mae"] < 0.3 and "barely varies" in " ".join(good["reasons"])
    wrong = obs.assign(effluent_nh4=5 - nh4)                        # moves opposite to the model
    assert replay.validate(base, fake_inputs(idx, wrong), conf)["status"] == "not_validated"
    biased = obs.assign(effluent_nh4=nh4 * 2.0)
    assert replay.validate(base, fake_inputs(idx, biased), conf)["status"] == "not_validated"
    assert replay.validate(base, fake_inputs(idx, obs.assign(do_aerobic=do + 1.0)), conf)["status"] == "not_validated"
    assert replay.validate(base, fake_inputs(idx, obs[["effluent_nh4"]]), conf)["status"] == "partly_validated"
    nothing = replay.validate(base, fake_inputs(idx, pd.DataFrame(index=idx)), conf)
    assert nothing["status"] == "cannot_validate" and "model-only" in " ".join(nothing["reasons"])

def test_metrics_basics():
    s = pd.Series([1.0, 2, 3, 4, 5], index=pd.date_range("2026-01-01", periods=5, freq="D"))
    assert replay.metrics(s, s)["nse"] == 1.0 and replay.metrics(s + 1, s)["bias_pct"] == pytest.approx(33.3, abs=0.1)
    assert replay.metrics(s * 0 + 3, s)["nse"] == pytest.approx(0.0)         # no better than the mean
    assert replay.metrics(s.iloc[:2], s.iloc[:2])["nse"] is None             # too few days to score

# ---------- report and command line ----------
def test_report_html_escapes_user_text_and_shows_the_verdict():
    r = dict(site="<script>alert(1)</script>", window=dict(start="2026-01-01 00:00", end="2026-01-20 00:00", days=19, warmup_days_excluded=3),
             current_control=dict(do_setpoint=2.0), candidate=dict(so_ref=1.7), validation=dict(status="not_validated", indicators={}, reasons=["x <b>y</b>"],
             thresholds=dict(nse_min=0.5, bias_max_pct=20)), consents=[], low_do_share=dict(baseline=0, candidate=0),
             appraisal=dict(baseline=dict(energy_kwh=1, energy_kwh_per_day=1, cost_gbp=1, carbon_t=1, cost_gbp_range=[1, 1], carbon_t_range=[1, 1], calibrated=False,
                                          annualised=dict(energy_kwh=1, cost_gbp=1, carbon_t=1, note="n")),
                            candidate=dict(energy_kwh=1, energy_kwh_per_day=1, cost_gbp=1, carbon_t=1), difference=dict(energy_pct=0.0, energy_kwh=0, cost_gbp=0, carbon_t=0)),
             recommendation=dict(status="research_only", reason="r", checks=[], staged_setpoints=[], statement="s"), sweep=None,
             data_quality=dict(file="f.csv", rows_read=1, days=1, issues=[], notes=[]), assumptions=["a"],
             series=dict(effluent_nh4=dict(day=[], baseline=[], candidate=[]), aeration_kwh_d=dict(day=[], baseline=[], candidate=[])))
    page = report.html(r)
    assert "<script>" not in page and "&lt;script&gt;" in page and "does NOT reproduce" in page and "research only" in page

def test_cli_assignments_and_init(tmp_path, capsys):
    assert cli.parse_assignments(["so_ref=1.8", "k_do=40"]) == dict(so_ref=1.8, k_do=40.0)
    for bad in (["so_ref"], ["so_ref=abc"]):
        with pytest.raises(cfg.ConfigError):
            cli.parse_assignments(bad)
    assert cli.main(["init", str(tmp_path / "mine")]) == 0
    template = (tmp_path / "mine" / "site.toml").read_text()
    assert 'name = "My works"' in template and "SYNTHETIC" not in template
    assert cli.main(["init", str(tmp_path / "mine")]) == 2 and "already exists" in capsys.readouterr().err

def test_cli_check_reports_problems_with_exit_codes(tmp_path, capsys):
    times = local_strings("2026-06-01 00:00", 4 * 24 * 8)
    (tmp_path / "d.csv").write_text(csv_from(times))
    (tmp_path / "site.toml").write_text(GOOD.replace('unit = "Ml/d"', 'unit = "m3/h"') + "\n[validation]\nmin_days = 7\n")
    assert cli.main(["check", str(tmp_path / "site.toml")]) == 0 and "Periods that can be replayed" in capsys.readouterr().out
    (tmp_path / "site.toml").write_text(GOOD.replace('column = "Q"', 'column = "Wrong"'))
    assert cli.main(["check", str(tmp_path / "site.toml")]) == 2 and "Columns found" in capsys.readouterr().err

# ---------- end to end (needs the BSM1 archive) ----------
@pytest.fixture(scope="module")
def works(tmp_path_factory):
    folder = tmp_path_factory.mktemp("works")
    demo.generate(folder, days=14, mismatch=0.0)
    return folder

@needs_archive
def test_demo_data_check_finds_every_planted_problem(works):
    data = importer.load(cfg.load(works / "site.toml"), works)
    text = " ".join(data.report["issues"] + data.report["notes"])
    for needle in ("duplicate timestamp", "stuck sensor", "outside the physical range", "non-numeric", "longest gap", "autumn clock change"):
        assert needle in text, needle
    assert data.report["tags"]["do_aerobic"]["flatline"] == 32 and data.windows

@needs_archive
def test_shadow_mode_end_to_end_on_a_consistent_synthetic_works(works):
    out = works / "report"
    r = shadow.run(works / "site.toml", out, dict(so_ref=1.7), sweep=[1.5, 2.5], max_days=10.0, log=lambda *a: None)
    assert r["validation"]["status"] == "validated"
    assert r["validation"]["indicators"]["aeration_energy"]["calibration_factor"] == pytest.approx(demo.BLOWER_FACTOR, rel=0.05)
    assert r["appraisal"]["candidate"]["energy_kwh"] < r["appraisal"]["baseline"]["energy_kwh"]           # a lower setpoint uses less air
    energy = [t["energy_kwh_per_day"] for t in r["sweep"]]
    nh4 = [t["mean_effluent_nh4"] for t in r["sweep"]]
    assert energy[0] < energy[1] and nh4[0] > nh4[1]                                                        # more air, less ammonium
    assert r["recommendation"]["status"] in (guardrails.READY, guardrails.REJECTED) and r["recommendation"]["advisory_only"]
    assert len(r["consents"]) == 2 and all(c["baseline"]["status"] in ("within", "exceeds") for c in r["consents"])
    assert (out / "report.html").exists() and (out / "report.json").exists() and (out / "data_quality.md").exists()
    ok, message = audit.verify(out / "audit.jsonl")
    assert ok and "2 entries" in message
    audit.approve(out / "audit.jsonl", out / "report.json", "Test Engineer", "reviewed")
    assert audit.verify(out / "audit.jsonl")[0]
    lines = (out / "audit.jsonl").read_text().splitlines()
    (out / "audit.jsonl").write_text("\n".join([lines[0].replace("import", "imported"), *lines[1:]]) + "\n")
    assert not audit.verify(out / "audit.jsonl")[0]

@needs_archive
def test_the_validation_gate_rejects_a_works_that_differs_from_the_model(tmp_path):
    demo.generate(tmp_path, days=14, mismatch=0.45)
    r = shadow.run(tmp_path / "site.toml", tmp_path / "report", dict(so_ref=1.7), max_days=10.0, log=lambda *a: None)
    assert r["validation"]["status"] == "not_validated"
    assert r["recommendation"]["status"] in (guardrails.RESEARCH, guardrails.REJECTED)
    assert "does NOT reproduce" in (tmp_path / "report" / "report.html").read_text()

# ---------- regression tests for review findings ----------
def two_day_gate(tmp_path, nh4=None, kwh_scale=1.0, obs_extra=None, days_n=10, do=None, **config_validation):
    idx = pd.date_range("2026-06-01", periods=96 * days_n, freq="15min", tz="UTC")
    day = np.repeat(np.arange(days_n), 96)
    kwh = 3000 + 200 * np.cos(day)
    nh4_model = 2 + np.sin(day)
    base = model_frame(idx, nh4_model, kwh / kwh_scale, np.full(len(idx), 2.0) if do is None else do)
    obs = pd.DataFrame(dict(effluent_nh4=nh4_model if nh4 is None else nh4, blower_power=kwh / 24 * 1.4, do_aerobic=np.full(len(idx), 2.0)), index=idx)
    if obs_extra:
        obs = obs.assign(**obs_extra)
    conf = guard_config(tmp_path)
    if config_validation:
        conf = conf.model_copy(update=dict(validation=conf.validation.model_copy(update=config_validation)))
    return replay.validate(base, fake_inputs(idx, obs), conf), idx

def test_ammonium_that_cannot_be_scored_never_earns_validated(tmp_path):
    v, idx = two_day_gate(tmp_path, nh4=np.full(960, 5.0))                  # recorded ammonium constant
    assert v["status"] == "partly_validated" and v["indicators"]["effluent_nh4"]["ok"] is None
    assert any("NOT scored" in r for r in v["reasons"]) and any("effluent ammonium was not checked" in r for r in v["reasons"])
    assert guardrails.review(guard_config(tmp_path), dict(so_ref=1.7), v, within(), within(), 0, 0)["status"] == guardrails.RESEARCH

def test_energy_that_needed_an_unbelievable_scaling_fails(tmp_path):
    v, _ = two_day_gate(tmp_path, kwh_scale=7.0)                             # the model uses 7 times too little air
    assert v["status"] == "not_validated" and v["indicators"]["aeration_energy"]["calibration_factor"] > 9
    assert "believable range" in " ".join(v["reasons"])

def test_too_few_days_cannot_validate(tmp_path):
    v, _ = two_day_gate(tmp_path, days_n=4)                                  # 3 days after warm-up
    assert v["status"] == "cannot_validate" and all(i["ok"] is None for i in v["indicators"].values())

def test_a_very_low_ammonium_works_is_judged_in_mg_per_litre_not_per_cent(tmp_path):
    idx = pd.date_range("2026-06-01", periods=96 * 10, freq="15min", tz="UTC")
    day = np.repeat(np.arange(10), 96)
    low = 0.30 + 0.25 * np.sin(day)                                          # recorded ammonium around 0.3 mg/l with real variation
    v, _ = two_day_gate(tmp_path, nh4=low, obs_extra={})
    assert v["indicators"]["effluent_nh4"]["bias_abs"] is not None
    close = low + 0.1                                                        # the model is 0.1 mg/l high: a large per cent, a small amount
    base = model_frame(idx, close, 3000 + 200 * np.cos(day), np.full(len(idx), 2.0))
    obs = pd.DataFrame(dict(effluent_nh4=low, blower_power=(3000 + 200 * np.cos(day)) / 24 * 1.4), index=idx)
    r = replay.validate(base, fake_inputs(idx, obs), guard_config(tmp_path))
    assert abs(r["indicators"]["effluent_nh4"]["bias_pct"]) > 20 and r["indicators"]["effluent_nh4"]["ok"] is True and r["status"] == "validated"

def test_energy_calibration_is_not_biased_by_gaps_in_the_blower_record(tmp_path):
    idx = pd.date_range("2026-06-01", periods=96 * 10, freq="15min", tz="UTC")
    day = np.repeat(np.arange(10), 96)
    load = 3000 + 1500 * (np.arange(len(idx)) % 96 < 48)                     # a daily rhythm: half the day is high load
    base = model_frame(idx, 2 + np.sin(day), load, np.full(len(idx), 2.0))
    power = load / 24 * 1.4
    power = np.where(np.arange(len(idx)) % 96 < 48, np.nan, power)           # the blower logger only worked during the low load half
    inp = fake_inputs(idx, pd.DataFrame(dict(blower_power=power), index=idx))
    assert replay.energy_calibration(base, inp) == pytest.approx(1.4, rel=1e-6)

def test_daily_values_use_local_calendar_days():
    idx = pd.date_range("2026-07-01 22:00", periods=8, freq="1h", tz="UTC")               # 23:00 BST on the 1st to 06:00 BST on the 2nd
    s = pd.Series(np.arange(8.0), index=idx)
    d = replay.daily(s, tz="Europe/London")
    assert len(d) == 2 and str(d.index[0].date()) == "2026-07-01" and d.iloc[0] == pytest.approx(0.0) and d.iloc[1] == pytest.approx(np.mean(range(1, 8)))
    assert len(replay.daily(s, tz="UTC")) == 2 and replay.daily(s, tz="UTC").iloc[0] == pytest.approx(np.mean(range(0, 2)))

def test_unusable_cod_is_reported_not_silently_dropped(tmp_path):
    times = local_strings("2026-06-01 00:00", 4 * 24 * 9)
    lines = csv_from(times).split("\n")
    rows = ["Timestamp,Q,N,C"] + [f"{l},{400 + 5 * np.sin(i):.1f}" if i != 100 else f"{l}," for i, l in enumerate(lines[1:])]
    for i in range(1 + 200, 1 + 260):
        rows[i] = ",".join(rows[i].split(",")[:3]) + ","                      # a long COD gap (15 hours): longer than the fill limit
    conf = make_config(tmp_path, "\n".join(rows), extra_tags={"influent_cod": dict(column="C", unit="mg/l")})
    data = importer.load(conf, tmp_path)
    inputs = replay.prepare(data.table, data.windows[0], conf)
    assert inputs.cod_used is False

def test_iso_dates_are_read_year_first_and_uk_dates_day_first(tmp_path):
    iso = ["2026-03-04 10:00", "2026-03-04 10:15", "2026-03-04 10:30", "2026-03-20 00:00"]
    uk = ["04/03/2026 10:00", "04/03/2026 10:15", "04/03/2026 10:30", "20/03/2026 00:00"]
    for stamps in (iso, uk):
        text = "Timestamp,Q,N\n" + "\n".join(f"{t},{1250 + i},{30 + i}" for i, t in enumerate(stamps))
        data = importer.load(make_config(tmp_path, text), tmp_path)
        assert not data.report["issues"] or all("could not be read" not in i for i in data.report["issues"])
        assert data.table.index[0] == pd.Timestamp("2026-03-04 10:00", tz="UTC") and data.table.index[-1].month == 3 and data.table.index[-1].day == 20

def test_offset_timestamps_with_a_local_setting_give_a_clear_error_and_bad_zone_names_too(tmp_path):
    text = "Timestamp,Q,N\n2026-03-04T10:00:00+01:00,1250,30\n2026-03-04T10:15:00+01:00,1251,31\n"
    with pytest.raises(cfg.ConfigError, match="timestamp_is_local = false"):
        importer.load(make_config(tmp_path, text), tmp_path)
    ok = importer.load(make_config(tmp_path, text, timestamp_is_local=False), tmp_path)
    assert ok.table.index[0] == pd.Timestamp("2026-03-04 09:00", tz="UTC")
    with pytest.raises(cfg.ConfigError, match="not known"):
        cfg.load(write_toml(tmp_path, GOOD.replace("[data]", 'timezone = "Mars/Olympus"\n[data]', 1)))

def test_stuck_sensor_threshold_is_in_hours_whatever_the_logging_interval(tmp_path):
    def stuck_run(step_min, hours):
        n = int(24 * 60 / step_min)
        t = pd.Timestamp("2026-06-01", tz="UTC") + pd.to_timedelta(np.arange(n) * step_min, unit="min")
        local = [x.tz_convert("Europe/London").strftime("%d/%m/%Y %H:%M") for x in t]
        flat = int(hours * 60 / step_min)
        rows = [f"{ts},{1250 + 3 * np.sin(i):.3f},{35.0 if 10 <= i < 10 + flat else 30 + np.cos(i):.3f}" for i, ts in enumerate(local)]
        return "Timestamp,Q,N\n" + "\n".join(rows)
    for step in (5, 15, 60):
        kept = importer.load(make_config(tmp_path, stuck_run(step, 5)), tmp_path).report["tags"]["influent_nh4"]["flatline"]
        removed = importer.load(make_config(tmp_path, stuck_run(step, 7)), tmp_path).report["tags"]["influent_nh4"]["flatline"]
        assert kept == 0 and removed == int(7 * 60 / step), (step, kept, removed)

def test_a_value_that_is_legitimately_constant_can_be_exempted(tmp_path):
    n = 24 * 4
    times = local_strings("2026-06-01 00:00", n)
    rows = "Timestamp,Q,N\n" + "\n".join(f"{t},{1250 + 3 * np.sin(i):.3f},{12.5 if i < 80 else 30 + np.cos(i):.3f}" for i, t in enumerate(times))
    assert importer.load(make_config(tmp_path, rows), tmp_path).report["tags"]["influent_nh4"]["flatline"] == 80
    kept = importer.load(make_config(tmp_path, rows, flatline_exempt=["influent_nh4"]), tmp_path)
    assert kept.report["tags"]["influent_nh4"]["flatline"] == 0
    with pytest.raises(Exception, match="not a tag"):
        make_config(tmp_path, rows, flatline_exempt=["lab_nh4"])

def test_gaps_longer_than_the_fill_limit_are_left_entirely_empty(tmp_path):
    def gap_of(steps, **data):
        times = local_strings("2026-06-01 00:00", 200)
        lines = csv_from(times).split("\n")
        for i in range(1 + 50, 1 + 50 + steps):
            lines[i] = lines[i].split(",")[0] + ",," + lines[i].split(",")[2]
        return importer.load(make_config(tmp_path, "\n".join(lines), **data), tmp_path)
    assert gap_of(6).table["influent_flow"].iloc[49:57].notna().all() and gap_of(6).report["tags"]["influent_flow"]["filled"] == 6
    long = gap_of(10)                                                                 # 2.5 h: longer than the 2 h limit
    assert long.report["tags"]["influent_flow"]["filled"] == 0 and long.table["influent_flow"].iloc[50:60].isna().all()
    assert gap_of(10, max_fill_hours=0).report["tags"]["influent_flow"]["filled"] == 0
    assert gap_of(2, max_fill_hours=0).table["influent_flow"].isna().sum() == 2        # a limit of zero fills nothing, and does not crash

def test_the_first_of_two_conflicting_duplicate_rows_is_the_one_kept(tmp_path):
    times = local_strings("2026-06-01 00:00", 12)
    lines = csv_from(times).split("\n")
    lines.append(f"{times[4]},{9000.0},{44.0}")                                      # same time stamp as row 4, different values
    data = importer.load(make_config(tmp_path, "\n".join(lines)), tmp_path)
    original = float(csv_from(times).split("\n")[5].split(",")[1])
    assert data.table["influent_flow"].iloc[4] == pytest.approx(original * 24)

def test_decimal_commas_are_reported_not_turned_into_wrong_numbers(tmp_path):
    times = local_strings("2026-06-01 00:00", 40)
    lines = csv_from(times).split("\n")
    lines[4] = lines[4].split(",")[0] + ',"1,5",30'                                    # a European decimal comma
    lines[6] = lines[6].split(",")[0] + ',"1,250",30'                                  # a thousands separator
    data = importer.load(make_config(tmp_path, "\n".join(lines)), tmp_path)
    info = data.report["tags"]["influent_flow"]
    assert info["not_numeric"] == 1 and any("non-numeric" in i for i in data.report["issues"])
    assert data.table["influent_flow"].iloc[5] == pytest.approx(1250.0 * 24, rel=0.01)        # "1,250" became 1250 m3/h, not 1.25 or 1250000

def test_tariff_bands_must_make_sense():
    with pytest.raises(Exception, match="ends before it starts"):
        cfg.Tariff(bands=[cfg.Band(start_hour=22, end_hour=6, gbp_per_kwh=0.1)])
    with pytest.raises(Exception, match="overlap"):
        cfg.Tariff(bands=[cfg.Band(start_hour=0, end_hour=8, gbp_per_kwh=0.1), cfg.Band(start_hour=6, end_hour=12, gbp_per_kwh=0.2)])
    ok = cfg.Tariff(bands=[cfg.Band(start_hour=22, end_hour=24, gbp_per_kwh=0.1), cfg.Band(start_hour=0, end_hour=6, gbp_per_kwh=0.1)])
    price = appraisal.price_series(pd.date_range("2026-01-15 00:00", periods=96, freq="15min", tz="UTC"), ok, "Europe/London")
    assert price[0] == 0.1 and price[4 * 6] == 0.25 and price[4 * 23] == 0.1

def test_consent_sampling_uses_the_worst_phase_and_real_calendar_days():
    values = [1.0] * 30
    values[20] = 9.0                                                                  # one bad day, which a naive day-0 start would miss
    r = consent.check(spec(kind="absolute", limit=5.0, sample_every_days=7), days(values))
    assert r["status"] == "exceeds" and "sampling phases" in r["detail"]
    gappy = days(values).drop(days(values).index[5:10])                                # missing days must not shift the spacing
    assert consent.check(spec(kind="absolute", limit=5.0, sample_every_days=7), gappy)["status"] == "exceeds"
    short = consent.check(spec(kind="lut", limit=5.0, lut=[(8, 1)]), days([1, 2, 3, 6]))
    assert "indicative only" in short["detail"] and short["status"] == "exceeds"      # 1 failure in 4 samples: the table allows 0 for so few

def test_site_candidates_are_limited_to_what_site_mode_supports():
    base = cfg.Control()
    assert replay.controller_from(dict(so_ref=1.8, k_do=40), base).so_ref == 1.8
    for bad in (dict(kla_max=5000), dict(nh_gain=1.0)):
        with pytest.raises(ValueError, match="site mode can test"):
            replay.controller_from(bad, base)

def test_report_shows_whether_each_indicator_was_scored():
    r = dict(site="s", window=dict(start="a", end="b", days=1, warmup_days_excluded=3), current_control=dict(do_setpoint=2.0), candidate=None,
             validation=dict(status="partly_validated", indicators={"effluent_nh4": dict(n=2, nse=None, bias_pct=None, r2=None, ok=None),
                                                                    "aeration_energy": dict(n=9, nse=0.9, bias_pct=0.0, r2=0.9, ok=True)},
                             reasons=["x"], thresholds=dict(nse_min=0.5, bias_max_pct=20)), consents=[], low_do_share=dict(baseline=0, candidate=0),
             appraisal=dict(baseline=dict(energy_kwh=1, energy_kwh_per_day=1, cost_gbp=1, carbon_t=1, cost_gbp_range=[1, 1], carbon_t_range=[1, 1], calibrated=False,
                                          annualised=dict(energy_kwh=1, cost_gbp=1, carbon_t=1, note="n")),
                            candidate=dict(energy_kwh=1, energy_kwh_per_day=1, cost_gbp=1, carbon_t=1), difference=None),
             recommendation=None, sweep=None, data_quality=dict(file="f", rows_read=1, days=1, issues=[], notes=[]), assumptions=["a"],
             series=dict(effluent_nh4=dict(day=[], baseline=[], candidate=[]), aeration_kwh_d=dict(day=[], baseline=[], candidate=[])))
    page = report.html(r)
    assert "effluent nh4 <b>(not scored)</b>" in page and "aeration energy <b>(pass)</b>" in page

def test_a_synthetic_demo_report_says_so_loudly():
    r = dict(site="Demo works (synthetic data)", synthetic=True, window=dict(start="a", end="b", days=1, warmup_days_excluded=3), current_control=dict(do_setpoint=2.0), candidate=None,
             validation=dict(status="validated", indicators={}, reasons=[], thresholds=dict(nse_min=0.5, bias_max_pct=20)), consents=[], low_do_share=dict(baseline=0, candidate=0),
             appraisal=dict(baseline=dict(energy_kwh=1, energy_kwh_per_day=1, cost_gbp=1, carbon_t=1, cost_gbp_range=[1, 1], carbon_t_range=[1, 1], calibrated=False,
                                          annualised=dict(energy_kwh=1, cost_gbp=1, carbon_t=1, note="n")),
                            candidate=dict(energy_kwh=1, energy_kwh_per_day=1, cost_gbp=1, carbon_t=1), difference=None),
             recommendation=None, sweep=None, data_quality=dict(file="f", rows_read=1, days=1, issues=[], notes=[]), assumptions=["a"],
             series=dict(effluent_nh4=dict(day=[], baseline=[], candidate=[]), aeration_kwh_d=dict(day=[], baseline=[], candidate=[])))
    page = report.html(r)
    assert "SYNTHETIC DATA" in page and page.index("SYNTHETIC DATA") < page.index("Can the model be trusted")
    assert "SYNTHETIC DATA" not in report.html(dict(r, synthetic=False))

def test_chart_axis_numbers_are_readable():
    chart = report.chart(dict(day=["a", "b"], baseline=[7650.2, 8300.7], candidate=[7600.0, 8200.0]), "t", "kWh/d")
    assert "e+03" not in chart and "8,301" in chart and "7,600" in chart

# ---------- calibration ----------
from aera.site import calibrate as cal_mod

def cal_world(tmp_path, days_n=24, regime_change=False, with_nh4=True, true_mu=0.6, flat_nh4=False):
    """A stand-in plant: modelled ammonium = profile / mu (more nitrifier activity, less ammonium), and its energy ignores oxygen transfer.
    The works' recorded ammonium is profile / true_mu, so calibration should find mu = true_mu. With regime_change the works
    behaves like the benchmark again from day 16, so a fit made on the early days is wrong for the late (held-out) days."""
    idx = pd.date_range("2026-06-01", periods=96 * days_n, freq="15min", tz="UTC")
    day = np.repeat(np.arange(days_n), 96)
    profile = np.full(len(idx), 2.0) if flat_nh4 else 2.0 + np.sin(day / 2.0)
    energy = 3000 + 200 * np.cos(day / 3.0)
    truth = np.where(day < 16, true_mu, 1.0) if regime_change else np.full(len(idx), true_mu)
    observed = pd.DataFrame(dict(blower_power=energy / 24 * 1.4), index=idx)
    if with_nh4:
        observed["effluent_nh4"] = profile / truth
    inputs = replay.Inputs(idx, np.full(len(idx), 1000.0), np.full(len(idx), 30.0), np.zeros((len(idx), 13)), 1.0, 3.0, observed)
    def fake_simulate(inp, controller, mode="fast", scenario=None):
        mu = scenario.mu_a_scale if scenario else 1.0
        return pd.DataFrame(dict(effluent_nh4=profile / mu, aeration_kwh_d=energy, do_aerobic=np.full(len(idx), 2.0), flow=np.full(len(idx), 1000.0)), index=idx)
    return inputs, fake_simulate

def run_cal(monkeypatch, tmp_path, **world):
    inputs, fake = cal_world(tmp_path, **world)
    monkeypatch.setattr(replay, "simulate", fake)
    conf = guard_config(tmp_path).model_copy(update=dict(calibration=cfg.Calibration(enabled=True)))
    return cal_mod.calibrate(inputs, conf, dyn.Controller(), workers=1, log=lambda *a: None), inputs, conf

def test_days_are_split_into_training_then_held_out(tmp_path):
    inputs, _ = cal_world(tmp_path)
    conf = guard_config(tmp_path).model_copy(update=dict(calibration=cfg.Calibration(train_fraction=0.6)))
    train, test = cal_mod.split_days(inputs, conf, "UTC")
    assert len(train) + len(test) == 21 and train[-1] < test[0] and 12 <= len(train) <= 13      # 24 days minus 3 warm-up, 60% to fit

def test_calibration_recovers_a_known_parameter_and_leaves_the_unidentifiable_one_alone(monkeypatch, tmp_path):
    r, _, _ = run_cal(monkeypatch, tmp_path, true_mu=0.6)
    assert r["status"] == "accepted" and r["used"] and r["params"]["mu_a_scale"] == pytest.approx(0.6, rel=0.2)
    assert r["identifiable"] == dict(mu_a_scale=True, alpha_scale=False) and r["params"]["alpha_scale"] == 1.0
    assert any("alpha_scale" in n and "cannot be identified" in n for n in r["notes"])
    assert r["held_out"]["improvement_pct"] > 50 and r["train_days"] + r["test_days"] in (21, 22)

def test_a_fit_that_does_not_generalise_to_the_held_out_days_is_refused(monkeypatch, tmp_path):
    r, _, _ = run_cal(monkeypatch, tmp_path, regime_change=True)
    assert r["status"] == "not_improved" and not r["used"] and r["params"] == dict(mu_a_scale=1.0, alpha_scale=1.0)
    assert any("NOT used" in n for n in r["notes"])
    assert r["fitted"]["mu_a_scale"] != 1.0                                # something was fitted on the training days, then rejected

def test_calibration_declines_without_enough_days_or_without_ammonium(monkeypatch, tmp_path):
    short, _, _ = run_cal(monkeypatch, tmp_path, days_n=10)
    assert short["status"] == "insufficient_data" and not short["used"] and "longer data window" in short["notes"][0]
    none, _, _ = run_cal(monkeypatch, tmp_path, with_nh4=False)
    assert none["status"] == "needs_effluent_ammonium"
    flat, _, _ = run_cal(monkeypatch, tmp_path, flat_nh4=True)
    assert flat["status"] == "not_improved" and "barely varies" in flat["notes"][0]

def test_calibrated_validation_is_judged_on_held_out_days_only(tmp_path):
    inputs, fake = cal_world(tmp_path, true_mu=1.0)
    sim = fake(inputs, None)
    conf = guard_config(tmp_path)
    everything = replay.validate(sim, inputs, conf)
    late = replay.validate(sim, inputs, conf, start=pd.Timestamp("2026-06-14", tz="UTC"))
    assert everything["days_compared"] in (21, 22) and 11 <= late["days_compared"] <= 12 and late["status"] == "validated"     # local days include partial edge days

def test_the_report_and_config_describe_calibration():
    assert cfg.Calibration().enabled is False and cfg.Calibration().train_fraction == 0.6
    with pytest.raises(Exception):
        cfg.Calibration(train_fraction=0.95)
    base = dict(site="s", window=dict(start="a", end="b", days=1, warmup_days_excluded=3), current_control=dict(do_setpoint=2.0), candidate=None,
                validation=dict(status="validated", indicators={}, reasons=[], thresholds=dict(nse_min=0.5, bias_max_pct=20), evaluated_on="the 7 days held out"),
                consents=[], low_do_share=dict(baseline=0, candidate=0), recommendation=None, sweep=None,
                appraisal=dict(baseline=dict(energy_kwh=1, energy_kwh_per_day=1, cost_gbp=1, carbon_t=1, cost_gbp_range=[1, 1], carbon_t_range=[1, 1], calibrated=False,
                                             annualised=dict(energy_kwh=1, cost_gbp=1, carbon_t=1, note="n")),
                               candidate=dict(energy_kwh=1, energy_kwh_per_day=1, cost_gbp=1, carbon_t=1), difference=None),
                data_quality=dict(file="f", rows_read=1, days=1, issues=[], notes=[]), assumptions=["a"],
                series=dict(effluent_nh4=dict(day=[], baseline=[], candidate=[]), aeration_kwh_d=dict(day=[], baseline=[], candidate=[])))
    used = dict(base, calibration=dict(status="accepted", used=True, params=dict(mu_a_scale=0.6, alpha_scale=1.0), train_days=14, test_days=7,
                                       held_out=dict(nh4_error_before=1.2, nh4_error_after=0.2, improvement_pct=83.3), notes=["alpha_scale cannot be identified"]))
    page = report.html(used)
    assert "never saw" in page and "0.6 times the benchmark" in page and "83.3% improvement" in page and "judged on the 7 days held out" in page.lower().replace("judged on", "judged on")
    refused = dict(base, calibration=dict(status="not_improved", used=False, notes=["not used"]))
    assert "Calibration was not used" in report.html(refused)

@needs_archive
def test_calibration_recovers_a_mismatched_synthetic_works_end_to_end(tmp_path):
    demo.generate(tmp_path, days=21, mismatch=0.4)                   # the "real" works has 40% less nitrifier activity and oxygen transfer than the benchmark
    plain = shadow.run(tmp_path / "site.toml", tmp_path / "plain", dict(so_ref=1.7), max_days=21.0, log=lambda *a: None)
    fitted = shadow.run(tmp_path / "site.toml", tmp_path / "fitted", dict(so_ref=1.7), max_days=21.0, log=lambda *a: None, calibrate=True)
    assert plain["validation"]["status"] == "not_validated"
    c = fitted["calibration"]
    assert c["status"] == "accepted" and c["params"]["mu_a_scale"] == pytest.approx(0.6, rel=0.2) and c["params"]["alpha_scale"] == pytest.approx(0.6, rel=0.2), c
    assert c["identifiable"] == dict(mu_a_scale=True, alpha_scale=True)
    assert c["held_out"]["improvement_pct"] > 50
    assert fitted["validation"]["status"] == "validated" and "held out" in fitted["validation"]["evaluated_on"]
    assert "Calibration" in (tmp_path / "fitted" / "report.html").read_text()

def test_the_command_line_entry_point_is_safe_for_worker_processes():
    """macOS and Windows start workers by re-importing the main module, so it must not run the command line on import."""
    source = (Path(__file__).resolve().parent.parent / "aera" / "site" / "__main__.py").read_text()
    assert 'if __name__ == "__main__"' in source
    import importlib
    importlib.import_module("aera.site.__main__")            # importing it must do nothing and must not exit

# ---------- temperature ----------
def test_temperature_factors_are_exactly_neutral_at_15_degrees():
    rate, kla, sosat = dyn.temperature_factors(15.0)
    assert (rate == 1.0).all() and kla == 1.0 and sosat == dyn.SOSAT

def test_temperature_factors_match_known_values():
    rate10, kla10, so10 = dyn.temperature_factors(10.0)
    rate20, kla20, so20 = dyn.temperature_factors(20.0)
    assert 0.5 * rate10[2] == pytest.approx(0.3, rel=0.08) and 0.5 * rate20[2] == pytest.approx(0.8, rel=0.08)      # ASM1 nitrifier growth at 10 and 20 C
    assert so10 == pytest.approx(8 * 11.29 / 10.08, rel=0.02) and so20 == pytest.approx(8 * 9.09 / 10.08, rel=0.02)  # oxygen solubility in water
    assert rate10[2] < 1 < rate20[2] and kla10 < 1 < kla20 and so10 > dyn.SOSAT > so20
    assert dyn.temperature_factors(10.0) is dyn.temperature_factors(10.0)                                         # cached

def test_the_benchmark_plant_is_bit_for_bit_unchanged_at_15_degrees():
    y = dyn.initial_state()
    y[dyn.I_QA] = 3 * dyn.Q0
    influent = lambda t: (dyn.Q0, dyn.plant.RAW)
    plain = dyn.make_rhs(dyn.Controller(), influent, None)(0.1, y)
    for temperature in (15.0, 15, lambda t: 15.0 if False else 15.0):
        same = dyn.make_rhs(dyn.Controller(), influent, None, dyn.Scenario(), 15.0)(0.1, y)
        assert np.array_equal(plain, same)
    assert not np.allclose(dyn.make_rhs(dyn.Controller(), influent, None, dyn.Scenario(), 8.0)(0.1, y), plain)

def test_cooler_water_slows_nitrification_in_the_model_rates():
    tank = np.array([30, 2, 1150, 80, 2550, 150, 450, 2.0, 5, 8.0, 1, 5, 5.0])
    warm, cold = dyn.scaled_rates(tank, 1.0, dyn.temperature_factors(20.0)[0]), dyn.scaled_rates(tank, 1.0, dyn.temperature_factors(8.0)[0])
    assert cold[2] < warm[2] and cold[2] / warm[2] == pytest.approx(1.1 ** -12, rel=0.01)

def test_temperature_is_taken_from_the_record_or_assumed(tmp_path):
    times = local_strings("2026-06-01 00:00", 96 * 9)
    n = len(times)
    temps = 12 + 5 * np.arange(n) / n
    rows = ["Timestamp,Q,N,T"] + [f"{t},{1250 + 3 * np.sin(i):.3f},{30 + np.cos(i):.3f},{temps[i]:.3f}" for i, t in enumerate(times)]
    rows[300] = rows[300].rsplit(",", 1)[0] + ","                                                  # a missing temperature reading
    conf = make_config(tmp_path, "\n".join(rows), extra_tags={"temperature": dict(column="T", unit="degC")})
    inputs = replay.prepare(importer.load(conf, tmp_path).table, importer.load(conf, tmp_path).windows[0], conf)
    assert not np.isnan(inputs.temperature).any() and inputs.temperature[0] == pytest.approx(12.0, abs=0.1) and inputs.temperature[-1] > 16.5
    assert "follows your recorded temperature" in inputs.temperature_note
    plain = make_config(tmp_path, csv_from(times), design=30000)
    flat = replay.prepare(importer.load(plain, tmp_path).table, importer.load(plain, tmp_path).windows[0], plain)
    assert (flat.temperature == 15.0).all() and "benchmark value" in flat.temperature_note
    warm = plain.model_copy(update=dict(site=plain.site.model_copy(update=dict(temperature_c=11.0))))
    assert (replay.prepare(importer.load(warm, tmp_path).table, importer.load(warm, tmp_path).windows[0], warm).temperature == 11.0).all()

def test_a_slowly_changing_temperature_probe_is_never_called_stuck(tmp_path):
    n = 4 * 24
    times = local_strings("2026-06-01 00:00", n)
    rows = ["Timestamp,Q,N,T"] + [f"{t},{1250 + 3 * np.sin(i):.3f},{30 + np.cos(i):.3f},{14.2 if i < 60 else 14.3}" for i, t in enumerate(times)]
    conf = make_config(tmp_path, "\n".join(rows), extra_tags={"temperature": dict(column="T", unit="degC")})
    assert importer.load(conf, tmp_path).report["tags"]["temperature"]["flatline"] == 0

def test_temperature_settings_are_validated():
    with pytest.raises(Exception):
        cfg.Site(design_flow_m3_d=30000, temperature_c=70)
    assert cfg.Site(design_flow_m3_d=30000).temperature_c == 15.0
    with pytest.raises(Exception, match="not supported"):
        cfg.SiteConfig.model_validate(dict(site=dict(design_flow_m3_d=30000), data=dict(file="x", tags=dict(
            influent_flow=dict(column="a", unit="m3/d"), influent_nh4=dict(column="b", unit="mg/l"), temperature=dict(column="t", unit="degF")))))

@needs_archive
def test_following_the_recorded_temperature_fits_a_cooling_works_better_than_assuming_15_degrees(tmp_path):
    demo.generate(tmp_path, days=14, mismatch=0.0, temperature=True)                 # cools from about 17.5 to 11 degrees
    with_probe = shadow.run(tmp_path / "site.toml", tmp_path / "with", dict(so_ref=1.7), max_days=14.0, log=lambda *a: None)
    text = (tmp_path / "site.toml").read_text()
    (tmp_path / "site.toml").write_text(text.replace('[data.tags.temperature]\ncolumn = "Temp_C"\nunit = "degC"\n', ""))
    without = shadow.run(tmp_path / "site.toml", tmp_path / "without", dict(so_ref=1.7), max_days=14.0, log=lambda *a: None)
    a, b = with_probe["validation"]["indicators"]["effluent_nh4"], without["validation"]["indicators"]["effluent_nh4"]
    assert "follows your recorded temperature" in with_probe["temperature"] and "benchmark value" in without["temperature"]
    assert with_probe["validation"]["status"] == "validated" and a["nse"] > 0.8
    assert b["nse"] < a["nse"] - 0.1 or b["ok"] is False, (a["nse"], b["nse"])      # ignoring the cooling must visibly hurt the fit
    assert any("Temperature" in t and "typical literature values" in t for t in with_probe["assumptions"])

# ---------- watch folder ----------
from aera.site import watch as watch_mod

class FakeClock:
    def __init__(self, now=1_000_000.0):
        self.now = now
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds

def fake_runner(calls, fail_for=()):
    """Stands in for shadow.run: records the call, writes the files a real run writes, or raises."""
    def run(config_path, run_dir, candidate, sweep, max_days, mode, log, calibrate, workers, data_file=None):
        calls.append(Path(data_file).name)
        if Path(data_file).name in fail_for:
            raise cfg.ConfigError("No period of the data is long enough to replay.\nSee data_quality.md")
        run_dir.mkdir(parents=True, exist_ok=True)
        report = dict(validation=dict(status="validated"), recommendation=dict(status="ready_for_operator_review"), calibration=None,
                      appraisal=dict(difference=dict(energy_pct=-1.6)), window=dict(start="2026-10-14 00:00", end="2026-11-03 22:45"))
        (run_dir / "report.json").write_text(json.dumps(report))
        (run_dir / "report.html").write_text("<html>report</html>")
        return report
    return run

def watcher_for(tmp_path, calls, fail_for=(), settle=10.0):
    (tmp_path / "inbox").mkdir(exist_ok=True)
    (tmp_path / "site.toml").write_text(GOOD)
    clock = FakeClock()
    w = watch_mod.Watcher(tmp_path / "site.toml", tmp_path / "inbox", tmp_path / "reports", settle=settle, runner=fake_runner(calls, fail_for),
                          clock=clock, sleep=clock.sleep, log=lambda *a: None)
    return w, clock

def put(tmp_path, name, text, age=100.0, clock=None):
    """Write a file whose modification time is `age` seconds before the fake clock's now."""
    import os
    path = tmp_path / "inbox" / name
    path.write_text(text)
    t = (clock.now if clock else 1_000_000.0) - age
    os.utime(path, (t, t))
    return path

def test_a_new_complete_export_is_processed_once_and_only_once(tmp_path):
    calls = []
    w, clock = watcher_for(tmp_path, calls)
    put(tmp_path, "export_1.csv", "a,b\n1,2\n", clock=clock)
    assert w.poll_once() == 1 and calls == ["export_1.csv"]
    assert w.poll_once() == 0 and calls == ["export_1.csv"]                          # the same content is never run twice
    again = watch_mod.Watcher(tmp_path / "site.toml", tmp_path / "inbox", tmp_path / "reports", runner=fake_runner(calls), clock=clock, sleep=clock.sleep, log=lambda *a: None)
    assert again.poll_once() == 0                                                     # and that is remembered across restarts
    put(tmp_path, "export_1.csv", "a,b\n1,3\n", clock=clock)
    assert w.poll_once() == 1 and calls == ["export_1.csv", "export_1.csv"]          # a changed file is a new export

def test_a_file_that_is_still_being_written_is_left_alone(tmp_path):
    calls = []
    w, clock = watcher_for(tmp_path, calls, settle=10.0)
    put(tmp_path, "export_2.csv", "a,b\n1,2\n", age=3.0, clock=clock)                # modified 3 seconds ago
    assert w.poll_once() == 0 and calls == []
    clock.now += 20
    assert w.poll_once() == 1 and calls == ["export_2.csv"]                            # untouched for long enough

def test_hidden_temporary_and_non_csv_files_are_ignored(tmp_path):
    calls = []
    w, clock = watcher_for(tmp_path, calls)
    for name in (".hidden.csv", "~$lock.csv", "partial.csv.part", "data.csv.tmp", "notes.txt", "export.xlsx"):
        put(tmp_path, name, "x", clock=clock)
    (tmp_path / "inbox" / "subfolder.csv").mkdir()
    assert w.poll_once() == 0 and calls == []
    put(tmp_path, "real.CSV", "a,b\n1,2\n", clock=clock)
    assert w.poll_once() == 1 and calls == ["real.CSV"]

def test_the_inbox_is_never_modified(tmp_path):
    calls = []
    w, clock = watcher_for(tmp_path, calls, fail_for=("bad.csv",))
    paths = [put(tmp_path, "ok.csv", "a,b\n1,2\n", clock=clock), put(tmp_path, "bad.csv", "x\n", clock=clock)]
    snapshot = {p.name: (p.read_bytes(), p.stat().st_mtime, p.stat().st_size) for p in paths}
    w.poll_once(); w.poll_once()
    assert sorted(p.name for p in (tmp_path / "inbox").iterdir()) == ["bad.csv", "ok.csv"]       # nothing added, moved or removed
    assert {p.name: (p.read_bytes(), p.stat().st_mtime, p.stat().st_size) for p in (tmp_path / "inbox").iterdir()} == snapshot

def test_reports_must_not_be_written_inside_the_inbox(tmp_path):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "site.toml").write_text(GOOD)
    for out in (tmp_path / "inbox", tmp_path / "inbox" / "reports"):
        with pytest.raises(cfg.ConfigError, match="outside the inbox"):
            watch_mod.Watcher(tmp_path / "site.toml", tmp_path / "inbox", out)
    with pytest.raises(cfg.ConfigError, match="does not exist"):
        watch_mod.Watcher(tmp_path / "site.toml", tmp_path / "nowhere", tmp_path / "r")
    (tmp_path / "bad.toml").write_text("[site\nbroken")
    with pytest.raises(cfg.ConfigError, match="not valid TOML"):
        watch_mod.Watcher(tmp_path / "bad.toml", tmp_path / "inbox", tmp_path / "r")

def test_a_failed_run_is_recorded_does_not_stop_the_watcher_and_is_not_retried(tmp_path):
    calls = []
    w, clock = watcher_for(tmp_path, calls, fail_for=("bad.csv",))
    put(tmp_path, "bad.csv", "x\n", clock=clock)
    put(tmp_path, "good.csv", "a,b\n1,2\n", clock=clock)
    assert w.poll_once() == 2 and sorted(calls) == ["bad.csv", "good.csv"]            # the good file was processed despite the bad one
    assert w.poll_once() == 0 and len(calls) == 2                                      # the failure is not retried
    entry = next(r for r in w.state["processed"].values() if r["file"] == "bad.csv")
    assert entry["status"] == "failed" and "No period" in entry["error"]
    assert "No period of the data" in (tmp_path / "reports" / entry["run"] / "error.txt").read_text()
    index = (tmp_path / "reports" / "index.html").read_text()
    assert "failed: No period" in index and "good.csv" in index

def test_every_step_is_in_a_tamper_evident_log_and_the_index_lists_runs(tmp_path):
    calls = []
    w, clock = watcher_for(tmp_path, calls)
    put(tmp_path, "export_1.csv", "a,b\n1,2\n", clock=clock)
    w.poll_once()
    trail = tmp_path / "reports" / "watch_audit.jsonl"
    actions = [e["action"] for e in audit.read(trail)]
    assert actions == ["watch_started", "file_seen", "run_completed"] and audit.verify(trail)[0]
    assert audit.read(trail)[0]["details"]["read_only"] is True
    assert (tmp_path / "reports" / "latest_report.json").exists() and (tmp_path / "reports" / "latest_report.html").read_text() == "<html>report</html>"
    index = (tmp_path / "reports" / "index.html").read_text()
    assert "export_1.csv" in index and "validated" in index and "ready for operator review" in index and "read only" in index

def test_the_index_escapes_file_names(tmp_path):
    calls = []
    w, clock = watcher_for(tmp_path, calls)
    put(tmp_path, "<img src=x onerror=alert(1)>&.csv", "a,b\n1,2\n", clock=clock)
    w.poll_once()
    index = (tmp_path / "reports" / "index.html").read_text()
    assert "<img src=x" not in index and "&lt;img src=x onerror=alert(1)&gt;&amp;.csv" in index

def test_run_once_and_max_runs_stop_the_loop(tmp_path):
    calls = []
    w, clock = watcher_for(tmp_path, calls)
    put(tmp_path, "a.csv", "a,b\n1,2\n", clock=clock)
    put(tmp_path, "b.csv", "a,b\n1,3\n", clock=clock)
    assert w.run(once=True) == 2
    put(tmp_path, "c.csv", "a,b\n1,4\n", clock=clock)
    assert w.run(interval=1.0, max_runs=1) == 1 and calls[-1] == "c.csv"

def test_the_watch_command_line_reports_problems_and_stops_after_once(tmp_path, capsys):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "site.toml").write_text(GOOD)
    assert cli.main(["watch", str(tmp_path / "site.toml"), "--inbox", str(tmp_path / "missing")]) == 2 and "does not exist" in capsys.readouterr().err
    assert cli.main(["watch", str(tmp_path / "site.toml"), "--inbox", str(tmp_path / "inbox"), "--out", str(tmp_path / "inbox" / "r"), "--once"]) == 2
    assert cli.main(["watch", str(tmp_path / "site.toml"), "--inbox", str(tmp_path / "inbox"), "--out", str(tmp_path / "r"), "--once"]) == 0
    assert "index.html" in capsys.readouterr().out

def test_the_watch_module_makes_no_network_calls_and_never_opens_the_inbox_for_writing():
    source = (Path(__file__).resolve().parent.parent / "aera" / "site" / "watch.py").read_text()
    for banned in ("import socket", "import urllib", "import requests", "import http", "import smtplib", "os.remove", "os.rename", "shutil.move", ".unlink(", ".rename("):
        assert banned not in source, banned
    assert '"rb"' in source and "inbox" in source

@needs_archive
def test_the_watcher_runs_real_shadow_mode_on_a_dropped_export_and_not_again(tmp_path):
    works = tmp_path / "works"
    demo.generate(works, days=14, mismatch=0.0, temperature=True)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    import shutil, os
    shutil.copy(works / "historian.csv", inbox / "export_2026_11_03.csv")
    os.utime(inbox / "export_2026_11_03.csv", (1.0, 1.0))                              # old enough to be complete
    before = (inbox / "export_2026_11_03.csv").read_bytes()
    w = watch_mod.Watcher(works / "site.toml", inbox, tmp_path / "reports", candidate=dict(so_ref=1.7), max_days=14.0, log=lambda *a: None)
    assert w.run(once=True) == 1
    entry = next(iter(w.state["processed"].values()))
    assert entry["status"] == "done" and entry["validation"] == "validated"
    run = tmp_path / "reports" / entry["run"]
    assert (run / "report.html").exists() and audit.verify(run / "audit.jsonl")[0] and audit.verify(tmp_path / "reports" / "watch_audit.jsonl")[0]
    assert json.loads((tmp_path / "reports" / "latest_report.json").read_text())["validation"]["status"] == "validated"
    assert w.run(once=True) == 0                                                         # the same export is not run again
    assert (inbox / "export_2026_11_03.csv").read_bytes() == before and [p.name for p in inbox.iterdir()] == ["export_2026_11_03.csv"]

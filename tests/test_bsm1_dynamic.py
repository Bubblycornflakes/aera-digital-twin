"""Closed loop BSM1 checks against the published dry weather reference (BSM1_R2019b, Results/closedloop_dyn.pdf).

These need the IWA archive extracted under data/ (see docs/AEROBENCH_DESIGN.md, section 13). Without it they skip.
"""
import numpy as np
import pytest
from aera import bsm1_dynamic as d

needs_archive = pytest.mark.skipif(not (d.ARCHIVE / "dryinfluent.mat").exists(), reason="BSM1 archive not extracted")

from aera.reference_values import PUBLISHED as REF
PUBLISHED = dict(ae=REF["aeration_energy_kwh_d"], eqi=REF["eqi"], snh=REF["snh_avg"], total_n=REF["total_n_avg"],
                 tss=REF["tss_avg"], cod=REF["cod_avg"], bod5=REF["bod5_avg"], over_n=REF["over_total_n"],
                 over_snh=REF["over_snh"], p95_snh=REF["p95_snh"], p95_n=REF["p95_total_n"], qintr=REF["qintr_steady"])

@pytest.fixture(scope="module")
def dry():
    return d.run()

@needs_archive
def test_steady_state_matches_published_recycle():
    y = d.stabilise(**d.MODES["full"])
    tanks = y[:65].reshape(5, 13)
    assert y[d.I_QA] == pytest.approx(PUBLISHED["qintr"], rel=1e-3)
    assert tanks[4, 7] == pytest.approx(2.0, abs=1e-3)
    assert tanks[1, 8] == pytest.approx(1.0, abs=1e-3)

@needs_archive
def test_reproduces_published_dry_weather(dry):
    i = d.indices(dry)
    assert i["aeration_energy_kwh_d"] == pytest.approx(PUBLISHED["ae"], rel=0.01)
    assert i["eqi"] == pytest.approx(PUBLISHED["eqi"], rel=0.03)
    assert i["average"]["snh"] == pytest.approx(PUBLISHED["snh"], rel=0.10)
    assert i["average"]["total_n"] == pytest.approx(PUBLISHED["total_n"], rel=0.03)
    assert i["average"]["tss"] == pytest.approx(PUBLISHED["tss"], rel=0.05)
    assert i["average"]["cod"] == pytest.approx(PUBLISHED["cod"], rel=0.05)
    assert i["share_over_limit"]["total_n"] == pytest.approx(PUBLISHED["over_n"], abs=0.03)
    assert i["share_over_limit"]["snh"] == pytest.approx(PUBLISHED["over_snh"], abs=0.03)
    assert i["p95"]["snh"] == pytest.approx(PUBLISHED["p95_snh"], rel=0.10)
    assert i["p95"]["total_n"] == pytest.approx(PUBLISHED["p95_n"], rel=0.05)
    assert i["samples"] == 672

@needs_archive
def test_states_stay_physical(dry):
    assert dry["samples"][:, 2:2 + 145].min() > -1e-6

@needs_archive
def test_run_is_deterministic(dry):
    again = d.run()
    assert np.array_equal(dry["samples"], again["samples"])

@needs_archive
def test_fouling_raises_aeration_demand(dry):
    fouled = d.run(scenario=d.Scenario(alpha_scale=0.6))
    assert d.indices(fouled)["aeration_energy_kwh_d"] > d.indices(dry)["aeration_energy_kwh_d"]

def test_return_liquor_adds_exact_ammonia_mass():
    flow = np.full(1344, 18446.0)
    feed = np.tile(np.arange(13, dtype=float) + 1, (1344, 1))
    sc = d.Scenario(return_liquor_kg=100.0)
    feed2, flow2 = d.apply_return_liquor(feed, flow, sc)
    added_g = np.sum(feed2[:, 9] * flow2 - feed[:, 9] * flow) / 96
    assert added_g == pytest.approx(100 * 1000, rel=1e-9)
    first = int(round((sc.return_liquor_day + 8 / 24) * 96))
    assert np.array_equal(flow2[:first], flow[:first]) and np.array_equal(flow2[first + 24:], flow[first + 24:])
    assert np.all(flow2[first:first + 24] > flow[first:first + 24])
    assert d.apply_return_liquor(feed, flow, d.Scenario())[1] is not flow  # never mutates the input
    assert np.array_equal(flow, np.full(1344, 18446.0))

@needs_archive
@pytest.mark.parametrize("weather", ["rain", "storm"])
def test_reproduces_published_rain_and_storm(weather):
    from aera.reference_values import PUBLISHED_WEATHER
    ref = PUBLISHED_WEATHER[weather]
    i = d.indices(d.run(scenario=d.Scenario(weather=weather)))
    assert i["aeration_energy_kwh_d"] == pytest.approx(ref["aeration_energy_kwh_d"], rel=0.01)
    assert i["eqi"] == pytest.approx(ref["eqi"], rel=0.03)
    assert i["average"]["total_n"] == pytest.approx(ref["total_n_avg"], rel=0.06)
    assert i["average"]["snh"] == pytest.approx(ref["snh_avg"], rel=0.10)
    assert i["share_over_limit"]["total_n"] == pytest.approx(ref["over_total_n"], abs=0.03)
    assert i["share_over_limit"]["snh"] == pytest.approx(ref["over_snh"], abs=0.03)
    assert i["share_over_limit"]["tss"] == pytest.approx(ref["over_tss"], abs=0.005)
    assert i["p95"]["snh"] == pytest.approx(ref["p95_snh"], rel=0.05)
    assert i["p95"]["total_n"] == pytest.approx(ref["p95_total_n"], rel=0.03)

@needs_archive
def test_fast_mode_agrees_with_full_mode_on_dry_weather(dry):
    full = d.indices(d.run(mode="full"))
    fast = d.indices(dry)
    assert fast["aeration_energy_kwh_d"] == pytest.approx(full["aeration_energy_kwh_d"], rel=1e-3)
    assert fast["eqi"] == pytest.approx(full["eqi"], rel=1e-3)
    for limit in d.LIMITS:
        assert fast["share_over_limit"][limit] == pytest.approx(full["share_over_limit"][limit], abs=0.005)

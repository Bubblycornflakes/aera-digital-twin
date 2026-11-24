"""Shadow mode: replay a works' own influent through the model under two controllers and compare.

Nothing here controls a plant. The replay answers "what would the model say if the DO setpoint had been X", and it also
checks the model against what the works actually recorded (the validation gate) so the answer can be trusted or not.

Scaling: the benchmark plant treats 18,446 m3/d. A larger or smaller works is represented by feeding the benchmark plant
flow / f, where f = design flow / 18,446, and multiplying energy back by f (similarity scaling). It is a stand-in for the
real layout, which is why validation against measured data matters."""
from dataclasses import dataclass, replace
import numpy as np
import pandas as pd
from .. import bsm1 as plant, bsm1_dynamic as dyn
from . import characterise

Q_BENCH = 18446.0
STEP_DAYS = 1 / 96

@dataclass
class Inputs:
    index: pd.DatetimeIndex
    flow_site: np.ndarray        # m3/d
    nh4: np.ndarray
    feed: np.ndarray             # (n, 13) at benchmark scale
    scale: float
    warmup_days: float
    observed: pd.DataFrame       # measured tags on the same index
    cod_used: bool = False       # False: COD was not usable and was assumed to scale with ammonium
    temperature: object = None   # Celsius, one value per record (None: the benchmark's 15 degrees)
    temperature_note: str = ""   # how the temperature was obtained, for the report

def prepare(site_table, window, config, max_days=28.0, warmup_days=3.0):
    """Cut the replay window out of the imported table and build the model inputs."""
    start, end = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    end = min(end, start + pd.Timedelta(days=max_days))
    seg = site_table.loc[start:end]
    scale = config.site.design_flow_m3_d / Q_BENCH
    cod = seg["influent_cod"].to_numpy() if "influent_cod" in seg and seg["influent_cod"].notna().all() else None
    feed = characterise.asm1_feed(seg["influent_nh4"].to_numpy(), cod)
    temp, note = _temperature(seg, config)
    return Inputs(seg.index, seg["influent_flow"].to_numpy(), seg["influent_nh4"].to_numpy(), feed, scale, warmup_days, seg, cod is not None, temp, note)

def _temperature(seg, config):
    """Celsius per record: the recorded temperature (gaps filled from neighbours, then the mean), else the assumed constant."""
    if "temperature" in seg and seg["temperature"].notna().any():
        t = seg["temperature"].interpolate(limit_direction="both")
        t = t.fillna(float(t.mean()))
        lo, hi = float(t.min()), float(t.max())
        return t.to_numpy(), f"follows your recorded temperature (mean {t.mean():.1f}, range {lo:.1f} to {hi:.1f} degrees Celsius)"
    c = config.site.temperature_c
    return np.full(len(seg), c), (f"assumed constant at {c:g} degrees Celsius, the benchmark value" if c == 15.0 else f"assumed constant at {c:g} degrees Celsius (site.temperature_c)")

SUPPORTED = ("so_ref", "k_do", "ti_do")

def controller_from(params, base):
    """A BSM1 controller from site settings plus overrides. Site mode supports so_ref, k_do and ti_do only."""
    unknown = set(params or {}) - set(SUPPORTED)
    if unknown:
        raise ValueError(f"site mode can test {', '.join(SUPPORTED)}; not {', '.join(sorted(unknown))}")
    merged = dict(so_ref=base.do_setpoint, k_do=base.k_do, ti_do=base.ti_do)
    merged.update(params or {})
    return dyn.Controller(**merged)

def simulate(inputs, controller, mode="fast", scenario=None):
    """Run one controller over the window. Returns a table on the replay index in site units.
    scenario: a bsm1_dynamic.Scenario carrying calibrated plant parameters (alpha_scale, mu_a_scale); None is the benchmark plant."""
    scenario = scenario or dyn.Scenario()
    q_model = inputs.flow_site / inputs.scale
    days = min(7.0, len(q_model) * STEP_DAYS)
    n0 = max(int(days / STEP_DAYS), 1)
    temp = inputs.temperature
    y0 = dyn.stabilise_at(controller, q_model[:n0].mean(), inputs.feed[:n0].mean(axis=0), scenario=scenario,
                          temperature=None if temp is None else float(np.mean(temp[:n0])), **dyn.MODES["full"])
    samples = dyn.run_series(controller, q_model, inputs.feed, y0, scenario=scenario, mode=mode, temperature=temp)
    eff = np.array([dyn.effluent(row[2:]) for row in samples])
    kla5 = samples[:, 2 + dyn.I_KA + 1]
    kla = np.stack([np.zeros(len(samples)), np.zeros(len(samples)), np.full(len(samples), 240.0), np.full(len(samples), 240.0), kla5], axis=1)
    ae = (dyn.SOSAT * kla * dyn.VOLUME).sum(axis=1) / (1.8 * 1000) * inputs.scale          # kWh/d at site scale
    out = pd.DataFrame(dict(effluent_nh4=eff[:, 9], effluent_tss=0.75 * eff[:, [2, 3, 4, 5, 6]].sum(axis=1),
                            do_aerobic=samples[:, 2 + 52 + 7], aeration_kwh_d=ae, flow=inputs.flow_site), index=inputs.index)
    return out

def after_warmup(df, inputs, start=None):
    """The rows that count: everything after the warm-up days, or from `start` if given (for example the first held-out day)."""
    return df.loc[start if start is not None else df.index[0] + pd.Timedelta(days=inputs.warmup_days):]

def daily(series, flow=None, tz="UTC"):
    """Daily values on LOCAL calendar days (the works' clock). Flow-weighted means when flow is given, a stand-in for a
    24 hour composite sample."""
    s = series.copy()
    s.index = s.index.tz_convert(tz)
    if flow is None:
        return s.resample("1D").mean().dropna()
    f = flow.copy()
    f.index = f.index.tz_convert(tz)
    num = (s * f).resample("1D").sum()
    den = f.where(s.notna()).resample("1D").sum()
    return (num / den).dropna()

def metrics(model, observed):
    """Nash-Sutcliffe efficiency, bias (per cent of the recorded mean, and in the unit itself), correlation and spread of
    the recorded values, on the days both exist."""
    both = pd.concat([model, observed], axis=1, keys=["m", "o"]).dropna()
    if len(both) < 3 or both["o"].var() == 0:
        return dict(n=len(both), nse=None, bias_pct=None, bias_abs=None, r2=None, observed_std=round(float(both["o"].std()), 4) if len(both) > 1 else None)
    err = both["m"] - both["o"]
    nse = 1 - (err ** 2).sum() / ((both["o"] - both["o"].mean()) ** 2).sum()
    corr = float(np.corrcoef(both["m"], both["o"])[0, 1]) if both["m"].var() > 0 else 0.0
    return dict(n=len(both), nse=round(float(nse), 3), bias_pct=round(100 * float(err.mean() / both["o"].mean()), 1),
                bias_abs=round(float(err.mean()), 3), r2=round(corr ** 2, 3), observed_std=round(float(both["o"].std()), 4))

def energy_calibration(baseline, inputs, start=None):
    """Factor that turns the model's aeration energy into the blower energy the works recorded (level only, not shape).
    Uses only the 15 minute records where BOTH exist, so gaps in the blower record do not bias it."""
    if "blower_power" not in inputs.observed or inputs.observed["blower_power"].isna().all():
        return None
    pair = pd.concat([after_warmup(inputs.observed["blower_power"] * 24.0, inputs, start), after_warmup(baseline["aeration_kwh_d"], inputs, start)],
                     axis=1, keys=["o", "m"]).dropna()
    return float(pair["o"].mean() / pair["m"].mean()) if len(pair) and pair["m"].mean() > 0 else None

def validate(baseline, inputs, config, start=None):
    """The validation gate: does the model reproduce what the works recorded?

    'validated' needs BOTH effluent ammonium and blower energy to have been scored and passed, and no scored indicator to fail.
    An indicator that cannot be scored (too few days, recorded values that barely vary, no data) never counts as a pass."""
    v, tz = config.validation, config.site.timezone
    base, obs = after_warmup(baseline, inputs, start), after_warmup(inputs.observed, inputs, start)
    ind, reasons = {}, []

    def finish(name, m, ok, reason, **extra):
        ind[name] = dict(m, ok=ok, scorable=ok is not None, **extra)
        reasons.append(f"{name}: {reason}")

    if "effluent_nh4" in obs and obs["effluent_nh4"].notna().any():
        m = metrics(daily(base["effluent_nh4"], base["flow"], tz), daily(obs["effluent_nh4"], base["flow"], tz))
        if m["n"] < v.min_days_compared:
            finish("effluent_nh4", m, None, f"only {m['n']} day(s) could be compared (needs {v.min_days_compared}), so it was NOT scored")
        elif m["nse"] is None or m["observed_std"] < v.nh4_min_std:
            finish("effluent_nh4", m, None, f"recorded daily ammonium barely varies (standard deviation {m['observed_std']} mg/l, needs {v.nh4_min_std:g}), so it cannot test the model and was NOT scored")
        else:
            ok = m["nse"] >= v.nse_min and (abs(m["bias_pct"]) <= v.bias_max_pct or abs(m["bias_abs"]) <= v.nh4_abs_bias_mg_l)
            finish("effluent_nh4", m, ok, f"NSE {m['nse']} (needs {v.nse_min:g}), bias {m['bias_pct']}% or {m['bias_abs']} mg/l (needs within {v.bias_max_pct:g}% or {v.nh4_abs_bias_mg_l:g} mg/l): {'pass' if ok else 'FAIL'}")

    factor = energy_calibration(baseline, inputs, start)
    if factor is not None:
        mod = daily(base["aeration_kwh_d"] * factor, tz=tz)
        m = metrics(mod, daily(obs["blower_power"] * 24.0, tz=tz))
        if m["n"] < v.min_days_compared or m["nse"] is None:
            finish("aeration_energy", m, None, f"too few days or no variation to score (compared {m['n']}, needs {v.min_days_compared}), so it was NOT scored", calibration_factor=round(factor, 3))
        else:
            in_band = v.energy_factor_min <= factor <= v.energy_factor_max
            ok = m["nse"] >= v.nse_min and in_band
            finish("aeration_energy", m, ok, f"day-to-day shape NSE {m['nse']} (needs {v.nse_min:g}); model energy had to be scaled by {factor:.2f} to match your blowers "
                   f"(believable range {v.energy_factor_min:g} to {v.energy_factor_max:g}): {'pass' if ok else 'FAIL'}. The scaling fixes the level only, so only the shape is tested.",
                   calibration_factor=round(factor, 3))

    if "do_aerobic" in obs and obs["do_aerobic"].notna().any():
        md, od = daily(base["do_aerobic"], tz=tz), daily(obs["do_aerobic"], tz=tz)
        m = metrics(md, od)
        pair = pd.concat([md, od], axis=1, keys=["m", "o"]).dropna()
        mae = round(float((pair["m"] - pair["o"]).abs().mean()), 3) if len(pair) else None
        if m["n"] < v.min_days_compared or mae is None:
            finish("do_aerobic", dict(m, kind="level", mae=mae), None, f"only {m['n']} day(s) could be compared, so it was NOT scored")
        else:
            ok = mae <= v.do_mae_max
            finish("do_aerobic", dict(m, kind="level", mae=mae), ok, f"daily values are off by {mae} mg/l on average (needs {v.do_mae_max:g} or less): {'pass' if ok else 'FAIL'}. "
                   "DO is held near its setpoint, so it barely varies and Nash-Sutcliffe is not used. This is a weak check: the model is driven to the setpoint you configured.")

    if "effluent_tss" in obs and obs["effluent_tss"].notna().any():
        m = metrics(daily(base["effluent_tss"], base["flow"], tz), daily(obs["effluent_tss"], base["flow"], tz))
        if m["n"] < v.min_days_compared or m["nse"] is None:
            finish("effluent_tss", m, None, "too few days or no variation to score, so it was NOT scored. Informational: it only gates a suspended solids consent")
        else:
            ok = m["nse"] >= v.nse_min and abs(m["bias_pct"]) <= v.bias_max_pct
            finish("effluent_tss", m, ok, f"NSE {m['nse']}, bias {m['bias_pct']}%: {'pass' if ok else 'FAIL'}. Informational: it only gates a suspended solids consent")

    core = {k: ind[k]["ok"] for k in ("effluent_nh4", "aeration_energy", "do_aerobic") if k in ind}
    failed = [k for k, ok in core.items() if ok is False]
    nh4_ok, energy_ok = core.get("effluent_nh4") is True, core.get("aeration_energy") is True
    if failed:
        status = "not_validated"
    elif nh4_ok and energy_ok:
        status = "validated"
    elif nh4_ok or energy_ok:
        status = "partly_validated"
        missing = "blower energy" if nh4_ok else "effluent ammonium"
        reasons.append(f"Only one of effluent ammonium and blower energy could be scored; {missing} was not checked, so the model is not fully validated.")
    else:
        status = "cannot_validate"
        reasons.append("Nothing recorded could be scored against the model (no usable effluent ammonium or blower power). Results are model-only.")
    return dict(status=status, indicators=ind, reasons=reasons, days_compared=int(len(daily(base["flow"], tz=tz))),
                thresholds=dict(nse_min=v.nse_min, bias_max_pct=v.bias_max_pct, do_mae_max=v.do_mae_max, min_days_compared=v.min_days_compared,
                                nh4_abs_bias_mg_l=v.nh4_abs_bias_mg_l, energy_factor_range=[v.energy_factor_min, v.energy_factor_max]))

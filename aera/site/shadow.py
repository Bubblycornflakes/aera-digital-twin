"""The shadow-mode run: import data, replay it under two controllers, validate the model against the record, check consents,
appraise energy and carbon, apply guardrails, and write the report. Advice only; nothing touches a plant."""
import json
from pathlib import Path
import pandas as pd
from .. import bsm1_dynamic as dyn
from . import appraisal, audit, calibrate as calibration, config as cfg, consent, guardrails, importer, replay

LOW_DO = 0.5
ASSUMPTIONS = [
    "The plant is the IWA BSM1 benchmark scaled to your design flow (similarity scaling). Your real tank layout, aeration system and settlers differ.",
    "Influent composition is estimated from measured flow, ammonium and (if given) COD using benchmark fractions.",
    "Sensors are treated as ideal; the real DO controller's noise and delay are not modelled, and the model's DO is driven to the setpoint you configured.",
    "Energy is the model's aeration energy, scaled to your recorded blower energy where you gave blower power. The scaling fixes the level, so only day-to-day shape is tested.",
    "A 'sample' for consent checks is a flow-weighted daily mean on local calendar days, which is not how your permit is sampled.",
    "Cost and carbon ranges reflect only the tariff and carbon-factor uncertainty you configured, not model or calibration error.",
]

def _series(base, cand, observed, column, warmup, tz, weight=True):
    """Daily series for a chart: model today, model candidate and, where recorded, the observation (local calendar days)."""
    pick = lambda df: df.loc[df.index[0] + pd.Timedelta(days=warmup):]
    b, c = pick(base), pick(cand)
    use = (lambda df: replay.daily(df[column], df["flow"], tz)) if weight else (lambda df: replay.daily(df[column], tz=tz))
    bd, cd = use(b), use(c)
    out = dict(day=[str(d.date()) for d in bd.index], baseline=[round(float(v), 3) for v in bd.to_numpy()],
               candidate=[round(float(v), 3) for v in cd.reindex(bd.index).to_numpy()])
    if observed is not None:
        o = pick(observed)
        od = replay.daily(o, b["flow"], tz) if weight else replay.daily(o, tz=tz)
        out["observed"] = [None if d not in od.index else round(float(od[d]), 3) for d in bd.index]
    return out

def run(config_path, out_dir, candidate=None, sweep=None, max_days=28.0, mode="fast", log=print, calibrate=None, workers=None, data_file=None):
    """Run shadow mode for the site described by config_path. Returns the report dictionary (also written to out_dir).
    data_file: use this CSV instead of the file named in the configuration (the watch folder uses it); it is only ever read."""
    config_path, out = Path(config_path), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    config = cfg.load(config_path)
    if data_file is not None:
        config = config.model_copy(update=dict(data=config.data.model_copy(update=dict(file=str(Path(data_file).resolve())))))
    tz = config.site.timezone
    candidate = dict(candidate or {})
    try:
        base_ctrl, cand_ctrl = replay.controller_from({}, config.control), replay.controller_from(candidate, config.control)
    except ValueError as error:
        raise cfg.ConfigError(str(error)) from None
    trail = out / "audit.jsonl"
    log("Reading the data file...")
    data = importer.load(config, config_path.parent)
    (out / "data_quality.md").write_text(importer.quality_markdown(data.report))
    audit.append(trail, "import", dict(config_sha256=audit.file_hash(config_path), data_file=data.report["file"],
                                       data_sha256=audit.file_hash(config_path.parent / config.data.file), days=data.report["days"],
                                       issues=len(data.report["issues"])))
    if not data.windows:
        raise cfg.ConfigError("No period of the data is long enough to replay. See data_quality.md for why.")
    window = max(data.windows, key=lambda w: w[1] - w[0])
    inputs = replay.prepare(data.table, window, config, max_days=max_days)
    local = lambda ts: ts.tz_convert(tz).strftime("%Y-%m-%d %H:%M")
    log(f"Replaying {len(inputs.index) / 96:.0f} days ({local(inputs.index[0])[:10]} to {local(inputs.index[-1])[:10]}) under today's control...")
    cal, scenario, start = None, None, None
    if config.calibration.enabled if calibrate is None else calibrate:
        cal = calibration.calibrate(inputs, config, base_ctrl, workers, log)
        log(f"Calibration: {cal['status'].replace('_', ' ')}" + (f" (nitrifier activity x{cal['params']['mu_a_scale']}, oxygen transfer x{cal['params']['alpha_scale']})" if cal.get("used") else ""))
        if cal.get("used"):
            scenario, start = dyn.Scenario(**cal["params"]), pd.Timestamp(cal["test_start"])
    base = replay.simulate(inputs, base_ctrl, mode, scenario)
    validation = replay.validate(base, inputs, config, start)
    validation["evaluated_on"] = (f"the {cal['test_days']} days held out from the calibration (from {start.tz_convert(tz).strftime('%Y-%m-%d')})" if start is not None
                                  else f"all {validation['days_compared']} days after warm-up")
    factor = validation["indicators"].get("aeration_energy", {}).get("calibration_factor")
    log(f"Model check: {validation['status'].replace('_', ' ')}")
    if candidate:
        log("Replaying the candidate setting...")
        cand = replay.simulate(inputs, cand_ctrl, mode, scenario)
    else:
        cand = base
    warm = lambda df: replay.after_warmup(df, inputs)
    b, c = warm(base), warm(cand)

    consents = []
    for spec in config.consent:
        series = lambda df: replay.daily(df[spec.tag], df["flow"], tz)
        consents.append(dict(baseline=consent.check(spec, series(b)), candidate=consent.check(spec, series(c))))
    low_b, low_c = float((b["do_aerobic"] < LOW_DO).mean()), float((c["do_aerobic"] < LOW_DO).mean())
    energy_b, energy_c = appraisal.appraise(b, factor, config), appraisal.appraise(c, factor, config)
    rec = None
    if candidate:
        rec = guardrails.review(config, dict(so_ref=cand_ctrl.so_ref, k_do=cand_ctrl.k_do, ti_do=cand_ctrl.ti_do), validation,
                                [x["baseline"] for x in consents], [x["candidate"] for x in consents], low_b, low_c)

    table = None
    if sweep:
        log(f"Replaying {len(sweep)} DO setpoints for the sweep...")
        table = []
        for sp in sweep:
            sim = warm(replay.simulate(inputs, replay.controller_from(dict(so_ref=sp), config.control), mode, scenario))
            ap = appraisal.appraise(sim, factor, config)
            checks = [consent.check(spec, replay.daily(sim[spec.tag], sim["flow"], tz)) for spec in config.consent]
            table.append(dict(so_ref=sp, energy_kwh_per_day=ap["energy_kwh_per_day"], cost_gbp=ap["cost_gbp"],
                              consents_exceeded=[c["name"] for c in checks if c["status"] == "exceeds"],
                              low_do_pct=round(100 * float((sim["do_aerobic"] < LOW_DO).mean()), 1),
                              mean_effluent_nh4=round(float(replay.daily(sim["effluent_nh4"], sim["flow"], tz).mean()), 2)))
    obs = inputs.observed
    assumptions = list(ASSUMPTIONS)
    assumptions.insert(2, f"Temperature {inputs.temperature_note}. The temperature coefficients are typical literature values for activated sludge, not calibrated to your works; "
                          "calibration does not fit them.")
    if cal and cal.get("used"):
        assumptions.append("The plant was calibrated on the first part of your data (two multipliers: nitrifier activity and oxygen transfer). Other plant properties are still the benchmark's.")
    if "influent_cod" in data.table.columns and not inputs.cod_used:
        assumptions.insert(1, "Influent COD was configured but had gaps in the replayed period, so it was NOT used: COD was assumed to scale with ammonium.")
    scale_energy = lambda df: df.assign(aeration_kwh_d=df["aeration_kwh_d"] * (factor or 1))
    report = dict(site=config.site.name, generated_by="aera.site", synthetic="synthetic" in config.site.name.lower(),
                  window=dict(start=local(inputs.index[0]), end=local(inputs.index[-1]), timezone=tz, days=round(len(inputs.index) / 96, 1),
                              warmup_days_excluded=inputs.warmup_days),
                  scale_factor=round(inputs.scale, 3), temperature=inputs.temperature_note, current_control=config.control.model_dump(), candidate=candidate or None,
                  data_quality=data.report, validation=validation, calibration=cal, consents=consents, low_do_share=dict(baseline=low_b, candidate=low_c),
                  appraisal=dict(baseline=energy_b, candidate=energy_c, difference=appraisal.compare(energy_b, energy_c) if candidate else None),
                  recommendation=rec, sweep=table, assumptions=assumptions,
                  series=dict(effluent_nh4=_series(base, cand, obs["effluent_nh4"] if "effluent_nh4" in obs else None, "effluent_nh4", inputs.warmup_days, tz),
                              aeration_kwh_d=_series(scale_energy(base), scale_energy(cand), obs["blower_power"] * 24 if "blower_power" in obs else None,
                                                     "aeration_kwh_d", inputs.warmup_days, tz, weight=False)))
    from .report import html
    path, page = out / "report.json", out / "report.html"
    path.write_text(json.dumps(report, indent=1, default=str))
    page.write_text(html(report))
    entry = audit.append(trail, "replay", dict(report=path.name, report_sha256=audit.file_hash(path), report_html_sha256=audit.file_hash(page),
                                               validation=validation["status"], candidate=candidate or None,
                                               recommendation=rec["status"] if rec else None))
    report["audit_head"] = entry["hash"]
    log(f"Audit record head: {entry['hash'][:12]} (write this down somewhere else to detect a truncated record later)")
    return report

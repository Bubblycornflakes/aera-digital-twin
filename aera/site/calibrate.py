"""Calibration: fit two plant parameters to a works' own data, and prove the fit on days it never saw.

What is fitted (both are multipliers on the benchmark plant, 1.0 = unchanged):
- mu_a_scale: nitrifier activity. It sets how fast the plant converts ammonium, so it is what recorded effluent ammonium tells us.
- alpha_scale: oxygen transfer efficiency (fouling, diffuser condition). It sets how hard the blowers must work for a given DO.

How the fit is judged, in order, and why it is built to refuse:
1. The replayed days are split: the first share (train_fraction) is used to fit, the rest are HELD OUT.
2. A coarse grid, then a pattern search that shrinks its step around the best point, are scored on the training days only. Each point is one
   full replay. Ammonium error is measured on a log scale (relative error), because effluent ammonium can span a factor of 20 and near
   nitrifier washout it is extremely steep in the parameters.
3. A parameter whose change barely moves the error cannot be identified from these data. It is put back to 1.0, not fitted to noise.
4. The calibrated plant is then scored on the held-out days against the uncalibrated one. It is only used if it cuts the held-out
   ammonium error by at least min_improvement, without making the energy shape worse. Otherwise the benchmark plant is kept.
The validation gate afterwards is judged on the held-out days only, so a calibration cannot grade its own homework."""
import os
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import pandas as pd
from .. import bsm1_dynamic as dyn
from . import replay

BOUNDS = (0.4, 2.5)
COARSE = [0.5, 0.71, 1.0, 1.41, 2.0]
START_STEP, MIN_STEP, MAX_EVALS = 1.41, 1.04, 90
PROBE = 1.2                       # the change used to test whether a parameter is identifiable
LOG_OFFSET = 0.2                  # mg/l added before taking logs, so near-zero ammonium does not dominate
MEANING = dict(mu_a_scale="nitrifier activity (1.0 = the benchmark plant)", alpha_scale="oxygen transfer efficiency (1.0 = the benchmark plant)")

def split_days(inputs, config, tz):
    """Local calendar days after warm-up, split into training and held-out days."""
    days = replay.daily(pd.Series(inputs.flow_site, index=inputs.index), tz=tz)
    first = inputs.index[0] + pd.Timedelta(days=inputs.warmup_days)
    days = [d for d in days.index if d >= first.tz_convert(tz).normalize()]
    n_train = int(round(config.calibration.train_fraction * len(days)))
    return days[:n_train], days[n_train:]

def _errors(sim, inputs, days, tz, nh4_std, energy_std):
    """Standardised error terms on the given days. Energy is compared after removing the level (a scaling is fitted on these days)."""
    out = {}
    obs = inputs.observed
    m = replay.daily(sim["effluent_nh4"], sim["flow"], tz).reindex(days)
    o = replay.daily(obs["effluent_nh4"], sim["flow"], tz).reindex(days)
    pair = pd.concat([m, o], axis=1, keys=["m", "o"]).dropna()
    out["nh4"] = float(np.sqrt(((np.log(pair["m"] + LOG_OFFSET) - np.log(pair["o"] + LOG_OFFSET)) ** 2).mean()) / nh4_std) if len(pair) else np.inf
    if "blower_power" in obs and obs["blower_power"].notna().any():
        me = replay.daily(sim["aeration_kwh_d"], tz=tz).reindex(days)
        oe = replay.daily(obs["blower_power"] * 24.0, tz=tz).reindex(days)
        pe = pd.concat([me, oe], axis=1, keys=["m", "o"]).dropna()
        if len(pe) and pe["m"].mean() > 0:
            k = pe["o"].mean() / pe["m"].mean()
            out["energy"] = float(np.sqrt(((k * pe["m"] - pe["o"]) ** 2).mean()) / energy_std)
    return out

def _loss(errors):
    return errors["nh4"] + 0.5 * errors.get("energy", 0.0)

def _job(args):
    """One grid point: a full replay with the trial parameters, scored on the training days. Top level so it can run in a process pool."""
    (mu, alpha), inputs, config, controller, days, nh4_std, energy_std = args
    sim = replay.simulate(inputs, controller, "fast", dyn.Scenario(mu_a_scale=mu, alpha_scale=alpha))
    return _loss(_errors(sim, inputs, days, config.site.timezone, nh4_std, energy_std))

def _map(fn, jobs, workers):
    if workers <= 1 or len(jobs) == 1:
        return [fn(j) for j in jobs]
    with ProcessPoolExecutor(min(workers, len(jobs))) as pool:
        return list(pool.map(fn, jobs))

def calibrate(inputs, config, controller, workers=None, log=print):
    """Returns a dictionary describing the outcome. status is accepted, not_improved, insufficient_data or needs_effluent_ammonium."""
    workers = workers or min(8, os.cpu_count() or 1)
    v, c, tz = config.validation, config.calibration, config.site.timezone
    obs = inputs.observed
    if "effluent_nh4" not in obs or obs["effluent_nh4"].notna().sum() < 10:
        return dict(status="needs_effluent_ammonium", notes=["Calibration needs recorded effluent ammonium; none was usable."], used=False)
    train, test = split_days(inputs, config, tz)
    if len(train) < v.min_days_compared or len(test) < v.min_days_compared:
        return dict(status="insufficient_data", used=False, train_days=len(train), test_days=len(test),
                    notes=[f"Calibration needs at least {v.min_days_compared} days to fit and {v.min_days_compared} held out (this window gives {len(train)} and {len(test)}). Use a longer data window."])
    flow = pd.Series(inputs.flow_site, index=inputs.index)
    nh4_obs = replay.daily(obs["effluent_nh4"], flow, tz).reindex(train).dropna()
    spread = float(nh4_obs.std()) if len(nh4_obs) > 1 else 0.0
    if not spread or spread < v.nh4_min_std:
        return dict(status="not_improved", used=False, notes=[f"Recorded ammonium barely varies on the fitting days (standard deviation {spread:.2f} mg/l), so it cannot guide a fit."])
    nh4_std = max(float(np.log(nh4_obs + LOG_OFFSET).std()), 0.15)
    energy_std = 1.0
    if "blower_power" in obs and obs["blower_power"].notna().any():
        energy_std = float(replay.daily(obs["blower_power"] * 24.0, tz=tz).reindex(train).std()) or 1.0
    job = lambda p: (p, inputs, config, controller, train, nh4_std, energy_std)
    grid, seen = [], {}

    def run(points):
        todo = [p for p in points if (round(p[0], 4), round(p[1], 4)) not in seen]
        log(f"Calibration: scoring {len(todo)} plant settings on {len(train)} training days...")
        for p, loss in zip(todo, _map(_job, [job(p) for p in todo], workers)):
            seen[(round(p[0], 4), round(p[1], 4))] = loss
            grid.append(dict(mu_a_scale=round(p[0], 3), alpha_scale=round(p[1], 3), loss=round(loss, 4)))

    clip = lambda x: float(np.clip(x, *BOUNDS))
    key = lambda p: (round(p[0], 4), round(p[1], 4))
    run([(m, a) for m in COARSE for a in COARSE])
    best, step = min(seen, key=seen.get), START_STEP
    while step > MIN_STEP and len(seen) < MAX_EVALS:                      # pattern search: look all round the best point, shrink when nothing is better
        run([(clip(best[0] * a), clip(best[1] * b)) for a in (1 / step, 1, step) for b in (1 / step, 1, step) if (a, b) != (1, 1)])
        new = min(seen, key=seen.get)
        step = step ** 0.5 if new == best else step
        best = new
    lowest = seen[best]
    probes = [(clip(best[0] * f), best[1]) for f in (1 / PROBE, PROBE)] + [(best[0], clip(best[1] * f)) for f in (1 / PROBE, PROBE)]
    run(probes)                                                           # identifiability: does a 20% change in each parameter move the error?
    notes, identifiable, final = [], {}, list(best)
    for i, name in enumerate(("mu_a_scale", "alpha_scale")):
        rise = (seen[key(probes[2 * i])] + seen[key(probes[2 * i + 1])]) / 2 - lowest
        identifiable[name] = bool(rise >= c.flat_threshold)
        if not identifiable[name]:
            final[i] = 1.0
            notes.append(f"{name} ({MEANING[name]}) cannot be identified from these data: changing it by 20% barely changes the error. It was left at 1.0.")
    if final != list(best) and any(identifiable.values()):                # the other one was put back to 1.0, so re-fit the identifiable one alone
        i = 0 if identifiable["mu_a_scale"] else 1
        here, step = final[i], START_STEP
        pick = lambda x: tuple(final[:i] + [x] + final[i + 1:])
        run([pick(here)])
        while step > MIN_STEP and len(seen) < MAX_EVALS:
            run([pick(clip(here / step)), pick(clip(here * step))])
            new = min((here, clip(here / step), clip(here * step)), key=lambda x: seen[key(pick(x))])
            step = step ** 0.5 if new == here else step
            here = new
        final = list(pick(here))
    params = dict(mu_a_scale=round(final[0], 3), alpha_scale=round(final[1], 3))
    hit = [k for k, x in params.items() if abs(x - BOUNDS[0]) < 1e-3 or abs(x - BOUNDS[1]) < 1e-3]
    if hit:
        notes.append(f"{', '.join(hit)} reached the edge of its allowed range {BOUNDS[0]}-{BOUNDS[1]}: the benchmark plant may be the wrong shape for this works.")

    log("Calibration: checking the fit on the held-out days...")
    default_sim = replay.simulate(inputs, controller, "fast")
    fitted_sim = replay.simulate(inputs, controller, "fast", dyn.Scenario(**params))
    before = _errors(default_sim, inputs, test, tz, nh4_std, energy_std)
    after = _errors(fitted_sim, inputs, test, tz, nh4_std, energy_std)
    gain = 1 - after["nh4"] / before["nh4"] if before["nh4"] and np.isfinite(before["nh4"]) else 0.0
    worse_energy = "energy" in before and after["energy"] > before["energy"] * 1.10
    accepted = gain >= c.min_improvement and not worse_energy and any(identifiable.values())
    if not any(identifiable.values()):
        notes.append("Neither parameter could be identified, so nothing was fitted.")
    elif gain < c.min_improvement:
        notes.append(f"On the held-out days the fit cut the ammonium error by {100 * gain:.0f}% (needs {100 * c.min_improvement:.0f}%), so it was NOT used.")
    elif worse_energy:
        notes.append("On the held-out days the fit made the energy shape worse, so it was NOT used.")
    test_start = pd.Timestamp(test[0]).tz_convert("UTC") if pd.Timestamp(test[0]).tzinfo else pd.Timestamp(test[0]).tz_localize(tz).tz_convert("UTC")
    return dict(status="accepted" if accepted else "not_improved", used=accepted, params=params if accepted else dict(mu_a_scale=1.0, alpha_scale=1.0),
                fitted=params, identifiable=identifiable, notes=notes, train_days=len(train), test_days=len(test), test_start=str(test_start),
                held_out=dict(nh4_error_before=round(before["nh4"], 3), nh4_error_after=round(after["nh4"], 3), improvement_pct=round(100 * gain, 1),
                              energy_shape_error_before=round(before.get("energy", float("nan")), 3), energy_shape_error_after=round(after.get("energy", float("nan")), 3)),
                grid=sorted(grid, key=lambda g: g["loss"])[:12], evaluations=len(seen), meaning=MEANING)

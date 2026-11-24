"""BSM1 closed loop with dynamic influent. Days, m3/day, g/m3.

Controller, sensor and actuator models follow BSM1_R2019b (reginit.m, sensorinit.m, Simulink
model, description PDF). The plant is the verified open-loop model in bsm1.py, generalised to a
time-varying influent flow and internal recycle. Archive files are read from AERA_BSM1_DIR
(default data/bsm1_extracted/BSM1_R2019b); they are data only and not committed.
"""
import functools
import hashlib
import os
import threading
import time
import warnings
from dataclasses import dataclass, replace
from pathlib import Path
import numpy as np
from scipy.integrate import solve_ivp
from scipy.io import loadmat
from scipy.sparse import csc_matrix
from . import bsm1 as plant
from .asm1 import MATRIX, rates

ARCHIVE = Path(os.environ.get("AERA_BSM1_DIR", Path(__file__).resolve().parent.parent / "data/bsm1_extracted/BSM1_R2019b"))
NPLANT = 145
MODEL_VERSION = "2"    # bump when plant, controller or index code changes results; invalidates the results cache
SOSAT = 8.0
VOLUME = plant.VOLUME
Q0, RAS, WASTE = 18446.0, plant.RAS, plant.WASTE
F_P, I_XB, I_XP = 0.08, 0.08, 0.06
LIMITS = dict(total_n=18.0, total_cod=100.0, snh=4.0, tss=30.0, bod5=10.0)
# State layout after the 145 plant states.
I_DS, I_KA, I_IDO, I_NS, I_QA, I_IQ, NSTATE = 145, 147, 149, 150, 158, 159, 160

@dataclass(frozen=True)
class Controller:
    """BSM1 default DO loop on reactor 5 (tunable) plus the default nitrate loop (fixed)."""
    so_ref: float = 2.0
    k_do: float = 25.0       # 1/d per (g/m3)
    ti_do: float = 0.002     # d
    tt_do: float = 0.001     # d, anti-windup tracking
    kla_offset: float = 144.0
    kla_max: float = 360.0   # 1/d
    no_ref: float = 1.0
    k_q: float = 10000.0
    ti_q: float = 0.025
    tt_q: float = 0.015
    q_offset: float = 18500.0
    q_max: float = 5 * Q0
    # Stage 2 ammonia cascade (ideal tank 5 ammonium sensor): DO setpoint = so_ref + nh_gain * (NH4 - nh_ref), limited.
    nh_gain: float = 0.0     # 0 switches the cascade off
    nh_ref: float = 1.0
    so_min: float = 0.5
    so_max: float = 4.0

@dataclass(frozen=True)
class Scenario:
    """Weather file plus faults and plant perturbations. Defaults reproduce plain BSM1."""
    weather: str = "dry"
    noise_scale: float = 1.0        # multiplies the BSM1 sensor noise
    do_bias: float = 0.0            # additive DO sensor error, g/m3
    lag_scale: float = 1.0          # multiplies the DO sensor time constant (extra delay)
    alpha_scale: float = 1.0        # scales oxygen transfer (fouling)
    mu_a_scale: float = 1.0         # scales nitrifier growth rate
    return_liquor_kg: float = 0.0   # extra ammonia, kg N delivered over 6 h on return_liquor_day at 08:00
    return_liquor_day: float = 9.0
    noise_shift: float = 0.0        # days; rotates the sensor noise file so a scenario does not reuse training noise

# Solver modes. Both reproduce the strict rtol 1e-6 indices to within 0.05% (measured on dry weather).
MODES = dict(fast=dict(rtol=1e-3, atol=1e-5), full=dict(rtol=1e-4, atol=1e-6))

BOUNDS = dict(so_ref=(0.5, 5.0), k_do=(1.0, 500.0), ti_do=(0.0005, 0.02), kla_max=(120.0, 360.0))
BOUNDS2 = dict(BOUNDS, nh_gain=(0.0, 2.0), nh_ref=(0.5, 4.0))

T_SO = 1 / (24 * 60) / 3.89      # class A DO sensor, two equal lags
T_KLA = 4 / (24 * 60) / 3.89     # KLa5 actuator, two equal lags
T_NO = 10 / (24 * 60) / 11.7724  # class B0 nitrate sensor, eight equal lags
T_QA = 0.001                     # Qintr actuator, first order (QintrT = T*10, T = 1e-4 d)

def weather(name):
    """Dynamic influent as (time, feed (n, 13), flow (n,)). Zero-order hold between records."""
    key = {"dry": "DRYINFLUENT", "rain": "RAININFLUENT", "storm": "STORMINFLUENT"}[name]
    a = loadmat(ARCHIVE / f"{name}influent.mat")[key]
    return a[:, 0], a[:, 1:14], a[:, 15]

def sensor_noise(shift=0.0):
    """DO and nitrate noise, rotated by `shift` days (the file covers 14 days at one sample per minute)."""
    a = loadmat(ARCHIVE / "sensornoise.mat")["SENSORNOISE"]
    t, so, no = a[:, 0], a[:, 1], a[:, 2]
    k = int(round(shift * 1440))
    if k:
        n = len(t) - 1
        so, no = (np.r_[np.roll(v[:n], -k), np.roll(v[:n], -k)[0]] for v in (so, no))
    return t, so, no

def settler(layers, feed, qf, qe):
    """plant.settler with the feed and effluent flows as arguments."""
    mass = np.r_[plant.tss(feed), feed[plant.SOLUBLE]]
    x = np.maximum(layers[:, 0], 0)
    excess = np.maximum(x - .00228 * mass[0], 0)
    velocity = np.minimum(250., 474 * (np.exp(-.000576 * excess) - np.exp(-.00286 * excess)))
    downward = velocity * x
    settling = np.minimum(downward[:-1], downward[1:])
    settling[:4] = np.where(x[1:5] <= 3000, downward[:4], settling[:4])
    flux = np.vstack((-qe * layers[:5], (RAS + WASTE) * layers[4:])) / plant.AREA
    flux[1:-1, 0] += settling
    change = -np.diff(flux, axis=0)
    change[4] += qf / plant.AREA * mass
    return change / plant.HEIGHT

def jacobian_pattern():
    """Sparsity of d(rhs)/dy. A superset of the true dependencies (checked numerically in the tests), tight enough
    that the solver needs 43 column groups per Jacobian instead of 160."""
    full = np.zeros((NSTATE, NSTATE), dtype=bool)
    full[:NPLANT, :NPLANT] = plant.jacobian_pattern().toarray()
    so5, nh5, no2 = 52 + 7, 52 + 9, 13 + 8
    full[I_DS, [so5, I_DS]] = True
    full[I_DS + 1, [I_DS, I_DS + 1]] = True
    # DO PI output: filtered DO, its integrator and (stage 2) tank 5 ammonium
    full[I_KA, [I_DS + 1, I_IDO, nh5, I_KA]] = True
    full[I_KA + 1, [I_KA, I_KA + 1]] = True
    full[I_IDO, [I_DS + 1, I_IDO, nh5, I_KA]] = True
    full[I_NS, [no2, I_NS]] = True
    for i in range(1, 8):
        full[I_NS + i, [I_NS + i - 1, I_NS + i]] = True
    full[I_QA, [I_NS + 7, I_IQ, I_QA]] = True
    full[I_IQ, [I_NS + 7, I_IQ, I_QA]] = True
    full[:NPLANT, I_QA] = True         # every plant row depends on the internal recycle flow
    full[so5, I_KA + 1] = True         # tank 5 oxygen depends on the KLa5 actuator output
    return csc_matrix(full)

def clip(x, low, high):
    return min(max(x, low), high)

# Temperature, anchored so that 15 degrees Celsius reproduces the benchmark exactly. Each factor is theta ** (T - 15). The
# coefficients are TYPICAL literature values for ASM1 (nitrifier growth about 1.10, so that 10 and 20 degrees give roughly the
# ASM1 values 0.3 and 0.8 against 0.5 at 15), NOT calibrated to any works. Saturation constants are held fixed.
THETA = dict(mu_h=1.07, b_h=1.12, mu_a=1.10, b_a=1.07, k_a=1.07, k_h=1.10, kla=1.024)
T_REF = 15.0

@functools.lru_cache(maxsize=16384)
def temperature_factors(t_c):
    """(rate factors for the 8 ASM1 processes, oxygen transfer factor, oxygen saturation in g/m3) at t_c degrees Celsius."""
    d = t_c - T_REF
    f = {k: v ** d for k, v in THETA.items()}
    rate = np.array([f["mu_h"], f["mu_h"], f["mu_a"], f["b_h"], f["b_a"], f["k_a"], f["k_h"], f["k_h"]])
    return rate, f["kla"], SOSAT * _solubility(t_c) / _solubility(T_REF)

def _solubility(t_c):
    """Shape of oxygen solubility against temperature (Kelvin form used in the BSM2 documentation); only ratios are used."""
    t = (t_c + 273.15) / 100.0
    return float(np.exp(-66.7354 + 87.4755 / t + 24.4526 * np.log(t)))

def scaled_rates(tank, mu_a_scale, factors=None):
    r = rates(tank)
    if factors is not None:
        r = r * factors
    r[2] *= mu_a_scale
    return r

def make_rhs(ctrl, influent, noise, sc=Scenario(), temperature=None):
    """influent(t) -> (flow, 13 feed concentrations). noise: None, or (time, DO noise, NO noise) arrays;
    t is days from the start of the weather file. temperature: None or 15 (the benchmark), a constant in Celsius, or a
    function of t returning Celsius."""
    t_so = T_SO * sc.lag_scale
    benchmark = temperature is None or (not callable(temperature) and float(temperature) == T_REF)
    fixed = None if callable(temperature) or benchmark else temperature_factors(float(temperature))
    def rhs(t, y):
        q_in, raw = influent(t)
        if benchmark:
            tf, kla_f, sosat = None, 1.0, SOSAT
        else:
            tf, kla_f, sosat = fixed if fixed is not None else temperature_factors(float(temperature(t)))
        tanks = y[:65].reshape(5, 13)
        layers = y[65:NPLANT].reshape(10, 8)
        so_true, no_true = tanks[4, 7], tanks[1, 8]
        n_so = n_no = 0.0
        if noise is not None:
            n_so = 0.25 * sc.noise_scale * np.interp(t, noise[0], noise[1])
            n_no = 0.5 * sc.noise_scale * np.interp(t, noise[0], noise[2])
        so_meas = clip(y[I_DS + 1] + n_so + sc.do_bias, 0.0, 10.0)
        no_meas = clip(y[I_NS + 7] + n_no, 0.0, 20.0)
        # DO PI with back-calculation anti-windup
        so_set = ctrl.so_ref
        if ctrl.nh_gain:
            so_set = clip(ctrl.so_ref + ctrl.nh_gain * (tanks[4, 9] - ctrl.nh_ref), ctrl.so_min, ctrl.so_max)
        e = so_set - so_meas
        u = ctrl.kla_offset + ctrl.k_do * e + y[I_IDO]
        u_sat = clip(u, 0.0, ctrl.kla_max)
        d_ido = ctrl.k_do * e / ctrl.ti_do + (u_sat - u) / ctrl.tt_do
        # nitrate PI on the internal recycle
        e_q = ctrl.no_ref - no_meas
        v = ctrl.q_offset + ctrl.k_q * e_q + y[I_IQ]
        v_sat = clip(v, 0.0, ctrl.q_max)
        d_iq = ctrl.k_q * e_q / ctrl.ti_q + (v_sat - v) / ctrl.tt_q
        kla5 = y[I_KA + 1]
        q_a = max(y[I_QA], 0.0)
        qf, qe = q_in + RAS, q_in - WASTE
        last = tanks[4]
        mixed = (q_in * raw + q_a * last + RAS * plant.stream(layers[-1], last)) / (qf + q_a)
        inlets = np.vstack((mixed, tanks[:-1]))
        change = (qf + q_a) / VOLUME[:, None] * (inlets - tanks)
        change += np.stack([MATRIX @ scaled_rates(tank, sc.mu_a_scale, tf) for tank in tanks])
        kla = np.array([0.0, 0.0, 240.0, 240.0, kla5])
        change[:, 7] += sc.alpha_scale * kla_f * kla * (sosat - tanks[:, 7])
        out = np.empty(NSTATE)
        out[:65] = change.ravel()
        out[65:NPLANT] = settler(layers, last, qf, qe).ravel()
        out[I_DS] = (so_true - y[I_DS]) / t_so
        out[I_DS + 1] = (y[I_DS] - y[I_DS + 1]) / t_so
        out[I_KA] = (u_sat - y[I_KA]) / T_KLA
        out[I_KA + 1] = (y[I_KA] - y[I_KA + 1]) / T_KLA
        out[I_IDO] = d_ido
        out[I_NS] = (no_true - y[I_NS]) / T_NO
        out[I_NS + 1:I_NS + 8] = (y[I_NS:I_NS + 7] - y[I_NS + 1:I_NS + 8]) / T_NO
        out[I_QA] = (v_sat - y[I_QA]) / T_QA
        out[I_IQ] = d_iq
        return out
    return rhs

def initial_state(ctrl=Controller()):
    y = np.zeros(NSTATE)
    y[:NPLANT] = plant.initial_state()
    y[I_DS:I_DS + 2] = 1.0
    y[I_KA:I_KA + 2] = ctrl.kla_offset
    y[I_NS:I_NS + 8] = 1.0
    y[I_QA] = 3 * Q0
    return y

def integrate(rhs, y0, t0, t1, rtol=1e-6, atol=1e-8, t_eval=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sol = solve_ivp(rhs, (t0, t1), y0, method="BDF", rtol=rtol, atol=atol,
                        jac_sparsity=jacobian_pattern(), t_eval=t_eval)
    if not sol.success or not np.isfinite(sol.y).all():
        raise RuntimeError(f"BSM1 closed loop failed: {sol.message}")
    return sol

def stabilise(ctrl=Controller(), days=100.0, **solver):
    """Closed loop with constant influent and no sensor noise, as the BSM1 protocol requires."""
    rhs = make_rhs(ctrl, lambda t: (Q0, plant.RAW), None)
    return integrate(rhs, initial_state(ctrl), 0.0, days, **solver).y[:, -1]

def stabilise_at(ctrl, flow, feed, days=100.0, scenario=Scenario(), temperature=None, **solver):
    """Closed loop steady state for a constant influent (flow m3/d, 13 concentrations): the start of a site replay."""
    rhs = make_rhs(ctrl, lambda t: (flow, np.asarray(feed, dtype=float)), None, scenario, temperature)
    return integrate(rhs, initial_state(ctrl), 0.0, days, **solver).y[:, -1]

def run_series(ctrl, flow, feed, y0, step_days=1 / 96, scenario=Scenario(), mode="fast", temperature=None, **solver):
    """Run any influent series: flow[k] (m3/d) and feed[k] (13 concentrations) are held over [k, k+1) * step_days.
    temperature: None or 15 (benchmark), a constant, or an array with one Celsius value per record.
    Returns samples with columns (time in days, flow, 160 states), one row per record start, ideal sensors."""
    solver = {**MODES[mode], **solver}
    flow, feed = np.asarray(flow, dtype=float), np.asarray(feed, dtype=float)
    last = len(flow) - 1
    def influent(t):
        k = min(int(t / step_days + 1e-9), last)
        return flow[k], feed[k]
    grid = np.arange(len(flow)) * step_days
    if temperature is not None and np.ndim(temperature) > 0:
        series = np.asarray(temperature, dtype=float)
        if np.all(series == series[0]):
            temperature = float(series[0])                              # constant: no per-step work
        else:
            temperature = lambda t: float(series[min(int(t / step_days + 1e-9), last)])
    sol = integrate(make_rhs(ctrl, influent, None, scenario, temperature), np.asarray(y0, dtype=float), 0.0, len(flow) * step_days,
                    t_eval=grid, **solver)
    return np.column_stack([grid, flow, sol.y.T])

def effluent(y):
    tanks = y[:65].reshape(5, 13)
    layers = y[65:NPLANT].reshape(10, 8)
    return plant.stream(layers[0], tanks[4])

def apply_return_liquor(feed, flow, sc):
    """Mix a six hour ammonia pulse (800 g N/m3 liquor, a typical digestate strength) into the influent."""
    feed, flow = feed.copy(), flow.copy()
    if sc.return_liquor_kg <= 0:
        return feed, flow
    first = int(round((sc.return_liquor_day + 8 / 24) * 96))
    records = np.arange(first, first + 24)
    liquor_flow = sc.return_liquor_kg * 1000 / 24 / 800 * 96          # m3/d during each 15 minute record
    for k in records:
        total = flow[k] + liquor_flow
        feed[k] = feed[k] * flow[k] / total
        feed[k, 9] += 800 * liquor_flow / total
        flow[k] = total
    return feed, flow

def run(ctrl=Controller(), scenario=Scenario(), y0=None, segments=False, mode="fast", **solver):
    """Run one 14 day weather file. Returns 15 minute samples (days 0 to 14; evaluation uses days 7 to 14).

    The influent is held constant over each 15 minute record. By default one stiff solve covers the whole
    file; segments=True restarts the solver at every record (slower, used to cross-check)."""
    solver = {**MODES[mode], **solver}
    started = time.perf_counter()
    t_in, feed, flow = weather(scenario.weather)
    feed, flow = apply_return_liquor(feed, flow, scenario)
    y = standard_start() if y0 is None else np.array(y0)
    nz = sensor_noise(scenario.noise_shift) if scenario.noise_scale > 0 else None
    last = len(flow) - 1
    def influent(t):
        k = min(int(t * 96 + 1e-9), last)
        return flow[k], feed[k]
    grid = np.arange(len(t_in)) / 96
    if segments:
        samples = []
        for k in range(len(t_in)):
            samples.append(np.r_[t_in[k], flow[k], y])
            end = t_in[k + 1] if k + 1 < len(t_in) else 14.0
            y = integrate(make_rhs(ctrl, influent, nz, scenario), y, t_in[k], end, **solver).y[:, -1]
        samples = np.array(samples)
    else:
        sol = integrate(make_rhs(ctrl, influent, nz, scenario), y, 0.0, 14.0, t_eval=grid, **solver)
        samples = np.column_stack([grid, flow, sol.y.T])
    return dict(samples=samples, controller=ctrl, scenario=scenario, seconds=time.perf_counter() - started)

START = Path(__file__).resolve().parent.parent / "data" / "bsm1_start_dry.npy"

def standard_start(refresh=False):
    """BSM1 protocol: constant influent closed loop (ideal sensors), then one noisy 14 day dry weather run,
    whose final state starts every evaluated run. Always uses the default controller and the full solver
    mode. Cached on disk."""
    if START.exists() and not refresh:
        return np.load(START)
    ctrl = Controller()
    y = stabilise(ctrl, **MODES["full"])
    y = run(ctrl, Scenario(), y0=y, mode="full")["samples"][-1, 2:]
    START.parent.mkdir(exist_ok=True)
    tmp = START.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp.npy")
    np.save(tmp, y)
    os.replace(tmp, START)        # atomic: parallel workers never read a partial file
    return y

def fingerprint():
    """Identifies every input that is not in a scenario or a controller: model version, solver modes and the
    standard start state. Part of the results cache key."""
    h = hashlib.sha256(f"{MODEL_VERSION}|{sorted(MODES.items())}".encode())
    h.update(np.asarray(standard_start(), dtype=float).tobytes())
    return h.hexdigest()[:16]

def indices(result, start=7.0):
    """BSM1 effluent quality, aeration energy and violation indices over days start to 14 (perf_plant.m)."""
    s = result["samples"]
    s = s[s[:, 0] >= start - 1e-9]
    dt = 1 / 96
    total = len(s) * dt
    eff = np.array([effluent(row[2:]) for row in s])
    qe = s[:, 1] - WASTE
    ss, xi, xs, bh, ba, xp = eff[:, 1], eff[:, 2], eff[:, 3], eff[:, 4], eff[:, 5], eff[:, 6]
    snh, sno, snd, xnd, si = eff[:, 9], eff[:, 8], eff[:, 10], eff[:, 11], eff[:, 0]
    tss = .75 * (xs + xi + bh + ba + xp)
    cod = si + ss + xi + xs + bh + ba + xp
    snkj = snh + snd + xnd + I_XB * (bh + ba) + I_XP * (xp + xi)
    total_n = sno + snkj
    bod5 = .25 * (ss + xs + (1 - F_P) * (bh + ba))
    eqi = np.sum((2 * tss + cod + 30 * snkj + 10 * sno + 2 * bod5) * qe * dt) / (total * 1000)
    kla5 = s[:, 2 + I_KA + 1]
    kla = np.stack([np.zeros(len(s)), np.zeros(len(s)), np.full(len(s), 240.), np.full(len(s), 240.), kla5], axis=1)
    ae = float(np.mean((SOSAT * kla * VOLUME).sum(axis=1) / (1.8 * 1000)))
    series = dict(total_n=total_n, total_cod=cod, snh=snh, tss=tss, bod5=bod5)
    over = {k: float(np.mean(v > LIMITS[k])) for k, v in series.items()}
    so5 = s[:, 2 + 52 + 7]
    return dict(eqi=float(eqi), aeration_energy_kwh_d=ae, share_over_limit=over,
                low_do_share=float(np.mean(so5 < 0.5)),
                average=dict(snh=float(np.mean(snh)), total_n=float(np.mean(total_n)), tss=float(np.mean(tss)),
                             cod=float(np.mean(cod)), bod5=float(np.mean(bod5))),
                p95=dict(snh=float(np.percentile(snh, 95)), total_n=float(np.percentile(total_n, 95)),
                         tss=float(np.percentile(tss, 95))),
                samples=len(s), days=total)

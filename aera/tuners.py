"""Reference tuners. Each is `tuner(env) -> params` and may use at most env.budget trials.

Bring your own: write a function with this signature and run
    python -m aera.run_benchmark --tuner mymodule:mytuner
"""
import importlib
from dataclasses import replace
import numpy as np
from scipy.optimize import differential_evolution
from . import bsm1_dynamic as dyn
from .benchmark import DEFAULT, BudgetExceeded, fitness, scenario_for, TRAIN

LOG = {"k_do", "ti_do"}

def encode(params, bounds):
    out = []
    for k in bounds:
        lo, hi = bounds[k]
        v = params[k]
        out.append((np.log(v) - np.log(lo)) / (np.log(hi) - np.log(lo)) if k in LOG else (v - lo) / (hi - lo))
    return np.clip(out, 0, 1)

def decode(x, bounds):
    out = {}
    for k, u in zip(bounds, np.clip(x, 0, 1)):
        lo, hi = bounds[k]
        out[k] = float(np.exp(np.log(lo) + u * (np.log(hi) - np.log(lo)))) if k in LOG else float(lo + u * (hi - lo))
    return out

def default_controller(env):
    """The BSM1 default settings, no tuning."""
    return dict(env.default)

def random_search(env, seed=0):
    rng = np.random.default_rng(seed)
    while env.used < env.budget:
        env.trial(decode(rng.random(len(env.bounds)), env.bounds))
    return env.best()

def differential(env, seed=0):
    rng = np.random.default_rng(seed)
    size = 8
    n = len(env.bounds)
    init = rng.random((size, n))
    generations = max((env.budget - env.used - size) // size, 0)
    def objective(x):
        return fitness(env.trial(decode(x, env.bounds)))
    try:
        differential_evolution(objective, [(0, 1)] * n, init=init, maxiter=generations, polish=False,
                               tol=0, seed=int(rng.integers(1 << 31)), updating="immediate")
    except BudgetExceeded:
        pass
    return env.best()

def _gp_posterior(x, y, cand, length=0.35, noise=1e-4):
    def kern(a, b):
        d = ((a[:, None, :] - b[None, :, :]) ** 2).sum(-1)
        return np.exp(-0.5 * d / length ** 2)
    k = kern(x, x) + noise * np.eye(len(x))
    ks = kern(cand, x)
    chol = np.linalg.cholesky(k)
    alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, y))
    mean = ks @ alpha
    v = np.linalg.solve(chol, ks.T)
    var = np.clip(1.0 - (v ** 2).sum(0), 1e-12, None)
    return mean, np.sqrt(var)

def bayesian(env, seed=0, initial=8):
    """Gaussian process with expected improvement on log fitness."""
    from math import erf, sqrt, pi
    rng = np.random.default_rng(seed)
    xs, ys = [], []
    def observe(x):
        t = env.trial(decode(x, env.bounds))
        xs.append(np.array(x))
        ys.append(np.log(fitness(t)))
    for _ in range(min(initial, env.budget - env.used)):
        observe(rng.random(len(env.bounds)))
    while env.used < env.budget:
        y = np.array(ys)
        mu, sd = y.mean(), y.std() or 1.0
        z = (y - mu) / sd
        cand = rng.random((3000, len(env.bounds)))
        mean, std = _gp_posterior(np.array(xs), z, cand)
        best = z.min()
        gap = best - mean
        u = gap / std
        cdf = 0.5 * (1 + np.vectorize(erf)(u / sqrt(2)))
        pdf = np.exp(-0.5 * u ** 2) / sqrt(2 * pi)
        observe(cand[int(np.argmax(gap * cdf + std * pdf))])
    return env.best()

def fopdt(grid, resp, step):
    """First order plus dead time fit of a step response by Smith's two point method (28.3% and 63.2% times)."""
    gain = resp[-1] / step
    t28, t63 = np.interp([0.283, 0.632], resp / resp[-1], grid)
    tau = max(1.5 * (t63 - t28), 1e-4)       # time constant
    dead = max(t63 - tau, 1e-4)              # dead time
    return dict(gain=float(gain), dead=float(dead), tau=float(tau))

def step_test(plant):
    """Open loop KLa5 step from the BSM1 steady state. Returns process gain, dead time and time constant."""
    ctrl = dyn.Controller()
    y0 = dyn.stabilise(ctrl, **dyn.MODES["full"])
    sc = scenario_for(plant, replace(TRAIN["dry"], noise_scale=0.0))
    hold = replace(ctrl, k_do=0.0)
    rhs = dyn.make_rhs(hold, lambda t: (dyn.Q0, dyn.plant.RAW), None, sc)
    grid = np.linspace(0, 0.04, 801)
    step = 10.0
    y1 = y0.copy()
    y1[dyn.I_IDO] += step
    drift = dyn.integrate(rhs, y0, 0.0, 0.04, t_eval=grid, **dyn.MODES["full"]).y[52 + 7]
    resp = dyn.integrate(rhs, y1, 0.0, 0.04, t_eval=grid, **dyn.MODES["full"]).y[52 + 7] - drift
    return fopdt(grid, resp, step)

def ziegler_nichols(env):
    """Ziegler-Nichols reaction curve PI rule from one open loop step test: Kc = 0.9 T / (K L), Ti = 3.33 L, where K is
    the process gain, T the time constant and L the dead time. The step test is charged as 2 trials and the
    confirming trial as 1, so a run uses 3 trials."""
    env.charge(2)
    st = step_test(env.plant)
    kc = 0.9 * st["tau"] / (st["gain"] * st["dead"])
    params = dict(env.default, k_do=kc, ti_do=3.33 * st["dead"])
    env.trial(params)
    return params

TUNERS = {"bsm1_default": default_controller, "random_search": random_search,
          "differential_evolution": differential, "bayesian_optimisation": bayesian,
          "ziegler_nichols": ziegler_nichols}

def load_tuner(spec):
    """Resolve a built-in name or 'module:function'."""
    if spec in TUNERS:
        return TUNERS[spec]
    module, _, name = spec.partition(":")
    return getattr(importlib.import_module(module), name)

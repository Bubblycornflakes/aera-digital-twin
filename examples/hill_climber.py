"""Example plug-in tuner: coordinate hill climbing from the BSM1 default.

    python -m aera.run_benchmark --tuner examples.hill_climber:hill_climber --seeds 1

A tuner is any function `tuner(env) -> params`. `env.trial(params)` runs the training scenario and returns
metrics, feasibility and a trajectory. Stop when `env.used` reaches `env.budget`. `env.bounds` gives the allowed
range of every parameter and `env.default` the BSM1 default settings.
"""
import numpy as np
from aera.benchmark import fitness

def hill_climber(env, seed=0):
    rng = np.random.default_rng(seed)
    best = dict(env.default)
    best_trial = env.trial(best)
    step = 0.25                                   # fraction of each parameter's range
    while env.used < env.budget:
        key = rng.choice(list(env.bounds))
        lo, hi = env.bounds[key]
        candidate = dict(best)
        candidate[key] = float(np.clip(best[key] + rng.normal(0, step) * (hi - lo), lo, hi))
        trial = env.trial(candidate)
        if fitness(trial) < fitness(best_trial):
            best, best_trial = candidate, trial
        else:
            step = max(step * 0.95, 0.02)
    return best

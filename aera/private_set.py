"""A private held-out set for AeroBench, with commit-reveal so results can be verified later.

Why: the public held-out scenarios are in this repository, so anyone can tune against them. A private set is generated from a secret
seed that only the maintainer knows. The maintainer scores submitted answers on it and publishes the scores, plus a commitment (the
SHA-256 of the seed). After a round, revealing the seed lets anyone regenerate the set, check it matches the commitment, and
reproduce the scores. Until then the scenarios cannot be reconstructed.

    python -m aera.private_set generate --seed-file secret_seed.txt --out private_set.json     # keep both files private
    python -m aera.rescore --held-out private_set.json                                          # score stored answers on it
    python -m aera.private_set verify --seed-file secret_seed.txt --set private_set.json        # anyone, after the reveal

What this does not do: a tuner run on the same machine can read private_set.json (see the integrity note in docs/AEROBENCH.md), and
the set is only as secret as the seed. The generator's ranges are public, so a tuner can be robust to them, which is the point."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
from . import benchmark as bench, bsm1_dynamic as dyn

VERSION = 1
N_SCENARIOS, N_PLANTS = 6, 3
WEATHER = ("dry", "rain", "storm")
RANGES = dict(return_liquor_kg=(60.0, 200.0), return_liquor_day=(7.2, 12.5), noise_scale=(0.5, 3.0), do_bias=(-0.5, 0.5),
              lag_scale=(1.0, 8.0), noise_shift=(0.0, 13.0), alpha_scale=(0.6, 1.05), mu_a_scale=(0.7, 1.15))

def commitment(seed):
    return hashlib.sha256(str(seed).encode()).hexdigest()

def generate(seed, n_scenarios=N_SCENARIOS, n_plants=N_PLANTS):
    """Deterministic: the same seed always gives the same set. Returns a JSON-serialisable dictionary."""
    rng = np.random.default_rng(int(hashlib.sha256(f"aerobench-private-set-v{VERSION}:{seed}".encode()).hexdigest()[:16], 16))
    u = lambda key: float(rng.uniform(*RANGES[key]))
    scenarios = {}
    for i in range(n_scenarios):
        weather = WEATHER[i % len(WEATHER)]                                       # every weather file appears
        liquor = u("return_liquor_kg") if rng.random() < 0.6 else 0.0
        faulty = rng.random() < 0.6
        scenarios[f"private_{i + 1}"] = dict(weather=weather, return_liquor_kg=round(liquor, 1), return_liquor_day=round(u("return_liquor_day"), 2) if liquor else 9.0,
                                             noise_scale=round(u("noise_scale") if faulty else 1.0, 2), do_bias=round(u("do_bias") if faulty else 0.0, 2),
                                             lag_scale=round(u("lag_scale") if faulty else 1.0, 2), noise_shift=float(round(u("noise_shift"))))
    plants = {f"private_plant_{i + 1}": dict(alpha_scale=round(u("alpha_scale"), 3), mu_a_scale=round(u("mu_a_scale"), 3)) for i in range(n_plants)}
    return dict(version=VERSION, commitment=commitment(seed), scenarios=scenarios, plants=plants)

def label(spec):
    """Short identifier recorded with every result scored on the set."""
    body = json.dumps(dict(scenarios=spec["scenarios"], plants=spec["plants"]), sort_keys=True)
    return f"private:{spec['commitment'][:8]}:{hashlib.sha256(body.encode()).hexdigest()[:6]}"

def load(path):
    """Read a private set file into (scenarios, plants, label) ready for bench.score."""
    spec = json.loads(Path(path).read_text())
    if spec.get("version") != VERSION:
        raise ValueError(f"unsupported private set version {spec.get('version')}")
    scenarios = {name: dyn.Scenario(**s) for name, s in spec["scenarios"].items()}
    plants = {name: bench.Plant(name, **p) for name, p in spec["plants"].items()}
    return scenarios, plants, label(spec)

def verify(seed, path):
    """True if the set in `path` is exactly what `seed` generates and matches its commitment."""
    spec = json.loads(Path(path).read_text())
    n_s, n_p = len(spec["scenarios"]), len(spec["plants"])
    return generate(seed, n_s, n_p) == spec

def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m aera.private_set", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate"); g.add_argument("--seed-file", required=True); g.add_argument("--out", required=True)
    g.add_argument("--scenarios", type=int, default=N_SCENARIOS); g.add_argument("--plants", type=int, default=N_PLANTS)
    v = sub.add_parser("verify"); v.add_argument("--seed-file", required=True); v.add_argument("--set", required=True)
    a = p.parse_args(argv)
    seed = Path(a.seed_file).read_text().strip()
    if a.cmd == "generate":
        if len(seed) < 16:
            print("The seed is too short to be secret: use at least 16 characters (for example the output of `openssl rand -hex 16`).", file=sys.stderr)
            return 2
        spec = generate(seed, a.scenarios, a.plants)
        Path(a.out).write_text(json.dumps(spec, indent=1))
        print(f"Wrote {a.out}. Publish this commitment, keep the seed and the file private:\n  {spec['commitment']}")
        return 0
    ok = verify(seed, a.set)
    print("MATCH: the set is exactly what this seed generates, and the commitment agrees." if ok else "MISMATCH: this seed does not generate this set.")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())

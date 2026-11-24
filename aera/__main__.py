import argparse
import json
from .model import Settings, simulate
parser = argparse.ArgumentParser(description="Run an AERA basin experiment")
parser.add_argument("--hours", type=int, default=24)
parser.add_argument("--storm", action="store_true")
parser.add_argument("--returns", action="store_true")
print(json.dumps(simulate(Settings(**vars(parser.parse_args())))))

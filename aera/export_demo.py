"""Write results/runs and the leaderboard into the frontend as a static snapshot, so the Agent trials page works
without the API (for example on a static host).

    python -m aera.export_demo
"""
import json
from pathlib import Path
from .aerobench_api import load_runs
from .leaderboard import build

TARGET = Path(__file__).resolve().parent.parent / "frontend" / "src" / "aerobench-results.json"
SITE_SOURCE = Path(__file__).resolve().parent.parent / "results" / "site" / "demo_calibrated" / "shadow_report" / "report.json"
SITE_TARGET = Path(__file__).resolve().parent.parent / "frontend" / "src" / "site-demo-report.json"

if __name__ == "__main__":
    TARGET.write_text(json.dumps(dict(leaderboard=build(), runs=load_runs()), separators=(",", ":")))
    print("wrote", TARGET)
    if SITE_SOURCE.exists():                      # the synthetic works report shown by the Shadow mode page
        SITE_TARGET.write_text(SITE_SOURCE.read_text())
        print("wrote", SITE_TARGET)

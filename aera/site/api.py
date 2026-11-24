"""Read-only endpoint for the Shadow mode page: serves the newest report.json found under results/site/ (or AERA_SITE_REPORT)."""
import json
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/site")
ROOT = Path(__file__).resolve().parent.parent.parent / "results" / "site"

def latest():
    env = os.environ.get("AERA_SITE_REPORT")
    if env and Path(env).exists():
        return Path(env)
    found = sorted(ROOT.glob("**/report.json"), key=lambda p: p.stat().st_mtime) if ROOT.exists() else []
    return found[-1] if found else None

@router.get("/report")
def report():
    path = latest()
    if path is None:
        raise HTTPException(404, "No shadow mode report yet. Run: python -m aera.site demo --out results/site/demo")
    return json.loads(path.read_text())

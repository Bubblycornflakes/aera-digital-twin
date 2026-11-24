"""Read-only endpoints for the Agent trials page. Results come from results/runs/*.json."""
import json
from fastapi import APIRouter
from .leaderboard import ROOT, build

router = APIRouter(prefix="/api/aerobench")

def load_runs():
    return [json.loads(p.read_text()) for p in sorted((ROOT / "runs").glob("*.json"))]

@router.get("/results")
def results():
    return dict(leaderboard=build(), runs=load_runs())

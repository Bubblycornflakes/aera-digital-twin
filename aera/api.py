from fastapi import FastAPI
from .model import Settings, simulate, reference
from .aerobench_api import router as aerobench_router
from .site.api import router as site_router

app = FastAPI(title="AERA", version="0.1.0")
app.include_router(aerobench_router)
app.include_router(site_router)
@app.get("/api/reference")
def baseline():
    return reference()

@app.post("/api/simulation")
def run(config: Settings):
    return simulate(config)

@app.post("/api/asm1/benchmark")
def benchmark():
    from .bsm1 import simulate as verify
    return verify()

from pydantic import BaseModel, ConfigDict, Field
from .process_playback import playback

class ProcessSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    command: float = Field(.35,ge=0,le=1)
    pulse: bool = True

@app.post("/api/asm1/playback")
def process_run(config: ProcessSettings):
    return playback(config.command,config.pulse)

# Serve the built frontend when present (used by the Docker image).
from pathlib import Path
from fastapi.staticfiles import StaticFiles
_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")

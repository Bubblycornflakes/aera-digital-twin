"""Illustrative single basin. Time in hours, concentrations mg/L as O2 or N."""
from datetime import datetime, timezone
from math import cos, pi
import numpy as np
from scipy.integrate import solve_ivp
from pydantic import BaseModel, ConfigDict, Field

class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    hours: int = Field(24, ge=1, le=72)
    volume: float = Field(2000, ge=500, le=8000)
    alpha: float = Field(.7, ge=.4, le=.9)
    beta: float = Field(.93, ge=.9, le=.95)
    target: float = Field(2, ge=.5, le=5)
    kp: float = Field(.12, ge=0, le=2)
    ki: float = Field(.8, ge=0, le=5)
    kd: float = Field(0, ge=0, le=.1)
    storm: bool = False
    returns: bool = False
    bias: float = Field(0, ge=-1, le=1)
    noise: float = Field(0, ge=0, le=.5)
    seed: int = Field(42, ge=0)

def reference():
    flow = 150000 * .225 * 365
    site = flow * .64
    air, pump = site*.55, site*.12
    saving = air*.2 + pump*.15
    return dict(flow_m3=flow, site_kwh=site, aeration_kwh=air, pumping_kwh=pump,
                cost_gbp=site*.25, scope2_t=site*.13096/1000, saving_kwh=saving,
                saving_gbp=saving*.25, return_kwh=150000*.011*365*.18*2.03)

def loads(t, cfg):
    phase = t % 24
    daily = 1 + .17*cos(2*pi*(phase-8)/24) + .12*cos(4*pi*(phase-8)/24)
    flow = 150000*.225/24/4 * daily
    ammonia = 22*daily
    if cfg.storm and 12 <= phase < 18:
        flow *= 1.4
        ammonia *= .75
    if cfg.returns and 9 <= phase < 15:
        # One quarter of the site's daily return N, delivered over six hours.
        kg_h = 150000*.011*.18/4/6
        liquor_flow = kg_h*1000/800
        ammonia = (flow*ammonia + kg_h*1000)/(flow+liquor_flow)
        flow += liquor_flow
    return flow, ammonia, daily

def rates(y, u, load, cfg):
    do, n = np.maximum(y, 0)
    flow, inlet, daily = load
    dilution = flow/cfg.volume
    reaction = 6*n/(1+n)*do/(.5+do)
    transfer = 12*cfg.alpha*u*(cfg.beta*9.1-do)
    demand = 9*daily*do/(.25+do) + 4.57*reaction
    return [transfer + dilution*(.5-do)-demand, dilution*(inlet-n)-reaction]

def control(error, previous, integral, dt, cfg):
    base = .4 + cfg.kp*error + cfg.kd*(error-previous)/dt
    trial = integral + cfg.ki*error*dt
    if (base+trial > 1 and error>0) or (base+trial < 0 and error<0):
        trial = integral
    return float(np.clip(base+trial,0,1)), trial

def simulate(cfg, tolerance=1e-6):
    rng = np.random.default_rng(cfg.seed)
    step = 1/60
    state = [2., 2.]
    previous = cfg.target-state[0]
    integral = energy = 0.
    records = []
    for minute in range(cfg.hours*60+1):
        t = minute/60
        load = loads(t,cfg)
        error = cfg.target-(state[0]+cfg.bias+rng.normal(0,cfg.noise))
        u, integral = control(error, previous, integral, step, cfg)
        previous = error
        power = 0 if u==0 else 12 + 118*u**1.4
        records.append(dict(hour=t, do=float(state[0]), nh4=float(state[1]), airflow=u,
                            power_kw=power, energy_kwh=energy, flow_m3h=load[0], inlet_n=load[1]))
        if minute < cfg.hours*60:
            solution = solve_ivp(lambda _, y: rates(y,u,load,cfg), (0,step),state,
                                 rtol=tolerance, atol=tolerance*.01)
            if not solution.success:
                raise RuntimeError(solution.message)
            state = solution.y[:,-1]
            energy += power*step
    return dict(version="0.1.0", timestamp=datetime.now(timezone.utc).isoformat(),
                settings=cfg.model_dump(), solver=dict(method="RK45",rtol=tolerance,
                atol=tolerance*.01,sample_seconds=60), records=records)

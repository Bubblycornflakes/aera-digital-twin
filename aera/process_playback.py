"""Scenario playback, conditional on BSM1 biology. Equipment is a separate illustrative configuration."""
from functools import lru_cache
import numpy as np
from . import bsm1 as plant

@lru_cache(maxsize=1)
def warm_state():
    solution,_=plant.integrate(plant.initial_state(),150)
    return tuple(solution.y[:,-1])

def playback(command=.35, pulse=True):
    # Fixed-flow controller on R5; anoxic R1/2 and fixed R3/4 aeration.
    fractions=np.array([0,0,1,1,command])
    kla=240*fractions
    # Design free-air volume at max command obtained from zero-DO process OTR,
    # 0.28 kg O2/m³ intake air and illustrative 20% transfer efficiency.
    air=kla*8/1000*plant.VOLUME/24/(.28*.20)
    pressure_ratio=(101325+55000)/101325
    power=air/3600*101325*(1.4/.4)*(pressure_ratio**(.4/1.4)-1)/(.72*.94)/1000
    state=np.array(warm_state())
    records=[]
    diagnostics=[]
    for start,end,factor in [(0,8,1),(8,12,1.5 if pulse else 1),(12,24,1)]:
        feed=plant.RAW.copy()
        feed[9]*=factor
        sol,stats=plant.integrate(state,(end-start)/24,raw=feed,kla=kla,dense=True)
        diagnostics.append(stats)
        for minute in range(60*start,60*end+(1 if end==24 else 0),5):
            y=sol.sol((minute/60-start)/24)
            if not np.isfinite(y).all() or y.min() < -1e-8:
                raise RuntimeError("Invalid interpolated ASM1 sample")
            tanks=y[:65].reshape(5,13)
            layers=y[65:].reshape(10,8)
            records.append(dict(minute=minute,do=tanks[:,7].tolist(),nh4=tanks[:,9].tolist(),
                                effluent_nh4=float(layers[0,5]),effluent_tss=float(layers[0,0]),
                                energy_kwh=(power*minute/60).tolist()))
        state=sol.y[:,-1]
    return dict(model="BSM1 · fixed 15°C parameters",records=records,air_m3h=air.tolist(),
                power_kw=power.tolist(),command=fractions.tolist(),volume=plant.VOLUME.tolist(),
                kla_day=kla.tolist(),internal=plant.INTERNAL,ras=plant.RAS,waste=plant.WASTE,
                effluent_flow=plant.EFF,train_flow=plant.FEED+plant.INTERNAL,
                pulse=pulse,diagnostics=diagnostics)

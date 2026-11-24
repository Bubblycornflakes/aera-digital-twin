"""Fixed-temperature BSM1 biology. State units and sources in SCIENTIFIC_REFERENCE_REGISTER."""
import numpy as np
from scipy.integrate import solve_ivp

STATES = ("SI","SS","XI","XS","XBH","XBA","XP","SO","SNO","SNH","SND","XND","SALK")
PROCESSES = ("aerobic_H","anoxic_H","aerobic_A","decay_H","decay_A","ammonification","hydrolysis_C","hydrolysis_N")
YH, YA, FP, IXB, IXP = .67, .24, .08, .08, .06
DENIT = (1-YH)/(2.86*YH)
# Rows follow STATES; columns follow PROCESSES. Alkalinity in mol/m³.
MATRIX = np.array([
 [0]*8,
 [-1/YH,-1/YH,0,0,0,0,1,0],
 [0]*8,
 [0,0,0,1-FP,1-FP,0,-1,0],
 [1,1,0,-1,0,0,0,0],
 [0,0,1,0,-1,0,0,0],
 [0,0,0,FP,FP,0,0,0],
 [-(1-YH)/YH,0,-(4.57-YA)/YA,0,0,0,0,0],
 [0,-DENIT,1/YA,0,0,0,0,0],
 [-IXB,-IXB,-IXB-1/YA,0,0,1,0,0],
 [0,0,0,0,0,-1,0,1],
 [0,0,0,IXB-FP*IXP,IXB-FP*IXP,0,0,-1],
 [-IXB/14,(DENIT-IXB)/14,-IXB/14-1/(7*YA),0,0,1/14,0,0],
])
MATRIX.setflags(write=False)

def rates(state):
    """Volumetric rates per day, using positive activities during implicit solver iterations."""
    _, ss, _, xs, bh, ba, _, oxygen, no, nh, nd, xnd, _ = np.maximum(state, 0.)
    aerobic = oxygen/(.2+oxygen)
    anoxic = .2/(.2+oxygen)*no/(.5+no)
    growth = 4*bh*ss/(10+ss)
    # Algebraically cancel XS in hydrolysis_N; zero at a biomass-free boundary.
    hydro = 3*bh*(aerobic+.8*anoxic)/(.1*bh+xs) if bh>0 else 0.
    return np.array([growth*aerobic,growth*.8*anoxic,.5*ba*nh/(1+nh)*oxygen/(.4+oxygen),
                     .3*bh,.05*ba,.05*nd*bh,hydro*xs,hydro*xnd])

def reactor(initial, inlet, *, flow, volume, kla, days, rtol=1e-8, atol=1e-10):
    """One constant-volume CSTR with constant feed, prescribed process kLa /day and BSM1 saturation."""
    initial, inlet = (np.asarray(x,dtype=float) for x in (initial,inlet))
    for x in (initial,inlet):
        if x.shape!=(13,) or not np.all(np.isfinite(x)) or np.any(x<0):
            raise ValueError("Expected 13 finite nonnegative concentrations")
    if not np.all(np.isfinite([flow,volume,kla,days,rtol,atol])) or min(volume,days,rtol,atol)<=0 or min(flow,kla)<0:
        raise ValueError("Invalid hydraulics, duration or tolerance")
    def rhs(_, y):
        change = flow/volume*(inlet-y) + MATRIX @ rates(y)
        change[7] += kla*(8-y[7])
        return change
    result = solve_ivp(rhs,(0,days),initial,method="BDF",rtol=rtol,atol=atol)
    if not result.success or not np.isfinite(result.y).all() or result.y.min() < -10*atol:
        raise RuntimeError("Integration failed or left the physical concentration domain")
    return result

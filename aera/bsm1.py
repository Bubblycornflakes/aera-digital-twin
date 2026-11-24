"""BSM1 constant-influent open-loop plant. Days, m³/day, g/m³, mol/m³."""
import json
import time
import warnings
import numpy as np
from scipy.integrate import solve_ivp
from scipy.sparse import csc_matrix
from .asm1 import MATRIX, STATES, rates

RAW = np.array([30,69.5,51.2,202.32,28.17,0,0,0,0,31.56,6.95,10.59,7.])
SOLUBLE = [0,1,7,8,9,10,12]
PARTICLE = [2,3,4,5,6,11]
VOLUME = np.array([1000,1000,1333,1333,1333])
KLA = np.array([0,0,240,240,84])
Q, INTERNAL, RAS, WASTE = 18446.,55338.,18446.,385.
FEED, UNDER, EFF = Q+RAS, RAS+WASTE, Q-WASTE
AREA, HEIGHT = 1500., .4

def tss(state):
    return .75*sum(state[2:7])

def settler(layers, feed):
    """Columns: TSS, then seven soluble states. Positive flux points downwards."""
    mass = np.r_[tss(feed),feed[SOLUBLE]]
    x = np.maximum(layers[:,0],0)
    excess = np.maximum(x-.00228*mass[0],0)
    velocity = np.minimum(250.,474*(np.exp(-.000576*excess)-np.exp(-.00286*excess)))
    downward = velocity*x
    settling = np.minimum(downward[:-1],downward[1:])
    settling[:4] = np.where(x[1:5]<=3000,downward[:4],settling[:4])
    flux = np.vstack((-EFF*layers[:5],UNDER*layers[4:]))/AREA
    flux[1:-1,0] += settling
    change = -np.diff(flux,axis=0)
    change[4] += FEED/AREA*mass
    return change/HEIGHT

def stream(layer, feed):
    result = feed.copy()
    total = tss(feed)
    result[PARTICLE] *= layer[0]/total if total>0 else 0
    result[SOLUBLE] = layer[1:]
    return result

def balances(_, state, raw=RAW, kla=KLA):
    tanks = state[:65].reshape(5,13)
    layers = state[65:].reshape(10,8)
    last = tanks[-1]
    mixed = (Q*raw+INTERNAL*last+RAS*stream(layers[-1],last))/(FEED+INTERNAL)
    inlets = np.vstack((mixed,tanks[:-1]))
    change = (FEED+INTERNAL)/VOLUME[:,None]*(inlets-tanks)
    change += np.stack([MATRIX@rates(tank) for tank in tanks])
    change[:,7] += kla*(8-tanks[:,7])
    return np.r_[change.ravel(),settler(layers,last).ravel()]

def initial_state():
    # Positive synthetic seed, independent of benchmark outlet fixtures.
    seed = RAW.copy()
    seed[[4,5,7]]=[1500,80,1]
    return np.r_[np.tile(seed,5),np.tile(np.r_[1500,seed[SOLUBLE]],10)]


def jacobian_pattern():
    # Five tank blocks, downstream advection, upstream recycles, and nearest-neighbour settler flux.
    mask=np.zeros((145,145),dtype=bool)
    for i in range(5):
        mask[13*i:13*i+13,13*max(0,i-1):13*i+13]=True
    mask[:13,52:65]=True
    mask[:13,-8:]=True
    mask[65:,52:65]=True
    for i in range(10):
        mask[65+8*i:73+8*i,65+8*max(i-1,0):65+8*min(i+2,10)]=True
    return csc_matrix(mask)

def integrate(initial, days, *, method="BDF", rtol=1e-7, atol=1e-9, raw=RAW, kla=KLA, dense=False):
    if method not in ("BDF", "Radau") or not np.isfinite([days,rtol,atol]).all() or min(days,rtol,atol)<=0:
        raise ValueError("Invalid stiff solver configuration")
    started=time.perf_counter()
    with warnings.catch_warnings(record=True) as messages:
        warnings.simplefilter("always")
        sol=solve_ivp(balances,(0,days),initial,args=(raw,kla),method=method,
                      rtol=rtol,atol=atol,jac_sparsity=jacobian_pattern(),dense_output=dense)
    minimum=float(sol.y.min())
    if not sol.success or not np.isfinite(sol.y).all() or minimum < -10*atol:
        raise RuntimeError(f"{method}: {sol.message}; minimum accepted concentration={minimum}")
    diagnostics=dict(method=method,rtol=rtol,atol=atol,nfev=sol.nfev,njev=sol.njev,
                     nlu=sol.nlu,minimum_state=minimum,seconds=time.perf_counter()-started,
                     warnings=[str(w.message) for w in messages])
    return sol,diagnostics

def simulate(days=150, **solver):
    sol,diagnostics=integrate(initial_state(),days,**solver)
    state=sol.y[:,-1]
    tanks=state[:65].reshape(5,13)
    layers=state[65:].reshape(10,8)
    return dict(diagnostics=diagnostics,days=days,states=STATES,tanks=tanks.tolist(),layer_tss=layers[:,0].tolist(),
                effluent=stream(layers[0],tanks[-1]).tolist(),underflow=stream(layers[-1],tanks[-1]).tolist(),
                terminal_max_rate=float(np.abs(balances(days,state)).max()))

if __name__=='__main__':
    print(json.dumps(simulate(),indent=2))

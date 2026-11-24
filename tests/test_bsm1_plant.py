import json
from pathlib import Path
import numpy as np
from aera.bsm1 import simulate, settler, RAW, FEED, UNDER, EFF, HEIGHT, AREA, SOLUBLE, tss

def test_transient_settler_budget():
    layers=np.random.default_rng(126).uniform(1,5000,(10,8))
    inventory_rate=AREA*HEIGHT*settler(layers,RAW).sum(axis=0)
    external=FEED*np.r_[tss(RAW),RAW[SOLUBLE]]-UNDER*layers[-1]-EFF*layers[0]
    np.testing.assert_allclose(inventory_rate,external,rtol=1e-11)

def test_whole_plant_openloop():
    ref=json.loads(Path(__file__).with_name('bsm1_plant_reference.json').read_text())
    result=simulate()
    for i,tank in enumerate(result['tanks'],1):
        np.testing.assert_allclose(tank,ref[f'Reactor {i}'][:13],atol=.0003,rtol=2e-5)
    for name in ['effluent','underflow']:
        np.testing.assert_allclose(result[name],ref['Settler '+name][:13],atol=.0003,rtol=2e-5)
    np.testing.assert_allclose(result['layer_tss'],ref['Settler internal (1 is top layer)'],atol=.0003,rtol=2e-5)
    assert result['terminal_max_rate'] < .0001
    # Keep the displayed verification snapshot synchronised with the actual model.
    artifact=json.loads((Path(__file__).parents[1]/'frontend/src/bsm1-report.json').read_text())
    for key in ('effluent','underflow','tanks','layer_tss'):
        np.testing.assert_allclose(artifact[key],result[key],atol=1e-5)

def test_whole_plant_convergence():
    # Resolve the rapid settler startup using two independent stiff methods.
    first=simulate(.05,rtol=1e-9,atol=1e-11)
    other=simulate(.05,method="Radau",rtol=1e-9,atol=1e-11)
    np.testing.assert_allclose(other['tanks'],first['tanks'],rtol=2e-6,atol=1e-6)
    np.testing.assert_allclose(other['layer_tss'],first['layer_tss'],rtol=2e-6)
    tight=simulate(rtol=3e-8)
    ref=json.loads(Path(__file__).with_name('bsm1_plant_reference.json').read_text())
    np.testing.assert_allclose(tight['effluent'],ref['Settler effluent'][:13],atol=.0003,rtol=2e-5)

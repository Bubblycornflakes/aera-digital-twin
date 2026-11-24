import json
from pathlib import Path
import numpy as np
import pytest
from aera.asm1 import MATRIX, rates, reactor, IXB, IXP, DENIT

def test_process_budgets():
    # Organic N in biomass and products + dissolved/particulate N.
    n = np.array([0,0,0,0,IXB,IXB,IXP,0,1,1,1,1,0])
    np.testing.assert_allclose(n@MATRIX,[0,-DENIT,0,0,0,0,0,0],atol=1e-14)
    # Electron equivalents: nitrate to N2 consumes 2.86, ammonia oxidation to nitrate 4.57.
    cod = np.array([1,1,1,1,1,1,1,-1,-4.57,0,0,0,0])
    np.testing.assert_allclose(cod@MATRIX,[0,(4.57-2.86)*DENIT,0,0,0,0,0,0],atol=1e-14)
    assert np.isfinite(rates(np.zeros(13))).all()

def test_anoxic_switch():
    y=np.ones(13); y[7]=0
    r=rates(y)
    assert r[0]==r[2]==0 and r[1]>0
    y[8]=0
    assert rates(y)[1]==0

def test_hydraulic_washout():
    y=np.zeros(13); y[0]=10
    out=reactor(y,np.zeros(13),flow=2,volume=1,kla=0,days=1)
    assert out.y[0,-1]==pytest.approx(10*np.exp(-2),rel=2e-7)
    with pytest.raises(ValueError):
        reactor(-y,y,flow=2,volume=1,kla=0,days=1)

@pytest.mark.parametrize("rtol",[1e-6,1e-9])
def test_published_open_loop_train(rtol):
    ref=json.loads(Path(__file__).with_name('bsm1_steady.json').read_text())
    inlet=np.array(ref['Input to AS'])
    for i,(vol,kla) in enumerate(zip([1000,1000,1333,1333,1333],[0,0,240,240,84]),1):
        # Start each tank at its incoming concentration; propagate computed outlet downstream.
        sol=reactor(inlet,inlet,flow=92230,volume=vol,kla=kla,days=1,rtol=rtol)
        inlet=sol.y[:,-1]
        np.testing.assert_allclose(inlet,ref[f'Reactor {i}'],atol=.0003,rtol=2e-5)

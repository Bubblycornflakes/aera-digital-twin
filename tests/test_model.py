import numpy as np
import pytest
from fastapi.testclient import TestClient
from aera.api import app
from aera.model import Settings, control, loads, rates, reference, simulate

def test_annual():
    assert list(reference().values()) == pytest.approx([12318750,7884000,4336200,
        946080,1971000,1032.48864,1009152,252288,220064.175],rel=.001)

def test_mass_balances():
    cfg=Settings()
    flow,n,daily=loads(0,cfg)
    oxygen,nrate=rates([2,3],0,(flow,n,daily),cfg)
    removed=flow/cfg.volume*(n-3)-nrate
    assert removed == pytest.approx(6*.75*.8)
    assert oxygen == pytest.approx(flow/cfg.volume*(-1.5)-9*daily*2/2.25-4.57*removed)
    assert rates([0,0],0,(flow,n,daily),cfg)[0] > 0
    sat=cfg.beta*9.1
    assert rates([sat,3],1,(flow,n,daily),cfg)==pytest.approx(rates([sat,3],0,(flow,n,daily),cfg))

def test_events_and_control():
    cfg=Settings()
    base=loads(13,cfg)
    storm=loads(13,Settings(storm=True))
    assert storm[0]*storm[1]/(base[0]*base[1])==pytest.approx(1.05)
    ret=loads(13,Settings(returns=True))
    assert (ret[0]*ret[1]-base[0]*base[1])*6/1000==pytest.approx(74.25)
    assert control(10,10,0,1/60,cfg)==(1,0)
    assert control(-10,-10,0,1/60,cfg)==(0,0)

def test_trajectory():
    cfg=Settings(hours=1,noise=.02)
    r=simulate(cfg)["records"]
    assert r==simulate(cfg)["records"]
    assert r[-1]["energy_kwh"]==pytest.approx(sum(x["power_kw"]/60 for x in r[:-1]))
    fine=simulate(cfg,1e-9)["records"]
    assert np.allclose([x["do"] for x in r],[x["do"] for x in fine],atol=.0001)
    assert min(min(x["do"],x["nh4"]) for x in r)>=0

def test_api():
    client=TestClient(app)
    assert client.get("/api/reference").status_code==200
    assert client.post("/api/simulation",json={"kp":-1}).status_code==422
    assert len(client.post("/api/simulation",json={"hours":1}).json()["records"])==61

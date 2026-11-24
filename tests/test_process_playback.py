from fastapi.testclient import TestClient
from aera.api import app
import pytest

def test_asm1_timeline_and_equipment():
    client=TestClient(app)
    assert client.post('/api/asm1/playback',json={'command':2}).status_code==422
    data=client.post('/api/asm1/playback',json={'command':.35}).json()
    rows=data['records']
    assert [r['minute'] for r in rows]==list(range(0,1441,5))
    assert data['kla_day']==[0,0,240,240,84]
    assert rows[0]['effluent_nh4']==pytest.approx(1.7333,abs=.001)
    assert max(r['effluent_nh4'] for r in rows)>2
    assert rows[-1]['energy_kwh'][4]==pytest.approx(24*data['power_kw'][4])
    assert data['air_m3h'][:2]==[0,0]

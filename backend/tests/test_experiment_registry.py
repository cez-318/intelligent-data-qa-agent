import csv
import hashlib
import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from improved import experiment_registry as registry
from improved.experiments import ExperimentRejected
from improved.auth import _recent


def fixture():
    cfg=registry.configurations()['hillstrom_email_2008'].copy()
    cfg['expected_rows']=60
    rows=[]
    for arm in cfg['allocation']:
        for i in range(20):
            rows.append(dict(zip(cfg['required_columns'],
                ['1','1) low','30','1','0','Urban','0','Web',arm,str(i%2),str(i%2),'0'])))
    return cfg,rows


def encode(rows,fields):
    stream=io.StringIO()
    writer=csv.DictWriter(stream,fieldnames=fields)
    writer.writeheader(); writer.writerows(rows)
    return stream.getvalue().encode()


def test_duplicates_retained_and_zero_variance_balanced():
    cfg,rows=fixture()
    groups,quality=registry.summarize_csv(encode(rows,cfg['required_columns']),cfg)
    assert sum(g['n'] for g in groups.values())==60
    assert quality['exact_duplicate_extra_rows']==54
    assert not any(r['flag'] for r in quality['baseline_balance'])


@pytest.mark.parametrize('column,value', [('conversion',''),('conversion','2'),('segment','new'),('history','NaN'),('recency','bad')])
def test_invalid_source_rejected(column,value):
    cfg,rows=fixture()
    rows[0][column]=value
    with pytest.raises(ExperimentRejected):
        registry.summarize_csv(encode(rows,cfg['required_columns']),cfg)


def test_missing_rows_and_schema_never_silently_accepted():
    cfg,rows=fixture()
    with pytest.raises(ExperimentRejected,match='INCOMPLETE'):
        registry.summarize_csv(encode(rows[:-1],cfg['required_columns']),cfg)
    with pytest.raises(ExperimentRejected,match='SCHEMA'):
        registry.summarize_csv(b'bad\n1',cfg)


def test_empty_arm_and_large_imbalance_are_visible():
    cfg,rows=fixture()
    rows[0]['history']='1000000'
    _,quality=registry.summarize_csv(encode(rows,cfg['required_columns']),cfg)
    assert any(r['flag'] for r in quality['baseline_balance'])
    for row in rows:
        row['segment']='No E-Mail'
    with pytest.raises(ExperimentRejected,match='INSUFFICIENT'):
        registry.summarize_csv(encode(rows,cfg['required_columns']),cfg)


def test_registered_path_checksum_and_availability(tmp_path,monkeypatch):
    cfg,rows=fixture()
    cfg['data_file']='source.csv'
    raw=encode(rows,cfg['required_columns'])
    cfg['sha256']=hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(registry,'DATA',tmp_path)
    monkeypatch.setattr(registry,'configurations',lambda:{'test':cfg})
    with pytest.raises(ExperimentRejected,match='NOT_REGISTERED'):
        registry.evaluate_registered('../private')
    with pytest.raises(ExperimentRejected,match='NOT_AVAILABLE'):
        registry.evaluate_registered('test')
    (tmp_path/'source.csv').write_bytes(b'wrong')
    with pytest.raises(ExperimentRejected,match='CHECKSUM'):
        registry.evaluate_registered('test')
    (tmp_path/'source.csv').write_bytes(raw)
    assert registry.evaluate_registered('test')['status']=='complete'
    cfg['data_file']='../outside.csv'
    with pytest.raises(ExperimentRejected,match='PATH'):
        registry.evaluate_registered('test')


def test_original_app_api_auth_and_unregistered_design(monkeypatch):
    from main import create_app
    monkeypatch.setenv('DATA_AGENT_API_TOKEN','unit-test-token')
    _recent.clear()
    client=TestClient(create_app())
    assert client.get('/api/health').json()['experiments'][0]['id']=='hillstrom_email_2008'
    body={'experiment_id':'hillstrom_email_2008'}
    assert client.post('/api/experiments/evaluate',json=body).status_code==401
    headers={'Authorization':'Bearer unit-test-token'}
    assert client.post('/api/experiments/evaluate',headers=headers,json={**body,'filters':{'conversion':1}}).status_code==422
    assert client.post('/api/experiments/evaluate',headers=headers,json={'experiment_id':'retail_ii'}).status_code==422
    monkeypatch.setattr('app.api.routers.experiment_router.evaluate_registered',lambda _: {'status':'complete'})
    assert client.post('/api/experiments/evaluate',headers=headers,json=body).json()['status']=='complete'
    _recent.clear()

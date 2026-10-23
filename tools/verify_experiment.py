"""Independent raw CSV SQL + statsmodels oracle, optionally against the live API."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import duckdb
import httpx
from statsmodels.stats.proportion import confint_proportions_2indep

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
SQL = "SELECT segment, COUNT(*) AS n, SUM(conversion) AS conversions, SUM(visit) AS visits FROM read_csv_auto(?) GROUP BY segment ORDER BY segment"


def verify(result):
    db=duckdb.connect()
    rows=db.execute(SQL,[str(ROOT/'datasets/hillstrom/hillstrom.csv')]).fetchall()
    db.close()
    oracle={r[0]:{'n':r[1],'conversion':r[2],'visit':r[3]} for r in rows}
    assert result['status']=='complete'
    assert result['diagnostics']['arms']==oracle
    assert result['comparison_count']==4
    assert result['interval_level']==.9875
    checks=[]
    for row in result['effects']:
        treatment,control=oracle[row['treatment']],oracle['No E-Mail']
        key=row['outcome']
        expected=treatment[key]/treatment['n']-control[key]/control['n']
        interval=confint_proportions_2indep(treatment[key],treatment['n'],control[key],control['n'],method='newcomb',compare='diff',alpha=.05/4)
        error=max(abs(row['risk_difference']-expected), abs(row['ci_low']-interval[0]),abs(row['ci_high']-interval[1]))
        assert error<1e-12
        checks.append({'arm':row['treatment'],'outcome':key,'absolute_max_error':error,'passed':True})
    chi2=sum((r['n']-64000/3)**2/(64000/3) for r in oracle.values())
    assert abs(result['diagnostics']['sample_ratio_p']-math.exp(-chi2/2))<1e-12
    return {'source_sql':SQL,'oracle_counts':oracle,'effect_checks':checks,
            'srm_check_passed':True,'note':'Calculation consistency, not observed ground-truth causal accuracy.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api',action='store_true')
    parser.add_argument('--port',type=int,default=8000)
    args=parser.parse_args()
    started=time.perf_counter()
    if args.api:
        from improved.settings import load_env_file
        load_env_file(ROOT/'backend/.env')
        with httpx.Client(base_url=f'http://127.0.0.1:{args.port}',trust_env=False,timeout=30) as client:
            assert client.post('/api/experiments/evaluate',json={'experiment_id':'hillstrom_email_2008'}).status_code==401
            headers={'Authorization':'Bearer '+os.environ['DATA_AGENT_API_TOKEN']}
            assert client.post('/api/experiments/evaluate',headers=headers,json={'experiment_id':'retail_ii'}).status_code==422
            response=client.post('/api/experiments/evaluate',headers=headers,json={'experiment_id':'hillstrom_email_2008'})
            response.raise_for_status()
            result=response.json()
            request_id=response.headers.get('x-request-id')
    else:
        from improved.experiment_registry import evaluate_registered
        result=evaluate_registered('hillstrom_email_2008')
        request_id=None
    audit=verify(result)
    stamp=datetime.now(timezone.utc)
    report={'executed_at_utc':stamp.isoformat(),'live_http':args.api,'request_id':request_id,
            'elapsed_seconds':round(time.perf_counter()-started,3),'result':result,'independent_verification':audit,
            'software_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                ['backend/improved/experiments.py','backend/improved/experiment_registry.py','backend/conf/experiments.json','tools/verify_experiment.py']}}
    path=ROOT/'reports'/f'experiment_{"live" if args.api else "direct"}_{stamp:%Y%m%d_%H%M%S}.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(path.name, '4/4 effects and intervals match independent oracle; SRM matches.')


if __name__=='__main__':
    main()

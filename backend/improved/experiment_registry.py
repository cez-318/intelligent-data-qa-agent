"""Server-owned registry and strict public experiment loading; no arbitrary paths/SQL."""
from collections import Counter
import csv
import hashlib
import io
import json
import math
from pathlib import Path
from improved.experiments import ExperimentRejected, analyze_binary_experiment

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / 'backend/conf/experiments.json'
DATA = ROOT / 'datasets'


def configurations():
    return json.loads(REGISTRY.read_text(encoding='utf-8'))


def catalog():
    return [{'id':key,'title':value['title'],'design':value['design'],
             'source':value['randomization_source'],'window':value['window'],
             'population':value['population']} for key,value in configurations().items()]


def summarize_csv(raw, config):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if reader.fieldnames != config['required_columns']:
        raise ExperimentRejected('DATA_SCHEMA_MISMATCH')
    groups = {arm:{'n':0,**{name:0 for name in config['outcomes']}} for arm in config['allocation']}
    baselines = {a:{f:[] for f in config['baseline_numeric']} for a in groups}
    fingerprints = Counter()
    total = 0
    for row in reader:
        total += 1
        if total > config['expected_rows'] or any(not isinstance(v,str) or not v.strip() for v in row.values()):
            raise ExperimentRejected('MISSING_OR_EXCESS_DATA')
        arm = row.get(config['assignment_column'])
        if arm not in groups:
            raise ExperimentRejected('UNKNOWN_ASSIGNMENT')
        groups[arm]['n'] += 1
        for outcome in config['outcomes']:
            if row[outcome] not in {'0','1'}:
                raise ExperimentRejected('NONBINARY_OR_MISSING_OUTCOME')
            groups[arm][outcome] += int(row[outcome])
        for field in config['baseline_numeric']:
            try:
                value = float(row[field])
            except ValueError:
                raise ExperimentRejected('INVALID_BASELINE') from None
            if not math.isfinite(value):
                raise ExperimentRejected('INVALID_BASELINE')
            baselines[arm][field].append(value)
        fingerprints[tuple(row.items())] += 1
    if total != config['expected_rows']:
        raise ExperimentRejected('INCOMPLETE_FOLLOWUP_EXPORT')
    # Balance is a diagnostic, not evidence that randomization necessarily worked.
    balance=[]
    def moments(values):
        if len(values)<2:
            raise ExperimentRejected('INSUFFICIENT_SAMPLE')
        mean=math.fsum(values)/len(values)
        return mean,math.fsum((v-mean)**2 for v in values)/(len(values)-1)
    for arm in groups:
        if arm==config['control']:
            continue
        for field in config['baseline_numeric']:
            m1,v1=moments(baselines[arm][field])
            m0,v0=moments(baselines[config['control']][field])
            pooled=math.sqrt((v1+v0)/2)
            smd=(m1-m0)/pooled if pooled else (0.0 if m1==m0 else None)
            balance.append({'treatment':arm,'field':field,'standardized_mean_difference':smd,
                            'flag':smd is None or abs(smd)>.1})
    return groups, {'rows':total,'missing_outcomes':0,'excluded_rows':0,
                    'exact_duplicate_extra_rows':sum(n-1 for n in fingerprints.values()),
                    'duplicate_policy':'保留全部原始行；无客户ID，相同行不能据此认定是同一客户，无法独立核验每人一行。',
                    'baseline_balance':balance, 'balance_note':'仅检查注册的数值型处理前变量，|SMD|>0.1提示检查；不是随机性或无混杂证明。'}


def evaluate_registered(experiment_id):
    registry=configurations()
    if experiment_id not in registry:
        raise ExperimentRejected('EXPERIMENT_NOT_REGISTERED')
    config=registry[experiment_id]
    path=(DATA/config['data_file']).resolve()
    if not path.is_relative_to(DATA.resolve()):
        raise ExperimentRejected('DATA_PATH_REJECTED')
    if not path.is_file() or path.stat().st_size>20_000_000:
        raise ExperimentRejected('DATA_NOT_AVAILABLE')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=config['sha256']:
        raise ExperimentRejected('DATA_CHECKSUM_MISMATCH')
    groups,quality=summarize_csv(raw,config)
    result=analyze_binary_experiment(groups,config)
    result.update(experiment_id=experiment_id,title=config['title'],data_quality=quality,
                  evidence={'source':config['randomization_source'],'data_sha256':config['sha256'],
                            'registry_sha256':hashlib.sha256(REGISTRY.read_bytes()).hexdigest(),
                            'window':config['window'],'population':config['population'],
                            'provenance_note':config['provenance_note'],
                            'model_generated_statistics':False,'customer_identity_verified':False})
    return result

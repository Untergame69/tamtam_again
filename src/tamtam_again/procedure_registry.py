"""Prospective procedure contracts and immutable choices; no reserved reads."""
import json,time
from .accounting import decimal
from .discovery import fingerprint


def now_ms():return int(time.time()*1000)


def initialize(store):
    store.connection.executescript('''
    create table if not exists procedure_contracts (
      procedure_id text primary key,registered_ms integer not null,contract_json text not null);
    create table if not exists procedure_choices (
      procedure_id text not null,period_index integer not null,available_ms integer not null,
      choice_json text not null,primary key(procedure_id,period_index),
      foreign key(procedure_id) references procedure_contracts(procedure_id));''')


def register(store,contract):
    initialize(store);identity=fingerprint(contract)
    old=store.connection.execute('select registered_ms from procedure_contracts where procedure_id=?',(identity,)).fetchone()
    if old:return {'procedure_id':identity,'registered_ms':old[0]}
    stamp=now_ms()
    if contract.get('version')!='prospective-procedure-v1' or not contract.get('policy_version') or not contract.get('justification'):
        raise ValueError('Explicit versioned procedure policy and justification required')
    periods=contract.get('periods',[])
    if not periods:raise ValueError('Prospective periods required')
    previous=None
    for period in periods:
        start,end=period['start_ms'],period['end_ms']
        if type(start) is not int or type(end) is not int or not stamp<start<end or (previous is not None and start!=previous):
            raise ValueError('Contiguous future periods required')
        previous=end
    references=contract.get('references',[])
    if not references or len({r['name'] for r in references})!=len(references):
        raise ValueError('Distinct predeclared references required')
    for r in references:
        if r.get('kind') not in {'cash','fixed_rule','selection_control'} or not r.get('evidence_ref') or type(r.get('available_ms')) is not int or not 0<=r['available_ms']<=stamp:
            raise ValueError('Reference unavailable at registration')
        if r['kind']!='cash' and not r.get('variant_id'):
            raise ValueError('Executable reference identity required')
    if decimal(contract['initial_capital_usdc'])<=0 or not contract.get('risk_budget_id'):
        raise ValueError('Positive common capital and explicit risk budget required')
    store.connection.execute('insert into procedure_contracts values(?,?,?)',(identity,stamp,json.dumps(contract,sort_keys=True)))
    store.connection.commit()
    return {'procedure_id':identity,'registered_ms':stamp}


def record_choice(store,procedure_id,period_index,choice):
    initialize(store)
    old=store.connection.execute('select choice_json,available_ms from procedure_choices where procedure_id=? and period_index=?',(procedure_id,period_index)).fetchone()
    encoded=json.dumps(choice,sort_keys=True)
    if old:
        if old['choice_json']!=encoded:raise ValueError('Recorded choice is immutable')
        return {'available_ms':old['available_ms'],'replayed':True}
    row=store.connection.execute('select * from procedure_contracts where procedure_id=?',(procedure_id,)).fetchone()
    if not row:raise ValueError('Unknown registered procedure')
    contract=json.loads(row['contract_json']);stamp=now_ms()
    if type(period_index) is not int or not 0<=period_index<len(contract['periods']):raise ValueError('Invalid period index')
    if not row['registered_ms']<=stamp<contract['periods'][period_index]['start_ms']:
        raise ValueError('Decision must precede its observation period')
    if period_index and not store.connection.execute('select 1 from procedure_choices where procedure_id=? and period_index=?',(procedure_id,period_index-1)).fetchone():
        raise ValueError('Previous decision missing; waiting periods cannot be erased')
    if not choice.get('evidence_refs') or not choice.get('diagnostic') or any(type(t) is not int or not 0<=t<=stamp for t in choice['knowledge_available_ms']):
        raise ValueError('Available knowledge and decision provenance required')
    if choice['selected_variant_id'] is not None and choice['selected_variant_id'] not in choice['considered_variant_ids']:
        raise ValueError('Selected variant absent from candidates')
    store.connection.execute('insert into procedure_choices values(?,?,?,?)',(procedure_id,period_index,stamp,encoded))
    store.connection.commit()
    return {'available_ms':stamp,'replayed':False}

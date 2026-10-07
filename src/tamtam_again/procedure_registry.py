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
    if not references or any(r.get('name')=='adaptive' for r in references) or len({r['name'] for r in references})!=len(references):
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


def bind_session(store,procedure_id,period_index,role,session_id):
    """Bind an already-started session before the period, never pick its past PnL."""
    initialize(store)
    store.connection.execute('create table if not exists procedure_session_bindings '
        '(procedure_id text not null,period_index integer not null,role text not null,'
        'session_id text not null,available_ms integer not null,'
        'primary key(procedure_id,period_index,role))')
    old=store.connection.execute('select * from procedure_session_bindings where procedure_id=? and period_index=? and role=?',
        (procedure_id,period_index,role)).fetchone()
    if old:
        if old['session_id']!=session_id:raise ValueError('Session binding is immutable')
        return {'available_ms':old['available_ms'],'replayed':True}
    row=store.connection.execute('select * from procedure_contracts where procedure_id=?',(procedure_id,)).fetchone()
    choice=store.connection.execute('select * from procedure_choices where procedure_id=? and period_index=?',(procedure_id,period_index)).fetchone()
    if not row or not choice:raise ValueError('Registered procedure and choice required')
    contract=json.loads(row['contract_json']);stamp=now_ms()
    if type(period_index) is not int or not 0<=period_index<len(contract['periods']):raise ValueError('Invalid period index')
    if not choice['available_ms']<=stamp<contract['periods'][period_index]['start_ms']:
        raise ValueError('Session binding must precede the period')
    if role=='adaptive':expected=json.loads(choice['choice_json'])['selected_variant_id']
    else:
        refs=[r for r in contract['references'] if r['name']==role and r['kind']!='cash']
        if len(refs)!=1:raise ValueError('Unknown executable reference role')
        expected=refs[0]['variant_id']
    session=store.connection.execute('select variant_id,network,address,started_ms,status from paper_sessions where session_id=?',(session_id,)).fetchone()
    if not session or session['variant_id']!=expected or not row['registered_ms']<=session['started_ms']<=stamp or session['status']!='active':
        raise ValueError('Matching active prospective paper session required')
    if session['network']!=contract.get('network') or session['address']!=contract.get('address'):
        raise ValueError('Explicit procedure network/account scope mismatch')
    store.connection.execute('insert into procedure_session_bindings values(?,?,?,?,?)',(procedure_id,period_index,role,session_id,stamp))
    store.connection.commit()
    return {'available_ms':stamp,'replayed':False}


def bound_outcomes(store,procedure_id,period_index,*,as_of_ms):
    """Resolve only prebound paper snapshots. Never replay reserved archives."""
    from .paper_outcome import period_outcome
    row=store.connection.execute('select * from procedure_contracts where procedure_id=?',(procedure_id,)).fetchone()
    if not row or type(as_of_ms) is not int or as_of_ms<row['registered_ms']:raise ValueError('Unavailable procedure contract')
    contract=json.loads(row['contract_json'])
    if type(period_index) is not int or not 0<=period_index<len(contract['periods']):raise ValueError('Invalid period index')
    period=contract['periods'][period_index];results={}
    if period['end_ms']>as_of_ms:return {'status':'unknown','reason':'period not yet completed','outcomes':{}}
    choice=store.connection.execute('select * from procedure_choices where procedure_id=? and period_index=?',(procedure_id,period_index)).fetchone()
    if not choice or choice['available_ms']>as_of_ms:return {'status':'unknown','reason':'decision unavailable','outcomes':{}}
    roles=['adaptive']+[r['name'] for r in contract['references']]
    exists=store.connection.execute("select 1 from sqlite_master where name='procedure_session_bindings'").fetchone()
    for role in roles:
        cash=(role=='adaptive' and json.loads(choice['choice_json'])['selected_variant_id'] is None) or any(r['name']==role and r['kind']=='cash' for r in contract['references'])
        if cash:
            results[role]={'status':'declared_cash','net_pnl':'0','limits':['no interest, fees or external flows modeled']};continue
        binding=store.connection.execute('select * from procedure_session_bindings where procedure_id=? and period_index=? and role=?',(procedure_id,period_index,role)).fetchone() if exists else None
        if not binding or binding['available_ms']>as_of_ms:
            results[role]={'status':'unknown','net_pnl':None,'reason':'prospective session binding absent'};continue
        results[role]=period_outcome(store,binding['session_id'],start_ms=period['start_ms'],end_ms=period['end_ms'],as_of_ms=as_of_ms)
    return {'status':'unknown' if any(v['net_pnl'] is None for v in results.values()) else 'bound_model_outcomes',
        'procedure_id':procedure_id,'period_index':period_index,'outcomes':results}

"""Model net result between exact immutable paper observations, never state replay."""
import json
from .engine import fingerprint, number


def period_outcome(store,session_id,*,start_ms,end_ms,as_of_ms):
    if any(type(t) is not int for t in (start_ms,end_ms,as_of_ms)) or not 0<=start_ms<end_ms:
        raise ValueError('Explicit ordered paper period required')
    result={'status':'unknown','net_pnl':None,'available_ms':end_ms,
            'start_ms':start_ms,'end_ms':end_ms,'session_id':session_id,
            'flat_at_boundaries':False,'costs_included':False,'unknown_reasons':[]}
    def unknown(reason):
        result['unknown_reasons'].append(reason)
        return result
    if end_ms>as_of_ms:return unknown('period not yet available')
    if not store.connection.execute("select 1 from sqlite_master where name='paper_snapshots'").fetchone():
        return unknown('immutable paper snapshots absent')
    session=store.connection.execute('select s.variant_id,v.spec_json,p.synthetic from paper_sessions s '
        'join strategy_variants v on v.variant_id=s.variant_id '
        'join validation_plans p on p.plan_id=v.plan_id where s.session_id=?',(session_id,)).fetchone()
    if not session:return unknown('session or immutable variant provenance absent')
    spec=json.loads(session['spec_json'])
    result.update(variant_id=session['variant_id'],synthetic=bool(session['synthetic']),
        risk_budget_id=fingerprint({'starting_capital_usdc':spec['starting_capital_usdc'],
                                    'max_exposure':spec['max_exposure']}))
    rows=store.connection.execute('select * from paper_snapshots where session_id=? '
        'and available_ms>=? and available_ms<=? order by available_ms,snapshot_id',
        (session_id,start_ms,end_ms)).fetchall()
    boundaries=[]
    for timestamp in (start_ms,end_ms):
        candidates=[r for r in rows if r['available_ms']==timestamp]
        if len(candidates)!=1:return unknown('missing or ambiguous exact boundary snapshot')
        boundaries.append(candidates[0])
    values=[json.loads(r['metrics_json']) for r in boundaries]
    for value in values:
        if value.get('flat_end') is not True or value.get('pending_end')!=0:
            return unknown('open position or pending order at period boundary')
        for field in ('net_pnl','fees','funding'):
            if field not in value or not number(value[field]).is_finite():
                return unknown('model accounting metric missing or nonfinite')
    for row in rows:
        diagnostics=json.loads(row['metrics_json']).get('diagnostics')
        if not isinstance(diagnostics,list) or diagnostics:
            return unknown('paper diagnostics missing or require review within period')
    result.update(status='model_period_measured',
        net_pnl=str(number(values[1]['net_pnl'])-number(values[0]['net_pnl'])),
        flat_at_boundaries=True,costs_included=True,
        evidence_ref='paper_snapshots:'+boundaries[0]['snapshot_id']+'..'+boundaries[1]['snapshot_id'],
        limits=['net result includes modeled execution costs and observed funding only',
                'no proof of feed completeness, actual execution or statistical advantage',
                'same session only; capital continuity across replacements not established'])
    return result

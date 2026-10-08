"""Start isolated reference paper sessions only for predeclared prospective roles."""
import json
from .procedure_registry import bind_session,now_ms


def validate_reference_start(store,variant_id,binding,stamp):
    row=store.connection.execute('select * from procedure_contracts where procedure_id=?',(binding['procedure_id'],)).fetchone()
    if not row:raise ValueError('Unknown procedure reference contract')
    contract=json.loads(row['contract_json']);index=binding['period_index']
    if type(index) is not int or not 0<=index<len(contract['periods']) or not row['registered_ms']<=stamp<contract['periods'][index]['start_ms']:
        raise ValueError('Reference must start before prospective period')
    if not store.connection.execute('select 1 from procedure_choices where procedure_id=? and period_index=? and available_ms<=?',(binding['procedure_id'],index,stamp)).fetchone():
        raise ValueError('Procedure choice required before reference start')
    refs=[r for r in contract['references'] if r['name']==binding['role'] and r['kind']!='cash' and r['variant_id']==variant_id]
    if len(refs)!=1:raise ValueError('Predeclared executable reference required')
    scope=refs[0].get('scope',contract)
    actual=store.connection.execute('select p.network,p.address from strategy_variants v join validation_plans p using(plan_id) where variant_id=?',(variant_id,)).fetchone()
    if not actual or actual['network']!=scope.get('network') or actual['address']!=scope.get('address'):
        raise ValueError('Reference strategy scope mismatch')


def start_reference(store,procedure_id,period_index,role,*,synthetic_recipe=False):
    from .paper import start_paper
    row=store.connection.execute('select contract_json from procedure_contracts where procedure_id=?',(procedure_id,)).fetchone()
    if not row:raise ValueError('Unknown procedure')
    refs=[r for r in json.loads(row[0])['references'] if r['name']==role and r['kind']!='cash']
    if len(refs)!=1:raise ValueError('Executable reference role required')
    provenance=store.connection.execute('select p.synthetic from strategy_variants v join validation_plans p using(plan_id) where variant_id=?',(refs[0]['variant_id'],)).fetchone()
    if provenance and provenance[0] and not synthetic_recipe:raise ValueError('Synthetic reference requires explicit fixture recipe')
    binding={'procedure_id':procedure_id,'period_index':period_index,'role':role}
    if period_index>0:
        validate_reference_start(store,refs[0]['variant_id'],binding,now_ms())
        prior=store.connection.execute('select b.session_id,s.status from procedure_session_bindings b join paper_sessions s using(session_id) where procedure_id=? and period_index=? and role=?',
            (procedure_id,period_index-1,role)).fetchone()
        if not prior or prior['status']!='active':raise ValueError('Continuous active reference required; missing/suspended predecessor cannot be reset')
        result={'session_id':prior['session_id'],'continued_reference':True}
    else:
        result=start_paper(store,refs[0]['variant_id'],synthetic_recipe=synthetic_recipe,reference_binding=binding)
    bind_session(store,procedure_id,period_index,role,result['session_id'])
    return result


def tick_references(store,*,max_starts=1):
    if type(max_starts) is not int or not 1<=max_starts<=16:raise ValueError('Bounded reference-start budget required')
    if not store.connection.execute("select 1 from sqlite_master where name='procedure_contracts'").fetchone():return []
    stamp=now_ms();results=[]
    for row in store.connection.execute('select procedure_id,contract_json from procedure_contracts order by registered_ms,procedure_id').fetchall():
        contract=json.loads(row['contract_json'])
        for index,period in enumerate(contract['periods']):
            if period['start_ms']<=stamp:continue
            if not store.connection.execute('select 1 from procedure_choices where procedure_id=? and period_index=?',(row['procedure_id'],index)).fetchone():continue
            for ref in contract['references']:
                if ref['kind']=='cash':continue
                exists=store.connection.execute("select 1 from sqlite_master where name='procedure_session_bindings'").fetchone()
                if exists and store.connection.execute('select 1 from procedure_session_bindings where procedure_id=? and period_index=? and role=?',(row['procedure_id'],index,ref['name'])).fetchone():continue
                variant=store.connection.execute('select p.synthetic from strategy_variants v join validation_plans p using(plan_id) where variant_id=?',(ref['variant_id'],)).fetchone()
                if not variant or variant[0]:continue
                try:result=start_reference(store,row['procedure_id'],index,ref['name'])
                except ValueError as exc:result={'status':'waiting','reason':str(exc)}
                results.append({'procedure_id':row['procedure_id'],'period_index':index,'role':ref['name'],**result})
                if len(results)>=max_starts:return results
    return results

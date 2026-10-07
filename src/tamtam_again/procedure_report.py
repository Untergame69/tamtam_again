"""Evaluate registered choices against prebound model observations and registry costs."""
import json
from .accounting import decimal
from .discovery import fingerprint
from .procedure_registry import bound_outcomes
from .procedure_costs import provider_cost_ledger
from .procedure_evaluation import evaluate_procedure


def registered_report(store,procedure_id,*,as_of_ms):
    row=store.connection.execute('select * from procedure_contracts where procedure_id=?',(procedure_id,)).fetchone()
    if not row or type(as_of_ms) is not int or as_of_ms<row['registered_ms']:
        raise ValueError('Available registered procedure required')
    contract=json.loads(row['contract_json']);periods=contract['periods']
    if periods[-1]['end_ms']>as_of_ms:
        return {'status':'waiting','procedure_id':procedure_id,'wake_ms':periods[-1]['end_ms'],'performance':None}
    if not contract.get('network') or not contract.get('address'):
        raise ValueError('Explicit cost-attribution network/account scope required')
    choices=[];resolved=[];missing=[]
    for index,period in enumerate(periods):
        choice=store.connection.execute('select * from procedure_choices where procedure_id=? and period_index=?',(procedure_id,index)).fetchone()
        if not choice or choice['available_ms']>as_of_ms:
            missing.append('decision absent: '+str(index));continue
        choices.append(choice);resolved.append(bound_outcomes(store,procedure_id,index,as_of_ms=as_of_ms))
    costs=provider_cost_ledger(store,network=contract['network'],address=contract['address'],
        start_ms=row['registered_ms'],end_ms=periods[-1]['end_ms'],as_of_ms=as_of_ms)
    if missing:return {'status':'unknown','procedure_id':procedure_id,'unknown_reasons':missing,'performance':None,'costs':costs}
    reports={}
    for reference in contract['references']:
        trace={'as_of_ms':as_of_ms,'policy_version':contract['policy_version'],
            'fixed_variant_id':None if reference['kind']=='cash' else 'reference:'+reference['name'],
            'baseline_available_ms':row['registered_ms'],'baseline_evidence_ref':'procedure_contracts:'+procedure_id,
            'risk_budget_id':contract['risk_budget_id'],'capital_contract':{
                'initial_capital':contract['initial_capital_usdc'],'currency':'USDC','external_flows':'none',
                'available_ms':row['registered_ms'],'evidence_ref':'procedure_contracts:'+procedure_id},'steps':[]}
        previous=None;extra=[]
        for index,(period,choice,observations) in enumerate(zip(periods,choices,resolved)):
            value=json.loads(choice['choice_json']);selected=value['selected_variant_id']
            selected_key=None if selected is None else 'adaptive:'+selected
            change=selected!=previous;previous=selected
            change_cost=value.get('change_cost')
            if change_cost is None:
                if change:extra.append('change cost absent: '+str(index))
                change_cost='0'
            outcomes={}
            for role,key in (('adaptive',selected_key),(reference['name'],trace['fixed_variant_id'])):
                if key is not None:outcomes[key]=observations['outcomes'].get(role,{'net_pnl':None})
            trace['steps'].append({**period,'decision_ms':choice['available_ms'],
                'selected_variant_id':selected_key,'considered_variant_ids':['adaptive:'+v for v in value['considered_variant_ids']],
                'knowledge_available_ms':value['knowledge_available_ms'],
                'evidence_refs':value['evidence_refs']+['procedure_choices:'+procedure_id+':'+str(index)],
                'research_attempts':[],'change_cost':change_cost,'outcomes':outcomes})
        result=evaluate_procedure(trace)
        # Expenses may be registered after the last decision. Include all of them,
        # without pretending that they were knowledge available at that decision.
        extra.extend('research cost unknown: '+i for i in costs['unknown_cost_attempts'])
        result['observed_research_cost']=costs['known_provider_cost_usd']
        if extra:
            result['status']='unknown';result['capital_continuity_status']='unknown';result['unknown_reasons'].extend(extra)
            result['adaptive_net_after_research_and_change_costs']=None
            result['procedure_wealth_after_external_research_and_change_costs']=None
        elif result['adaptive_net_after_research_and_change_costs'] is not None:
            expense=decimal(costs['known_provider_cost_usd'])
            result['adaptive_net_after_research_and_change_costs']=str(decimal(result['adaptive_net_after_research_and_change_costs'])-expense)
            result['procedure_wealth_after_external_research_and_change_costs']=str(decimal(result['procedure_wealth_after_external_research_and_change_costs'])-expense)
        result['research_attempts']=len(costs['attempts']);result['input_trace_fingerprint']=fingerprint(trace)
        reports[reference['name']]=result
    return {'version':'registered-procedure-report-v1','procedure_id':procedure_id,'as_of_ms':as_of_ms,
        'status':'unknown' if any(r['status']=='unknown' for r in reports.values()) else 'registered_model_inputs_evaluated',
        'comparisons':reports,'costs':costs,'synthetic_observations':any(v.get('synthetic') is True for r in resolved for v in r['outcomes'].values()),'limits':['registry provider expenses attributed by account and registration window, not total infrastructure expense',
            'reference costs not included; separately researched controls require their own procedure report',
            'nominal USD/USDC convention, no executed currency conversion',
            'declared knowledge/cohort proofs require independent review; no statistical advantage established']}

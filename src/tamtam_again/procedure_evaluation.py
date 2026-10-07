"""Replay recorded adaptive choices; never choose a hindsight winner."""
from __future__ import annotations
from .accounting import decimal
from .discovery import fingerprint


def evaluate_procedure(trace):
    asof=trace['as_of_ms'];steps=trace['steps'];fixed=trace['fixed_variant_id']
    if not trace.get('policy_version') or not trace.get('baseline_evidence_ref'):
        raise ValueError('Predeclared procedure and baseline evidence required')
    if steps and trace['baseline_available_ms']>steps[0]['decision_ms']:
        raise ValueError('Baseline chosen after procedure started')
    adaptive=decimal(0);baseline=decimal(0);research=decimal(0);switching=decimal(0)
    waits=0;previous=None;end=-1;ledger=[];unknown=[];attempt_ids=set()
    capital=trace.get('capital_contract')
    balances={}
    if capital is not None:
        if capital.get('currency')!='USDC' or capital.get('external_flows')!='none' or not capital.get('evidence_ref'):
            raise ValueError('Explicit no-flow USDC capital contract required')
        initial=decimal(capital['initial_capital'])
        if initial<=0 or type(capital['available_ms']) is not int or (steps and capital['available_ms']>steps[0]['decision_ms']):
            raise ValueError('Initial capital unavailable or invalid')
        balances={'adaptive':initial,'fixed':initial}
    for step in steps:
        start,stop,decision=(step[k] for k in ('start_ms','end_ms','decision_ms'))
        if not 0<=decision<=start<stop<=asof or start<end:
            raise ValueError('Decision chronology or nonoverlapping periods invalid')
        if not step.get('evidence_refs') or any(t>decision for t in step['knowledge_available_ms']):
            raise ValueError('Unavailable knowledge or decision provenance')
        end=stop
        selected=step['selected_variant_id']
        if selected is not None and selected not in step['considered_variant_ids']:
            raise ValueError('Selected version absent from recorded candidates')
        for attempt in step['research_attempts']:
            if attempt['id'] in attempt_ids:raise ValueError('Research cost counted twice')
            attempt_ids.add(attempt['id'])
            if attempt['available_ms']>decision:raise ValueError('Future research attempt')
            cost_available=attempt.get('cost_available_ms',attempt['available_ms'])
            if cost_available is not None and (type(cost_available) is not int or cost_available<attempt['available_ms']):
                raise ValueError('Invalid provider-cost availability chronology')
            if attempt.get('cost') is None or cost_available is None or cost_available>asof:
                unknown.append('research cost unknown: '+attempt['id'])
            else:
                cost=decimal(attempt['cost'])
                if cost<0:raise ValueError('Negative research cost')
                research+=cost
        change=selected!=previous
        cost=decimal(step['change_cost'])
        if cost<0 or not change and cost!=0:
            raise ValueError('Invalid change cost')
        switching+=cost;previous=selected
        def outcome(variant):
            if variant is None:return decimal(0)
            value=step['outcomes'].get(variant)
            if not value or value.get('net_pnl') is None or value.get('available_ms',asof+1)>asof:
                unknown.append('outcome unavailable: '+variant);return None
            if ('start_ms' in value and value['start_ms']!=start) or ('end_ms' in value and value['end_ms']!=stop):
                raise ValueError('Outcome belongs to a different period')
            if value['available_ms']<stop:
                raise ValueError('Period outcome available before period ended')
            if not value.get('flat_at_boundaries') or value.get('risk_budget_id')!=trace['risk_budget_id']:
                raise ValueError('Unattributed positions or incomparable risk budgets')
            if not value.get('evidence_ref') or value.get('costs_included') is not True:
                raise ValueError('Net outcome provenance/cost accounting unproven')
            return decimal(value['net_pnl'])
        result=outcome(selected);reference=outcome(fixed)
        if capital is not None:
            if ledger and start!=ledger[-1]['end_ms']:
                raise ValueError('Capital continuity requires contiguous periods')
            for track,variant,pnl in (('adaptive',selected,result),('fixed',fixed,reference)):
                if balances[track] is None:continue
                if variant is None:continue  # Explicit cash wait, no interest or flow.
                value=step['outcomes'].get(variant,{})
                if pnl is None or any(value.get(k) is None for k in ('opening_capital','closing_capital')):
                    unknown.append('capital boundary unavailable: '+track)
                    balances[track]=None;continue
                opening=decimal(value['opening_capital']);closing=decimal(value['closing_capital'])
                if opening!=balances[track] or closing-opening!=pnl:
                    raise ValueError('Capital reset or unreconciled period result')
                if value.get('external_flows')!='none' or value.get('currency')!='USDC':
                    raise ValueError('Unsupported capital flows or currency')
                balances[track]=closing
        if result is not None:adaptive+=result
        if reference is not None:baseline+=reference
        waits+=selected is None
        ledger.append({'start_ms':start,'end_ms':stop,'decision_ms':decision,
                       'selected_variant_id':selected,'considered_variant_ids':step['considered_variant_ids'],
                       'changed':change,'net_pnl_observed':str(result) if result is not None else None,
                       'evidence_refs':step['evidence_refs']})
    return {'version':'recorded-procedure-replay-v1','status':'unknown' if unknown else 'evaluated_inputs',
            'adaptive_net_after_research_and_change_costs':None if unknown else str(adaptive-research-switching),
            'fixed_net':None if unknown else str(baseline),'cash_net':'0',
            'observed_research_cost':str(research),'observed_change_cost':str(switching),
            'capital_continuity_status':('unverified' if capital is None else 'unknown' if unknown else 'verified_supplied_boundaries'),
            'trading_capital':{k:str(v) if v is not None else None for k,v in balances.items()},
            'procedure_wealth_after_external_research_and_change_costs':None if capital is None or unknown else str(balances['adaptive']-research-switching),
            'wait_periods':waits,'research_attempts':len(attempt_ids),'ledger':ledger,
            'unknown_reasons':unknown,'input_fingerprint':fingerprint(trace),
            'limits':['flat positions required at period boundaries; open-position switching unsupported',
                      'input evidence must be independently verified by archive adapter',
                      'evaluation of supplied choices, no proof of statistical advantage']}

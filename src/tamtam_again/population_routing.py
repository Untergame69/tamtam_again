"""Immutable next actions from reviewed hypotheses; never infer executable rules from prose."""
import json
from .engine import canonical
from .harness_extensions import capability
from .validation import now_ms


def route(store,request_id):
    store.connection.execute('create table if not exists population_hypothesis_routes '
        '(request_id text primary key,created_ms integer not null,route_json text not null)')
    store.connection.commit()
    previous=store.connection.execute('select route_json from population_hypothesis_routes where request_id=?',(request_id,)).fetchone()
    if previous:return json.loads(previous[0])
    row=store.connection.execute('select status,result_json from population_research_jobs where request_id=?',(request_id,)).fetchone()
    if not row or row['status'] in ('sealed','running'):raise ValueError('Terminal population decision required')
    result=json.loads(row['result_json'] or '{}')
    decision=result.get('critique') or result.get('proposal') or {}
    output={'request_id':request_id,'source_status':row['status'],'promotion_authorized':False,
        'economic_rejection':False,'evidence_refs':['population_research:'+request_id],
        'diagnostic':decision.get('diagnostic',result.get('error_type','terminal request without hypothesis')),
        'wake':decision.get('wake',{}),'created_ms':now_ms()}
    if row['status']=='hypothesis_recorded':
        if (result.get('promotion_authorized') is not False or result.get('profitability_proven') is not False
                or decision.get('decision')!='consistent'):
            raise ValueError('Reviewed non-economic hypothesis required')
        hypothesis=result['proposal']['hypothesis'];missing=hypothesis['required_data']
        if missing:
            output.update(state='needs_data',required_data=missing,
                next_action='collect specified observations, then reassess on changed evidence',
                wake={'kind':'required_observations_available','observations':missing,
                      'new_input_fingerprint_required':True})
        elif 'executable_spec' not in hypothesis:
            output.update(state='specification_required',next_action='compile an explicit executable contract and preregister a new prospective experiment',
                wake={'kind':'executable_contract_supplied','new_input_fingerprint_required':True})
        else:
            spec=hypothesis['executable_spec']
            markets=([leg.get('market') for leg in spec.get('legs',[])]
                     if spec.get('engine')=='portfolio_reference_v1' else [spec.get('market')])
            if set(markets)!=set(hypothesis['markets']) or (spec.get('type') is not None and spec['type']!=hypothesis['type']):
                raise ValueError('Executable contract must preserve hypothesis markets and type')
            supported=capability(spec)
            output['capability']=supported
            output.update(state=supported['state'],next_action='resolve capability diagnostic')
            if supported['state'] in ('executable','executable_experimental'):
                # An experimental replay engine is not necessarily connected to N1/N2.
                integrated=supported['contract']['real_validation_adapter']
                output.update(state='prospective_plan_required' if integrated else 'unsupported_validation_adapter',
                    next_action='preregister future windows, criteria and experiment budget' if integrated else 'implement and verify the prospective validation adapter',
                    wake={'kind':'prospective_plan_registered' if integrated else 'validation_adapter_verified'})
    else:
        output.update(state=row['status'],next_action={
            'needs_data':'collect observations specified by decision',
            'unsupported_mechanism':'implement and verify missing mechanism',
            'non_identifiable':'archive until a new source makes mechanism observable',
            'reject':'archive economic or hypothesis rejection with its original diagnostic',
        }.get(row['status'],'resolve interruption or contract failure before any explicitly budgeted new attempt'))
    store.connection.execute('insert or ignore into population_hypothesis_routes values(?,?,?)',
        (request_id,output['created_ms'],canonical(output)));store.connection.commit()
    return json.loads(store.connection.execute('select route_json from population_hypothesis_routes where request_id=?',(request_id,)).fetchone()[0])

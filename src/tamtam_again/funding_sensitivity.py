"""Preregistered adverse funding sensitivity, never a venue rate bound or N1 proof."""
from datetime import datetime, timezone
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
import json
import sqlite3
from time import monotonic

VERSION='frozen_hourly_debit_sensitivity_v1'
HOUR=3_600_000
ADMINISTRATIVE_COMPLETION='abandon_unused_final_after_comparison_with_existing_release_grace_v1'
DEFAULT_POLICY={'version':'funding-sensitivity-policy-v1','promotion_authorized':False,
    'administrative_completion':ADMINISTRATIVE_COMPLETION,
    'lookback_ms':86_400_000,'max_envelopes':64,'max_decoded_bytes':2_000_000,
    'max_records':100_000,'max_duration_ms':5000}
CAPS={'lookback_ms':86_400_000,'max_envelopes':64,'max_decoded_bytes':2_000_000,
      'max_records':100_000,'max_duration_ms':10_000}


def _ms(value):return int(datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()*1000)
def _iso(value):return datetime.fromtimestamp(value/1000,timezone.utc).isoformat(timespec='milliseconds')


def validate_scenario(contract,*,market=None):
    from .engine import fingerprint, number
    if not isinstance(contract,dict):raise ValueError('Frozen funding sensitivity contract required')
    original=dict(contract);claimed=original.pop('fingerprint',None)
    if (contract.get('version')!=VERSION or claimed!=fingerprint(original)
            or contract.get('interval_ms')!=HOUR or contract.get('currency')!='USDC'
            or contract.get('classification')!='chosen_cost_sensitivity_not_physical_bound'
            or contract.get('rule')!='adverse_symmetric_sample_envelope'
            or contract.get('promotion_authorized') is not False
            or contract.get('administrative_completion')!=ADMINISTRATIVE_COMPLETION
            or contract.get('settlement_clock')!='nominal_utc_hour_pre_boundary_inventory_v1'
            or type(contract.get('available_ms')) is not int or contract['available_ms']<0
            or not isinstance(contract.get('market'),str) or not contract['market']
            or (market is not None and contract['market']!=market)
            or number(contract.get('debit_usdc_per_base_unit'))<=0
            or not contract.get('evidence_refs') or not contract.get('source_periods')):
        raise ValueError('Verified positive, nonpromoting chosen funding sensitivity required')
    return contract


def build_scenario(store,witness_contract,*,network,address,market,cutoff_ms,policy=None):
    """Select at most 64 recent envelopes, verify at most 2MB total, no provider.

    Source accounts are guarded before EACH payload selection. The maximum is
    merely the declared future sensitivity parameter; no rounding guarantee,
    confidence bound or stable future rate is inferred from this sample.
    """
    from .engine import canonical,fingerprint,number
    from .funding_witnesses import validate_contract,_verify_market
    from .population_local_join import _decode_verified
    from .research_memory import authorized_account_history
    from .discovery import protected_addresses
    if policy is not None and not isinstance(policy,dict):raise ValueError('Structured funding sensitivity policy required')
    effective={**DEFAULT_POLICY,**(policy or {})}
    if not isinstance(effective.get('version'),str) or not effective['version'] or effective.get('promotion_authorized') is not False or effective.get('administrative_completion')!=ADMINISTRATIVE_COMPLETION:
        raise ValueError('Versioned explicitly nonpromoting sensitivity policy required')
    if any(type(effective.get(key)) is not int or not 1<=effective[key]<=cap for key,cap in CAPS.items()):
        raise ValueError('Funding sensitivity read bounds exceed approved envelope')
    if type(cutoff_ms) is not int or cutoff_ms<0:raise ValueError('Explicit causal calibration cutoff required')
    validate_contract(witness_contract,network=network,market=market,address=address)
    if witness_contract['available_ms']>cutoff_ms:raise ValueError('Funding witness contract is not yet available')
    deadline=monotonic()+effective['max_duration_ms']/1000
    def check():
        if monotonic()>=deadline:raise ValueError('Funding calibration preparation time bound exceeded')
    _verify_market(store,witness_contract);check()
    accounts=list(dict.fromkeys([address.lower(),*witness_contract['addresses']]))
    lower=max(0,cutoff_ms-effective['lookback_ms']);metadata=[]
    for account in accounts:
        check()
        if account in protected_addresses(store) or not authorized_account_history(store,network,account,cutoff_ms):continue
        tracked=store.connection.execute("select added_at from candidates where network=? and address=? and status='tracked'",(network,account)).fetchone()
        if tracked is None or _ms(tracked[0])>cutoff_ms:continue
        store.connection.set_progress_handler(lambda:int(monotonic()>=deadline),10000)
        try:
            rows=store.connection.execute('select observation_id,entity_id,observed_at,requested_at,response_sha256,length(response_json) encoded_bytes '
                "from raw_observations where network=? and source='hyperliquid-websocket-v1' "
                "and entity_type='account' and entity_id=? and endpoint='userFundings' "
                'and observed_at>=? and observed_at<=? and requested_at<=? '
                'order by observation_id desc limit ?',
                (network,account,_iso(lower),_iso(cutoff_ms),_iso(cutoff_ms),effective['max_envelopes'])).fetchall()
        except sqlite3.OperationalError as exc:
            if monotonic()>=deadline:
                raise ValueError('Funding calibration metadata preparation time bound exceeded') from exc
            raise
        finally:store.connection.set_progress_handler(None,0)
        metadata.extend(rows)
    metadata=sorted(metadata,key=lambda row:row['observation_id'],reverse=True)[:effective['max_envelopes']]
    decoded_bytes=records=0;samples=[];manifests=[];periods=[]
    for meta in metadata:
        check();account=meta['entity_id']
        if account in protected_addresses(store) or not authorized_account_history(store,network,account,cutoff_ms):continue
        if meta['encoded_bytes']>effective['max_decoded_bytes']:
            raise ValueError('Funding calibration encoded/decoded byte bound exceeded')
        row=store.connection.execute(
            "select * from raw_observations where observation_id=? and network=? and source='hyperliquid-websocket-v1' "
            "and entity_type='account' and entity_id=? and endpoint='userFundings' and length(response_json)<=? "
            'and observed_at=? and requested_at=? and observed_at<=? and requested_at<=?',
            (meta['observation_id'],network,account,effective['max_decoded_bytes'],
             meta['observed_at'],meta['requested_at'],_iso(cutoff_ms),_iso(cutoff_ms))).fetchone()
        if row is None or row['response_sha256']!=meta['response_sha256']:raise ValueError('Funding calibration archive identity changed')
        payload,size=_decode_verified(row,max_decoded_bytes=effective['max_decoded_bytes'],with_size=True)
        decoded_bytes+=size
        if decoded_bytes>effective['max_decoded_bytes']:raise ValueError('Funding calibration aggregate decoded-byte bound exceeded')
        data=payload.get('data',{}) if isinstance(payload,dict) else {}
        if (not isinstance(payload,dict) or payload.get('channel')!='userFundings'
                or not isinstance(data,dict) or not isinstance(data.get('user'),str)
                or data['user'].lower()!=account):raise ValueError('Funding calibration sender/channel mismatch')
        values=data.get('fundings',[])
        if not isinstance(values,list):raise ValueError('Structured settled funding rows required')
        records+=len(values)
        if records>effective['max_records']:raise ValueError('Funding calibration record bound exceeded')
        available=max(_ms(row['requested_at']),_ms(row['observed_at']))
        ref='raw_observations:'+str(row['observation_id'])
        period={'network':network,'address':account,'market':'*','start_ms':0,'end_ms':available+1}
        if period not in periods:periods.append(period)
        manifests.append({'evidence_ref':ref,'response_sha256':row['response_sha256'],
            'available_ms':available,'source_period':period})
        for index,value in enumerate(values):
            if index%256==0:check()
            if not isinstance(value,dict) or value.get('coin')!=market:continue
            stamp=value.get('time')
            if type(stamp) is not int or not lower<=stamp<=cutoff_ms or stamp>_ms(row['requested_at']):continue
            if 'szi' not in value or 'usdc' not in value:continue
            units=number(value['szi'])
            if not units:continue
            with localcontext() as arithmetic:
                arithmetic.prec=28;arithmetic.rounding=ROUND_HALF_EVEN
                coefficient=number(value['usdc'])/units
            samples.append({'coefficient':str(coefficient),'quoted_usdc':str(value['usdc']),
                'quoted_szi':str(value['szi']),'reported_ms':stamp,'scheduled_ms':stamp//HOUR*HOUR,
                'evidence_ref':ref,'response_sha256':row['response_sha256'],
                'row_index':index,'source_address':account})
    # Every guarded envelope has a zero-based account-wide source interval.
    # Their exact union is one longest prefix per source, not one copy per lot.
    union={}
    for period in periods:
        key=(period['network'],period['address'],period['market'],period['start_ms'])
        if key not in union or period['end_ms']>union[key]['end_ms']:union[key]=period
    periods=[union[key] for key in sorted(union)]
    coverage={'lookback_ms':effective['lookback_ms'],'event_start_ms':lower,'event_end_ms':cutoff_ms,
        'selection':'latest archived envelopes by observation_id before cutoff; exact market rows in final24h only',
        'envelopes_selected':len(metadata),'envelopes_verified':len(manifests),'decoded_bytes':decoded_bytes,
        'funding_rows_seen':records,'matching_coefficients':len(samples),'exhaustive_history_proven':False}
    if not samples:return {'contract':None,'reason':'no_verified_same_market_settled_coefficients','coverage':coverage,'evidence_refs':[],'source_periods':periods}
    maximum=max(samples,key=lambda sample:(abs(number(sample['coefficient'])),canonical(sample)))
    debit=abs(number(maximum['coefficient']))
    if not debit:return {'contract':None,'reason':'no_positive_observed_debit_sensitivity','coverage':coverage,'evidence_refs':[],'source_periods':periods}
    slots={}
    for sample in samples:
        slots.setdefault(sample['scheduled_ms'],set()).add(number(sample['coefficient']))
    conflicts=[{'scheduled_ms':slot,'distinct_signed_coefficients':len(values),
                'exact_coefficients_fingerprint':fingerprint([str(value.normalize()) for value in sorted(values)])}
               for slot,values in sorted(slots.items()) if len(values)>1]
    refs=list(dict.fromkeys([*witness_contract['evidence_refs'],*[m['evidence_ref'] for m in manifests]]))
    from .position_projection import compact_records
    manifest_table=compact_records(manifests,scalar_maps_as_cells=False)
    contract={'version':VERSION,'market':market,'network':network,'currency':'USDC','interval_ms':HOUR,
        'available_ms':cutoff_ms,'classification':'chosen_cost_sensitivity_not_physical_bound',
        'rule':'adverse_symmetric_sample_envelope','promotion_authorized':False,
        'administrative_completion':ADMINISTRATIVE_COMPLETION,
        'settlement_clock':'nominal_utc_hour_pre_boundary_inventory_v1',
        'debit_usdc_per_base_unit':str(debit),'policy_fingerprint':fingerprint(effective),
        'calibration':{**coverage,'arithmetic':{'decimal_precision':28,'decimal_rounding':'ROUND_HALF_EVEN',
            'meaning':'Ratio of printed amount/size under declared Decimal arithmetic, not venue precision or a physical rate bound'},
            'minimum_signed_coefficient':str(min(number(s['coefficient']) for s in samples)),
            'maximum_signed_coefficient':str(max(number(s['coefficient']) for s in samples)),
            'exact_sample_fingerprint':fingerprint(samples),'maximum_producing_sample':maximum,
            'coefficient_disputes':conflicts,'source_manifests':manifest_table},
        'evidence_refs':refs,'source_periods':periods,
        'limits':['Chosen symmetric debit sensitivity, not a measured future rate, physical bound or venue rounding claim.',
            'Every nominal hour debits absolute OUR pre-boundary position; no funding credit is assumed.',
            'Raw signed observations, disagreements, actual timestamps and source scope remain independently preserved.',
            'A scenario result cannot select a final reserve or authorize paper or promotion.']}
    contract['fingerprint']=fingerprint(contract);validate_scenario(contract,market=market);check()
    return {'contract':contract,'evidence_refs':refs,'source_periods':periods,'coverage':coverage}


def apply_through(state,spec,now,stress):
    """Advance chosen model cash only; do not create execution-triggering events."""
    from .engine import number
    contract=spec['execution']['funding_sensitivity_scenario']
    ledger=state.setdefault('funding_sensitivity_ledger',[])
    if 'funding_sensitivity_next_ms' not in state:
        start=state.get('funding_sensitivity_window',{}).get('start_ms',now)
        state['funding_sensitivity_next_ms']=(start+HOUR-1)//HOUR*HOUR
    boundary=state['funding_sensitivity_next_ms']
    if now>=boundary and (now-boundary)//HOUR>100_000:raise ValueError('Sensitivity settlement resource bound exceeded')
    while boundary<=now:
        position=sum((number(fill['size']) for fill in state['fills'] if fill['received_ms']<boundary),Decimal(0))
        debit=-abs(position)*number(contract['debit_usdc_per_base_unit'])*stress
        state['cash']=str(number(state['cash'])+debit);state['funding']=str(number(state['funding'])+debit)
        if debit and state['equity_curve']:
            state['equity_curve'].append([boundary,str(number(state['equity_curve'][-1][1])+debit)])
        ledger.append({'scheduled_ms':boundary,'inventory_before_boundary':str(position),
            'model_debit_usdc':str(debit),'stress_multiplier':str(stress),'observed_settlement':False})
        boundary+=HOUR
    state['funding_sensitivity_next_ms']=boundary

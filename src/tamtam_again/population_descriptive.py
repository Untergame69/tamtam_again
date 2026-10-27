"""Deterministic descriptive summaries from already archived, authorized account observations."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

from .engine import canonical, fingerprint
from .storage import decode_observation_payload
from .research_memory import authorized_account_history
from .hype_diagnostics import start_position_chain_summary


VERSION = 'population-descriptive-summary-v1'
FILL_ENDPOINTS = ('userFills', 'userFillsByTime')


def _event_time(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(timespec='milliseconds')


def _d(value):
    return Decimal(str(value))


def _fill_identity(fill):
    return str(fill.get('tid')) if fill.get('tid') is not None else None


def _decode_verified(row):
    payload = decode_observation_payload(row)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if hashlib.sha256(encoded).hexdigest() != row['response_sha256']:
        raise ValueError(f"Archived observation integrity check failed: {row['observation_id']}")
    return payload


def _get_fill_array(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get('data'), dict):
            return payload['data'].get('fills', [])
        return payload.get('fills', payload.get('data', []))
    return []


def _load_fills(store, network, address, cutoff_ms):
    cutoff_utc = _event_time(cutoff_ms)
    rows = store.connection.execute(
        "select * from raw_observations where network=? and source='hyperliquid-population-rest-v1' "
        "and entity_type='account' and entity_id=? and endpoint in ('userFills','userFillsByTime') "
        "and observed_at<=? and (window_end_ms is null or window_end_ms<=?) order by observation_id",
        (network, address, cutoff_utc, cutoff_ms)).fetchall()
    by_tid = defaultdict(list)
    all_rows = 0
    records_after_cutoff = 0
    missing_identity = 0
    refs = []
    page_statuses = Counter()
    for row in rows:
        payload = _decode_verified(row)
        fills = _get_fill_array(payload)
        all_rows += len(fills)
        request = json.loads(row['request_json'] or '{}')
        page_statuses[request.get('pagination_status', 'unknown')] += 1
        refs.append({'kind': 'raw_observation', 'id': str(row['observation_id']),
            'endpoint': row['endpoint'], 'sha256': row['response_sha256'],
            'observed_at': row['observed_at'], 'window_start_ms': row['window_start_ms'],
            'window_end_ms': row['window_end_ms'], 'record_count': row['record_count'],
            'complete': bool(row['complete']), 'pagination_status': request.get('pagination_status', 'unknown')})
        for fill in fills:
            if not isinstance(fill, dict):
                missing_identity += 1
                continue
            tid = _fill_identity(fill)
            if tid is None:
                missing_identity += 1
                continue
            if type(fill.get('time')) is not int:
                missing_identity += 1
                continue
            if fill['time'] > cutoff_ms:
                records_after_cutoff += 1
                continue
            by_tid[tid].append(fill)

    fills = []
    duplicate_instances = 0
    conflicts = []
    for tid, variants in sorted(by_tid.items()):
        canonical_variants = {canonical(v) for v in variants}
        duplicate_instances += len(variants) - 1
        if len(canonical_variants) != 1:
            conflicts.append(tid)
            continue
        fills.append(variants[0])
    fills.sort(key=lambda row: (row['time'], str(row['coin']), str(row['tid'])))
    event_times = [f['time'] for f in fills]
    coverage = {
        'raw_observation_count': len(rows), 'decoded_record_count': all_rows,
        'unique_fill_id_count': len(by_tid), 'usable_unique_fill_count': len(fills),
        'duplicate_fill_instances': duplicate_instances, 'conflicting_fill_identity_count': len(conflicts),
        'conflicting_fill_id_examples': conflicts[:20], 'rows_missing_identity_or_time': missing_identity,
        'records_after_cutoff_excluded': records_after_cutoff,
        'first_observed_at': rows[0]['observed_at'] if rows else None,
        'last_observed_at': rows[-1]['observed_at'] if rows else None,
        'first_fill_event_ms': min(event_times) if event_times else None,
        'last_fill_event_ms': max(event_times) if event_times else None,
        'first_fill_event_utc': _event_time(min(event_times)) if event_times else None,
        'last_fill_event_utc': _event_time(max(event_times)) if event_times else None,
        'unbounded_request_window_count': sum(row['window_end_ms'] is None for row in rows),
        'raw_observation_complete_true_count': sum(bool(row['complete']) for row in rows),
        'raw_observation_complete_false_count': sum(not bool(row['complete']) for row in rows),
        'pagination_status_counts': dict(sorted(page_statuses.items())),
        'retention_proven': False,
        'continuity_proven': False,
        'note': ('Counts are deduplicated observations within archived request windows, not an exhaustive account history. '
            'REST recorder marks source pages incomplete; page exhaustion is not retention proof.')}
    return fills, coverage, refs


def _load_funding(store, network, address, cutoff_ms):
    cutoff_utc = _event_time(cutoff_ms)
    rows = store.connection.execute(
        "select * from raw_observations where network=? and source='hyperliquid-population-rest-v1' "
        "and entity_type='account' and entity_id=? and endpoint='userFunding' and observed_at<=? "
        "and (window_end_ms is null or window_end_ms<=?) order by observation_id",
        (network, address, cutoff_utc, cutoff_ms)).fetchall()
    unique = {}
    refs = []
    page_statuses = Counter()
    raw_count = 0
    after_cutoff = 0
    for row in rows:
        payload = _decode_verified(row)
        values = payload if isinstance(payload, list) else payload.get('fundings', []) if isinstance(payload, dict) else []
        raw_count += len(values)
        request = json.loads(row['request_json'] or '{}')
        page_statuses[request.get('pagination_status', 'unknown')] += 1
        refs.append({'kind': 'raw_observation', 'id': str(row['observation_id']),
            'endpoint': row['endpoint'], 'sha256': row['response_sha256'],
            'observed_at': row['observed_at'], 'window_start_ms': row['window_start_ms'],
            'window_end_ms': row['window_end_ms'], 'record_count': row['record_count'],
            'complete': bool(row['complete']), 'pagination_status': request.get('pagination_status', 'unknown')})
        for item in values:
            if not isinstance(item, dict) or type(item.get('time')) is not int:
                continue
            if item['time'] > cutoff_ms:
                after_cutoff += 1
                continue
            delta = item.get('delta') or {}
            coin = delta.get('coin')
            if not isinstance(coin, str):
                continue
            key = (str(item.get('hash')), int(item['time']), coin,
                str(delta.get('usdc')), str(delta.get('szi')))
            unique[key] = {'time_ms': int(item['time']), 'coin': coin,
                'usdc': delta.get('usdc'), 'szi': delta.get('szi'), 'hash': str(item.get('hash'))}
    events = sorted(unique.values(), key=lambda x: (x['time_ms'], x['coin'], x['hash']))
    coverage = {'raw_observation_count': len(rows), 'decoded_record_count': raw_count,
        'deduplicated_event_count': len(events), 'duplicate_event_instances': raw_count-len(events),
        'records_after_cutoff_excluded': after_cutoff,
        'first_observed_at': rows[0]['observed_at'] if rows else None,
        'last_observed_at': rows[-1]['observed_at'] if rows else None,
        'pagination_status_counts': dict(sorted(page_statuses.items())),
        'raw_observation_complete_true_count': sum(bool(row['complete']) for row in rows),
        'raw_observation_complete_false_count': sum(not bool(row['complete']) for row in rows),
        'retention_proven': False, 'continuity_proven': False}
    return events, coverage, refs


def _position_flows(fills):
    """Price cashflows and signed fill fees only for locally bounded flat/reversal legs."""
    chain = start_position_chain_summary(fills, include_fill_events=True)
    cursor = 0
    episodes = []
    right_censored = 0
    left_censored_closures = 0
    for offset in chain['ordered_segment_event_offsets']:
        events = chain['ordered_segment_fill_events'][cursor:cursor + offset['event_count']]
        cursor += offset['event_count']
        active = None

        def begin(fill):
            return {'start_ms': int(fill['time']), 'entry_tid': str(fill['tid']), 'parts': []}

        def add_part(ep, fill, qty, role):
            full = _d(fill['sz'])
            px = _d(fill['px'])
            fee = _d(fill['fee']) * qty / full if fill.get('fee') is not None and full else None
            ep['parts'].append({'tid': str(fill['tid']), 'side': fill['side'], 'qty': qty,
                'px': px, 'cash': -px*qty if fill['side']=='B' else px*qty,
                'fee': fee, 'fee_token': fill.get('feeToken'), 'role': role})

        def finish(ep, fill, close_type):
            buy = sum((p['qty'] for p in ep['parts'] if p['side']=='B'), Decimal(0))
            sell = sum((p['qty'] for p in ep['parts'] if p['side']=='A'), Decimal(0))
            buy_notional = sum((p['px']*p['qty'] for p in ep['parts'] if p['side']=='B'), Decimal(0))
            sell_notional = sum((p['px']*p['qty'] for p in ep['parts'] if p['side']=='A'), Decimal(0))
            fees=defaultdict(Decimal); missing=0
            for p in ep['parts']:
                if p['fee'] is None: missing+=1
                else: fees[str(p['fee_token'] or 'unknown')] += p['fee']
            episodes.append({'start_ms':ep['start_ms'],'end_ms':int(fill['time']),
                'entry_tid':ep['entry_tid'],'exit_tid':str(fill['tid']),'close_type':close_type,
                'fill_part_count':len(ep['parts']),'buy_quantity':str(buy),'sell_quantity':str(sell),
                'buy_notional_quote_units':str(buy_notional),'sell_notional_quote_units':str(sell_notional),
                'price_result_quote_units':str(sell_notional-buy_notional),
                'signed_fees_by_token':{k:str(v) for k,v in sorted(fees.items())},
                'fee_part_missing_count':missing})

        for event in events:
            fill=event['fill']; pre=_d(event['pre_position']); post=_d(event['post_position']); size=_d(fill['sz'])
            if pre*post<0:
                close_qty=abs(pre); open_qty=abs(post)
                if active is None:
                    left_censored_closures+=1
                else:
                    add_part(active,fill,close_qty,'inversion_close')
                    finish(active,fill,'position_reversal')
                active=begin(fill)
                add_part(active,fill,open_qty,'inversion_open')
            elif pre==0 and post!=0:
                if active is not None:
                    right_censored+=1
                active=begin(fill)
                add_part(active,fill,size,'fill')
            elif pre!=0 and post==0:
                if active is None:
                    left_censored_closures+=1
                else:
                    add_part(active,fill,size,'flat_close')
                    finish(active,fill,'returned_to_zero')
                    active=None
            elif active is not None:
                add_part(active,fill,size,'fill')
        if active is not None:
            right_censored+=1
    return chain, episodes, {'right_censored_open_episode_count':right_censored,
        'left_censored_close_count':left_censored_closures}


def _market_summaries(fills, funding_events, declared_scope_markets):
    by_market=defaultdict(list)
    for fill in fills:
        market=fill.get('coin')
        if isinstance(market,str):by_market[market].append(fill)
    funding_by_market=defaultdict(list)
    for event in funding_events:funding_by_market[event['coin']].append(event)
    output={}
    for market in sorted(set(by_market)|set(funding_by_market)):
        rows=by_market.get(market,[])
        chain,episodes,censored=_position_flows(rows) if rows else ({},[],{})
        ruptures=chain.get('position_chain_ruptures',[])
        invalid=chain.get('invalid_timestamp_groups',[])
        fees=defaultdict(Decimal); missing_fee=0
        for fill in rows:
            if fill.get('fee') is None:missing_fee+=1
            else:fees[str(fill.get('feeToken') or 'unknown')]+=_d(fill['fee'])
        bounded_fees=defaultdict(Decimal)
        for ep in episodes:
            for token,value in ep['signed_fees_by_token'].items():bounded_fees[token]+=_d(value)
        archive_fees={k:str(v) for k,v in sorted(fees.items())}
        residual_fees={k:str(v-bounded_fees.get(k,Decimal(0))) for k,v in sorted(fees.items())}

        # Funding is attributed only where one bounded local episode and exact
        # pre-event position agree. All other events remain explicitly unassigned.
        timeline=[]
        if chain:
            timeline=[{'time':int(e['fill']['time']),'post':_d(e['post_position'])}
                for e in chain.get('ordered_segment_fill_events',[])]
        attributed=[]; unmatched=Counter(); unmatched_amount=defaultdict(Decimal)
        by_episode=Counter(); episode_positions=[]
        for ep_index,ep in enumerate(episodes):episode_positions.append((ep['start_ms'],ep['end_ms'],ep_index))
        for fund in funding_by_market.get(market,[]):
            stamp=fund['time_ms']; candidates=[i for start,end,i in episode_positions if start<stamp<end]
            amount=_d(fund['usdc'] or 0)
            if len(candidates)!=1:
                reason='outside_or_multiple_bounded_episodes'
            else:
                prior=[f for f in timeline if f['time']<stamp]
                exact_time=any(f['time']==stamp for f in timeline)
                if exact_time or not prior:reason='no_strict_prior_position_observation'
                else:
                    position=prior[-1]['post']
                    try:fund_position=_d(fund['szi'])
                    except Exception:fund_position=None
                    if fund_position is None or fund_position!=position:reason='funding_position_mismatch'
                    else:
                        reason=None;attributed.append(fund);by_episode[candidates[0]]+=1
            if reason:
                unmatched[reason]+=1;unmatched_amount[reason]+=amount
        fundings=funding_by_market.get(market,[])
        output[market]={
            'scope_membership':('listed_by_available_scope_report' if market in declared_scope_markets
                else 'observed_in_fill_archive_but_not_listed_by_available_scope_report'),
            'activity':{'unique_fill_count':len(rows),'first_fill_event_ms':min((f['time'] for f in rows),default=None),
                'last_fill_event_ms':max((f['time'] for f in rows),default=None),
                'maker_fill_count':sum(f.get('crossed') is False for f in rows),
                'taker_fill_count':sum(f.get('crossed') is True for f in rows),
                'crossed_unknown_count':sum(f.get('crossed') is None for f in rows)},
            'positions':{'unique_fills_with_start_position':chain.get('unique_fills_with_start_position',0),
                'fills_skipped_missing_position_fields':chain.get('fills_skipped_missing_position_fields',0),
                'timestamp_groups':chain.get('timestamp_groups',0),
                'ambiguous_timestamp_groups':chain.get('ambiguous_timestamp_groups',0),
                'invalid_timestamp_group_count':len(invalid),
                'invalid_timestamp_group_examples':invalid[:5]+invalid[-5:] if len(invalid)>10 else invalid,
                'invalid_timestamp_groups_fingerprint':fingerprint(invalid),
                'position_chain_segments':chain.get('position_chain_segments',[]),
                'position_chain_rupture_count':len(ruptures),
                'position_chain_rupture_examples':ruptures[:5]+ruptures[-5:] if len(ruptures)>10 else ruptures,
                'position_chain_ruptures_fingerprint':fingerprint(ruptures),
                'locally_reconstructible_flat_to_flat_episode_count':chain.get('locally_reconstructible_flat_to_flat_episode_count',0),
                **censored,'unknown_completeness':True},
            'price_result':{'currency':'market quote units; not converted or summed across markets',
                'bounded_episode_count':len(episodes),
                'return_to_zero_count':sum(e['close_type']=='returned_to_zero' for e in episodes),
                'position_reversal_count':sum(e['close_type']=='position_reversal' for e in episodes),
                'buy_quantity':str(sum((_d(e['buy_quantity']) for e in episodes),Decimal(0))),
                'sell_quantity':str(sum((_d(e['sell_quantity']) for e in episodes),Decimal(0))),
                'buy_notional_quote_units':str(sum((_d(e['buy_notional_quote_units']) for e in episodes),Decimal(0))),
                'sell_notional_quote_units':str(sum((_d(e['sell_notional_quote_units']) for e in episodes),Decimal(0))),
                'price_result_quote_units':str(sum((_d(e['price_result_quote_units']) for e in episodes),Decimal(0))),
                'episodes_fingerprint':fingerprint(episodes),
                'episode_examples_first_2':episodes[:2],
                'episode_examples_last_2':episodes[-2:] if len(episodes)>2 else []},
            'signed_fees':{'basis':'archived signed fee field; reported separately from price result',
                'fill_count_with_fee':len(rows)-missing_fee,'fill_count_missing_fee':missing_fee,
                'archive_fill_signed_fee_by_token':archive_fees,
                'bounded_episode_part_signed_fee_by_token':{k:str(v) for k,v in sorted(bounded_fees.items())},
                'observed_fee_outside_bounded_episode_parts_by_token':residual_fees},
            'funding':{'currency':'USDC field as archived','observed_event_count':len(fundings),
                'observed_amount_usdc':str(sum((_d(e['usdc'] or 0) for e in fundings),Decimal(0))),
                'strictly_position_attributed_event_count':len(attributed),
                'strictly_position_attributed_amount_usdc':str(sum((_d(e['usdc'] or 0) for e in attributed),Decimal(0))),
                'unattributed_event_count':sum(unmatched.values()),
                'unattributed_amount_usdc_by_reason':{k:str(v) for k,v in sorted(unmatched_amount.items())},
                'continuity_unknown':True}}
    return output


def prepare_candidate_summary(store, network, address, *, cutoff_ms, candidate=None):
    """Build a stable, cutoff-bound summary without acquisition or external calls."""
    address=address.lower()
    if type(cutoff_ms) is not int or cutoff_ms<0:
        raise ValueError('Explicit nonnegative archive cutoff required')
    if not authorized_account_history(store,network,address,cutoff_ms):
        raise PermissionError('Account archives intersect an unreleased reserved period at cutoff')
    report_row=store.connection.execute('select report_id,available_ms,payload_json from account_scope_reports '
        'where network=? and address=? and available_ms<=? order by available_ms desc,rowid desc limit 1',
        (network,address,cutoff_ms)).fetchone()
    if not report_row:
        raise ValueError('No authorized account-scope report available at cutoff')
    report=json.loads(report_row['payload_json'])
    report_hash=hashlib.sha256(report_row['payload_json'].encode('utf-8')).hexdigest()
    fills,fill_coverage,fill_refs=_load_fills(store,network,address,cutoff_ms)
    funding,funding_coverage,funding_refs=_load_funding(store,network,address,cutoff_ms)
    scope_profile=report.get('current_pass_behavior_profile') or {}
    summary={
        'schema_version':VERSION,'candidate':candidate,'network':network,'address':address,
        'cutoff_ms':cutoff_ms,'scope_report':{'report_id':report_row['report_id'],
            'available_ms':report_row['available_ms'],'sha256':report_hash,
            'single_report_observed_unique_fills':(report.get('activity') or {}).get('observed_unique_fills'),
            'single_report_window_seconds':(report.get('activity') or {}).get('window_seconds'),
            'single_report_fill_request_start_ms':report.get('fills_requested_start_ms'),
            'single_report_fill_request_end_ms':report.get('fills_requested_end_ms'),
            'declared_markets':report.get('markets',[]),
            'profile_evidence_refs':scope_profile.get('evidence_refs',[]),
            'profile_fills_observed':scope_profile.get('fills_observed')},
        'coverage':{'account_history_authorized_at_cutoff':True,'fill_archive':fill_coverage,
            'funding_archive':funding_coverage},
        'markets':_market_summaries(fills,funding,set(report.get('markets',[]))),
        'evidence_refs':[f"account_scope_reports:{report_row['report_id']}#sha256:{report_hash}",
            *[f"raw_observations:{row['id']}#sha256:{row['sha256']}"
                for row in fill_refs+funding_refs]],
        'limits':['Archive coverage is bounded by the recorded REST requests; no retention prefix or continuous-history claim.',
            'Position chains are local arithmetic reconstructions only; listed ruptures are not bridged.',
            'Price results include only locally bounded flat-to-flat or reversal episodes, in each market quote unit.',
            'Signed fees remain in their archived fee token and are not merged with price result.',
            'Funding remains separate in the archived USDC field; only exact strict-interior position matches are attributed.',
            'No trader intent, unfilled orders, queue priority or external hedge is inferred.']}
    summary['evidence_fingerprint']=fingerprint({'version':VERSION,'network':network,'address':address,
        'cutoff_ms':cutoff_ms,'evidence_refs':summary['evidence_refs']})
    summary['summary_fingerprint']=fingerprint(summary)
    return summary


def prepare_candidate_market_detail(store, network, address, *, cutoff_ms, market):
    """Prepare a reusable, cutoff-bound detail for one declared market.

    This describes observed executions and locally coherent position paths; it
    cannot reconstruct quote placement or unfilled/cancelled orders.
    """
    if not isinstance(market,str) or not market:
        raise ValueError('An exact market symbol is required')
    if not authorized_account_history(store,network,address.lower(),cutoff_ms):
        raise PermissionError('Account history intersects an unreleased reserved period at cutoff')
    fills,coverage,refs=_load_fills(store,network,address.lower(),cutoff_ms)
    fills=[f for f in fills if f.get('coin')==market]
    chain=start_position_chain_summary(fills,include_fill_events=True)
    ordered=chain.get('ordered_segment_fill_events',[])
    offsets=chain.get('ordered_segment_event_offsets',[])
    segment_events=[];cursor=0;episode_rows=[]
    for segment in offsets:
        events=ordered[cursor:cursor+segment['event_count']];cursor+=segment['event_count']
        segment_events.append((segment['segment'],events))

    def blank():
        return {'fill_count':0,'size':'0','notional_quote_units':'0','signed_fees_by_token':{},
            'maker_fill_count':0,'taker_fill_count':0,'crossed_unknown_count':0,
            'position_increase_fill_count':0,'position_reduction_fill_count':0,
            'position_neutral_fill_count':0,'reversal_fill_count':0,
            'reversal_close_quantity':'0','reversal_open_quantity':'0',
            'crossed_fee_groups':{key:{'fill_count':0,'size':'0','signed_fees_by_token':{}}
                for key in ('maker_crossed_false','taker_crossed_true','crossed_unknown')}}
    all_effects=blank();by_day=defaultdict(blank);by_segment={}
    fee_acc=defaultdict(Decimal);size_values=[]
    for segment_no,events in segment_events:
        seg=blank();seg_fills=[e['fill'] for e in events]
        _,episodes,_=_position_flows(seg_fills)
        # TIDs are unique within a reconstructed segment. Build the lookup once;
        # rebuilding and scanning it for every episode is quadratic on active accounts.
        event_index_by_tid={str(e['fill']['tid']):index for index,e in enumerate(events)}
        for ep in episodes:
            ep['segment']=segment_no
            ep['duration_ms']=int(ep['end_ms'])-int(ep['start_ms'])
            try:
                first=event_index_by_tid[ep['entry_tid']];last=event_index_by_tid[ep['exit_tid']]
                if last < first:
                    raise ValueError('Episode exit precedes its entry')
                path_events=events[first:last+1]
                ep['peak_abs_position']=str(max((_d(e['pre_position']).copy_abs() for e in path_events),
                    default=Decimal(0)))
                ep['peak_abs_position']=str(max(_d(ep['peak_abs_position']),max((_d(e['post_position']).copy_abs()
                    for e in path_events),default=Decimal(0))))
            except (KeyError,ValueError):ep['peak_abs_position']=None
        episode_rows.extend(episodes)
        ep_fees=defaultdict(Decimal)
        for ep in episodes:
            for token,value in ep['signed_fees_by_token'].items():ep_fees[token]+=_d(value)
        by_segment[str(segment_no)]={'start_ms':min((int(e['fill']['time']) for e in events),default=None),
            'end_ms':max((int(e['fill']['time']) for e in events),default=None),
            'fill_count':len(events),'bounded_episode_count':len(episodes),
            'bounded_episode_return_to_zero_count':sum(ep['close_type']=='returned_to_zero' for ep in episodes),
            'bounded_episode_reversal_count':sum(ep['close_type']=='position_reversal' for ep in episodes),
            'bounded_episode_price_result_quote_units':str(sum((_d(ep['price_result_quote_units'])
                for ep in episodes),Decimal(0))),
            'bounded_episode_signed_fees_by_token':{k:str(v) for k,v in sorted(ep_fees.items())},
            'bounded_episode_fingerprint':fingerprint(episodes),
            'bounded_episode_examples_first_2':episodes[:2],
            'bounded_episode_examples_last_2':episodes[-2:] if len(episodes)>2 else []}
        for event in events:
            fill=event['fill'];pre=_d(event['pre_position']);post=_d(event['post_position'])
            qty=_d(fill['sz']);px=_d(fill['px']);fee=fill.get('fee');token=str(fill.get('feeToken') or 'unknown')
            day=datetime.fromtimestamp(int(fill['time'])/1000,timezone.utc).date().isoformat()
            same=[all_effects,seg,by_day[day]]
            signed_delta=abs(post)-abs(pre)
            fee_group=('maker_crossed_false' if fill.get('crossed') is False else
                'taker_crossed_true' if fill.get('crossed') is True else 'crossed_unknown')
            for agg in same:
                agg['fill_count']+=1;agg['size']=str(_d(agg['size'])+qty)
                agg['notional_quote_units']=str(_d(agg['notional_quote_units'])+qty*px)
                if fill.get('crossed') is False:agg['maker_fill_count']+=1
                elif fill.get('crossed') is True:agg['taker_fill_count']+=1
                else:agg['crossed_unknown_count']+=1
                if signed_delta>0:agg['position_increase_fill_count']+=1
                elif signed_delta<0:agg['position_reduction_fill_count']+=1
                else:agg['position_neutral_fill_count']+=1
                if pre*post<0:
                    agg['reversal_fill_count']+=1
                    agg['reversal_close_quantity']=str(_d(agg['reversal_close_quantity'])+abs(pre))
                    agg['reversal_open_quantity']=str(_d(agg['reversal_open_quantity'])+abs(post))
                if fee is not None:
                    fees=defaultdict(Decimal,{k:_d(v) for k,v in agg['signed_fees_by_token'].items()})
                    fees[token]+=_d(fee);agg['signed_fees_by_token']={k:str(v) for k,v in sorted(fees.items())}
                group=agg['crossed_fee_groups'][fee_group]
                group['fill_count']+=1;group['size']=str(_d(group['size'])+qty)
                if fee is not None:
                    group_fees=defaultdict(Decimal,{k:_d(v) for k,v in group['signed_fees_by_token'].items()})
                    group_fees[token]+=_d(fee)
                    group['signed_fees_by_token']={k:str(v) for k,v in sorted(group_fees.items())}
            if fee is not None:fee_acc[token]+=_d(fee)
            size_values.append(qty)
        by_segment[str(segment_no)]['activity']=seg

    by_segment_day=defaultdict(lambda:{'episode_count':0,'return_to_zero_count':0,'position_reversal_count':0,
        'buy_quantity':'0','sell_quantity':'0','buy_notional_quote_units':'0',
        'sell_notional_quote_units':'0','price_result_quote_units':'0','signed_fees_by_token':{}})
    for ep in episode_rows:
        day=datetime.fromtimestamp(ep['end_ms']/1000,timezone.utc).date().isoformat()
        row=by_segment_day[(str(ep['segment']),day)];row['episode_count']+=1
        if ep['close_type']=='returned_to_zero':row['return_to_zero_count']+=1
        else:row['position_reversal_count']+=1
        for field in ('buy_quantity','sell_quantity','buy_notional_quote_units','sell_notional_quote_units','price_result_quote_units'):
            row[field]=str(_d(row[field])+_d(ep[field]))
        fees=defaultdict(Decimal,{k:_d(v) for k,v in row['signed_fees_by_token'].items()})
        for token,value in ep['signed_fees_by_token'].items():fees[token]+=_d(value)
        row['signed_fees_by_token']={k:str(v) for k,v in sorted(fees.items())}
    # Include zero-episode days for activity and preserve segment boundaries.
    daily={day:{**values,'bounded_episode_results_by_segment':{}}
        for day,values in sorted(by_day.items())}
    for (segment,day),values in sorted(by_segment_day.items()):
        if day in daily:daily[day]['bounded_episode_results_by_segment'][segment]=values
    durations=[int(ep['end_ms'])-int(ep['start_ms']) for ep in episode_rows]
    sizes=sorted(size_values)
    peak_sizes=sorted(_d(e['peak_abs_position']) for e in episode_rows if e.get('peak_abs_position') is not None)
    def quantile(values,q):
        return None if not values else str(values[max(0,(q*len(values)+99)//100-1)])
    result={'schema_version':'population-market-execution-detail-v1','network':network,
        'address':address.lower(),'market':market,'cutoff_ms':cutoff_ms,
        'observed_fill_content_fingerprint':fingerprint(fills),
        'coverage':{'fill_archive':coverage,'selected_market_fill_count':len(fills),
            'position_chain_segment_count':len(segment_events),'rupture_count':len(chain.get('position_chain_ruptures',[])),
            'ruptures_fingerprint':fingerprint(chain.get('position_chain_ruptures',[])),
            'invalid_timestamp_groups':len(chain.get('invalid_timestamp_groups',[])),
            'ambiguous_timestamp_groups':chain.get('ambiguous_timestamp_groups',0),
            'continuity_proven':False},
        'execution_activity':all_effects,
        'position_path':{'segments':by_segment,'ruptures':chain.get('position_chain_ruptures',[]),
            'episodes':{'count':len(episode_rows),'return_to_zero_count':sum(e['close_type']=='returned_to_zero' for e in episode_rows),
                'position_reversal_count':sum(e['close_type']=='position_reversal' for e in episode_rows),
                'duration_ms':{'min':str(min(durations)) if durations else None,'p50':quantile(sorted(durations),50),
                    'p95':quantile(sorted(durations),95),'max':str(max(durations)) if durations else None},
                'peak_abs_position':{'min':str(peak_sizes[0]) if peak_sizes else None,
                    'p50':quantile(peak_sizes,50),'p95':quantile(peak_sizes,95),
                    'max':str(peak_sizes[-1]) if peak_sizes else None},
                'fill_size':{'count':len(sizes),'min':str(min(sizes)) if sizes else None,'p50':quantile(sizes,50),
                    'p95':quantile(sizes,95),'max':str(max(sizes)) if sizes else None},
                'episodes_fingerprint':fingerprint(episode_rows)}},
        'by_utc_day':daily,'fees_signed_by_token':{k:str(v) for k,v in sorted(fee_acc.items())},
        'evidence_refs':[f"raw_observations:{row['id']}#sha256:{row['sha256']}" for row in refs],
        'interpretation_limits':['Fills establish executions, not placement, amendment, cancellation, queue position or unfilled target orders.',
            'Position increase/reduction counts compare abs(startPosition) with the post-fill position; reversals are separately split into closed and opened quantities.',
            'Segments and episodes are local arithmetic reconstructions from incomplete archived request windows; gaps and censored endpoints remain.',
            'Maker/taker grouping uses the archived crossed flag; it does not reveal why or where an order was placed.']}
    result['evidence_fingerprint']=fingerprint({'schema_version':result['schema_version'],
        'network':network,'address':address.lower(),'market':market,'cutoff_ms':cutoff_ms,
        'evidence_refs':result['evidence_refs']})
    result['detail_fingerprint']=fingerprint(result)
    return result


def prepare_inventory_execution_association(store,network,address,*,cutoff_ms,market):
    """Deterministically cross-tab executions against pre-fill inventory.

    Closing/opening quantities split reversals at the recorded pre-position;
    no order-placement inference is made.
    """
    detail=prepare_candidate_market_detail(store,network,address,cutoff_ms=cutoff_ms,market=market)
    fills,coverage,refs=_load_fills(store,network,address.lower(),cutoff_ms)
    fills=[f for f in fills if f.get('coin')==market]
    chain=start_position_chain_summary(fills,include_fill_events=True)
    events=chain.get('ordered_segment_fill_events',[])
    segment_by_event={}
    for segment in chain.get('ordered_segment_event_offsets',[]):
        for i in range(segment['first_event'],segment['first_event']+segment['event_count']):
            segment_by_event[i]=segment['segment']
    nonzero=sorted(_d(e['pre_position']).copy_abs() for e in events if _d(e['pre_position'])!=0)
    def nearest_rank(q):
        if not nonzero:return None
        i=max(0,(q*len(nonzero)+99)//100-1)
        return nonzero[min(i,len(nonzero)-1)]
    cuts={'q25':nearest_rank(25),'q50':nearest_rank(50),'q75':nearest_rank(75)}
    def bucket(pre):
        mag=_d(pre).copy_abs()
        if mag==0:return 'flat'
        if mag<=cuts['q25']:return 'inventory_q1'
        if mag<=cuts['q50']:return 'inventory_q2'
        if mag<=cuts['q75']:return 'inventory_q3'
        return 'inventory_q4'
    def empty():
        return {'fill_count':0,'execution_quantity':'0','close_quantity':'0','open_quantity':'0',
            'reversal_count':0,'reversal_close_quantity':'0','reversal_open_quantity':'0',
            'signed_fees_by_token':{}}
    matrix=defaultdict(empty);by_segment_day=defaultdict(empty)
    for event_index,event in enumerate(events):
        fill=event['fill'];pre=_d(event['pre_position']);post=_d(event['post_position'])
        signed_delta=post-pre;qty=_d(fill['sz']);fee=fill.get('fee')
        if pre==0 or pre*signed_delta>=0:
            close_qty=Decimal(0);open_qty=qty
        else:
            close_qty=min(abs(pre),abs(signed_delta));open_qty=max(Decimal(0),qty-close_qty)
        crossed=('maker_crossed_false' if fill.get('crossed') is False else
            'taker_crossed_true' if fill.get('crossed') is True else 'crossed_unknown')
        side='flat' if pre==0 else 'long' if pre>0 else 'short'
        key=(side,bucket(pre),crossed)
        day=datetime.fromtimestamp(int(fill['time'])/1000,timezone.utc).date().isoformat()
        segment=segment_by_event[event_index]
        for agg in (matrix[key],by_segment_day[(str(segment),day,side,bucket(pre),crossed)]):
            agg['fill_count']+=1;agg['execution_quantity']=str(_d(agg['execution_quantity'])+qty)
            agg['close_quantity']=str(_d(agg['close_quantity'])+close_qty)
            agg['open_quantity']=str(_d(agg['open_quantity'])+open_qty)
            if close_qty and open_qty:
                agg['reversal_count']+=1
                agg['reversal_close_quantity']=str(_d(agg['reversal_close_quantity'])+close_qty)
                agg['reversal_open_quantity']=str(_d(agg['reversal_open_quantity'])+open_qty)
            if fee is not None:
                fees=defaultdict(Decimal,{k:_d(v) for k,v in agg['signed_fees_by_token'].items()})
                fees[str(fill.get('feeToken') or 'unknown')]+=_d(fee)
                agg['signed_fees_by_token']={k:str(v) for k,v in sorted(fees.items())}
    def flatten(rows):
        return [{'position_side':key[0],'inventory_bucket':key[1],'crossed_group':key[2],**value}
            for key,value in sorted(rows.items())]
    result={'schema_version':'population-inventory-execution-association-v1','network':network,
        'address':address.lower(),'market':market,'cutoff_ms':cutoff_ms,
        'source_detail_fingerprint':detail['detail_fingerprint'],
        'coverage':{'observed_market_fills':len(fills),'position_path_events':len(events),
            'segment_count':len(chain.get('position_chain_segments',[])),
            'rupture_count':len(chain.get('position_chain_ruptures',[])),
            'continuity_proven':False,'rows_missing_position_fields':chain.get('fills_skipped_missing_position_fields',0)},
        'inventory_magnitude_quantile_cuts':{k:str(v) if v is not None else None for k,v in cuts.items()},
        'by_position_side_inventory_bucket_and_crossed':flatten(matrix),
        'by_segment_utc_day_inventory_side_bucket_and_crossed':[{'segment':key[0],'utc_day':key[1],
            'position_side':key[2],'inventory_bucket':key[3],'crossed_group':key[4],**value}
            for key,value in sorted(by_segment_day.items())],
        'interpretation_limits':['Descriptive conditional execution frequencies are not causal effects; fills are clustered in a small number of local chains and days.',
            'Crossed groups describe executions only. They do not reveal order placement, cancellation, queue priority or target intent.',
            'Closing and opening quantities use recorded startPosition and executed size; a reversal is split at zero.',
            'Historical request windows are incomplete; the segment rupture and censored endpoints remain unknown.'],
        'evidence_refs':detail['evidence_refs']}
    result['evidence_fingerprint']=fingerprint({'schema_version':result['schema_version'],
        'network':network,'address':address.lower(),'market':market,'cutoff_ms':cutoff_ms,
        'evidence_refs':result['evidence_refs']})
    result['analysis_fingerprint']=fingerprint(result)
    return result


def enrich_research_packet(packet, summary, market_details=None):
    """Return a new packet; historical packets and decisions are never edited."""
    out=deepcopy(packet)
    if out.get('network')!=summary.get('network') or out.get('address','').lower()!=summary.get('address'):
        raise ValueError('Descriptive summary origin differs from packet identity')
    if out.get('available_ms',summary['cutoff_ms']+1)>summary['cutoff_ms']:
        raise ValueError('Packet availability is later than descriptive evidence cutoff')
    out.setdefault('observations',{})['descriptive_history_v1']=summary
    refs=out.setdefault('evidence_refs',[])
    for ref in summary['evidence_refs']:
        if ref not in refs:refs.append(ref)
    detail_fingerprints=[]
    for detail in market_details or []:
        if detail.get('network')!=summary.get('network') or detail.get('address')!=summary.get('address'):
            raise ValueError('Market detail origin differs from packet identity')
        if detail.get('cutoff_ms')!=summary.get('cutoff_ms'):
            raise ValueError('Market detail cutoff differs from descriptive evidence cutoff')
        out.setdefault('observations',{}).setdefault('market_execution_detail_v1',{})[detail['market']]=detail
        for ref in detail['evidence_refs']:
            if ref not in refs:refs.append(ref)
        detail_fingerprints.append(detail['detail_fingerprint'])
    out['research_input_fingerprint']=fingerprint({'base':out.get('research_input_fingerprint'),
        'descriptive_summary_version':VERSION,'summary_fingerprint':summary['summary_fingerprint'],
        'market_execution_detail_fingerprints':detail_fingerprints})
    out.pop('fingerprint',None)
    out['fingerprint']=fingerprint(out)
    return out


def _compact_repeated_reference_lists(packet):
    """Represent repeated reference lists as exact indices into the sealed pool."""
    pool=packet.get('evidence_refs',[])
    indices={ref:index for index,ref in enumerate(pool)}
    observations=packet.get('observations',{})
    sections=[(observations.get('descriptive_history_v1'), 'summary_fingerprint')]
    sections.extend((detail,'detail_fingerprint')
        for detail in observations.get('market_execution_detail_v1',{}).values())
    for section,fingerprint_field in sections:
        if not isinstance(section,dict) or not isinstance(section.get('evidence_refs'),list):
            continue
        refs=section['evidence_refs']
        if any(ref not in indices for ref in refs):
            raise ValueError('Projected evidence reference is absent from the sealed root pool')
        section['source_'+fingerprint_field]=section.pop(fingerprint_field)
        section['evidence_ref_indices']=[indices[ref] for ref in refs]
        section.pop('evidence_refs')
        section['reference_projection']={'version':'sealed-root-reference-indices-v1',
            'reference_pool':'packet.evidence_refs','reference_count':len(refs),
            'ordered_reference_fingerprint':fingerprint(refs),
            'note':'All aggregates retained; each index resolves exactly to the original source reference.'}
        section[fingerprint_field]=fingerprint(section)


def prepare_pilot_packet(store, base_packet, *, candidate, item, pilot_id, policy_version, cutoff_ms,
        local_analysis_report=None, local_analysis_protocol=None):
    """Build the ordinary pilot packet, optionally binding an authorized immutable report.

    The report-derived projection and finite local-analysis contract are added
    before either packet fingerprint is finalized. Callers remain responsible
    for validating the persisted report and its existing authorization first.
    """
    summary=prepare_candidate_summary(store,base_packet['network'],base_packet['address'],
        cutoff_ms=cutoff_ms,candidate=candidate)
    details=[prepare_candidate_market_detail(store,base_packet['network'],base_packet['address'],
        cutoff_ms=cutoff_ms,market=market) for market in item.get('descriptive_markets',[])]
    packet=enrich_research_packet(base_packet,summary,details)
    if (local_analysis_report is None) != (local_analysis_protocol is None):
        raise ValueError('Local-analysis report and protocol metadata must be supplied together')
    local_analysis_contract=None
    if local_analysis_report is not None:
        from .eth_report_projection import project as project_eth_report, semantic_fingerprint
        from .population_local_analysis_contract import contract_for_report, report_reference
        protocol=local_analysis_protocol
        report=local_analysis_report
        required_protocol=('protocol_id','network','address','market','start_ms','end_ms','finalised_ms')
        if not isinstance(protocol,dict) or any(key not in protocol for key in required_protocol):
            raise ValueError('Finalised local-analysis protocol metadata is incomplete')
        if (protocol['network']!=packet.get('network')
                or str(protocol['address']).lower()!=str(packet.get('address','')).lower()
                or protocol['protocol_id']!=report.get('protocol_id')
                or report.get('stage')!='final_24h'):
            raise ValueError('Local-analysis report identity differs from the prepared packet')
        window=report.get('window')
        if window is not None and (not isinstance(window,dict) or
                (window.get('start_ms'),window.get('end_ms')) != (protocol['start_ms'],protocol['end_ms'])):
            raise ValueError('Local-analysis report window differs from its finalised protocol')
        if type(protocol['finalised_ms']) is not int or protocol['finalised_ms'] < protocol['end_ms']:
            raise ValueError('Local-analysis finalisation cutoff is invalid')
        report_ref=report_reference({'protocol_id':protocol['protocol_id'],'stage':report['stage'],
            'semantic_fingerprint':semantic_fingerprint(report)})
        if report_ref not in packet.setdefault('evidence_refs',[]):
            packet['evidence_refs'].append(report_ref)
        local_analysis_contract=contract_for_report(packet=packet,report=report,
            network=protocol['network'],address=protocol['address'],market=protocol['market'],
            start_ms=protocol['start_ms'],end_ms=protocol['end_ms'])
        packet.setdefault('observations',{})['prospective_eth_observation_v1']=project_eth_report(report)
        packet['local_analysis_contract_v1']=local_analysis_contract
        packet['available_ms']=max(packet.get('available_ms',0),protocol['finalised_ms'])
        packet.setdefault('research_contract',{})['purpose']=(
            'compare authorized descriptive history with a completed prospective observation; '
            'archive-only deterministic analysis, no paper, orders, profitability or strategy approval')
    profile=packet.get('observations',{}).get('current_pass_behavior_profile')
    if isinstance(profile,dict):
        # The unprojected profile can contain a large list of every candidate
        # episode. The generic summary above carries comparable aggregate
        # metrics and cryptographic references, so retain a concise pointer to
        # the original profile instead of duplicating its event examples.
        compact=[]
        for row in profile.get('markets',[]):
            if not isinstance(row,dict):continue
            compact.append({k:row[k] for k in ('market','fill_count','maker_fills','taker_fills',
                'observed_orders','orders_with_multiple_fills','history_coverage',
                'candidate_episode_duration_ms') if k in row})
        packet['observations']['current_pass_behavior_profile']={
            'projection_version':'population-profile-summary-projection-v1',
            **{k:profile[k] for k in ('fingerprint','fills_observed','grouping_ms','market_count',
                'evidence_refs','limits') if k in profile},'markets':compact,
            'full_profile_reference':'account_scope_reports:'+summary['scope_report']['report_id']+
                '#sha256:'+summary['scope_report']['sha256'],
            'note':'Per-episode examples omitted from this packet; source report remains verifiable by reference.'}
    if pilot_id is not None:
        packet['pilot_research']={k:item[k] for k in ('candidate','rank','research_interest',
            'observability','paper_engine_compatibility') if k in item}
        if item.get('question'):
            packet['pilot_research']['question']=item['question']
        packet['pilot_research'].update({'pilot_id':pilot_id,'policy_version':policy_version,
            'economic_validation':'false; this is owner-authorized descriptive research only',
            'execution_compatibility_is_separate':True,'promotion_authorized':False,
            'admission_cutoff_ms':cutoff_ms})
    # Keep decision identity bound to source evidence, not its display projection.
    summary_source_fingerprint=summary['summary_fingerprint']
    if len(canonical(packet))>225000:
        _compact_repeated_reference_lists(packet)
    packet['research_input_fingerprint']=fingerprint({'base':packet['research_input_fingerprint'],
        'pilot_id':pilot_id,'candidate':candidate,'question':item.get('question'),
        'descriptive_summary_fingerprint':summary_source_fingerprint,
        'local_analysis_contract_fingerprint':fingerprint(local_analysis_contract) if local_analysis_contract else None,
        'prospective_report_fingerprint':semantic_fingerprint(local_analysis_report)
            if local_analysis_report is not None else None})
    packet.pop('fingerprint',None)
    packet['fingerprint']=fingerprint(packet)
    return packet

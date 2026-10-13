"""Resolve a paper needs-data request from authorized local archives only."""
from __future__ import annotations

import json
from collections import Counter, defaultdict

from .engine import canonical, fingerprint
from .paper import archive_events
from .research_memory import authorized_period
from .validation import now_ms

MAX_PACKET_CHARS = 225_000


def _stable_values(rows, key):
    values=sorted({str(row.get(key)) for row in rows if row.get(key) is not None})
    return {value:index for index,value in enumerate(values)},values


def _local_bundle(store,session,parent_packet,*,max_chars,clock_ms):
    state=json.loads(session['state_json'])
    start_ms=int(session['started_ms']);end_ms=int(state['last_ms'])
    if not start_ms<end_ms:
        raise ValueError('Paper archive interval is empty')
    periods=parent_packet.get('source_periods') or []
    if not periods or any(not authorized_period(store,p,clock_ms,end_inclusive=True) for p in periods):
        raise ValueError('Paper archive period is not released for this research')

    metrics={}
    events,cursor=archive_events(store,session['network'],session['address'],session['coin'],
        start_ms,end_ms,include_l2book=True,include_evidence_refs=True,query_metrics=metrics)
    opportunities=state.get('execution_opportunities')
    if not isinstance(opportunities,list):
        raise ValueError('Archived paper attempt records are missing')

    connection_codes,connections=_stable_values(opportunities,'connection_id')
    reason_codes,reasons=_stable_values(opportunities,'reason')
    source_codes,sources=_stable_values(opportunities,'quote_source')
    intent_codes,intents=_stable_values(opportunities,'intent')
    outcome_codes,outcomes=_stable_values(opportunities,'outcome')
    selection_codes,selections=_stable_values(opportunities,'order_selection')
    vocab={'connection_id':connections,'reason':reasons,'quote_source':sources,
        'intent':intents,'outcome':outcomes,'order_selection':selections}
    columns=['signal_decision_ms','due_ms','execution_decision_ms','intent_code','outcome_code',
        'eligible','reason_code','position_before','position_after','order_size','fill_size',
        'order_notional_usdc','quote_age_ms','quote_received_ms','quote_available_ms',
        'quote_source_code','connection_code','partial_fill','order_selection_code']
    attempt_rows=[]
    for row in opportunities:
        attempt_rows.append([row.get('signal_decision_ms'),row.get('due_ms'),row.get('execution_decision_ms'),
            intent_codes.get(str(row.get('intent'))),outcome_codes.get(str(row.get('outcome'))),row.get('eligible'),
            reason_codes.get(str(row.get('reason'))) if row.get('reason') is not None else None,
            row.get('position_before'),row.get('position_after'),row.get('order_size'),row.get('fill_size'),
            row.get('order_notional_usdc'),row.get('quote_age_ms'),row.get('quote_received_ms'),
            row.get('quote_available_ms'),source_codes.get(str(row.get('quote_source'))),
            connection_codes.get(str(row.get('connection_id'))),row.get('partial_fill'),
            selection_codes.get(str(row.get('order_selection'))) if row.get('order_selection') is not None else None])

    selected_quote_keys={(row.get('quote_source'),row.get('quote_received_ms'),row.get('connection_id'))
        for row in opportunities}
    manifest={};quotes={};by_quote_key=defaultdict(list)
    for event in events:
        if event.get('kind') in ('bbo','l2book'):
            event_key=(event.get('source'),event.get('received_ms'),event.get('session'))
            if event_key not in selected_quote_keys:
                continue
        elif event.get('kind') not in ('heartbeat','subscriptions','leader_fill','funding'):
            continue
        ref=event.get('evidence_ref')
        if ref and event.get('archive_response_sha256'):
            observation_id=int(ref.split(':',1)[1])
            manifest[(observation_id,event['archive_response_sha256'],event['archive_available_ms'])]=None
        if event.get('kind') not in ('bbo','l2book'):
            continue
        if not ref or not event.get('archive_response_sha256'):
            raise ValueError('Quote archive row lacks traceable content hash')
        manifest_key=(observation_id,event['archive_response_sha256'],event['archive_available_ms'])
        content=(event['source'],event.get('source_event_ms'),event['received_ms'],event.get('session'),
            event['bid'],event['ask'],event['bid_size'],event['ask_size'])
        quote_id=fingerprint({'source':content[0],'source_event_ms':content[1],'received_ms':content[2],
            'connection_id':content[3],'bid':content[4],'ask':content[5],
            'bid_size':content[6],'ask_size':content[7]})
        quotes.setdefault(quote_id,content)
        by_quote_key[(event['source'],event['received_ms'],event.get('session'))].append(
            (quote_id,manifest_key,event['archive_event_index'],event['available_ms']))
    manifest_keys=sorted(manifest)
    manifest_index={key:index for index,key in enumerate(manifest_keys)}
    response_hashes=sorted({item[1] for item in manifest_keys})
    response_hash_index={value:index for index,value in enumerate(response_hashes)}
    manifest_rows=[[item[0],response_hash_index[item[1]],item[2]] for item in manifest_keys]
    quote_ids=sorted(quotes)
    quote_index={value:index for index,value in enumerate(quote_ids)}
    quote_rows=[];quote_ref_rows=[]
    for quote_id in quote_ids:
        content=quotes[quote_id]
        quote_rows.append([source_codes.get(content[0]),content[1],content[2],
            connection_codes.get(str(content[3])),*content[4:]])
        seen_refs=set()
        for _,manifest_key,frame_index,available_ms in by_quote_key[(content[0],content[2],content[3])]:
            if _ != quote_id:continue
            ref=(manifest_index[manifest_key],frame_index,available_ms)
            if ref in seen_refs:continue
            seen_refs.add(ref);quote_ref_rows.append([quote_index[quote_id],*ref])

    attempt_quote_index={}
    quote_match_sizes=Counter();raw_quote_match_sizes=Counter();quote_receipt_age_ok=0
    stored_availability_before_decision=0;archive_available_before_decision=0;availability_timestamp_matches=0
    for index,row in enumerate(opportunities):
        key=(row.get('quote_source'),row.get('quote_received_ms'),row.get('connection_id'))
        candidates=by_quote_key.get(key,[])
        ids=sorted({quote_index[item[0]] for item in candidates})
        attempt_quote_index[index]=ids
        quote_match_sizes[len(ids)]+=1
        raw_quote_match_sizes[len(candidates)]+=1
        decision_ms=row.get('execution_decision_ms')
        if type(decision_ms) is int and type(row.get('quote_received_ms')) is int \
                and 0<=decision_ms-row['quote_received_ms']<=1000:
            quote_receipt_age_ok+=1
        if type(decision_ms) is int and type(row.get('quote_available_ms')) is int \
                and row['quote_available_ms']<decision_ms:
            stored_availability_before_decision+=1
        if type(decision_ms) is int and any(item[3]<decision_ms for item in candidates):
            archive_available_before_decision+=1
        if any(item[3]==row.get('quote_available_ms') for item in candidates):
            availability_timestamp_matches+=1
    attempt_quote_links=[[index,attempt_quote_index[index]] for index in range(len(opportunities))]

    health=[e for e in events if e.get('kind') in ('heartbeat','subscriptions')]
    market_sets=[];market_index={}
    health_rows=[]
    for e in health:
        markets=tuple(e.get('markets') or [])
        if markets not in market_index:
            market_index[markets]=len(market_sets);market_sets.append(list(markets))
        ref=e.get('evidence_ref');obs=int(ref.split(':',1)[1])
        health_manifest_index=manifest_index[(obs,e['archive_response_sha256'],e['archive_available_ms'])]
        health_rows.append([0 if e['kind']=='heartbeat' else 1,e.get('received_ms'),e.get('available_ms'),
            str(e.get('session') or ''),e.get('connected'),market_index[markets],health_manifest_index,
            e.get('archive_event_index')])

    fills=[e for e in events if e.get('kind')=='leader_fill']
    fill_rows=[]
    for e in fills:
        observation_id=int(e['evidence_ref'].split(':',1)[1])
        fill_manifest_index=manifest_index[(observation_id,e['archive_response_sha256'],e['archive_available_ms'])]
        fill_rows.append([e.get('id'),e.get('event_ms'),e.get('received_ms'),e.get('available_ms'),
            str(e.get('session') or ''),e.get('delta'),e.get('leader_start_position'),
            fill_manifest_index,e.get('archive_event_index')])

    field_names=['attempt_id','retry_parent_id','decision_id','source_event_id','target',
        'unrounded_adjustment','rounded_adjustment','eligibility_price','quote_id',
        'displayed_size_cap','fill_id','signal_decision_ms','execution_decision_ms',
        'position_before','position_after','order_size','fill_size','order_notional_usdc','reason',
        'quote_received_ms','quote_available_ms','quote_source','connection_id']
    field_counts={key:sum(row.get(key) is not None for row in opportunities) for key in field_names}
    quote_observation_rows=Counter()
    for event in events:
        if event.get('kind') in ('bbo','l2book'):
            quote_observation_rows[event.get('source')]+=1
    health_counts=Counter(e['kind'] for e in health)
    event_counts=Counter(e['kind'] for e in events)
    stable_query_metrics={'rows':metrics.get('rows',0),
        'rows_by_clause':{key:value.get('rows',0) for key,value in sorted(metrics.get('clauses',{}).items())}}

    report=store.connection.execute('select report_id,review_index,observed_through_ms,report_json '
        'from paper_experimental_reports where session_id=? order by review_index desc limit 1',
        (session['session_id'],)).fetchone()
    snapshot_columns={r[1] for r in store.connection.execute('pragma table_info(paper_snapshots)')}
    snapshot_fields=['snapshot_id','available_ms']+[name for name in ('observation_cursor','state_fingerprint') if name in snapshot_columns]
    snapshot=store.connection.execute('select '+','.join(snapshot_fields)+' '
        'from paper_snapshots where session_id=? order by available_ms desc limit 1',
        (session['session_id'],)).fetchone()
    suspension=store.connection.execute('select suspended_ms,diagnostics_json from paper_suspensions '
        'where session_id=? order by suspended_ms desc limit 1',(session['session_id'],)).fetchone()

    bundle={'schema_version':'paper-local-archive-bundle-v1',
        'coverage':{'start_ms':start_ms,'end_ms':end_ms,'query_metrics':stable_query_metrics,
            'archive_event_counts':dict(event_counts),'book_event_counts':dict(quote_observation_rows),
            'stream_health_counts':dict(health_counts),'live_leader_fill_events':len(fills),
            'archive_quote_row_candidate_cardinality':dict(raw_quote_match_sizes),
            'distinct_book_candidate_cardinality':dict(quote_match_sizes),
            'opportunities_with_receipt_age_at_most_1000ms':quote_receipt_age_ok,
            'opportunities_with_recorded_quote_availability_before_decision':stored_availability_before_decision,
            'opportunities_with_archive_availability_before_decision':archive_available_before_decision,
            'opportunities_where_archive_availability_matches_saved_quote_time':availability_timestamp_matches,
            'raw_observation_manifest_count':len(manifest_rows),'observation_cursor':cursor},
        'vocabulary':vocab,'opportunity_columns':columns,'opportunities':attempt_rows,
        'quote_columns':['source_code','source_event_ms','received_ms','connection_code','bid','ask','bid_size','ask_size'],
        'quotes':quote_rows,'quote_archive_ref_columns':['quote_index','manifest_index','archive_event_index','event_available_ms'],
        'quote_archive_refs':quote_ref_rows,'attempt_quote_links':attempt_quote_links,
        'archive_response_hashes':response_hashes,
        'archive_observation_manifest_columns':['observation_id','response_hash_index','archived_available_ms'],
        'archive_observation_manifest':manifest_rows,
        'health_columns':['kind_code','received_ms','available_ms','connection_id','connected','market_set_index','manifest_index','archive_event_index'],
        'market_sets':market_sets,'stream_health_events':health_rows,
        'leader_fill_columns':['event_id','event_ms','received_ms','available_ms','connection_id','signed_delta','leader_start_position','manifest_index','archive_event_index'],
        'leader_fill_events':fill_rows,
        'paper_endpoint':{'session_id':session['session_id'],'status':session['status'],
            'last_ms':end_ms,'position':state.get('position'),'fills':state.get('fills',[]),
            'pending':state.get('pending',[]),'funding_usdc_observed':state.get('funding'),
            'funding_events_observed':state.get('funding_events'),
            'suspension':{'suspended_ms':suspension['suspended_ms'],
                'diagnostics':json.loads(suspension['diagnostics_json'])} if suspension else None},
        'report_ref':{'report_id':report['report_id'],'review_index':report['review_index'],
            'observed_through_ms':report['observed_through_ms'],
            'report_fingerprint':fingerprint(json.loads(report['report_json']))} if report else None,
        'latest_snapshot_ref':dict(snapshot) if snapshot else None,
        'attempt_field_counts':field_counts}
    return bundle


def prepare_from_local_archives(store,request_id,*,clock_ms=None,max_chars=MAX_PACKET_CHARS):
    """Resolve v5's missing-data list and prepare an idempotent dormant child task."""
    from .paper_research import initialize
    initialize(store);store.connection.commit()
    clock=now_ms() if clock_ms is None else clock_ms
    if type(clock) is not int or clock<0 or type(max_chars) is not int or max_chars<1:
        raise ValueError('Explicit clock and bounded packet size required')
    parent=store.connection.execute('select request_id,adaptation_request_id,session_id,network,address,status,'
        'created_ms,updated_ms,packet_json,result_json from paper_research_jobs where request_id=?',(request_id,)).fetchone()
    if not parent or parent['status']!='needs_data' or parent['updated_ms']>clock:
        raise ValueError('Available terminal needs-data paper task required')
    source_packet=json.loads(parent['packet_json']);result=json.loads(parent['result_json'])
    hypothesis=result.get('proposal',{}).get('hypothesis',{})
    required=hypothesis.get('required_data')
    if not isinstance(required,list) or not required:
        raise ValueError('Explicit original needs-data list required')
    if source_packet.get('fingerprint')!=fingerprint({k:v for k,v in source_packet.items() if k!='fingerprint'}):
        raise ValueError('Original paper packet fingerprint mismatch')
    source_result_fingerprint=fingerprint({'status':parent['status'],'result':result})
    session_meta=store.connection.execute('select session_id,network,address from paper_sessions where session_id=?',
        (parent['session_id'],)).fetchone()
    if not session_meta or (session_meta['network'],session_meta['address'])!=(parent['network'],parent['address']):
        raise ValueError('Paper session scope differs from the preserved task')

    # Check every inherited period before reading session state or observation payloads.
    periods=source_packet.get('source_periods') or []
    if not periods or any(not authorized_period(store,p,clock,end_inclusive=True) for p in periods):
        raise ValueError('Original evidence period is not released for local research')
    session=store.connection.execute('select * from paper_sessions where session_id=?',(parent['session_id'],)).fetchone()
    bundle=_local_bundle(store,session,source_packet,max_chars=max_chars,clock_ms=clock)
    categories=[]
    for index,request in enumerate(required):
        text=request.casefold()
        if 'per-attempt' in text or 'retry ancestry' in text:
            category='partially_available'
            detail='Archived opportunities and simulated fills exist, but no unique attempt, retry, decision or fill identifiers and several requested sizing fields were not persisted.'
            refs=['paper_sessions:'+session['session_id'],'paper_experimental_reports:'+bundle['report_ref']['report_id']]
        elif 'quote' in text and 'stream-health' in text:
            category='available_with_ambiguity'
            detail='BBO, l2Book and connection/heartbeat receipts are archived and matched by source, receive time and connection; duplicate receipts, competing top-book values and differing availability timestamps prevent a unique stored quote-id join for some attempts.'
            refs=['paper_local_archive_bundle:quotes','paper_local_archive_bundle:stream_health_events']
        elif 'source-event-to-decision' in text or 'causal keys' in text:
            category='historical_link_unavailable'
            detail='The per-opportunity records contain decision times but no persisted source-event, decision or triggering fill key. Exact historical attribution cannot be reconstructed; temporal candidates are not exact links.'
            refs=['paper_sessions:'+session['session_id'],'paper_research:'+request_id]
        elif 'subsequent paper inventory' in text or 'pending-order resolution' in text:
            category='future_observation_required'
            detail='The archived endpoint retains the residual position and pending reduction at suspension. No subsequent virtual execution state proves closure; the session is not resumed in this tranche.'
            refs=['paper_sessions:'+session['session_id'],'paper_snapshots:'+str(bundle.get('latest_snapshot_ref',{}).get('snapshot_id'))]
        else:
            category='unclassified_request'
            detail='No deterministic local source mapping was found; preserve the original request for manual resolution.'
            refs=['paper_research:'+request_id]
        categories.append({'required_data_index':index,'request':request,'classification':category,
            'finding':detail,'evidence_refs':refs})

    available_values=[bundle['paper_endpoint']['last_ms']]
    available_values.extend(x[2] for x in bundle['archive_observation_manifest'])
    data_available_ms=max(available_values)
    result_fingerprint=source_result_fingerprint
    packet_body={'schema_version':'paper-local-evidence-research-v1',
        'network':parent['network'],'address':parent['address'],'session_id':parent['session_id'],
        'variant_id':source_packet.get('variant_id'),'available_ms':data_available_ms,
        'source_periods':source_packet['source_periods'],
        'source_period_membership':'immutable released parent research periods plus bounded local archive receipts',
        'source_result_fingerprint':result_fingerprint,
        'source_packet_fingerprint':source_packet['fingerprint'],
        'parent_research':{'request_id':request_id,'status':parent['status'],
            'diagnostic':result.get('critique',{}).get('diagnostic'),
            'hypothesis':hypothesis},
        'observations':{'markets':[source_packet.get('simulated_parameters',{}).get('spec',{}).get('market')],
            'missing_data_resolutions':categories,'local_archive_bundle':bundle,
            'resolution_limits':['Local quote/time matches are retrospective evidence links, not persisted decision IDs.',
                'No paper session, live collector, market endpoint or inference was started by this resolver.']},
        'evidence_refs':['paper_research:'+request_id,
            'paper_local_archive_bundle:'+fingerprint(bundle),
            *[item for entry in categories for item in entry['evidence_refs']]]}
    packet_body['fingerprint']=fingerprint(packet_body)
    packet_json=canonical(packet_body)
    if len(packet_json)>max_chars:
        raise ValueError(f'Local evidence packet exceeds bound ({len(packet_json)} > {max_chars})')
    evidence_fingerprint=fingerprint({'source_result_fingerprint':result_fingerprint,
        'source_packet_fingerprint':source_packet['fingerprint'],'packet_fingerprint':packet_body['fingerprint']})
    resolution_id=fingerprint({'parent_request_id':request_id,'evidence_fingerprint':evidence_fingerprint})
    identity=fingerprint({'adaptation_request_id':parent['adaptation_request_id'],'packet':packet_body['fingerprint']})
    old=store.connection.execute('select resolution_json,child_request_id from paper_local_evidence_resolutions where resolution_id=?',(resolution_id,)).fetchone()
    if old:
        child_result={'route':'strategic_analysis','state':'budget_required',
            'reason':'Local evidence packet prepared; any new inference requires separate explicit authorization.',
            'wake':{'kind':'explicit_task_authorization','new_task_id':old['child_request_id'],
                'packet_fingerprint':packet_body['fingerprint']},
            'evidence_refs':['paper_research:'+request_id,'paper_local_evidence_resolutions:'+resolution_id],
            'promotion_authorized':False,'profitability_proven':False}
        store.connection.execute('update paper_research_jobs set result_json=? where request_id=? '
            "and status='budget_required' and result_json is null",(canonical(child_result),old['child_request_id']))
        store.connection.commit()
        return {'status':'unchanged','request_id':request_id,'resolution_id':resolution_id,
            'child_request_id':old['child_request_id'],'evidence_fingerprint':evidence_fingerprint,
            'packet_fingerprint':packet_body['fingerprint'],'packet_chars':len(packet_json)}
    if clock<parent['updated_ms'] or data_available_ms>clock:
        raise ValueError('Local evidence is not available at the explicit cutoff')
    store.connection.execute('begin immediate')
    try:
        current=store.connection.execute('select status,updated_ms,result_json,packet_json from paper_research_jobs where request_id=?',(request_id,)).fetchone()
        if not current or current['status']!='needs_data' or current['updated_ms']>clock:
            raise ValueError('Parent state changed while resolving its archived evidence')
        if fingerprint({'status':current['status'],'result':json.loads(current['result_json'])})!=result_fingerprint:
            raise ValueError('Parent AI result changed during local resolution')
        store.connection.execute('insert into paper_local_evidence_resolutions '
            '(resolution_id,parent_request_id,source_result_fingerprint,source_packet_fingerprint,evidence_fingerprint,'
            'prepared_ms,data_available_ms,child_request_id,resolution_json,packet_json) values(?,?,?,?,?,?,?,?,?,?)',
            (resolution_id,request_id,result_fingerprint,source_packet['fingerprint'],evidence_fingerprint,
            clock,data_available_ms,identity,canonical({'resolution_id':resolution_id,
                'parent_request_id':request_id,'source_result_fingerprint':result_fingerprint,
                'evidence_fingerprint':evidence_fingerprint,'prepared_ms':clock,
                'data_available_ms':data_available_ms,'categories':categories}),packet_json))
        store.connection.execute('insert into paper_research_jobs '
            '(request_id,adaptation_request_id,session_id,created_ms,packet_json,policy_json,status,network,address,'
            'updated_ms,parent_request_id,activated_ms,data_available_ms,local_resolution_id,result_json) '
            'values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (identity,parent['adaptation_request_id'],parent['session_id'],clock,packet_json,
             store.connection.execute('select policy_json from paper_research_jobs where request_id=?',(request_id,)).fetchone()[0],
             'budget_required',parent['network'],parent['address'],clock,request_id,None,data_available_ms,resolution_id,
             canonical({'route':'strategic_analysis','state':'budget_required',
                'reason':'Local evidence packet prepared; any new inference requires separate explicit authorization.',
                'wake':{'kind':'explicit_task_authorization','new_task_id':identity,
                    'packet_fingerprint':packet_body['fingerprint']},
                'evidence_refs':['paper_research:'+request_id,'paper_local_evidence_resolutions:'+resolution_id],
                'promotion_authorized':False,'profitability_proven':False})))
        store.connection.commit()
    except BaseException:
        store.connection.rollback();raise
    return {'status':'prepared','request_id':request_id,'resolution_id':resolution_id,
        'child_request_id':identity,'evidence_fingerprint':evidence_fingerprint,
        'packet_fingerprint':packet_body['fingerprint'],'packet_chars':len(packet_json),
        'available_ms':data_available_ms,'classifications':categories}


def packet_for_resolution(store,resolution_id,*,clock_ms,max_chars):
    """Revalidate an immutable local packet before a later explicit activation."""
    row=store.connection.execute('select * from paper_local_evidence_resolutions where resolution_id=?',
        (resolution_id,)).fetchone()
    if not row or row['prepared_ms']>clock_ms or row['data_available_ms']>clock_ms:
        raise ValueError('Available immutable local evidence resolution required')
    packet=json.loads(row['packet_json'])
    child=store.connection.execute('select packet_json,local_resolution_id,status,activated_ms from paper_research_jobs where request_id=?',
        (row['child_request_id'],)).fetchone()
    if not child or child['local_resolution_id']!=resolution_id or child['status']!='budget_required' or child['activated_ms'] is not None:
        raise ValueError('Prepared local child task identity or dormant state changed')
    if packet.get('fingerprint')!=fingerprint({k:v for k,v in packet.items() if k!='fingerprint'}) \
            or packet.get('fingerprint')!=json.loads(child['packet_json']).get('fingerprint'):
        raise ValueError('Prepared local packet fingerprint mismatch')
    if packet.get('available_ms')!=row['data_available_ms'] or len(canonical(packet))>max_chars:
        raise ValueError('Prepared local packet availability or size changed')
    parent=store.connection.execute('select status,updated_ms,network,address,session_id,packet_json,result_json '
        'from paper_research_jobs where request_id=?',(row['parent_request_id'],)).fetchone()
    if not parent or parent['status']!='needs_data' or parent['updated_ms']>clock_ms \
            or (parent['network'],parent['address'],parent['session_id'])!=(packet['network'],packet['address'],packet['session_id']):
        raise ValueError('Original needs-data parent is no longer available in the same scope')
    if fingerprint({'status':parent['status'],'result':json.loads(parent['result_json'])})!=row['source_result_fingerprint']:
        raise ValueError('Original needs-data result changed')
    parent_packet=json.loads(parent['packet_json'])
    if parent_packet.get('fingerprint')!=row['source_packet_fingerprint']:
        raise ValueError('Original paper packet changed')
    periods=packet.get('source_periods') or []
    if not periods or any(not authorized_period(store,p,clock_ms,end_inclusive=True) for p in periods):
        raise ValueError('Inherited source periods are not authorized at activation')
    from datetime import datetime,timezone
    manifest=packet['observations']['local_archive_bundle']['archive_observation_manifest']
    response_hashes=packet['observations']['local_archive_bundle']['archive_response_hashes']
    for observation_id,response_hash_index,available_ms in manifest:
        response_sha256=response_hashes[response_hash_index]
        archived=store.connection.execute('select network,source,entity_type,entity_id,endpoint,observed_at,response_sha256 '
            'from raw_observations where observation_id=?',(observation_id,)).fetchone()
        if not archived or archived['network']!=packet['network'] \
                or archived['source']!='hyperliquid-websocket-v1' \
                or archived['response_sha256']!=response_sha256:
            raise ValueError('Referenced local archive row is missing or changed')
        market_ok=archived['entity_type']=='market' and archived['entity_id'] in packet['observations'].get('markets',[])
        account_ok=archived['entity_type']=='account' and archived['entity_id'].lower()==packet['address'].lower()
        stream_ok=archived['entity_type']=='stream' and archived['endpoint']=='streamHealth'
        if not (market_ok or account_ok or stream_ok) \
                or archived['endpoint'] not in {'bbo','l2Book','userFills','userFundings','streamHealth'}:
            raise ValueError('Local archive row falls outside the sealed market/account/health evidence scope')
        recorded=int(datetime.fromisoformat(archived['observed_at'].replace('Z','+00:00')).timestamp()*1000)
        if recorded!=available_ms or recorded>clock_ms:
            raise ValueError('Local archive availability changed or is in the future')
    return {'status':'packet_ready','packet':packet}

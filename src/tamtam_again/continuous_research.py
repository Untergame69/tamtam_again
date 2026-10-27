"""Bounded continuous research over existing archives, sharing the worker lock.

No model text is executed. Admission, inference, local analysis and prospective
evaluation remain separate recorded decisions; an idle or waiting subject never
owns the entire queue. This module sends no exchange orders.
"""
from __future__ import annotations

import json
from .engine import canonical, fingerprint
from .validation import now_ms


def initialize(store):
    from .population_research import initialize as jobs
    from .research_work_queue import initialize as queue
    jobs(store); queue(store)
    store.connection.execute('''create table if not exists continuous_research_candidates (
        network text not null,address text not null,market text not null,
        source_fingerprint text not null,status text not null,result_json text not null,
        updated_ms integer not null, primary key(network,address,market))''')
    store.connection.execute('''create table if not exists continuous_research_ticks (
        tick_id integer primary key,started_ms integer not null,finished_ms integer not null,
        dispatch integer not null,result_json text not null)''')
    store.connection.execute('''create table if not exists continuous_market_proofs (
        network text not null,address text not null,cutoff_ms integer not null,
        archive_id integer,proof_json text not null,checked_ms integer not null,
        primary key(network,address))''')
    store.connection.execute('''create table if not exists continuous_research_projections (
        source_fingerprint text primary key,available_ms integer not null,body_gzip blob not null)''')
    store.connection.commit()


def admission_inventory(store, policy, *, clock_ms):
    """Select an exact completed screen, not an arbitrary mixture of cutoffs."""
    from .descriptive_admission import evaluate_inventory, SCREEN_POLICY
    row=store.connection.execute('select max(as_of_ms) from population_historical_decisions '
        'where network=? and policy_version=? and as_of_ms<=?',
        (policy['network'],SCREEN_POLICY,clock_ms)).fetchone()
    if not row or row[0] is None:
        return {'candidate_evaluations':[], 'reason':'no completed historical inventory'}
    return evaluate_inventory(db_path=store.path,cutoff_ms=row[0],network=policy['network'],
        max_candidates=20000,queue_size=0)


def _save_candidate(store, item, source_fp, result, clock):
    store.connection.execute('insert into continuous_research_candidates values(?,?,?,?,?,?,?) '
        'on conflict(network,address,market) do update set source_fingerprint=excluded.source_fingerprint,'
        'status=excluded.status,result_json=excluded.result_json,updated_ms=excluded.updated_ms',
        (item['network'],item['address'],item['market'],source_fp,result['status'],canonical(result),clock))
    store.connection.commit()


def market_proofs(store, inventory, policy, clock):
    """Gradually resolve multi-market scopes from all authorized fills, bounded.

    Cache the deterministic tabulation, not a hand-picked market. At most two
    accounts are decoded per tick; all markets meeting the same criterion enter
    the ordinary queue on equal terms.
    """
    from .research_memory import authorized_account_history
    from .discovery import protected_addresses
    from .population_descriptive import _load_fills, _event_time
    from collections import defaultdict
    pending=[];proofs={};protected=protected_addresses(store)
    for row in inventory['candidate_evaluations']:
        if row.get('disposition')!='needs_more_evidence' or not row.get('candidate_id'):
            continue
        scope=row['scope']
        if scope.get('market_count',0)<2:continue
        address=row['candidate_id'].lower();cutoff=scope['cutoff_ms']
        if address in protected:continue
        if not authorized_account_history(store,policy['network'],address,cutoff):continue
        latest=store.connection.execute("select max(observation_id) from raw_observations where network=? "
            "and source='hyperliquid-population-rest-v1' and entity_id=? and endpoint in ('userFills','userFillsByTime') and observed_at<=?",
            (policy['network'],address,_event_time(cutoff))).fetchone()[0]
        old=store.connection.execute('select * from continuous_market_proofs where network=? and address=?',
            (policy['network'],address)).fetchone()
        if old and old['cutoff_ms']==cutoff and old['archive_id']==latest:
            for market,proof in json.loads(old['proof_json']).items():proofs[(address,market)]=proof
        else:pending.append((old['checked_ms'] if old else 0,address,scope,latest))
    for _,address,scope,latest in sorted(pending)[:2]:
        cutoff=scope['cutoff_ms'];start=scope['period_start_ms']
        counts=store.connection.execute("select count(*),coalesce(sum(record_count),0) from raw_observations "
            "where network=? and source='hyperliquid-population-rest-v1' and entity_id=? and endpoint in ('userFills','userFillsByTime')",
            (policy['network'],address)).fetchone()
        decoded={}
        if counts[0]<=2000 and counts[1]<=500000:
            fills,coverage,refs=_load_fills(store,policy['network'],address,cutoff)
            by_market=defaultdict(list)
            for fill in fills:
                if start<=fill['time']<cutoff:by_market[fill['coin']].append(fill)
            for market,rows in by_market.items():
                decoded[market]={'period_start_ms':start,'cutoff_ms':cutoff,'fills':len(rows),
                    'active_days':len({r['time']//86400000 for r in rows}),
                    'coverage':coverage,'evidence_ref':'authorized-market-tabulation:'+fingerprint(refs)}
        store.connection.execute('insert into continuous_market_proofs values(?,?,?,?,?,?) '
            'on conflict(network,address) do update set cutoff_ms=excluded.cutoff_ms,archive_id=excluded.archive_id,'
            'proof_json=excluded.proof_json,checked_ms=excluded.checked_ms',
            (policy['network'],address,cutoff,latest,canonical(decoded),clock));store.connection.commit()
        for market,proof in decoded.items():proofs[(address,market)]=proof
    return proofs


def prepare_packet(store, policy, item):
    from .population_packet import packet_for_account
    from .population_descriptive import prepare_pilot_packet
    from .research_memory import authorized_account_history
    if not authorized_account_history(store,policy['network'],item['address'],item['cutoff_ms']):
        return {'status':'reserved','reason':'unreleased evaluation period; excluded before archive reads'}
    bounds=store.connection.execute("select count(*),coalesce(sum(record_count),0) from raw_observations "
        "where network=? and source='hyperliquid-population-rest-v1' and entity_id=? "
        "and endpoint in ('userFills','userFillsByTime','userFunding')",
        (policy['network'],item['address'])).fetchone()
    if bounds[0]>2000 or bounds[1]>500000:
        return {'status':'technical_required','reason':'archive requires indexed bounded projection',
            'observed_pages':bounds[0],'record_upper_bound':bounds[1]}
    base=packet_for_account(store,policy['network'],item['address'],as_of_ms=item['cutoff_ms'],
        # Working representation only: the deterministic projector below
        # removes duplicated per-episode examples before the unchanged sealed
        # packet/prompt limits. No oversized representation reaches a model.
        max_chars=2000000)
    if base.get('status')!='packet_ready': return base
    packet=prepare_pilot_packet(store,base['packet'],candidate=item['candidate'],item=item,
        pilot_id=policy['policy_id'],policy_version=policy['version'],cutoff_ms=item['cutoff_ms'])
    packet['observations']['account_context_markets']=packet['observations'].get('markets',[])
    packet['observations']['markets']=[item['market']]
    packet['research_scope']={'market':item['market'],'admission_activity_start_ms':item['period_start_ms'],
        'archive_receipt_cutoff_ms':item['cutoff_ms'],
        'detail_period':'all authorized archived history through cutoff; admission activity uses preceding 30 days',
        'other_markets':'account context only, not eligible for this hypothesis'}
    if len(canonical(packet))>policy['task_policy']['max_packet_chars']:
        _project_other_markets(store,packet,item['market'],item['cutoff_ms'])
    from .continuous_research_identity import semantic_identity
    semantic=semantic_identity(packet,item['market'])
    from .research_evaluation import export_memory
    feedback=export_memory(store,policy['network'],item['address'],item['cutoff_ms'])
    if feedback:packet['research_evaluation_memory']=feedback
    # History and feedback were selected at this cutoff; never advertise the
    # older scope-report receipt as availability of the enriched packet.
    packet['available_ms']=item['cutoff_ms']
    packet['continuous_research']={'version':1,'policy_id':policy['policy_id'],
        'semantic_fingerprint':semantic,'market':item['market'],'source_ref':item['source_ref']}
    packet.pop('fingerprint',None);packet['fingerprint']=fingerprint(packet)
    if len(canonical(packet))>policy['task_policy']['max_packet_chars']:
        return {'status':'packet_too_large','reason':'full deterministic projection exceeds unchanged bound'}
    return {'status':'packet_ready','packet':packet,'semantic_fingerprint':semantic}


def _project_other_markets(store, packet, market, available_ms):
    """Keep selected-market statistics whole; archive the full context losslessly."""
    import gzip
    full=canonical(packet);source=fingerprint(packet)
    store.connection.execute('insert or ignore into continuous_research_projections values(?,?,?)',
        (source,available_ms,gzip.compress(full.encode(),mtime=0)));store.connection.commit()
    summary=packet['observations']['descriptive_history_v1']
    markets=summary.get('markets',{})
    summary['other_market_activity_context']={symbol:{'activity':row.get('activity',{}),
        'scope_membership':row.get('scope_membership')} for symbol,row in markets.items() if symbol!=market}
    summary['markets']={symbol:row for symbol,row in markets.items() if symbol==market}
    summary['full_account_context_reference']='continuous_research_projections:'+source
    summary['projection_scope']='All selected-market aggregates retained; other markets are activity context only; full source is losslessly archived.'
    summary.pop('summary_fingerprint',None);summary['summary_fingerprint']=fingerprint(summary)
    packet['evidence_refs'].append('continuous_research_projections:'+source)


def _seal(store, policy, item, prepared, clock):
    from .continuous_research_policy import authorize_task
    packet=prepared['packet'];semantic=prepared['semantic_fingerprint']
    from .continuous_research_identity import prior_equivalent
    equivalent=prior_equivalent(store,policy['network'],item['address'],item['market'],packet)
    if equivalent:return {'status':'unchanged_no_inference','request_id':equivalent['request_id']}
    existing=store.connection.execute('select request_id from continuous_research_tasks '
        'where network=? and address=? and market=? and semantic_fingerprint=?',
        (policy['network'],item['address'],item['market'],semantic)).fetchone()
    if existing:return {'status':'unchanged_no_inference','request_id':existing[0]}
    request_id=fingerprint({'origin':'continuous-research','network':policy['network'],
        'address':item['address'],'market':item['market'],'semantic':semantic})
    # A distinct packet identity includes the new question, preserving existing
    # jobs even if their underlying raw fill checksum matches this one.
    digest=fingerprint({'continuous_semantic':semantic})
    packet['research_input_fingerprint']=digest
    packet.pop('fingerprint',None);packet['fingerprint']=fingerprint(packet)
    prior=store.connection.execute('select request_id from population_research_jobs '
        'where network=? and address=? and input_fingerprint=?',
        (policy['network'],item['address'],digest)).fetchone()
    if prior:return {'status':'unchanged_no_inference','request_id':prior[0]}
    authorize_task(store,policy,request_id=request_id,candidate=item['candidate'],address=item['address'],
        market=item['market'],packet_fingerprint_value=packet['fingerprint'],
        semantic_fingerprint_value=semantic,authorized_ms=clock,sealed_job={
            'network':policy['network'],'address':item['address'],'input_fingerprint':digest,
            'packet_json':canonical(packet),'policy_json':canonical(policy['task_policy']),'created_ms':clock})
    return {'status':'sealed','request_id':request_id}


def _consume(store, request_id, experiment_policy, clock):
    from .continuous_research_resolution import resolve_result
    from .research_evaluation import handoff_locked
    # A just-finished response did not exist at the tick's start time.
    resolved=resolve_result(store,'population',request_id,clock_ms=max(clock,now_ms()))
    evaluated=handoff_locked(store,request_id,experiment_policy=experiment_policy)
    return {'request_id':request_id,'resolution':{key:resolved.get(key) for key in (
        'state','work_id','queue_status','next_candidate','next_packet','memory')},
        'evaluation':evaluated}


def tick(store, policy, *, dispatch=True, clock_ms=None, experiment_policy=None, collection_policy=None,
         reserve_policy=None, max_candidates=8):
    """One inference task at most; deterministic follow-ups proceed independently."""
    from .research import scheduler_lock
    from .continuous_research_policy import initialize as allowance, candidates_for_admission, report
    from .population_runtime import execute_job
    from .research_evaluation import poll
    clock=now_ms() if clock_ms is None else clock_ms
    if type(max_candidates) is not int or not 1<=max_candidates<=32:
        raise ValueError('Explicit candidate work bound between 1 and 32 required')
    with scheduler_lock(store):
        initialize(store);allowance(store,policy)
        result={'version':'continuous-research-tick-v1','started_ms':clock,'dispatch':dispatch,
            'followups':[],'candidates':[],'dispatched':[],'real_orders_authorized':False}
        if reserve_policy is not None:
            from .reserve_cycle import tick as release_closed_reserves
            result['reserves']=release_closed_reserves(store,reserve_policy,clock_ms=clock)
        # Only recover jobs owned by this policy after obtaining the shared
        # kernel lock. Unknown provider usage stays unknown and is not refunded.
        for row in store.connection.execute('select j.request_id,j.status from population_research_jobs j '
                'join continuous_research_tasks t using(request_id) where t.policy_id=? '
                "and j.status in ('sealed','running') order by j.created_ms",(policy['policy_id'],)).fetchall():
            if row['status']=='running':
                store.connection.execute("update population_research_jobs set status='interrupted',updated_ms=? where request_id=?",(clock,row['request_id']))
                store.connection.execute("update continuous_research_tasks set state='interrupted' where request_id=?",(row['request_id'],));store.connection.commit()
            elif dispatch and not result['dispatched']:
                job=store.connection.execute('select * from population_research_jobs where request_id=?',(row['request_id'],)).fetchone()
                try:result['dispatched'].append(execute_job(store,row['request_id'],job))
                except (ValueError,PermissionError) as exc:
                    store.connection.execute("update population_research_jobs set status='suspended',result_json=?,updated_ms=? where request_id=?",
                        (canonical({'error_type':type(exc).__name__,'diagnostic':'dispatch preflight failed; attempt preserved'}),clock,row['request_id']))
                    store.connection.execute("update continuous_research_tasks set state='suspended' where request_id=?",(row['request_id'],));store.connection.commit()
                    result['followups'].append({'request_id':row['request_id'],'status':'technical_required','reason':str(exc)})
        store.connection.execute('create table if not exists continuous_research_cursor (id integer primary key,last_request_id text not null)')
        cursor=store.connection.execute('select last_request_id from continuous_research_cursor where id=1').fetchone()
        last=cursor[0] if cursor else ''
        followup_rows=store.connection.execute('select j.request_id from population_research_jobs j '
                'join continuous_research_tasks t using(request_id) where t.policy_id=? '
                "and j.status not in ('sealed','running') order by (j.request_id<=?),j.request_id limit 16",(policy['policy_id'],last)).fetchall()
        for row in followup_rows:
            try:result['followups'].append(_consume(store,row['request_id'],experiment_policy,clock))
            except (ValueError,PermissionError,KeyError,TypeError) as exc:
                result['followups'].append({'request_id':row['request_id'],'status':'technical_required','reason':str(exc)})
        if followup_rows:
            store.connection.execute('insert or replace into continuous_research_cursor values(1,?)',(followup_rows[-1][0],));store.connection.commit()
        result['evaluations']=poll(store,limit=8)
        from .continuous_research_resolution import poll_waits
        result['data_waits']=poll_waits(store,clock_ms=clock,limit=8,collection_policy=collection_policy)
        inventory=admission_inventory(store,policy,clock_ms=clock)
        selections=candidates_for_admission(inventory,market_evidence=market_proofs(store,inventory,policy,clock))
        # Least recently considered candidates first within the same priority;
        # an unsupported or oversized subject cannot monopolize every tick.
        def ordering(item):
            old=store.connection.execute('select updated_ms from continuous_research_candidates '
                'where network=? and address=? and market=?',(policy['network'],item['address'],item['market'])).fetchone()
            account=store.connection.execute('select max(updated_ms) from continuous_research_candidates '
                'where network=? and address=?',(policy['network'],item['address'])).fetchone()[0]
            return (account or 0,0 if old is None else old[0],item.get('priority',''),item['candidate'])
        for item in sorted(selections,key=ordering)[:max_candidates]:
            item={**item,'network':policy['network'],'admission_cutoff_ms':item['cutoff_ms'],'cutoff_ms':clock}
            item['question']=('From the authorized executions on '+item['market']+', identify a falsifiable observable mechanism, '
                'separating price flow, signed fees, funding, inventory and coverage. Use all deterministic statistics; '
                'do not infer order placement from executed fills. If supported, specify an executable causal rule with '
                'explicit costs, timing and rejection criteria; otherwise record the exact missing observation or a useful '
                'descriptive conclusion. Trader private intentions and irrecoverable historical links are not prerequisites.')
            latest=store.connection.execute('select max(observation_id) from raw_observations '
                "where network=? and entity_type='account' and entity_id=? and source='hyperliquid-population-rest-v1'",
                (policy['network'],item['address'])).fetchone()[0]
            scope=store.connection.execute('select max(available_ms) from account_scope_reports where network=? and address=?',
                (policy['network'],item['address'])).fetchone()[0]
            wakes=None
            if store.connection.execute("select 1 from sqlite_master where name='research_observation_wakes'").fetchone():
                wakes=[tuple(r) for r in store.connection.execute('select w.request_id,w.evidence_fingerprint from research_observation_wakes w '
                    'join population_research_jobs j on j.request_id=w.request_id where j.network=? and j.address=? '
                    'and w.available_ms<=? order by w.request_id',(policy['network'],item['address'],clock))]
            source_fp=fingerprint({'source_ref':item['source_ref'],'admission_cutoff':item['admission_cutoff_ms'],
                'market':item['market'],'latest_archive_id':latest,'latest_scope':scope,'wakes':wakes})
            old=store.connection.execute('select source_fingerprint,status,result_json from continuous_research_candidates '
                'where network=? and address=? and market=?',(policy['network'],item['address'],item['market'])).fetchone()
            if old and old['source_fingerprint']==source_fp and old['status'] not in {'budget_exhausted','prepared','technical_required','needs_data','reserved'}:
                prior=json.loads(old['result_json']);current={'status':'unchanged_no_inference','request_id':prior.get('request_id')}
            else:
                try:
                    prepared=prepare_packet(store,policy,item)
                    if prepared['status']!='packet_ready':current=prepared
                    elif not dispatch:current={'status':'prepared','packet_fingerprint':prepared['packet']['fingerprint'],
                        'packet_chars':len(canonical(prepared['packet'])),'semantic_fingerprint':prepared['semantic_fingerprint']}
                    elif result['dispatched']:current={'status':'prepared','reason':'one inference task per tick'}
                    else:
                        current=_seal(store,policy,item,prepared,clock)
                        if current['status']=='sealed':
                            job=store.connection.execute('select * from population_research_jobs where request_id=?',(current['request_id'],)).fetchone()
                            execution=execute_job(store,current['request_id'],job)
                            result['dispatched'].append(execution)
                            current={**current,'status':execution['status']}
                            result['followups'].append(_consume(store,current['request_id'],experiment_policy,clock))
                except (ValueError,PermissionError,KeyError,TypeError) as exc:
                    message=str(exc)
                    current={'status':'budget_exhausted' if 'allowance exhausted' in message else 'technical_required','reason':message}
            _save_candidate(store,item,source_fp,current,clock)
            result['candidates'].append({'candidate':item['candidate'],'market':item['market'],**current})
            if result['dispatched']:break
        result['allowance']=report(store,policy,clock_ms=clock)
        result['finished_ms']=now_ms()
        store.connection.execute('insert into continuous_research_ticks(started_ms,finished_ms,dispatch,result_json) values(?,?,?,?)',
            (clock,result['finished_ms'],int(dispatch),canonical(result)));store.connection.commit()
        return result

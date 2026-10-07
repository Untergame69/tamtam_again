"""Provider expenses from research registries, including failed/interrupted trials."""
from datetime import datetime
from .accounting import decimal
from .discovery import fingerprint


def provider_cost_ledger(store,*,network,start_ms,end_ms,as_of_ms,address=None):
    if any(type(v) is not int for v in (start_ms,end_ms,as_of_ms)) or not 0<=start_ms<end_ms<=as_of_ms:
        raise ValueError('Explicit completed cost-attribution window and cutoff required')
    exists=lambda table:bool(store.connection.execute("select 1 from sqlite_master where name=? and type='table'",(table,)).fetchone())
    rows=[]
    if exists('population_research_jobs'):
        rows.extend(dict(r,source='population_research',identity=r['request_id'],registered_ms=r['created_ms'],cost_available_ms=r['updated_ms'])
            for r in store.connection.execute('select request_id,address,created_ms,updated_ms,status,actual_cost_usd,reserved_cost_usd from population_research_jobs where network=? and created_ms>=? and created_ms<?',
                (network,start_ms,end_ms)) if address is None or r['address']==address)
    if exists('isolated_research_jobs'):
        for r in store.connection.execute('select j.run_id,p.address,j.created_at,j.updated_at,j.status,j.actual_cost_usd,j.reserved_cost_usd from isolated_research_jobs j join validation_plans p using(plan_id) where p.network=?',(network,)):
            registered=int(datetime.fromisoformat(r['created_at']).timestamp()*1000)
            if start_ms<=registered<end_ms and (address is None or r['address']==address):
                rows.append(dict(r,source='isolated_research',identity=r['run_id'],registered_ms=registered,
                    cost_available_ms=int(datetime.fromisoformat(r['updated_at']).timestamp()*1000)))
    attempts=[];known=decimal(0);reservations=decimal(0);unknown=[]
    for row in sorted(rows,key=lambda r:(r['registered_ms'],r['source'],r['identity'])):
        available=row['cost_available_ms']<=as_of_ms
        terminal=available and row['status'] in {'hypothesis_recorded','ready_to_test','needs_data','non_identifiable','unsupported_mechanism','reject','rejected','suspended','expired','interrupted'}
        # Legacy suspended jobs may record only calls completed before a failed call.
        complete=not (row['source']=='isolated_research' and row['status']=='suspended')
        amount=row['actual_cost_usd'] if terminal and complete else None
        value=decimal(amount) if amount is not None else None
        if value is not None and value<0:raise ValueError('Negative provider expense')
        reservation=decimal(row['reserved_cost_usd']) if available and row['reserved_cost_usd'] is not None else None
        if reservation is not None:
            if reservation<0:raise ValueError('Negative reservation')
            reservations+=reservation
        identity=row['source']+':'+row['identity']
        if value is None:unknown.append(identity)
        else:known+=value
        attempts.append({'id':identity,'available_ms':row['registered_ms'],
            'cost_available_ms':row['cost_available_ms'] if available else None,
            'cost':str(value) if value is not None else None,
            'reserved_cost_usd':str(reservation) if reservation is not None else None,
            'status':row['status'] if available else 'state_not_available_at_cutoff',
            'evidence_ref':identity})
    result={'version':'registered-provider-costs-v1','network':network,'address':address,
        'start_ms':start_ms,'end_ms':end_ms,'as_of_ms':as_of_ms,
        'attribution':'all research registered in this half-open period, regardless of outcome',
        'attempts':attempts,'known_provider_cost_usd':str(known),
        'total_provider_cost_usd':None if unknown else str(known),
        'observed_reservations_usd':str(reservations),'unknown_cost_attempts':unknown,
        'status':'unknown' if unknown else 'registry_provider_costs_observed',
        'limits':['reservations are not provider invoices and are never substituted for missing costs',
            'provider included=0 does not mean no tokens, compute or subscription usage',
            'scope covers these two registries, not external calls, hosting or total infrastructure expense',
            'latest mutable cost state cannot reconstruct intermediate historical settlement events']}
    result['fingerprint']=fingerprint(result)
    return result

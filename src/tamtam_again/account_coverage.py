"""Separate archived pagination coverage from proof of retained event history."""
from __future__ import annotations


def pagination_coverage(pages, *, start_ms, end_ms, as_of_ms):
    if not 0<=start_ms<end_ms<=as_of_ms:
        raise ValueError('Explicit available coverage interval required')
    intervals=[];refs=[];incomplete=[]
    for page in pages:
        if page['available_ms']>as_of_ms:continue
        left,right=page.get('start_ms'),page.get('end_ms')
        if type(left) is not int or type(right) is not int or not 0<=left<=right:
            incomplete.append({'evidence_ref':page['evidence_ref'],'reason':'window bounds unavailable'})
            continue
        if right<start_ms or left>end_ms:continue
        refs.append(page['evidence_ref'])
        if page.get('pagination_status')!='pagination_exhausted':
            incomplete.append({'evidence_ref':page['evidence_ref'],
                               'reason':page.get('pagination_status','unknown')})
            continue
        intervals.append((max(start_ms,left),min(end_ms,right)))
    merged=[]
    for left,right in sorted(intervals):
        if merged and left<=merged[-1][1]:
            merged[-1][1]=max(merged[-1][1],right)
        else:merged.append([left,right])
    gaps=[];cursor=start_ms
    for left,right in merged:
        if left>cursor:gaps.append([cursor,left])
        cursor=max(cursor,right)
    if cursor<end_ms:gaps.append([cursor,end_ms])
    return {'status':'unknown','pagination_status':'covered' if not gaps else 'gaps',
            'pagination_intervals_ms':merged,'pagination_gaps_ms':gaps,
            'evidence_refs':sorted(set(refs)),'incomplete_pages':incomplete,
            'retention_proven':False,
            'reason':'exhausted API pages do not establish retention or economic scope completeness',
            'next_action':'finish missing pagination windows' if gaps else
                          'establish retained-history coverage and accounting scope independently'}


def retained_fill_coverage(pagination, witnesses, *, start_ms, end_ms, as_of_ms):
    """Latest unaggregated fills can witness that the requested window is retained.

    This is an endpoint-contract proof, not a guarantee against provider defects.
    It covers public account fills only, never funding/flows or valuation scope.
    """
    if any(type(t) is not int for t in (start_ms,end_ms,as_of_ms)) or not 0<=start_ms<end_ms<=as_of_ms:
        raise ValueError('Explicit available retention interval required')
    accepted=[];rejected=[]
    for witness in witnesses:
        ref=witness.get('evidence_ref');query=witness.get('request',{})
        requested=witness.get('requested_ms');available=witness.get('available_ms')
        rows=witness.get('fills')
        reason=None
        if (not ref or query.get('type')!='userFills' or query.get('aggregateByTime') is not False
            or any(k in query for k in ('startTime','endTime','dex'))):
            reason='latest all-account unaggregated request required'
        elif (type(requested) is not int or type(available) is not int
              or not end_ms<=requested<=available<=as_of_ms):
            reason='witness must be requested after period and available at cutoff'
        elif not isinstance(rows,list) or not rows or len(rows)>2000:
            reason='nonempty valid latest-fill response required; empty is not history proof'
        else:
            identities=set();stamps=[]
            for fill in rows:
                if (not isinstance(fill,dict) or type(fill.get('time')) is not int
                    or not 0<=fill['time']<=available or not isinstance(fill.get('coin'),str)
                    or not fill['coin'] or (fill.get('tid') is None and not fill.get('hash'))):
                    reason='malformed or future latest fill';break
                identity=(fill['coin'],fill['time'],str(fill.get('tid',fill.get('hash'))))
                if identity in identities:
                    reason='duplicate latest-fill identity';break
                identities.add(identity);stamps.append(fill['time'])
            if reason is None:
                if min(stamps)>start_ms:reason='latest-fill window does not reach period start'
                else:accepted.append({'evidence_ref':ref,'oldest_fill_ms':min(stamps),
                                      'requested_ms':requested,'available_ms':available})
        if reason:rejected.append({'evidence_ref':ref,'reason':reason})
    result=dict(pagination)
    proven=bool(accepted) and pagination.get('pagination_status')=='covered'
    result.update(status='complete' if proven else 'unknown',retention_proven=bool(accepted),
        retention_witnesses=accepted,rejected_retention_witnesses=rejected,
        evidence_refs=sorted(set(pagination.get('evidence_refs',[]))|{w['evidence_ref'] for w in accepted}),
        reason='period pagination covered and latest-fill window reaches its start' if proven else
               'period pagination or latest-fill retention witness missing',
        next_action='no additional fill-history collection required for this period' if proven else
                    'collect a latest unaggregated fill witness and close period pagination gaps',
        scope='public fills for this address only; no funding, ledger, equity or external hedge coverage',
        endpoint_contract_ref='https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint')
    return result

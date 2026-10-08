"""Local acquisition windows; never infer an economic timestamp or server freshness."""
from datetime import datetime


def acquisition_window(requested_at,observed_at):
    try:
        requested=datetime.fromisoformat(requested_at);observed=datetime.fromisoformat(observed_at)
        if requested.tzinfo is None or observed.tzinfo is None:raise ValueError('Timezone required')
        start=int(requested.timestamp()*1000);end=int(observed.timestamp()*1000)
        if not 0<=start<=end:raise ValueError('Invalid local clock order')
    except (TypeError,ValueError,OverflowError):
        return {'status':'unknown','requested_ms':None,'available_ms':None,'duration_ms':None,
                'reason':'missing, malformed, naive or reversed local timestamps'}
    return {'status':'local_acquisition_window','requested_ms':start,'available_ms':end,'duration_ms':end-start,
        'economic_time_inferred':False,
        'limits':['request and archive insertion times, not an atomic state timestamp',
            'server caching or lag may place economic state outside this local window']}


def acquisition_span(windows):
    if not windows or any(w.get('status')!='local_acquisition_window' for w in windows):
        return {'status':'unknown','duration_ms':None,'economic_alignment_proven':False}
    start=min(w['requested_ms'] for w in windows);end=max(w['available_ms'] for w in windows)
    common_start=max(w['requested_ms'] for w in windows);common_end=min(w['available_ms'] for w in windows)
    return {'status':'local_collection_span','requested_ms':start,'available_ms':end,'duration_ms':end-start,
        'requests_overlap':common_start<=common_end,'economic_alignment_proven':False,
        'limits':['overlapping requests do not establish simultaneous economic states or completeness']}

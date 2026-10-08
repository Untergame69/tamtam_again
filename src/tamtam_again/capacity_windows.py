"""Complete wall-clock buckets include idle time; no statistical independence claim."""
from __future__ import annotations
import math


def summarize_windows(rows, *, since, until, bucket_seconds=3600, local_budget=900,
                      recovery_fraction=.2):
    if not all(math.isfinite(x) for x in (since, until, local_budget, recovery_fraction)):
        raise ValueError('Finite measurement bounds required')
    if since >= until or type(bucket_seconds) is not int or bucket_seconds <= 0:
        raise ValueError('Ordered bounds and positive buckets required')
    if local_budget <= 0 or not 0 <= recovery_fraction < 1:
        raise ValueError('Invalid capacity policy')
    first=math.ceil(since/bucket_seconds)*bucket_seconds
    last=math.floor(until/bucket_seconds)*bucket_seconds
    buckets={start:{'start':start,'end':start+bucket_seconds,'attempts':0,
                    'reserved_weight':0,'rate_limits':0,'wait_seconds':0,
                    'response_bytes':0,'phases':{}}
             for start in range(first,last,bucket_seconds)}
    from .capacity import PHASES
    for row in rows:
        stamp=row['started_at']
        if not math.isfinite(stamp): raise ValueError('Invalid request time')
        start=math.floor(stamp/bucket_seconds)*bucket_seconds
        if start not in buckets:continue
        bucket=buckets[start];bucket['attempts']+=1
        for key in ('reserved_weight','wait_seconds','response_bytes'):
            value=row[key]
            if not math.isfinite(value) or value<0:raise ValueError('Invalid measurement')
            bucket[key]+=value
        bucket['rate_limits']+=row['http_status']==429
        phase=PHASES.get(row['task'],'unclassified')
        bucket['phases'][phase]=bucket['phases'].get(phase,0)+row['reserved_weight']
    operational=local_budget*(1-recovery_fraction)
    for bucket in buckets.values():
        bucket['reserved_weight_per_minute']=bucket['reserved_weight']/(bucket_seconds/60)
        bucket['exceeds_operational_budget']=bucket['reserved_weight_per_minute']>operational
    values=list(buckets.values())
    rates=sorted(b['reserved_weight_per_minute'] for b in values)
    return {'complete_buckets':values,'complete_bucket_count':len(values),
            'excluded_partial_seconds':until-since-len(values)*bucket_seconds,
            'mean_reserved_weight_per_minute':sum(rates)/len(rates) if rates else None,
            'p95_reserved_weight_per_minute':rates[math.ceil(.95*len(rates))-1] if rates else None,
            'maximum_reserved_weight_per_minute':max(rates) if rates else None,
            'operational_budget_per_minute':operational,
            'buckets_above_operational_budget':sum(b['exceeds_operational_budget'] for b in values),
            'limits':['idle complete buckets are included; missing instrumentation may resemble idle time',
                      'empirical quantiles, not confidence intervals or independent samples',
                      'request start assigns weight to a bucket; quota waiting can cross boundaries',
                      'weight reserved locally, not server billing; no extrapolated account capacity']}

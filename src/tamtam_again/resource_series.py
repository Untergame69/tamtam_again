"""Measured resource intervals, with gaps/identity changes left unknown."""
from .resources import resource_change
from .service_resources import service_changes


def summarize(samples,*,since,until,maximum_gap_seconds=180):
    if since>=until or maximum_gap_seconds<=0:raise ValueError('Ordered window and positive gap policy required')
    points=sorted((s for s in samples if since<=s['services']['sampled_at']<=until),key=lambda s:s['services']['sampled_at'])
    units={};storage_seconds=0;storage_growth=0;gaps=[];intervals=0
    for before,after in zip(points,points[1:]):
        elapsed=after['services']['sampled_at']-before['services']['sampled_at']
        if elapsed<=0:raise ValueError('Resource sample times must be distinct')
        intervals+=1
        delta=service_changes(before['services'],after['services'])
        gap=elapsed>maximum_gap_seconds
        if gap:gaps.append({'start':before['services']['sampled_at'],'end':after['services']['sampled_at'],'seconds':elapsed})
        for row in delta['units']:
            target=units.setdefault(row['unit'],{'known_seconds':0,'unknown_seconds':0,'cpu_seconds':0,'maximum_interval_cpu_cores':None})
            rate=row['cpu_cores_used']
            if gap or rate is None:target['unknown_seconds']+=elapsed
            else:
                target['known_seconds']+=elapsed;target['cpu_seconds']+=rate*elapsed
                peak=target['maximum_interval_cpu_cores']
                target['maximum_interval_cpu_cores']=rate if peak is None else max(peak,rate)
        sd=resource_change(before['storage'],after['storage'])
        if not gap and sd['same_database']:
            storage_seconds+=sd['elapsed_seconds']
            storage_growth+=sd['logical_live_growth_bytes_per_second']*sd['elapsed_seconds']
    window=until-since
    for unit,target in units.items():
        target['mean_cpu_cores_on_known_intervals']=target['cpu_seconds']/target['known_seconds'] if target['known_seconds'] else None
        target['known_fraction_of_requested_window']=target['known_seconds']/window
        memory=[r.get('MemoryCurrent') for s in points for r in s['services']['units'] if r['unit']==unit]
        known=[x for x in memory if type(x) is int and x>=0]
        target['maximum_sampled_cgroup_memory_bytes']=max(known) if known else None
        target['memory_meaning']='includes page cache and descendants; sampled maximum is not continuous peak or RSS'
    return {'version':'resource-series-v1','requested_seconds':window,'samples':len(points),'intervals':intervals,
      'first_sample_at':points[0]['services']['sampled_at'] if points else None,
      'last_sample_at':points[-1]['services']['sampled_at'] if points else None,
      'maximum_gap_seconds_policy':maximum_gap_seconds,'excluded_gaps':gaps,'units':units,
      'storage_known_seconds':storage_seconds,'storage_known_fraction_of_requested_window':storage_seconds/window,
      'logical_live_growth_bytes_per_second_on_known_intervals':storage_growth/storage_seconds if storage_seconds else None,
      'latest_disk_free_bytes':points[-1]['storage']['disk_free_bytes'] if points else None,
      'capacity_forecast':False,
      'limits':['CPU averages cover known same-invocation intervals only, never the entire window by default',
        'long sample gaps excluded even when counters remained available',
        'short oneshots between samples may be missed; child IA outside project groups not attributed',
        'storage growth is logical live pages including indexes, not unique payload bytes',
        'no extrapolated sustainable capacity or recurring-cost estimate']}

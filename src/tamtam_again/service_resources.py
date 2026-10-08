"""Project cgroup accounting without command lines, environment or secret access."""
import subprocess,time
from pathlib import Path

UNITS=tuple('tamtam-again-'+name+'.service' for name in
 ('collectors','population','discovery','population-research','research','paper'))
PROPERTIES=('ActiveState','SubState','InvocationID','ControlGroup','CPUUsageNSec','MemoryCurrent')


def parse_properties(text):
    fields={}
    for line in text.splitlines():
        key,sep,value=line.partition('=')
        if sep and key in PROPERTIES:fields[key]=value
    for key in ('CPUUsageNSec','MemoryCurrent'):
        try:
            value=int(fields.get(key,''))
            fields[key]=value if 0<=value<2**64-1 else None
        except ValueError:fields[key]=None
    return fields


def sample_services():
    records=[]
    for unit in UNITS:
        cmd=['systemctl','--user','show',unit]
        for key in PROPERTIES:cmd.extend(['-p',key])
        response=subprocess.run(cmd,capture_output=True,text=True,timeout=5)
        if response.returncode:
            records.append({'unit':unit,'status':'unavailable'});continue
        fields=parse_properties(response.stdout);memory={}
        group=fields.get('ControlGroup','')
        if group.startswith('/') and '..' not in Path(group).parts:
            try:
                for line in (Path('/sys/fs/cgroup')/group.lstrip('/')/'memory.stat').read_text().splitlines():
                    key,value=line.split()
                    if key in ('anon','file','kernel','shmem'):memory[key]=int(value)
            except (OSError,ValueError):pass
        records.append({'unit':unit,'status':'observed',**fields,'memory_components_bytes':memory})
    return {'sampled_at':time.time(),'units':records,
      'limits':['cgroup memory includes page cache; not process RSS',
        'CPU counters belong to one invocation; never subtract across a restart',
        'short invocations between samples may be missed; not full oneshot CPU accounting',
        'IA outside these cgroups and other machine workloads are not attributed']}


def service_changes(before,after):
    elapsed=after['sampled_at']-before['sampled_at']
    if elapsed<=0:raise ValueError('Resource samples must advance')
    prior={r['unit']:r for r in before['units']};result=[]
    for row in after['units']:
        old=prior.get(row['unit'],{})
        same=bool(row.get('InvocationID') and row.get('InvocationID')==old.get('InvocationID'))
        first,last=old.get('CPUUsageNSec'),row.get('CPUUsageNSec')
        known=same and isinstance(first,int) and isinstance(last,int) and last>=first
        result.append({'unit':row['unit'],'same_invocation':same,
            'cpu_cores_used':(last-first)/1e9/elapsed if known else None,
            'current_cgroup_memory_bytes':row.get('MemoryCurrent'),
            'cpu_status':'measured_same_invocation' if known else 'unknown_missing_or_restarted_invocation'})
    return {'elapsed_seconds':elapsed,'units':result,'capacity_forecast':False}

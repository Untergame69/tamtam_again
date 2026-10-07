#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from tamtam_again.resources import sample_resources,resource_change
from tamtam_again.telemetry import Telemetry

p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--telemetry',type=Path,required=True)
p.add_argument('--pid',type=int)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
t=Telemetry(a.telemetry)
with t.connect() as c:
    previous=c.execute("select metrics_json from collector_measurements where collector='resources' order by recorded_at desc limit 1").fetchone()
sample=sample_resources(a.db,pid=a.pid)
result={'sample':sample,'change':resource_change(json.loads(previous[0]),sample) if previous else None}
t.measure('resources',sample)
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))

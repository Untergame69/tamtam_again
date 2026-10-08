#!/usr/bin/env python3
"""Persist small metadata samples in separate telemetry; no archive reads."""
import argparse,json
from pathlib import Path
from tamtam_again.resources import sample_resources,resource_change
from tamtam_again.service_resources import sample_services,service_changes
from tamtam_again.telemetry import Telemetry
p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True)
p.add_argument('--telemetry',type=Path,required=True);a=p.parse_args()
t=Telemetry(a.telemetry)
with t.connect() as c:
 old=c.execute("select metrics_json from collector_measurements where collector='service-resources-v1' order by recorded_at desc limit 1").fetchone()
sample={'storage':sample_resources(a.db),'services':sample_services()}
previous=json.loads(old[0]) if old else None
report={'sample':sample,'change':{'storage':resource_change(previous['storage'],sample['storage']),
 'services':service_changes(previous['services'],sample['services'])} if previous else None}
t.measure('service-resources-v1',report['sample'])
print(json.dumps(report))

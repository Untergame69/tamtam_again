#!/usr/bin/env python3
"""Prepare deterministic descriptive packets from local authorized archives; never calls a model."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from tamtam_again.engine import canonical, fingerprint
from tamtam_again.population_packet import packet_for_authorized_pilot
from tamtam_again.population_descriptive import prepare_pilot_packet
from tamtam_again.population_pilot import _historically_qualified, validate_policy


class ReadOnlyStore:
    def __init__(self, path: Path):
        self.connection=sqlite3.connect(f'file:{path.resolve()}?mode=ro',uri=True)
        self.connection.row_factory=sqlite3.Row


def prepare(store, policy):
    validate_policy(policy)
    packets=[]
    task=policy['task_policy']
    allowed=[row['address'] for row in policy['selection']]
    cutoff=policy['admission']['cutoff_ms']
    for item in sorted(policy['selection'],key=lambda row:row['rank']):
        ok,reason=_historically_qualified(store,policy['network'],item['address'],cutoff)
        if not ok:
            packets.append({'candidate':item['candidate'],'status':'not_prepared','reason':reason})
            continue
        base=packet_for_authorized_pilot(store,policy['network'],item['address'],as_of_ms=cutoff,
            max_chars=task['max_packet_chars'],allowed_addresses=allowed)
        if base.get('status')!='packet_ready':
            packets.append({'candidate':item['candidate'],**base})
            continue
        packet=prepare_pilot_packet(store,base['packet'],candidate=item['candidate'],item=item,
            pilot_id=policy['pilot_id'],policy_version=policy['version'],cutoff_ms=cutoff)
        packet['descriptive_packet_char_count']=len(canonical(packet))
        if packet['descriptive_packet_char_count']>task['max_packet_chars']:
            packets.append({'candidate':item['candidate'],'status':'packet_too_large',
                'required_chars':packet['descriptive_packet_char_count'],'max_chars':task['max_packet_chars']})
        else:
            packets.append({'candidate':item['candidate'],'status':'packet_ready',
                'packet_fingerprint':packet['fingerprint'],'research_input_fingerprint':packet['research_input_fingerprint'],
                'summary_fingerprint':packet['observations']['descriptive_history_v1']['summary_fingerprint'],
                'packet':packet})
    result={'schema_version':'population-descriptive-packet-set-v1','summary_version':'population-descriptive-summary-v1',
        'pilot_id':policy['pilot_id'],'network':policy['network'],'cutoff_ms':cutoff,
        'source':'local sqlite archives only; no network acquisition or inference',
        'candidate_packets':packets}
    result['set_fingerprint']=fingerprint(result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--policy',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    policy=json.loads(args.policy.read_text())
    store=ReadOnlyStore(args.db)
    try:
        result=prepare(store,policy)
    finally:
        store.connection.close()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'output':str(args.output),'set_fingerprint':result['set_fingerprint'],
        'candidates':[{'candidate':row['candidate'],'status':row['status'],
            'packet_fingerprint':row.get('packet_fingerprint'),'summary_fingerprint':row.get('summary_fingerprint')}
            for row in result['candidate_packets']]},ensure_ascii=False))


if __name__=='__main__':
    main()

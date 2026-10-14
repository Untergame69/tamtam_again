import hashlib
import json
import tempfile
import unittest
import zlib
from datetime import datetime,timezone
from pathlib import Path

from tamtam_again.engine import canonical
from tamtam_again.population_descriptive import prepare_candidate_summary,prepare_pilot_packet
from tamtam_again.storage import Store


class PopulationDescriptiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'summary.sqlite3')
        self.store.connection.execute('create table account_scope_reports '
            '(report_id text primary key,network text,address text,available_ms integer,payload_json text)')
        self.network='hyperliquid-mainnet';self.address='0x'+'1'*40;self.cutoff=200
        report={'address':self.address,'markets':['COIN'],'fills_requested_start_ms':90,
            'fills_requested_end_ms':180,'activity':{'observed_unique_fills':2,'window_seconds':90},
            'current_pass_behavior_profile':{'fills_observed':2,'evidence_refs':['population_attempts:test']}}
        self.store.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',
            ('scope-test',self.network,self.address,190,json.dumps(report,sort_keys=True,separators=(',',':'))))
        self.store.connection.commit()

    def tearDown(self):
        self.store.close();self.tmp.cleanup()

    def _raw(self,observation_id,endpoint,payload,*,start=90,end=180,observed=190,complete=False,status='pagination_exhausted'):
        body=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        stamp=datetime.fromtimestamp(observed/1000,timezone.utc).isoformat(timespec='milliseconds')
        self.store.connection.execute('insert into raw_observations '
            '(observation_id,network,source,entity_type,entity_id,endpoint,request_json,requested_at,observed_at,'
            'window_start_ms,window_end_ms,record_count,complete,response_encoding,response_sha256,response_json,receipt_id) '
            'values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (observation_id,self.network,'hyperliquid-population-rest-v1','account',self.address,endpoint,
             json.dumps({'pagination_status':status},sort_keys=True),stamp,stamp,start,end,
             len(payload),int(complete),'zlib+json',hashlib.sha256(body.encode()).hexdigest(),
             zlib.compress(body.encode()),'receipt-'+str(observation_id)))
        self.store.connection.commit()

    def test_summary_and_enriched_packet_are_reproducible_and_keep_boundaries(self):
        fills=[
            {'coin':'COIN','tid':'open','time':100,'startPosition':'0','side':'B','sz':'1','px':'10','fee':'0.01','feeToken':'USDC','crossed':False},
            {'coin':'COIN','tid':'close','time':150,'startPosition':'1','side':'A','sz':'1','px':'12','fee':'-0.02','feeToken':'USDC','crossed':True},
            {'coin':'COIN','tid':'after','time':201,'startPosition':'0','side':'B','sz':'1','px':'9','fee':'0','feeToken':'USDC','crossed':False},
            {'coin':'COIN','tid':'conflict','time':120,'startPosition':'1','side':'A','sz':'0.1','px':'11','fee':'0','feeToken':'USDC','crossed':False},
        ]
        self._raw(1,'userFillsByTime',fills)
        self._raw(2,'userFillsByTime',[fills[0]])
        changed=dict(fills[3]);changed['px']='11.1'
        self._raw(3,'userFillsByTime',[changed])
        funding=[{'time':125,'hash':'fund-1','delta':{'coin':'COIN','usdc':'0.5','szi':'1'}}]
        self._raw(4,'userFunding',funding)

        summary=prepare_candidate_summary(self.store,self.network,self.address,cutoff_ms=self.cutoff,candidate='fixture')
        replay=prepare_candidate_summary(self.store,self.network,self.address,cutoff_ms=self.cutoff,candidate='fixture')
        self.assertEqual(summary['summary_fingerprint'],replay['summary_fingerprint'])
        self.assertEqual(summary['evidence_fingerprint'],replay['evidence_fingerprint'])
        self.assertEqual(summary['coverage']['fill_archive']['usable_unique_fill_count'],2)
        self.assertEqual(summary['coverage']['fill_archive']['duplicate_fill_instances'],2)
        self.assertEqual(summary['coverage']['fill_archive']['conflicting_fill_identity_count'],1)
        self.assertEqual(summary['coverage']['fill_archive']['records_after_cutoff_excluded'],1)
        market=summary['markets']['COIN']
        self.assertEqual(market['positions']['locally_reconstructible_flat_to_flat_episode_count'],1)
        self.assertEqual(market['price_result']['price_result_quote_units'],'2')
        self.assertEqual(market['signed_fees']['archive_fill_signed_fee_by_token']['USDC'],'-0.01')
        self.assertEqual(market['signed_fees']['bounded_episode_part_signed_fee_by_token']['USDC'],'-0.01')
        self.assertEqual(market['scope_membership'],'listed_by_available_scope_report')
        self.assertEqual(market['funding']['strictly_position_attributed_event_count'],1)
        self.assertEqual(market['funding']['strictly_position_attributed_amount_usdc'],'0.5')

        base={'schema_version':'fixture','network':self.network,'address':self.address,'available_ms':190,
            'research_input_fingerprint':'base','evidence_refs':['scope-test'],'observations':{}}
        item={'candidate':'fixture','rank':1,'research_interest':'fixture','observability':'partial',
            'paper_engine_compatibility':'unknown','question':'No inference in this test.'}
        packet=prepare_pilot_packet(self.store,base,candidate='fixture',item=item,pilot_id='p',
            policy_version='v',cutoff_ms=self.cutoff)
        packet2=prepare_pilot_packet(self.store,base,candidate='fixture',item=item,pilot_id='p',
            policy_version='v',cutoff_ms=self.cutoff)
        self.assertEqual(packet['fingerprint'],packet2['fingerprint'])
        self.assertEqual(base['evidence_refs'],['scope-test'])
        self.assertEqual(len(packet['evidence_refs']),len(set(packet['evidence_refs'])))
        self.assertTrue(any(ref.startswith('raw_observations:1#sha256:') for ref in packet['evidence_refs']))

    def test_unreleased_reserved_window_is_rejected_before_observation_decode(self):
        self.store.connection.execute('create table validation_plans '
            '(plan_id text,network text,address text,plan_json text)')
        plan={'comparison':{'start_ms':150,'end_ms':250},'final':{'start_ms':300,'end_ms':400}}
        self.store.connection.execute('insert into validation_plans values(?,?,?,?)',
            ('reserved',self.network,self.address,json.dumps(plan)))
        self.store.connection.execute('insert into raw_observations '
            '(observation_id,network,source,entity_type,entity_id,endpoint,request_json,requested_at,observed_at,'
            'window_start_ms,window_end_ms,record_count,complete,response_encoding,response_sha256,response_json,receipt_id) '
            'values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (90,self.network,'hyperliquid-population-rest-v1','account',self.address,'userFillsByTime','{}',
             '1970-01-01T00:00:00Z','1970-01-01T00:00:00Z',90,180,1,0,'zlib+json','bad',b'not-zlib','r'))
        self.store.connection.commit()
        with self.assertRaisesRegex(PermissionError,'unreleased reserved period'):
            prepare_candidate_summary(self.store,self.network,self.address,cutoff_ms=self.cutoff)


if __name__=='__main__':unittest.main()

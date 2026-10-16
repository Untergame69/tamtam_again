"""Resolution revisions must reach the next packet without reopening old work."""
import json
import unittest
from unittest.mock import patch

from tests.test_population_runtime import RuntimeTests
from tamtam_again.engine import canonical, fingerprint
from tamtam_again.population_memory import remember
from tamtam_again.population_packet import packet_for_account as build_packet
from tamtam_again.research_memory import export_knowledge
from tamtam_again.research_work_queue import enqueue, tick as queue_tick


class ResolutionMemoryTests(unittest.TestCase):
    setUp=RuntimeTests.setUp
    tearDown=RuntimeTests.tearDown

    def seed(self):
        self.result={'proposal':{'hypothesis':{'mechanism':'inventory association','markets':['ETH'],
            'required_data':['join existing context'],'rejection_criteria':'no association',
            'execution_constraints':'no execution','risk':'exploratory'}},
            'critique':{'decision':'consistent'},'promotion_authorized':False,'profitability_proven':False}
        self.write()
        self.original=remember(self.s,self.request)['knowledge_id']
        self.artifact={'network':'test','address':'account','market':'ETH',
            'window':{'start_ms':21,'end_ms':40,'archive_receipt_cutoff_ms':45},
            'next_action':{'remaining_question':'live availability unknown','automatic_action':'stop fixed task'}}
        self.digest=fingerprint(self.artifact)
        self.s.connection.execute('create table population_local_archive_resolutions(request_id text,artifact_fingerprint text,artifact_json text,created_ms integer)')
        self.s.connection.execute('insert into population_local_archive_resolutions values(?,?,?,?)',
            (self.request,self.digest,canonical(self.artifact),50))
        self.result['local_archive_resolutions_v1']={'contract':{'state':'complete','artifact_fingerprint':self.digest,'report_input_fingerprint':'report'}}
        self.result['resolution_assessment_v1']={'version':1,'question':'Does event association imply executable REST edge?',
            'new_evidence':[self.digest],'conclusion':'Reject that interpretation; live remains unmeasured.',
            'unknowns':['live edge','autonomous rule'],'next_action':'Stop existing-window task; retain descriptive result.',
            'disposition':'completed','artifact_fingerprints':[self.digest]}
        self.write()

    def write(self):
        self.s.connection.execute("update population_research_jobs set status='hypothesis_recorded',result_json=?,updated_ms=30",(canonical(self.result),))
        self.s.connection.commit()

    def test_revision_selected_in_next_packet_replay_and_timestamp_no_inference(self):
        with patch('tamtam_again.research_memory.clock',return_value=100):
            self.seed();saved=remember(self.s,self.request)
            self.assertNotEqual(saved['knowledge_id'],self.original)
            entries=export_knowledge(self.s,as_of_ms=100,network='test',address='account',market='*')
            self.assertEqual([e['knowledge_id'] for e in entries],[saved['knowledge_id']])
            self.assertEqual(entries[0]['item']['open_questions'],['live edge','autonomous rule'])
            self.assertTrue(any(p['end_ms']==46 for p in entries[0]['item']['periods']))
            packet=build_packet(self.s,'test','account',as_of_ms=100,max_chars=20000)['packet']
            self.assertEqual(packet['research_memory'][0]['knowledge_id'],saved['knowledge_id'])
            self.assertIn('knowledge:'+saved['knowledge_id'],packet['evidence_refs'])
            self.assertTrue(any(ref.startswith('population_resolution:') for ref in packet['evidence_refs']))
            self.s.connection.execute('update population_research_jobs set updated_ms=99');self.s.connection.commit()
            self.assertEqual(remember(self.s,self.request)['status'],'already_recorded')
            again=build_packet(self.s,'test','account',as_of_ms=100,max_chars=20000)['packet']
            self.assertEqual(packet['research_input_fingerprint'],again['research_input_fingerprint'])
            from tamtam_again.population_research import seal
            self.assertEqual(seal(self.s,'test','account',self.policy,clock_ms=100)['status'],'unchanged_no_inference')
            self.assertEqual(self.s.connection.execute('select count(*) from research_knowledge').fetchone()[0],2)
            self.assertEqual(self.s.connection.execute('select knowledge_id from population_research_memory').fetchone()[0],self.original)

    def test_original_available_at_old_cutoff_and_no_stale_revision_under_budget(self):
        with patch('tamtam_again.research_memory.clock',return_value=100):self.seed()
        with patch('tamtam_again.research_memory.clock',return_value=200):
            first=remember(self.s,self.request)
            early=export_knowledge(self.s,as_of_ms=100,network='test',address='account',market='*')
            self.assertEqual([e['knowledge_id'] for e in early],[self.original])
        self.result['resolution_assessment_v1']['conclusion']='Updated assessment '+('bounded evidence ' * 120)
        self.write()
        with patch('tamtam_again.research_memory.clock',return_value=300):
            latest=remember(self.s,self.request)
            self.assertNotEqual(latest['knowledge_id'],first['knowledge_id'])
            self.assertEqual(export_knowledge(self.s,as_of_ms=300,network='test',address='account',market='*',max_chars=2500),[])

    def test_first_import_after_resolution_is_stable(self):
        self.seed()
        self.s.connection.execute('delete from population_research_memory')
        self.s.connection.execute('delete from research_knowledge');self.s.connection.commit()
        first=remember(self.s,self.request)
        second=remember(self.s,self.request)
        self.assertEqual(first['knowledge_id'],second['knowledge_id'])
        self.assertEqual(second['status'],'already_recorded')
        self.assertEqual(self.s.connection.execute('select count(*) from research_knowledge').fetchone()[0],2)

    def test_tampered_artifact_or_assessment_rejected(self):
        self.seed()
        self.result['resolution_assessment_v1']['artifact_fingerprints']=['invented'];self.write()
        with self.assertRaisesRegex(ValueError,'current local artifacts'):remember(self.s,self.request)
        self.result['resolution_assessment_v1']['artifact_fingerprints']=[self.digest];self.write()
        self.s.connection.execute("update population_local_archive_resolutions set artifact_json='{}'")
        with self.assertRaisesRegex(ValueError,'fingerprint mismatch'):remember(self.s,self.request)

    def test_scheduler_consumes_revision_and_preserves_waiting_history(self):
        from tamtam_again.population_scheduler import tick
        self.seed()
        old,_=enqueue(self.s,'population_route',self.request,{'state':'needs_data'},status='waiting_data')
        with patch('tamtam_again.population_runtime.call') as call:
            result=tick(self.s,'test',self.policy,dispatch=False)
            replay=tick(self.s,'test',self.policy,dispatch=False)
            call.assert_not_called()
        current=self.s.connection.execute("select * from research_work_queue_current where source_kind='population_route'").fetchall()
        self.assertEqual(len(current),1);self.assertEqual(current[0]['status'],'completed')
        self.assertEqual(self.s.connection.execute('select status from research_work_queue where work_id=?',(old['work_id'],)).fetchone()[0],'waiting_data')
        self.assertEqual(result['routes'][0]['state'],'completed')
        self.assertNotIn('required_data',result['routes'][0])
        self.assertEqual(result['routes'][0]['resolved_data'],['join existing context'])
        self.assertEqual(result['memory'][0]['knowledge_id'],replay['memory'][0]['knowledge_id'])
        # An unrelated eligible local queue item still advances with the completed task present.
        other,_=enqueue(self.s,'eth_observation_report','other',{'protocol_id':'other','stage':'final_24h'})
        advanced=queue_tick(self.s,max_jobs=1)
        self.assertEqual(advanced['advanced'],[{'work_id':other['work_id'],'status':'waiting_data'}])

del RuntimeTests

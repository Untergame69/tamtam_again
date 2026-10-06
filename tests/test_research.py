from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tamtam_again.research import build_plan, packet_for, load_policy, prepare, run_job, enforce_profile
from tamtam_again.storage import Store
from tamtam_again.validation import now_ms

class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store=Store(Path(self.directory.name)/'test.sqlite3')
        self.addCleanup(self.store.connection.close)
        self.policy=load_policy();self.policy['packet_schema_version']=1;self.address='0x'+'1'*40
        self.store.add_candidate(self.policy['network'],self.address,'synthetic-test')
        self.store.connection.execute("UPDATE candidates SET status='tracked' WHERE address=?",(self.address,));self.store.connection.commit()
        clock=now_ms()
        self.cycles=[{'cycle_id':'synthetic-cycle','opened_at_ms':clock-5000,'closed_at_ms':clock-1000,'cycle_kind':'baseline_excursion','baseline_position':'10','ending_position':'10'}]
        self.events=[{'id':'quote','kind':'bbo','event_ms':clock-4000,'received_ms':clock-3900,'available_ms':clock-3800},
                     {'id':'signal','kind':'leader_fill','event_ms':clock-3000,'received_ms':clock-2900,'available_ms':clock-2800}]
        self.status={'accounts':[{'account':'compte-01','data_maturity_by_market':[{'coin':'BTC','hypothesis_gate_ready':True,'hypothesis_cycle_target':1,'exploitable_cycle_ids':['synthetic-cycle'],'exploitable_cycle_summaries':self.cycles}]}]}

    def prepared_job(self):
        with patch('tamtam_again.research.archive_events',return_value=(self.events,1)):
            result=prepare(self.store,self.policy,self.status)
        return result['created'][0]

    def test_prospective_disjoint_plan_and_unchanged_data_no_new_plan(self):
        job=self.prepared_job()
        plan=json.loads(self.store.connection.execute('SELECT plan_json FROM validation_plans').fetchone()[0])
        self.assertGreater(plan['comparison']['start_ms'],now_ms())
        self.assertGreaterEqual(plan['final']['start_ms'],plan['comparison']['end_ms']+plan['embargo_ms'])
        with patch('tamtam_again.research.archive_events',return_value=(self.events,1)):
            self.assertEqual(prepare(self.store,self.policy,self.status)['created'],[])

    def test_export_rejects_future_availability_and_crossing_cycles(self):
        clock=now_ms();plan=build_plan(self.address,'BTC',self.cycles,self.policy,clock)
        events=deepcopy(self.events);events[0]['available_ms']=clock
        with self.assertRaises(ValueError):packet_for(plan,self.cycles,events,self.policy)
        cycles=deepcopy(self.cycles);cycles[0]['closed_at_ms']=clock
        with self.assertRaises(ValueError):packet_for(plan,cycles,self.events,self.policy)

    def test_profile_cannot_lower_costs_or_increase_risk(self):
        packet={'strategy_template':deepcopy(self.policy['strategy_template'])}
        spec=deepcopy(packet['strategy_template']);spec['fees']['taker_bps']='0'
        with self.assertRaises(ValueError):enforce_profile(spec,packet)

    def test_two_roles_freeze_without_profitability_promotion_and_no_relaunch(self):
        job=self.prepared_job();spec=deepcopy(self.policy['strategy_template']);spec['market']='BTC'
        usage={'cost_usd':0,'cost_status':'included','duration_ms':1,'input_tokens':100,'output_tokens':100}
        proposal={'decision':'propose','diagnostic':'synthetic test','strategy_spec':spec}
        critique={'decision':'accept','diagnostic':'testable fixture only','wake':{}}
        with patch('tamtam_again.research.verify'),patch('tamtam_again.research.call',side_effect=[(json.dumps(proposal),usage),(json.dumps(critique),usage)]) as call:
            result=run_job(self.store,job['run_id'])
            self.assertEqual(result['status'],'ready_to_test');self.assertEqual(call.call_count,2)
            self.assertEqual(run_job(self.store,job['run_id'])['status'],'unchanged_no_inference')
            self.assertEqual(call.call_count,2)
        self.assertEqual(self.store.connection.execute('SELECT count(*) FROM paper_sessions').fetchone()[0],0)
        self.assertEqual(self.store.connection.execute('SELECT count(*) FROM validation_evaluations').fetchone()[0],0)

    def test_failure_consumes_input_and_budget_no_retry(self):
        job=self.prepared_job()
        with patch('tamtam_again.research.verify'),patch('tamtam_again.research.call',side_effect=TimeoutError) as call:
            self.assertEqual(run_job(self.store,job['run_id'])['status'],'suspended')
            self.assertEqual(run_job(self.store,job['run_id'])['status'],'unchanged_no_inference')
            self.assertEqual(call.call_count,1)
        row=self.store.connection.execute('SELECT reserved_cost_usd,actual_cost_usd FROM isolated_research_jobs').fetchone()
        self.assertEqual(row[0],'2');self.assertIsNone(row[1])

    def test_invalid_response_is_preserved_with_measured_usage(self):
        job=self.prepared_job()
        usage={'cost_usd':0,'cost_status':'included','duration_ms':1}
        with patch('tamtam_again.research.verify'),patch('tamtam_again.research.call',return_value=('invalid fixture response',usage)):
            self.assertEqual(run_job(self.store,job['run_id'])['status'],'suspended')
        row=self.store.connection.execute('SELECT result_json,usage_json FROM isolated_research_jobs').fetchone()
        self.assertEqual(json.loads(row[0])['raw_proposal_response'],'invalid fixture response')
        self.assertEqual(json.loads(row[1]),[usage])

    def test_isolation_failure_prevents_any_inference(self):
        job=self.prepared_job()
        with patch('tamtam_again.research.verify',side_effect=RuntimeError),patch('tamtam_again.research.call') as call:
            with self.assertRaises(RuntimeError):run_job(self.store,job['run_id'])
            call.assert_not_called()

    def test_missing_live_signal_cannot_create_a_plan(self):
        with patch('tamtam_again.research.archive_events',return_value=([],0)):
            self.assertEqual(prepare(self.store,self.policy,self.status)['created'],[])

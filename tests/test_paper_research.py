import unittest,json,sqlite3
from types import SimpleNamespace
from unittest.mock import patch
from tamtam_again.paper_research import packet,seal

class PaperResearchTests(unittest.TestCase):
 def setUp(self):
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.s=SimpleNamespace(connection=self.c)
  self.c.executescript('''create table paper_adaptation_requests(request_id text,session_id text,created_ms integer,diagnostic_json text);
   create table paper_sessions(session_id text,variant_id text,started_ms integer);
   create table validation_plans(plan_id text,network text,address text,coin text,plan_json text);
   create table strategy_variants(variant_id text,plan_id text,spec_json text,frozen_ms integer);
   create table research_period_releases(evaluation_id text,released_ms integer);
   create table validation_evaluations(evaluation_id text,plan_id text,stage text);''')
  d={'request_id':'a','session_id':'s','created_ms':200,'state':'research_budget_required','paper_snapshot_available_ms':190,'evidence_refs':['paper_snapshots:proof'],'observed_paper_metrics':{'net_pnl':'-5'}}
  self.c.execute('insert into paper_adaptation_requests values(?,?,?,?)',('a','s',200,json.dumps(d)))
  self.c.execute('insert into paper_sessions values(?,?,?)',('s','v',100))
  self.plan={'comparison':{'start_ms':0,'end_ms':50},'final':{'start_ms':50,'end_ms':90}}
  self.c.execute('insert into validation_plans values(?,?,?,?,?)',('p','test','address','BTC',json.dumps(self.plan)))
  self.c.execute('insert into strategy_variants values(?,?,?,?)',('v','p',json.dumps({'market':'BTC'}),90));self.c.commit()
  self.policy={'version':'paper-adaptation-research-v1','justification':'fixture','max_requests':1,'max_packet_chars':10000,'minimum_interval_ms':1,'timeout_seconds':1,'max_output_tokens':1,'max_request_age_ms':100,'model':'fixture','call_reservation_usd':'1'}
 def tearDown(self):self.c.close()
 def test_seal_once_without_model_or_old_rule_mutation(self):
  before=self.c.execute('select spec_json from strategy_variants').fetchone()[0]
  r=seal(self.s,'a',self.policy,clock_ms=200)
  self.assertEqual(r['status'],'sealed');self.assertEqual(r['model_calls'],0)
  self.assertEqual(seal(self.s,'a',self.policy,clock_ms=201)['status'],'unchanged_no_inference')
  self.assertEqual(self.c.execute('select spec_json from strategy_variants').fetchone()[0],before)
  from tamtam_again.procedure_trace import registry_trace
  trace=registry_trace(self.s,as_of_ms=200)
  self.assertEqual(len([e for e in trace['events'] if e['kind']=='paper_research_sealed']),1)
  self.assertNotIn('observed_paper_metrics',str(trace))
 def test_future_or_reserved_diagnostic_not_read(self):
  with self.assertRaises(ValueError):packet(self.s,'a',clock_ms=199,max_chars=10000)
  self.plan['final']['end_ms']=150
  self.c.execute('update validation_plans set plan_json=?',(json.dumps(self.plan),));self.c.commit()
  queries=[];self.c.set_trace_callback(queries.append)
  with self.assertRaises(ValueError):packet(self.s,'a',clock_ms=200,max_chars=10000)
  self.assertFalse(any('select spec_json' in q or 'select diagnostic_json' in q for q in queries))
 def test_full_packet_budget_and_nonperformance_diagnostic(self):
  self.assertEqual(packet(self.s,'a',clock_ms=200,max_chars=1)['status'],'needs_data')
  d=json.loads(self.c.execute('select diagnostic_json from paper_adaptation_requests').fetchone()[0]);d['state']='collection_correction_required'
  self.c.execute('update paper_adaptation_requests set diagnostic_json=?',(json.dumps(d),));self.c.commit()
  self.assertEqual(seal(self.s,'a',self.policy,clock_ms=200)['status'],'not_researchable')
 def test_new_policy_version_does_not_reset_total_budget(self):
  seal(self.s,'a',self.policy,clock_ms=200)
  d=json.loads(self.c.execute('select diagnostic_json from paper_adaptation_requests').fetchone()[0]);d.update(request_id='b',created_ms=201)
  self.c.execute('insert into paper_adaptation_requests values(?,?,?,?)',('b','s',201,json.dumps(d)));self.c.commit()
  self.assertEqual(seal(self.s,'b',self.policy,clock_ms=201)['status'],'budget_exhausted')

import json,sqlite3,unittest
from types import SimpleNamespace
from tamtam_again.engine import fingerprint
from tamtam_again.paper_adaptation import diagnose,record,recover

class PaperAdaptationTests(unittest.TestCase):
 def setUp(self):
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
  self.s=SimpleNamespace(connection=self.c)
  self.c.executescript('''create table paper_sessions(session_id text,variant_id text,status text,state_json text);
   create table paper_suspensions(session_id text,suspended_ms integer,diagnostics_json text);
   create table paper_snapshots(snapshot_id text,session_id text,available_ms integer,state_fingerprint text,metrics_json text);''')
 def tearDown(self):self.c.close()
 def fixture(self,code='paper_net_loss_budget_exhausted'):
  state={'diagnostics':[code],'positions':{'BTC':'1'}}
  self.c.execute('insert into paper_sessions values(?,?,?,?)',('s','v','suspended',json.dumps(state)))
  self.c.execute('insert into paper_suspensions values(?,?,?)',('s',100,json.dumps([code])))
  self.c.execute('insert into paper_snapshots values(?,?,?,?,?)',('proof','s',101,fingerprint(state),json.dumps({'net_pnl':'-5'})))
  self.c.commit()
 def test_collection_failure_precedes_performance_attribution(self):
  r=diagnose(['missing_live_heartbeat','paper_net_loss_budget_exhausted'])
  self.assertEqual(r['state'],'collection_correction_required')
  self.assertEqual(r['performance_attribution'],'unproven')
  self.assertEqual(r['model_calls_authorized'],0)
 def test_unknown_and_budget_and_delayed_signal_routes(self):
  for code,state in [('novel_unknown','diagnostic_review_required'),
   ('paper_duration_budget_exhausted','experiment_complete'),
   ('leader_signal_not_live','execution_model_review_required'),
   ('risk_drawdown_limit','research_budget_required')]:
   self.assertEqual(diagnose([code])['state'],state)
 def test_recovery_seals_one_request_preserves_position_and_replays(self):
  self.fixture();before=self.c.execute('select state_json from paper_sessions').fetchone()[0]
  r=recover(self.s,clock_ms=102)[0]
  self.assertEqual(r['state'],'research_budget_required')
  self.assertEqual(r['observed_paper_metrics']['net_pnl'],'-5')
  self.assertEqual(recover(self.s,clock_ms=200),[])
  self.assertEqual(record(self.s,'s',clock_ms=200),r)
  self.assertEqual(self.c.execute('select state_json from paper_sessions').fetchone()[0],before)
  self.assertFalse(r['promotion_authorized']);self.assertFalse(r['resume_authorized'])
 def test_missing_future_or_mismatched_evidence_is_not_inferred(self):
  self.fixture()
  with self.assertRaises(ValueError):record(self.s,'s',clock_ms=100)
  self.c.execute("update paper_snapshots set state_fingerprint='wrong'");self.c.commit()
  self.assertEqual(recover(self.s,clock_ms=102)[0]['state'],'paper_evidence_required')
  self.assertEqual(self.c.execute('select count(*) from paper_adaptation_requests').fetchone()[0],0)
 def test_disagreement_blocks_sealing(self):
  self.fixture();self.c.execute("update paper_suspensions set diagnostics_json='[\"missing_live_heartbeat\"]'")
  with self.assertRaises(ValueError):record(self.s,'s',clock_ms=102)
 def test_invalid_recovery_budget(self):
  for n in (0,17,True):
   with self.assertRaises(ValueError):recover(self.s,clock_ms=102,max_requests=n)

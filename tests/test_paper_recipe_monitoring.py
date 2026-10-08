"""Fixture market events use production monitoring and diagnosis persistence."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tamtam_again.storage import Store
from tamtam_again.recipe import synthetic_plan,synthetic_spec,synthetic_events
from tamtam_again.validation import create_plan,register_variant,evaluate
from tamtam_again.paper import start_paper,synthetic_recipe_tick

class PaperRecipeMonitoringTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'test.sqlite3')
  plan=synthetic_plan()
  plan['paper_monitoring']={'version':'paper-loss-budget-v1','max_net_loss_usdc':'1','justification':'synthetic safety trigger test'}
  p=create_plan(self.store,plan)
  v=register_variant(self.store,p['plan_id'],synthetic_spec())
  for stage in ('comparison','final'):
   evaluate(self.store,v['variant_id'],stage,synthetic_events(synthetic_plan()[stage]['start_ms']),provenance='synthetic')
  with patch('tamtam_again.paper.now_ms',return_value=30000):
   self.session=start_paper(self.store,v['variant_id'],synthetic_recipe=True)['session_id']
 def tearDown(self):
  self.store.close();self.tmp.cleanup()
 def disconnect(self):
  events=synthetic_events(30000)
  events.append({'id':'disconnect','kind':'connection','session':'fixture-session','connected':False,'received_ms':34000,'event_ms':34000})
  return events
 def test_event_driven_suspension_creates_immutable_diagnostic(self):
  r=synthetic_recipe_tick(self.store,self.session,self.disconnect(),clock_ms=34000)
  self.assertEqual(r['status'],'suspended')
  row=self.store.connection.execute('select * from paper_adaptation_requests').fetchone()
  d=json.loads(row['diagnostic_json'])
  self.assertEqual(d['state'],'collection_correction_required')
  self.assertEqual(d['created_ms'],34000)
  self.assertFalse(d['promotion_authorized'])
  self.assertEqual(d['observed_paper_metrics'],r['metrics'])
  with self.assertRaises(ValueError):synthetic_recipe_tick(self.store,self.session,self.disconnect(),clock_ms=34000)
  self.assertEqual(self.store.connection.execute('select count(*) from paper_adaptation_requests').fetchone()[0],1)
 def test_diagnosis_failure_rolls_back_suspension_and_snapshot(self):
  before=self.store.connection.execute('select state_json from paper_sessions').fetchone()[0]
  with patch('tamtam_again.paper_adaptation.record',side_effect=RuntimeError('interrupted')):
   with self.assertRaises(RuntimeError):synthetic_recipe_tick(self.store,self.session,self.disconnect(),clock_ms=34000)
  row=self.store.connection.execute('select status,state_json from paper_sessions').fetchone()
  self.assertEqual(row['status'],'active');self.assertEqual(row['state_json'],before)
  self.assertEqual(self.store.connection.execute('select count(*) from paper_suspensions').fetchone()[0],0)
  self.assertEqual(synthetic_recipe_tick(self.store,self.session,self.disconnect(),clock_ms=34000)['status'],'suspended')
 def test_future_timer_rejected_before_persistence(self):
  with self.assertRaises(ValueError):synthetic_recipe_tick(self.store,self.session,synthetic_events(30000),clock_ms=31000)
  self.assertEqual(self.store.connection.execute('select status from paper_sessions').fetchone()[0],'active')

 def test_loss_events_produce_research_request_without_injected_decision(self):
  events=synthetic_events(30000)
  for event in events:
   if event['kind']=='bbo' and event.get('bid')=='102':
    event['bid']='99';event['ask']='99.1'
  r=synthetic_recipe_tick(self.store,self.session,events,clock_ms=33140)
  self.assertEqual(r['status'],'suspended')
  self.assertIn('paper_net_loss_budget_exhausted',r['metrics']['diagnostics'])
  d=json.loads(self.store.connection.execute('select diagnostic_json from paper_adaptation_requests').fetchone()[0])
  self.assertEqual(d['state'],'research_budget_required')
  self.assertEqual(d['observed_paper_metrics'],r['metrics'])
  self.assertFalse(d['promotion_authorized'])

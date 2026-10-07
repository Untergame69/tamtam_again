import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tamtam_again.storage import Store
from tamtam_again.validation import decision,initialize,record_evaluation_terminal
from tamtam_again.procedure_trace import registry_trace

class DecisionEvidenceTests(unittest.TestCase):
 def test_new_candidate_evidence_not_hidden_by_same_wait_message(self):
  with tempfile.TemporaryDirectory() as tmp,Store(Path(tmp)/'db') as s:
   for variant in ('first','first','second','second'):
    decision(s,'synthetic','fixture','SYNTH','needs_data','window incomplete',{'end_ms':100},'wait',{'variant_id':variant})
   self.assertEqual(s.connection.execute('select count(*) from pipeline_decisions').fetchone()[0],2)
 def test_terminal_journal_immutable_timestamp_and_trace_without_reserved_status(self):
  with tempfile.TemporaryDirectory() as tmp,Store(Path(tmp)/'db') as s:
   initialize(s)
   from tamtam_again.recipe import synthetic_plan,synthetic_spec
   from tamtam_again.validation import create_plan,register_variant
   plan=create_plan(s,synthetic_plan())['plan_id'];variant=register_variant(s,plan,synthetic_spec())['variant_id']
   s.connection.execute('insert into validation_evaluations values(?,?,?,?,?,?,?,?)',('evaluation',variant,plan,'final','failed','fixture','{}','fixture'))
   s.connection.commit()
   with patch('tamtam_again.validation.now_ms',return_value=3000):record_evaluation_terminal(s,'evaluation','failed')
   s.connection.commit()
   self.assertEqual(registry_trace(s,as_of_ms=2999)['events'],[])
   with patch('tamtam_again.validation.now_ms',return_value=5000):record_evaluation_terminal(s,'evaluation','failed')
   self.assertEqual(s.connection.execute('select available_ms from evaluation_terminal_events').fetchone()[0],3000)
   with self.assertRaises(ValueError):record_evaluation_terminal(s,'evaluation','passed')
   later=registry_trace(s,as_of_ms=3000)
   self.assertEqual(later['events'][0]['kind'],'evaluation_terminal_recorded')
   self.assertNotIn('failed',str(later))
 def test_decision_trace_has_original_date_and_does_not_read_evidence(self):
  with tempfile.TemporaryDirectory() as tmp,Store(Path(tmp)/'db') as s:
   with patch('tamtam_again.validation.utc_now',return_value='1970-01-01T00:00:03+00:00'):
    decision(s,'synthetic','fixture','SYNTH','rejected','sensitive result',{},'review',{'reserved_metric':99})
   self.assertEqual(registry_trace(s,as_of_ms=2999)['events'],[])
   statements=[];s.connection.set_trace_callback(statements.append)
   r=registry_trace(s,as_of_ms=3000)
   self.assertEqual(r['events'][0]['kind'],'pipeline_decision_recorded')
   self.assertNotIn('rejected',str(r));self.assertNotIn('reserved_metric',str(r))
   self.assertFalse(any('evidence_json' in q or 'diagnostic' in q for q in statements))

"""Temporary synthetic proof only; no provider, archive or real paper use."""
import json
import unittest
from tests import test_population_experiments as fixtures
from tamtam_again.research_evaluation import handoff, poll
from tamtam_again.population_experiments import register_experiment
from tamtam_again.validation import evaluate
from tamtam_again.recipe import synthetic_events
from tamtam_again.experiments import select_final


class ResearchEvaluationTests(unittest.TestCase):
 setUp=fixtures.PopulationExperimentTests.setUp
 tearDown=fixtures.PopulationExperimentTests.tearDown
 def test_descriptive_terminal_and_replay(self):
  self.result['proposal']['hypothesis'].pop('executable_spec')
  self.s.connection.execute('update population_research_jobs set result_json=?',(json.dumps(self.result),));self.s.connection.commit()
  first=handoff(self.s,'request')
  self.assertEqual(first['state'],'descriptive')
  self.assertEqual(first['next_plan']['kind'],'next_candidate')
  self.assertEqual(first,handoff(self.s,'request'))
  self.assertEqual(self.s.connection.execute('select count(*) from research_evaluation_memory').fetchone()[0],1)
  self.assertEqual(self.s.connection.execute('select count(*) from strategy_variants').fetchone()[0],0)

 def test_comparison_rejection_feedback_then_next_candidate(self):
  family=register_experiment(self.s,'request',self.plan,self.profile)
  first=handoff(self.s,'request')
  self.assertEqual(first['state'],'awaiting_comparison')
  variant=family['attempts'][0]['variant_id']
  # Flat synthetic quotes exercise the actual cost and economic gates.
  events=synthetic_events(10000)
  for event in events:
   if event['kind']=='bbo':event.update(bid='100',ask='100.1')
  outcome=evaluate(self.s,variant,'comparison',events,provenance='synthetic')
  self.assertNotEqual(outcome['status'],'passed')
  decision=poll(self.s)['decisions'][0]
  self.assertEqual(decision['state'],'rejected')
  self.assertEqual(decision['evidence']['evaluations'][0]['outcome']['failures'],outcome['failures'])
  self.assertEqual(decision['next_plan']['kind'],'next_candidate')
  self.assertFalse(decision['next_plan']['rearm_budget'])
  self.assertEqual(poll(self.s)['decisions'][0],decision)
  self.assertEqual(self.s.connection.execute('select count(*) from validation_evaluations').fetchone()[0],1)
  memory=json.loads(self.s.connection.execute('select memory_json from research_evaluation_memory where event_id=?',(decision['event_id'],)).fetchone()[0])
  self.assertEqual(memory['evidence']['evaluations'][0]['evaluation_id'],outcome['evaluation_id'])

 def test_passed_final_requires_existing_paper_gate(self):
  family=register_experiment(self.s,'request',self.plan,self.profile)
  variant=family['attempts'][0]['variant_id']
  evaluate(self.s,variant,'comparison',synthetic_events(10000),provenance='synthetic')
  select_final(self.s,family['family_id'])
  self.assertEqual(poll(self.s)['decisions'][0]['state'],'awaiting_final')
  evaluate(self.s,variant,'final',synthetic_events(20000),provenance='synthetic')
  decision=poll(self.s)['decisions'][0]
  self.assertEqual(decision['state'],'paper_gate_required')
  self.assertFalse(decision['promotion_authorized'])
  self.assertEqual(self.s.connection.execute('select count(*) from paper_sessions').fetchone()[0],0)

 def test_missing_data_not_descriptive_success(self):
  self.result['proposal']['hypothesis']['required_data']=['causal quote unavailable']
  self.s.connection.execute('update population_research_jobs set result_json=?',(json.dumps(self.result),));self.s.connection.commit()
  self.assertEqual(handoff(self.s,'request')['state'],'needs_data')

 def test_invalid_poll_budget(self):
  for value in (True,0,65):
   with self.assertRaises(ValueError):poll(self.s,limit=value)

 def test_external_allocation_freezes_future_rule_once(self):
  from pathlib import Path
  from unittest.mock import patch
  policy=json.loads((Path(__file__).resolve().parents[1]/'config/experiment-allocation-policy.json').read_text())
  self.result['proposal']['hypothesis']['experiment_profile']=self.profile
  self.s.connection.execute('update population_research_jobs set result_json=?',(json.dumps(self.result),));self.s.connection.commit()
  with patch('tamtam_again.population_plans.now_ms',return_value=100000):
   first=handoff(self.s,'request',experiment_policy=policy)
  self.assertEqual(first['state'],'awaiting_comparison')
  plan_id=first['evidence']['plan_id']
  plan=json.loads(self.s.connection.execute('select plan_json from validation_plans where plan_id=?',(plan_id,)).fetchone()[0])
  self.assertGreater(plan['comparison']['start_ms'],100000)
  self.assertEqual(first,handoff(self.s,'request',experiment_policy=policy))
  self.assertEqual(self.s.connection.execute('select count(*) from population_plan_drafts').fetchone()[0],1)
  self.assertEqual(self.s.connection.execute('select count(*) from validation_evaluations').fetchone()[0],0)

 def test_feedback_cutoff_before_payload_read(self):
  from tamtam_again.research_evaluation import memory
  self.result['proposal']['hypothesis'].pop('executable_spec')
  self.s.connection.execute('update population_research_jobs set result_json=?',(json.dumps(self.result),));self.s.connection.commit()
  event=handoff(self.s,'request')
  self.assertEqual(memory(self.s,as_of_ms=event['created_ms']-1),[])
  self.assertEqual(memory(self.s,as_of_ms=event['created_ms'])[0]['evaluation_event_id'],event['event_id'])

 def test_export_feedback_scope_cutoff_and_reserve_protection(self):
  from tamtam_again.research_evaluation import export_memory
  self.result['proposal']['hypothesis'].pop('executable_spec')
  self.s.connection.execute('update population_research_jobs set result_json=?',(json.dumps(self.result),));self.s.connection.commit()
  event=handoff(self.s,'request')
  # Existing synthetic plan protects the whole account once comparison opens.
  self.assertEqual(export_memory(self.s,'synthetic','fixture-only',event['created_ms']),[])
  self.s.connection.execute('delete from validation_plans');self.s.connection.commit()
  records=export_memory(self.s,'synthetic','fixture-only',event['created_ms'])
  self.assertEqual(records[0]['item']['state'],'descriptive')
  self.assertEqual(records[0]['periods'][0]['end_ms'],51)
  self.assertEqual(export_memory(self.s,'synthetic','other',event['created_ms']),[])
  self.assertEqual(export_memory(self.s,'synthetic','fixture-only',event['created_ms']-1),[])

 def test_pipeline_archive_failure_is_technical_feedback_not_endless_wait(self):
  from tamtam_again.validation import decision
  family=register_experiment(self.s,'request',self.plan,self.profile)
  variant=family['attempts'][0]['variant_id']
  decision(self.s,'synthetic','fixture-only','SYNTH','needs_data','Missing complete archive',
   {'archive_or_plan_correction_required':True},'inspect_validation_evidence',
   {'variant_id':variant,'stage':'comparison'})
  outcome=poll(self.s)['decisions'][0]
  self.assertEqual(outcome['state'],'technical_required')
  self.assertEqual(outcome['next_plan']['kind'],'next_candidate')
  self.assertEqual(outcome['evidence']['archive_blockers'][0]['variant_id'],variant)

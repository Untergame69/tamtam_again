import copy
import json
from pathlib import Path
from unittest.mock import patch
import unittest
from tests import test_population_experiments as fixtures
from tamtam_again.research_evaluation import handoff
from tamtam_again.continuous_plan_allocation import DAY_MS


class ContinuousPlanAllocationTests(unittest.TestCase):
 setUp=fixtures.PopulationExperimentTests.setUp
 tearDown=fixtures.PopulationExperimentTests.tearDown

 def policy(self):
  policy=json.loads((Path(__file__).resolve().parents[1]/'config/experiment-allocation-policy.json').read_text())
  policy['policy_id']='continuous-test'
  policy['plan_template']['max_plans']=1
  policy['continuous_plan_allowance']={'version':'continuous-plan-allowance-v1','period_ms':DAY_MS,
   'max_plans_per_period':1,'max_concurrent_plans':2,'justification':'Synthetic bounded test'}
  self.s.connection.execute('create table if not exists continuous_research_tasks(request_id text primary key,policy_id text,authorized_ms integer)')
  return policy

 def candidate(self,name,stamp,policy):
  result=copy.deepcopy(self.result);profile=copy.deepcopy(self.profile)
  profile['hypothesis_id']=name
  result['proposal']['hypothesis']['experiment_profile']=profile
  self.s.connection.execute('insert into population_research_jobs values(?,?,?,?,?,?,?)',
   (name,'synthetic','fixture-only','hypothesis_recorded',json.dumps(result),stamp-1,json.dumps({'available_ms':stamp-2,'evidence_refs':['request']})))
  self.s.connection.execute('insert into continuous_research_tasks values(?,?,?)',(name,'continuous-research-fixture',stamp))
  self.s.connection.commit()
  with patch('tamtam_again.population_plans.now_ms',return_value=stamp):
   return handoff(self.s,name,experiment_policy=policy)

 def test_daily_renewal_active_cap_and_fixed_replay(self):
  policy=self.policy()
  first=self.candidate('first',100000,policy)
  self.assertEqual(first['state'],'awaiting_comparison')
  denied=self.candidate('same-day',100001,policy)
  self.assertEqual(denied['state'],'technical_required')
  self.assertIn('daily',denied['diagnostic'])
  second=self.candidate('second-day',DAY_MS+100000,policy)
  self.assertEqual(second['state'],'awaiting_comparison')
  third=self.candidate('third-day',2*DAY_MS+100000,policy)
  self.assertEqual(third['state'],'technical_required')
  self.assertIn('concurrent',third['diagnostic'])
  self.assertEqual(first,handoff(self.s,'first',experiment_policy=policy))
  self.assertEqual(self.s.connection.execute('select count(*) from population_plan_drafts').fetchone()[0],2)

 def test_failed_attempt_consumes_daily_reservation(self):
  policy=self.policy();policy['plan_template']['budget']['max_duration_ms']=1
  failed=self.candidate('bad-budget',100000,policy)
  self.assertEqual(failed['state'],'technical_required')
  self.assertIn('budget',failed['diagnostic'])
  second=self.candidate('another',100001,policy)
  self.assertIn('daily',second['diagnostic'])
  self.assertEqual(self.s.connection.execute('select count(*) from continuous_plan_reservations').fetchone()[0],1)
  self.assertEqual(self.s.connection.execute('select count(*) from population_plan_drafts').fetchone()[0],0)

 def test_legacy_request_retains_lifetime_cap(self):
  policy=self.policy()
  self.candidate('continuous',100000,policy)
  self.result['proposal']['hypothesis']['experiment_profile']=self.profile
  self.s.connection.execute('update population_research_jobs set result_json=? where request_id=?',(json.dumps(self.result),'request'))
  self.s.connection.commit()
  legacy=handoff(self.s,'request',experiment_policy=policy)
  self.assertEqual(legacy['state'],'awaiting_comparison')
  another=copy.deepcopy(self.result);another['proposal']['hypothesis']['experiment_profile']['hypothesis_id']='legacy-two'
  self.s.connection.execute('insert into population_research_jobs values(?,?,?,?,?,?,?)',
   ('legacy-two','synthetic','fixture-only','hypothesis_recorded',json.dumps(another),100,json.dumps({'available_ms':50,'evidence_refs':['request']})))
  self.s.connection.commit()
  self.assertEqual(handoff(self.s,'legacy-two',experiment_policy=policy)['state'],'allocation_required')
  self.assertEqual(self.s.connection.execute('select count(*) from population_plan_drafts').fetchone()[0],2)

 def test_expired_original_task_cannot_spend_next_day(self):
  policy=self.policy()
  # Review finished the following day; its original authorization is retained.
  result=copy.deepcopy(self.result);profile=copy.deepcopy(self.profile);profile['hypothesis_id']='old-task'
  result['proposal']['hypothesis']['experiment_profile']=profile
  self.s.connection.execute('insert into population_research_jobs values(?,?,?,?,?,?,?)',
   ('old-task','synthetic','fixture-only','hypothesis_recorded',json.dumps(result),100,json.dumps({'available_ms':50,'evidence_refs':['request']})))
  self.s.connection.execute('insert into continuous_research_tasks values(?,?,?)',('old-task','fixture',100))
  self.s.connection.commit()
  with patch('tamtam_again.population_plans.now_ms',return_value=DAY_MS+1):
   outcome=handoff(self.s,'old-task',experiment_policy=policy)
  self.assertEqual(outcome['state'],'technical_required')
  self.assertIn('expired',outcome['diagnostic'])

 def test_terminal_rejection_releases_concurrency_only_not_daily_spend(self):
  from tamtam_again.recipe import synthetic_events
  from tamtam_again.validation import evaluate
  from tamtam_again.experiments import select_final
  policy=self.policy()
  first=self.candidate('first',100000,policy)
  self.candidate('second',DAY_MS+100000,policy)
  plan=json.loads(self.s.connection.execute('select plan_json from validation_plans where plan_id=?',(first['evidence']['plan_id'],)).fetchone()[0])
  variant=first['evidence']['attempts'][0]['variant_id']
  evaluate(self.s,variant,'comparison',synthetic_events(plan['comparison']['start_ms']),provenance='synthetic')
  selected=select_final(self.s,first['evidence']['family_id'])
  self.assertEqual(selected['status'],'no_candidate')
  third=self.candidate('third',2*DAY_MS+100000,policy)
  self.assertEqual(third['state'],'awaiting_comparison')
  self.assertEqual(self.s.connection.execute('select count(*) from continuous_plan_reservations').fetchone()[0],3)

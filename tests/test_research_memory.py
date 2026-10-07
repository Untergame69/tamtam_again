import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tamtam_again.storage import Store
from tamtam_again.recipe import synthetic_plan,synthetic_spec
from tamtam_again.validation import create_plan,register_variant
from tamtam_again.research_memory import save_knowledge,export_knowledge,release_period,migrate

def item(stage='comparison'):
 window=synthetic_plan()[stage]
 return {'schema_version':1,'mechanism':'fixture hypothesis','origin_accounts':['fixture-only'],
  'origin_markets':['SYNTH'],'periods':[{'network':'synthetic','address':'fixture-only','market':'SYNTH',**window}],
  'evidence_refs':[{'kind':'evaluation','id':'evaluation'}],'experiments':['fixture'],
  'success_conditions':[],'failure_conditions':['fixture failure'],'execution_limits':['synthetic only'],
  'open_questions':['unknown edge'],'related_hypotheses':[],'status':'hypothesis'}

class ResearchMemoryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
  self.plan=create_plan(self.s,synthetic_plan())['plan_id'];migrate(self.s)
  self.variant=register_variant(self.s,self.plan,synthetic_spec())['variant_id']
  self.clock=patch('tamtam_again.research_memory.clock',return_value=100000);self.clock.start()
 def tearDown(self):self.clock.stop();self.s.close();self.tmp.cleanup()
 def evaluation(self,stage='comparison',status='failed'):
  self.s.connection.execute('insert into validation_evaluations values (?,?,?,?,?,?,?,?)',('evaluation',self.variant,self.plan,stage,status,'fixture',json.dumps({'status':status}),'fixture'));self.s.connection.commit()
 def release(self):return release_period(self.s,'evaluation',{'version':'fixture-v1','justification':'explicit reuse in later development','grace_ms':0})
 def test_unreleased_period_cannot_be_saved(self):
  self.evaluation()
  with self.assertRaises(ValueError):save_knowledge(self.s,item())
 def test_terminal_release_then_export_and_original_failure_retained(self):
  self.evaluation();release=self.release();saved=save_knowledge(self.s,item())
  out=export_knowledge(self.s,as_of_ms=100000,network='synthetic',address='fixture-only',market='SYNTH')
  self.assertEqual(out[0]['knowledge_id'],saved['knowledge_id'])
  self.assertEqual(self.s.connection.execute('select status from validation_evaluations').fetchone()[0],'failed')
  self.assertEqual(self.release(),release)
 def test_running_evaluation_not_releasable(self):
  self.evaluation(status='running')
  with self.assertRaises(ValueError):self.release()
 def test_future_grace_not_releasable(self):
  self.evaluation()
  with self.assertRaises(ValueError):release_period(self.s,'evaluation',{'version':'v','justification':'wait','grace_ms':100000})
 def test_final_requires_and_preserves_burn(self):
  self.evaluation(stage='final')
  with self.assertRaises(ValueError):self.release()
  self.s.connection.execute('insert into consumed_holdouts values (?,?,?,?,?,?,?)',('evaluation','synthetic','fixture-only','SYNTH',20000,26000,'fixture'));self.s.connection.commit()
  self.release();save_knowledge(self.s,item('final'))
  self.assertEqual(self.s.connection.execute('select count(*) from consumed_holdouts').fetchone()[0],1)
 def test_future_created_knowledge_not_exported_to_old_packet(self):
  self.evaluation();self.release();save_knowledge(self.s,item())
  self.assertEqual(export_knowledge(self.s,as_of_ms=99999,network='synthetic',address='fixture-only',market='SYNTH'),[])
 def test_idempotent_and_bounded_export(self):
  self.evaluation();self.release();a=save_knowledge(self.s,item());b=save_knowledge(self.s,item())
  self.assertEqual(a,b)
  self.assertEqual(export_knowledge(self.s,as_of_ms=100000,network='synthetic',address='fixture-only',market='SYNTH',max_chars=1),[])
 def test_arbitrary_path_not_access_grant(self):
  self.evaluation();self.release();i=item();i['evidence_refs']=[{'kind':'file','id':'/forbidden'}]
  with self.assertRaises(ValueError):save_knowledge(self.s,i)
 def test_account_wide_raw_evidence_cannot_hide_reserved_market(self):
  i=item();i['periods'][0]['market']='*';i['origin_markets']=['*']
  i['evidence_refs']=[{'kind':'raw_observation','id':0}]
  with self.assertRaisesRegex(ValueError,'unreleased reserved'):save_knowledge(self.s,i)

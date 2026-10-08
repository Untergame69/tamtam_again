import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tamtam_again.storage import Store
from tamtam_again.population import enroll,claim
from tamtam_again.validation import initialize,create_plan
from tamtam_again.recipe import synthetic_plan
from tamtam_again.research_needs import register
from tamtam_again.research_need_collection import tick_for_job

class NeedCollectionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db');initialize(self.s)
  self.address='0x'+'1'*40;self.s.add_candidate('synthetic',self.address,'fixture')
  p=json.loads((Path(__file__).resolve().parents[1]/'config/population-policy.json').read_text());p.pop('allocation')
  enroll(self.s,'synthetic',p,now_ms=1000);self.job=claim(self.s,'synthetic',now_ms=1000)
  self.policy={'version':'research-need-collection-v1','policy_id':'fixture','justification':'fixture only','max_needs_per_job':1,'max_pages_per_need':1,'max_attempts_per_need':3}
  from tamtam_again.population_research import initialize as initialize_research
  initialize_research(self.s)
  self.clock=patch('tamtam_again.research_need_collection.now_ms',return_value=30000);self.clock.start()
 def tearDown(self):self.clock.stop();self.s.close();self.tmp.cleanup()
 def plan(self,endpoints=('userFunding',),start=1000,end=2000):
  requests=[{'required_data_index':i,'source':'public_rest_history','endpoint':e,'start_ms':start,'end_ms':end,'proof':'pagination_coverage','decision_use':'inspect archived endpoint interval'} for i,e in enumerate(endpoints)]
  h={'required_data':['archive '+e for e in endpoints],'observation_requests':requests}
  result={'proposal':{'hypothesis':h},'critique':{'decision':'consistent'},'promotion_authorized':False,'profitability_proven':False}
  self.s.connection.execute('insert into population_research_jobs(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,updated_ms,result_json) values(?,?,?,?,?,?,?,?,?,?)',('hypothesis','synthetic',self.address,'original-fixture','{}','{}',100,'hypothesis_recorded',100,json.dumps(result)));self.s.connection.commit()
  register(self.s,'hypothesis',clock_ms=30000)
 def client(self,responses):
  class Client:
   calls=[]
   def post_info(this,q):
    this.calls.append(q)
    r=responses.pop(0)
    if isinstance(r,Exception):raise r
    return r
  return Client()
 def test_all_contracts_before_one_wake_and_no_repeated_calls(self):
  self.plan(('userFunding','userNonFundingLedgerUpdates'));c=self.client([[],[]])
  with patch('tamtam_again.storage.utc_now',return_value='1970-01-01T00:00:20.000+00:00'),patch('tamtam_again.population_history.utc_now',return_value='1970-01-01T00:00:19.000+00:00'):
   first=tick_for_job(self.s,c,self.job,self.policy,clock_ms=30000)
   self.assertEqual(first['wakes'],[])
   second=tick_for_job(self.s,c,self.job,self.policy,clock_ms=30000)
   self.assertEqual(second['wakes'],['hypothesis'])
   self.assertEqual(tick_for_job(self.s,c,self.job,self.policy,clock_ms=30000)['wakes'],[])
  self.assertEqual(len(c.calls),2)
  proof=json.loads(self.s.connection.execute('select evidence_json from research_observation_wakes').fetchone()[0])
  self.assertFalse(proof['economic_completeness_proven']);self.assertFalse(proof['promotion_authorized'])
 def test_scoped_cursor_resumes_inclusively_without_touching_regular_cursor(self):
  from tamtam_again.population_history import SCHEMA
  self.plan();self.s.connection.executescript(SCHEMA)
  self.s.connection.execute('insert into population_history_cursors values(?,?,?,?,?,?,?,?)',('synthetic',self.address,'userFunding',9999,None,'pagination_exhausted','fixture','{}'));self.s.connection.commit()
  c=self.client([[{'time':1000+i} for i in range(500)],[{'time':1499},{'time':1800}]])
  with patch('tamtam_again.storage.utc_now',return_value='1970-01-01T00:00:20.000+00:00'),patch('tamtam_again.population_history.utc_now',return_value='1970-01-01T00:00:19.000+00:00'):
   self.assertEqual(tick_for_job(self.s,c,self.job,self.policy,clock_ms=30000)['processed'][0]['state'],'needs_more_pages')
   self.assertEqual(tick_for_job(self.s,c,self.job,self.policy,clock_ms=30000)['wakes'],['hypothesis'])
  self.assertEqual(c.calls[1]['startTime'],1499)
  self.assertEqual(self.s.connection.execute("select cursor_ms from population_history_cursors where endpoint='userFunding'").fetchone()[0],9999)
 def test_failed_attempt_consumes_budget_and_retries_are_bounded(self):
  self.plan();c=self.client([OSError('private transport text')]);p={**self.policy,'max_attempts_per_need':1}
  r=tick_for_job(self.s,c,self.job,p,clock_ms=30000)
  self.assertEqual(r['processed'][0]['state'],'collection_failed')
  self.assertEqual(tick_for_job(self.s,c,self.job,p,clock_ms=30000)['processed'],[])
  self.assertEqual(len(c.calls),1)
  self.assertNotIn('private transport',self.s.connection.execute('select evidence_json from research_need_collection_states').fetchone()[0])
 def test_reserved_request_never_calls_or_reads_archived_payload(self):
  p=synthetic_plan();p['address']=self.address;create_plan(self.s,p)
  self.plan(start=10000,end=12000);c=self.client([]);queries=[];self.s.connection.set_trace_callback(queries.append)
  self.assertEqual(tick_for_job(self.s,c,self.job,self.policy,clock_ms=30000)['processed'],[])
  self.assertEqual(c.calls,[]);self.assertFalse(any('raw_observations' in q for q in queries))

 def test_stale_worker_cannot_publish_wake_after_lease_takeover(self):
  self.plan()
  outer=self
  class Client:
   calls=0
   def post_info(this,q):
    this.calls+=1
    outer.s.connection.execute('update population_accounts set lease_token=? where network=? and address=?',('new-lease','synthetic',outer.address));outer.s.connection.commit()
    return []
  c=Client()
  with patch('tamtam_again.storage.utc_now',return_value='1970-01-01T00:00:20.000+00:00'),patch('tamtam_again.population_history.utc_now',return_value='1970-01-01T00:00:19.000+00:00'):
   self.assertEqual(tick_for_job(self.s,c,self.job,self.policy,clock_ms=30000)['wakes'],[])
   self.assertEqual(self.s.connection.execute('select count(*) from research_observation_wakes').fetchone()[0],0)
   self.assertEqual(self.s.connection.execute('select count(*) from raw_observations').fetchone()[0],1)
   fresh={**self.job,'lease_token':'new-lease'}
   self.assertEqual(tick_for_job(self.s,self.client([[]]),fresh,self.policy,clock_ms=30000)['wakes'],['hypothesis'])
  self.assertEqual(self.s.connection.execute('select attempts from research_need_collection_states').fetchone()[0],2)
  statuses=[r[0] for r in self.s.connection.execute('select status from research_need_collection_attempts order by attempt_number')]
  self.assertEqual(statuses,['lease_revoked','proof_observed'])

 def test_verified_wake_changes_packet_and_seals_only_once_under_existing_budget(self):
  from tamtam_again.population_research import seal
  from tamtam_again.population_packet import packet_for_account
  self.plan()
  self.s.connection.execute('create table if not exists account_scope_reports(report_id text,network text,address text,available_ms integer,payload_json text)')
  report={'address':self.address,'markets':['SYNTH'],'activity':{'observed_unique_fills':1,'observed_fill_content_fingerprint':'same-fills'}}
  self.s.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',('fixture','synthetic',self.address,100,json.dumps(report)));self.s.connection.commit()
  before=packet_for_account(self.s,'synthetic',self.address,as_of_ms=30000,max_chars=30000)['packet']
  with patch('tamtam_again.storage.utc_now',return_value='1970-01-01T00:00:20.000+00:00'),patch('tamtam_again.population_history.utc_now',return_value='1970-01-01T00:00:19.000+00:00'):
   tick_for_job(self.s,self.client([[]]),self.job,self.policy,clock_ms=30000)
  after=packet_for_account(self.s,'synthetic',self.address,as_of_ms=30000,max_chars=30000)['packet']
  self.assertNotEqual(after['research_input_fingerprint'],before['research_input_fingerprint'])
  self.assertEqual(after['observations']['completed_observation_requests'][0]['pages'][0]['values'],[])
  root={'version':'population-research-v1','max_requests':2,'max_packet_chars':30000,'minimum_interval_ms':1,'timeout_seconds':1,'max_output_tokens':1000,'max_request_age_ms':3600000,'model':'fixture','call_reservation_usd':'1'}
  self.assertEqual(seal(self.s,'synthetic',self.address,root,clock_ms=30000)['status'],'sealed')
  self.assertEqual(seal(self.s,'synthetic',self.address,root,clock_ms=30000)['status'],'unchanged_no_inference')
  self.assertEqual(self.s.connection.execute('select count(*) from population_research_jobs').fetchone()[0],2)

 def test_wake_export_is_causal_and_new_reserve_blocks_before_payload_read(self):
  from tamtam_again.research_need_collection import export_wakes
  self.plan()
  with patch('tamtam_again.storage.utc_now',return_value='1970-01-01T00:00:20.000+00:00'),patch('tamtam_again.population_history.utc_now',return_value='1970-01-01T00:00:19.000+00:00'):
   tick_for_job(self.s,self.client([[]]),self.job,self.policy,clock_ms=30000)
  self.assertEqual(export_wakes(self.s,'synthetic',self.address,as_of_ms=29999),[])
  p=synthetic_plan();p['address']=self.address;p['exploration']={'start_ms':0,'end_ms':500};p['comparison']={'start_ms':1000,'end_ms':7000};p['final']={'start_ms':10000,'end_ms':16000};p['embargo_ms']=100
  create_plan(self.s,p)
  queries=[];self.s.connection.set_trace_callback(queries.append)
  with self.assertRaises(ValueError):export_wakes(self.s,'synthetic',self.address,as_of_ms=30000)
  self.assertFalse(any('response_json' in q for q in queries))

 def test_partial_or_duplicate_wake_rejected_even_with_recomputed_identity(self):
  from tamtam_again.research_need_collection import export_wakes
  from tamtam_again.engine import canonical,fingerprint
  self.plan(('userFunding','userNonFundingLedgerUpdates'))
  with patch('tamtam_again.storage.utc_now',return_value='1970-01-01T00:00:20.000+00:00'),patch('tamtam_again.population_history.utc_now',return_value='1970-01-01T00:00:19.000+00:00'):
   c=self.client([[],[]])
   tick_for_job(self.s,c,self.job,self.policy,clock_ms=30000)
   tick_for_job(self.s,c,self.job,self.policy,clock_ms=30000)
  original=json.loads(self.s.connection.execute('select evidence_json from research_observation_wakes').fetchone()[0])
  for proofs in ([],original['proofs'][:1],[original['proofs'][0]]*2):
   with self.subTest(proofs=len(proofs)):
    evidence={**original,'proofs':proofs}
    self.s.connection.execute('update research_observation_wakes set evidence_json=?,evidence_fingerprint=?',(canonical(evidence),fingerprint(evidence)));self.s.connection.commit()
    queries=[];self.s.connection.set_trace_callback(queries.append)
    with self.assertRaisesRegex(ValueError,'Complete non-promotional'):
     export_wakes(self.s,'synthetic',self.address,as_of_ms=30000)
    self.s.connection.set_trace_callback(None)
    self.assertFalse(any('select response_json' in q for q in queries))

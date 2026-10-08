import json
import tempfile
import unittest
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.account_coverage import pagination_coverage
from tamtam_again.account_adapter import millis
from tamtam_again.population import enroll, claim
from tamtam_again.population_history import collect_history

POLICY = {'version':'test','max_rest_accounts':1,'max_jobs_per_tick':1,
 'default_poll_seconds':3600,'min_poll_seconds':300,'max_poll_seconds':21600,
 'retention_fraction':.5,'retention_fills':10000,'lease_seconds':600,
 'retry_seconds':300,'initial_lookback_seconds':1,'sampling_seed':'test',
 'history_max_pages_per_endpoint':2}

class Client:
 def __init__(self, pages): self.pages=iter(pages);self.queries=[]
 def post_info(self,q):
  self.queries.append(q)
  value=next(self.pages)
  if isinstance(value,Exception):raise value
  return value

class PopulationHistoryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'test.sqlite3')
  self.s.add_candidate('test','0x'+'1'*40,'fixture')
  enroll(self.s,'test',POLICY,now_ms=1000);self.job=claim(self.s,'test',now_ms=1000)
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def cursor(self,endpoint):
  return self.s.connection.execute('select * from population_history_cursors where endpoint=?',(endpoint,)).fetchone()
 def test_inclusive_boundary_dedup_and_retention_remains_unknown(self):
  first=[{'time':1200+i,'tid':i} for i in range(500)]
  client=Client([first,[first[-1],{'time':1900,'tid':999}]])
  rows,report=collect_history(self.s,client,self.job,'userFillsByTime',2000)
  self.assertEqual(len(rows),501);self.assertEqual(client.queries[1]['startTime'],1699)
  self.assertEqual(report['pagination_status'],'pagination_exhausted')
  self.assertFalse(report['retention_proven']);self.assertEqual(report['coverage_status'],'unknown')
  self.assertEqual(self.cursor('userFillsByTime')['cursor_ms'],2000)
  self.assertTrue(all(not r[0] for r in self.s.connection.execute('select complete from raw_observations')))
 def test_saturated_same_timestamp_never_skipped(self):
  client=Client([[{'time':1000,'tid':i} for i in range(2000)]])
  _,report=collect_history(self.s,client,self.job,'userFillsByTime',2000)
  self.assertEqual(report['pagination_status'],'saturated_timestamp_unresolvable')
  self.assertEqual(self.cursor('userFillsByTime')['cursor_ms'],1000)
 def test_page_budget_backlog_target_preserved(self):
  self.job['policy']={**POLICY,'history_max_pages_per_endpoint':1}
  collect_history(self.s,Client([[{'time':1200+i,'tid':i} for i in range(500)]]),self.job,'userFunding',2000)
  client=Client([[]]);_,report=collect_history(self.s,client,self.job,'userFunding',3000)
  self.assertEqual(client.queries[0]['startTime'],1699)
  self.assertEqual(client.queries[0]['endTime'],2000)
  self.assertEqual(report['pagination_status'],'pagination_exhausted')
  self.assertIsNone(self.cursor('userFunding')['target_end_ms'])
 def test_endpoint_cursor_not_inherited_from_fills_or_job(self):
  self.job['last_success_ms']=1999
  collect_history(self.s,Client([[]]),self.job,'userFillsByTime',2000)
  client=Client([[]]);collect_history(self.s,client,self.job,'userFunding',3000)
  self.assertEqual(client.queries[0]['startTime'],2000)
  self.assertEqual(self.cursor('userFillsByTime')['cursor_ms'],2000)
 def test_failure_preserves_archived_progress(self):
  client=Client([[{'time':1200+i,'tid':i} for i in range(500)],RuntimeError('fixture')])
  with self.assertRaises(RuntimeError):collect_history(self.s,client,self.job,'userFunding',2000)
  self.assertEqual(self.cursor('userFunding')['cursor_ms'],1699)
  self.assertEqual(self.s.connection.execute('select count(*) from raw_observations').fetchone()[0],1)
 def test_out_of_window_response_archived_without_advancing(self):
  _,report=collect_history(self.s,Client([[{'time':2001}]]),self.job,'userFunding',2000)
  self.assertEqual(report['pagination_status'],'invalid_response_window')
  self.assertEqual(self.cursor('userFunding')['cursor_ms'],1000)
 def test_stale_lease_refused_before_network(self):
  self.job['lease_token']='stale';client=Client([[]])
  with self.assertRaises(ValueError):collect_history(self.s,client,self.job,'userFunding',2000)
  self.assertEqual(client.queries,[])
 def test_new_incremental_window_keeps_previous_end_inclusive(self):
  collect_history(self.s,Client([[]]),self.job,'userNonFundingLedgerUpdates',2000)
  client=Client([[]]);_,report=collect_history(self.s,client,self.job,'userNonFundingLedgerUpdates',4000)
  self.assertEqual(client.queries[0]['startTime'],2000)
  self.assertEqual(report['phase'],'incremental')
 def test_telemetry_phase_restored_after_network_failure(self):
  class MeasuredClient:
   task='population-rest-overview'
   def post_info(inner,q):
    self.assertEqual(inner.task,'population-rest-history_backfill')
    raise RuntimeError('fixture')
  client=MeasuredClient()
  with self.assertRaises(RuntimeError):collect_history(self.s,client,self.job,'userFunding',2000)
  self.assertEqual(client.task,'population-rest-overview')

 def coverage(self):
  pages=[]
  for r in self.s.connection.execute('select * from raw_observations'):
   q=json.loads(r['request_json'])
   pages.append({'start_ms':r['window_start_ms'],'end_ms':r['window_end_ms'],
    'available_ms':millis(r['observed_at']),'pagination_status':q['pagination_status'],
    'covered_until_ms':q.get('covered_until_ms'),'evidence_ref':str(r['observation_id'])})
  return pagination_coverage(pages,start_ms=1000,end_ms=2000,as_of_ms=9999999999999)
 def test_multi_page_coverage_and_missing_prefix(self):
  first=[{'time':1200+i,'tid':i} for i in range(500)]
  collect_history(self.s,Client([first,[first[-1],{'time':1900}]]),self.job,'userFunding',2000)
  self.assertEqual(self.coverage()['pagination_status'],'covered')
  self.assertFalse(self.coverage()['retention_proven'])
  self.s.connection.execute('delete from raw_observations where observation_id=1')
  self.assertEqual(self.coverage()['pagination_gaps_ms'],[[1000,1699]])
 def test_recovery_after_interruption_closes_prefix(self):
  first=[{'time':1200+i,'tid':i} for i in range(500)]
  with self.assertRaises(RuntimeError):
   collect_history(self.s,Client([first,RuntimeError('crash')]),self.job,'userFunding',2000)
  self.assertEqual(self.coverage()['pagination_gaps_ms'],[[1699,2000]])
  collect_history(self.s,Client([[first[-1]]]),self.job,'userFunding',2000)
  self.assertEqual(self.coverage()['pagination_status'],'covered')
 def test_split_jobs_and_saturated_endpoint_boundary(self):
  self.job['policy']={**POLICY,'history_max_pages_per_endpoint':1}
  collect_history(self.s,Client([[{'time':2000,'tid':i} for i in range(500)]]),self.job,'userFunding',2000)
  self.assertEqual(self.coverage()['pagination_gaps_ms'],[[2000,2000]])
  collect_history(self.s,Client([[{'time':2000,'tid':i} for i in range(500)]]),self.job,'userFunding',2000)
  self.assertEqual(self.coverage()['pagination_gaps_ms'],[[2000,2000]])
  collect_history(self.s,Client([[]]),self.job,'userFunding',2000)
  self.assertEqual(self.coverage()['pagination_status'],'covered')

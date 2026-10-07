import tempfile,unittest
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.procedure_costs import provider_cost_ledger

class CostTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
  self.s.connection.execute('create table population_research_jobs(request_id text,network text,address text,created_ms integer,updated_ms integer,status text,actual_cost_usd text,reserved_cost_usd text)')
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def add(self,i,created,updated,status,cost,address='account'):
  self.s.connection.execute('insert into population_research_jobs values(?,?,?,?,?,?,?,?)',(i,'test',address,created,updated,status,cost,'2'));self.s.connection.commit()
 def ledger(self,cutoff=100,address=None):return provider_cost_ledger(self.s,network='test',start_ms=0,end_ms=50,as_of_ms=cutoff,address=address)
 def test_failed_and_unknown_trials_preserved_reservation_not_cost(self):
  self.add('failed',1,10,'suspended','0.5');self.add('interrupted',2,20,'interrupted',None)
  r=self.ledger();self.assertEqual(r['known_provider_cost_usd'],'0.5')
  self.assertIsNone(r['total_provider_cost_usd']);self.assertEqual(len(r['attempts']),2)
  self.assertEqual(r['observed_reservations_usd'],'4')
 def test_future_cost_not_leaked_and_running_cost_not_complete(self):
  self.add('future',1,101,'hypothesis_recorded','99');self.add('running',2,20,'running','2')
  r=self.ledger();self.assertEqual(r['known_provider_cost_usd'],'0')
  self.assertEqual(r['attempts'][0]['status'],'state_not_available_at_cutoff')
  self.assertIsNone(r['attempts'][0]['cost_available_ms']);self.assertNotIn('99',str(r))
 def test_scope_and_half_open_window(self):
  self.add('first',1,10,'reject','0',address='first');self.add('end',50,60,'reject','1')
  r=self.ledger(address='first');self.assertEqual(len(r['attempts']),1)
  self.assertEqual(r['total_provider_cost_usd'],'0')
 def test_negative_expense_rejected(self):
  self.add('bad',1,10,'reject','-1')
  with self.assertRaises(ValueError):self.ledger()

 def test_isolated_scope_and_incomplete_legacy_failure(self):
  self.s.connection.execute('create table validation_plans(plan_id text,network text,address text)')
  self.s.connection.execute('create table isolated_research_jobs(run_id text,plan_id text,created_at text,updated_at text,status text,actual_cost_usd text,reserved_cost_usd text)')
  self.s.connection.execute("insert into validation_plans values('p','test','account')")
  for identity,state,cost in [('ok','ready_to_test','0.25'),('partial','suspended','0.25')]:
   self.s.connection.execute("insert into isolated_research_jobs values(?,?,?,?,?,?,?)",(identity,'p','1970-01-01T00:00:00.001+00:00','1970-01-01T00:00:00.010+00:00',state,cost,'2'))
  r=self.ledger(address='account');self.assertEqual(r['known_provider_cost_usd'],'0.25')
  self.assertEqual(r['unknown_cost_attempts'],['isolated_research:partial'])
 def test_unrecognized_state_is_not_assumed_terminal(self):
  self.add('new',1,10,'dispatching','1')
  self.assertIsNone(self.ledger()['total_provider_cost_usd'])

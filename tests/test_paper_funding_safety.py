"""Paper funding unknowns retain inventory and bounded archive cursor integrity."""
import json
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from tests import test_funding_witnesses as witness_fixtures
from tamtam_again.engine import initial_state, _fill, _order, reduce_event
from tamtam_again.paper import archive_events, _persist_monitored_tick
from tamtam_again.recipe import synthetic_spec, synthetic_plan
from tamtam_again.storage import Store
from tamtam_again.validation import create_plan, register_variant
from tamtam_again import paper_evidence


class FundingArchiveSafetyTests(unittest.TestCase):
    def setUp(self):self.fixture=witness_fixtures.FundingWitnessTests();self.fixture.setUp()
    def tearDown(self):self.fixture.tearDown()

    def primary(self,payload=None):
        f=self.fixture
        return f.save('userFundings',payload or f.funding(address=f.source),entity=f.source)

    def test_primary_funding_hash_and_sender_are_verified(self):
        f=self.fixture;oid=self.primary()
        f.store.connection.execute("update raw_observations set response_sha256='corrupt' where observation_id=?",(oid,));f.store.connection.commit()
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            archive_events(f.store,f.network,f.source,'BTC',1000,5000)
        f.store.connection.execute('delete from raw_observations where observation_id=?',(oid,));f.store.connection.commit()
        self.primary(f.funding(address=f.other))
        with self.assertRaisesRegex(ValueError,'sender/channel'):
            archive_events(f.store,f.network,f.source,'BTC',1000,5000)

    def race(self,*,witness):
        f=self.fixture;original=f.store.connection
        class BetweenSourceQueries:
            inserted=False
            def execute(proxy,sql,params=()):
                result=original.execute(sql,params)
                if not proxy.inserted and "endpoint='bbo'" in sql:
                    proxy.inserted=True
                    address=f.witness if witness else f.source
                    f.save('userFundings',f.funding(address=address),entity=address)
                    f.save('streamHealth',{'kind':'heartbeat','session':'s'},entity='s',entity_type='stream',stamp=2300)
                return result
            def __getattr__(proxy,name):return getattr(original,name)
        f.store.connection=BetweenSourceQueries()
        try:
            kwargs={'funding_witnesses':f.contract} if witness else {}
            first,cursor=archive_events(f.store,f.network,f.source,'BTC',1000,5000,**kwargs)
            self.assertEqual(first,[])
            second,_=archive_events(f.store,f.network,f.source,'BTC',1000,5000,after_observation_id=cursor,**kwargs)
            self.assertEqual(sum(e['kind']=='funding' for e in second),1)
        finally:f.store.connection=original

    def test_primary_insert_between_queries_cannot_be_skipped(self):self.race(witness=False)
    def test_witness_insert_between_queries_cannot_be_skipped(self):self.race(witness=True)


class PaperFundingPendingTests(unittest.TestCase):
    def test_pending_cost_keeps_position_waits_and_allows_only_fresh_reductions(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'fixture.db');plan=synthetic_plan()
            plan['paper_monitoring']={'version':'paper-loss-budget-v1','justification':'fixture','max_net_loss_usdc':'1'}
            planid=create_plan(store,plan)['plan_id'];spec=synthetic_spec()
            spec['execution']['funding_observation_interval_ms']=1000;spec['horizon_ms']=500
            variant=register_variant(store,planid,spec)['variant_id']
            state=initial_state(spec);_fill(state,Decimal(1),Decimal(100),Decimal(0),100)
            state.update(healthy_at_ms=1100,connected=True,session='s',last_ms=100,paper_funding_started_ms=0)
            store.connection.execute('insert into paper_sessions values(?,?,?,?,?,?,?,?,?,?)',
                ('session',variant,'synthetic','fixture-only','SYNTH',json.dumps(state),'active',0,0,'fixture'))
            store.connection.execute('create table paper_suspensions(session_id text primary key,suspended_ms integer,diagnostics_json text)')
            paper_evidence.initialize(store);store.connection.commit()
            session=store.connection.execute('select * from paper_sessions').fetchone()
            status,metric=_persist_monitored_tick(store,session,state,spec,plan,0,1100)
            self.assertEqual(status,'active');self.assertEqual(state['position'],'1')
            self.assertIsNone(metric['net_pnl']);self.assertIn('net_pnl_observed_components',metric)
            self.assertFalse(metric['economic_result_complete'])
            self.assertIn('awaiting_observed_funding_settlements',state['wait_conditions'])
            self.assertNotIn('paper_net_loss_budget_exhausted',state['diagnostics'])
            _order(state,spec,Decimal(2),1110);self.assertEqual(state['pending'],[])
            reduce_event(state,spec,{'id':'q','kind':'bbo','event_ms':1110,'received_ms':1110,
                'session':'s','bid':'100','ask':'100.1','bid_size':'100','ask_size':'100'})
            _order(state,spec,Decimal(0),1120)
            reduce_event(state,spec,{'id':'close','kind':'timer','event_ms':1130,'received_ms':1130})
            self.assertEqual(state['position'],'0')
            reduce_event(state,spec,{'id':'delayed-funding','kind':'funding','event_ms':1000,'received_ms':1400,
                'unit_funding_usdc':'-0.1'})
            self.assertEqual(Decimal(state['funding']),Decimal('-0.1'))
            status,complete=_persist_monitored_tick(store,session,state,spec,plan,0,1500)
            self.assertTrue(complete['economic_result_complete']);self.assertIsNotNone(complete['net_pnl'])
            from tamtam_again.paper_outcome import period_outcome
            outcome=period_outcome(store,'session',start_ms=1100,end_ms=1500,as_of_ms=1500)
            self.assertEqual(outcome['status'],'unknown')
            self.assertIn('funding costs incomplete at period boundary',outcome['unknown_reasons'])
            store.close()

    def test_pending_entry_ttl_is_not_rearmed_when_cost_arrives(self):
        spec=synthetic_spec();spec['execution']['funding_observation_interval_ms']=1000
        state=initial_state(spec);state['paper_funding_started_ms']=0
        _fill(state,Decimal(1),Decimal(100),Decimal(0),100)
        state['pending']=[{'target':'2','due_ms':1000,'expires_ms':1200}]
        reduce_event(state,spec,{'id':'pending','kind':'timer','event_ms':1100,'received_ms':1100})
        self.assertEqual(state['pending'][0]['expires_ms'],1200)
        reduce_event(state,spec,{'id':'settled','kind':'funding','event_ms':1000,'received_ms':1400,
            'unit_funding_usdc':'-0.1'})
        self.assertFalse(any(order['target']=='2' for order in state['pending']))
        self.assertIn('order_ttl_expired',state['nonexecution_reasons'])
        self.assertEqual(state['position'],'1')


if __name__=='__main__':unittest.main()

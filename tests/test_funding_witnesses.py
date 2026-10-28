"""Cost-only public witness fixtures; no live payloads or provider access."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tamtam_again.storage import Store
from tamtam_again.funding_witnesses import archive_funding_events
from tamtam_again.paper import archive_events
from tamtam_again.engine import initial_state, reduce_event, funding_coverage, _fill
from tamtam_again.recipe import synthetic_spec


def iso(stamp):
    return datetime.fromtimestamp(stamp/1000,timezone.utc).isoformat(timespec='milliseconds')


class FundingWitnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'fixture.db')
        self.network='hyperliquid-mainnet';self.source='0x'+'1'*40
        self.witness='0x'+'2'*40;self.other='0x'+'3'*40;self.reserved='0x'+'a'*40
        for address in (self.witness,self.other,self.reserved):
            self.store.connection.execute('insert into candidates values(?,?,?,?,?,?)',
                (self.network,address,'fixture','',iso(0),'tracked'))
        self.store.connection.commit()
        refs=[]
        for endpoint,payload in [('allPerpMetas',[{'collateralToken':0,'universe':[
                {'name':'BTC','szDecimals':4,'maxLeverage':40}]}]),
                ('spotMetaAndAssetCtxs',[{'tokens':[{'index':0,'name':'USDC','tokenId':'fixture-usdc'}]},[]])]:
            self.save(endpoint,payload,stamp=50,entity='collateral:all',source='hyperliquid-population-rest-v1',entity_type='market')
            refs.append('raw_observations:'+str(self.last_id()))
        self.contract={'version':'settled-funding-witnesses-v1','network':self.network,'market':'BTC',
            'currency':'USDC','available_ms':100,'addresses':[self.witness], 'evidence_refs':refs}

    def tearDown(self):self.store.close();self.tmp.cleanup()

    def last_id(self):return self.store.connection.execute('select max(observation_id) from raw_observations').fetchone()[0]

    def save(self,endpoint,payload,*,stamp=2100,entity=None,source='hyperliquid-websocket-v1',entity_type='account'):
        with patch('tamtam_again.storage.utc_now',return_value=iso(stamp)):
            self.store.save_observation(network=self.network,source=source,entity_type=entity_type,
                entity_id=entity or self.witness,endpoint=endpoint,payload=payload,
                request_payload={'type':endpoint},requested_at=iso(stamp-10))
        return self.last_id()

    def funding(self,*,address=None,coin='BTC',snapshot=False,stamp=2000,usdc='-0.2',szi='2'):
        return {'channel':'userFundings','data':{'user':address or self.witness,'isSnapshot':snapshot,
            'fundings':[{'coin':coin,'time':stamp,'usdc':usdc,'szi':szi}]}}

    def read(self,contract=None,after=0):
        return archive_funding_events(self.store,contract or self.contract,network=self.network,
            address=self.source,market='BTC',start_ms=1000,end_ms=5000,after_observation_id=after)

    def test_exact_coin_public_settlement_retains_hash_availability_and_cost_only_scope(self):
        oid=self.save('userFundings',self.funding())
        self.save('userFills',{'channel':'userFills','data':{'fills':[{'private':'unused'}]}})
        self.save('userFundings',self.funding(coin='ETH'),stamp=2200)
        self.store.connection.execute('pragma query_only=on')
        events,cursor=self.read()
        self.assertEqual(len(events),1);event=events[0]
        self.assertEqual(event['kind'],'funding');self.assertTrue(event['cost_only'])
        self.assertEqual(event['unit_funding_usdc'],'-0.1')
        self.assertEqual(event['event_ms'],2000);self.assertEqual(event['available_ms'],2100)
        self.assertEqual(event['evidence_ref'],'raw_observations:'+str(oid))
        self.assertEqual(event['archive_response_sha256'],self.store.connection.execute(
            'select response_sha256 from raw_observations where observation_id=?',(oid,)).fetchone()[0])
        self.assertEqual(event['source_period'],{'network':self.network,'address':self.witness,
            'market':'*','start_ms':0,'end_ms':2101})
        self.assertEqual(self.read(after=cursor)[0],[])

    def test_settled_snapshot_is_cost_history_never_a_leader_signal(self):
        self.save('userFundings',self.funding(snapshot=True))
        events,_=archive_events(self.store,self.network,self.source,'BTC',1000,5000,
            funding_witnesses=self.contract)
        self.assertEqual([e['kind'] for e in events],['funding'])
        self.assertTrue(events[0]['is_snapshot'])
        spec=synthetic_spec();spec['market']='BTC';spec['execution']['funding_observation_interval_ms']=1000
        state=initial_state(spec);_fill(state,Decimal(2),Decimal(100),Decimal(0),1500)
        _fill(state,Decimal(-2),Decimal(100),Decimal(0),2050)
        reduce_event(state,spec,events[0])
        self.assertEqual(Decimal(state['funding']),Decimal('-0.2'))
        self.assertEqual(state['signals_received'],0)
        self.assertEqual(funding_coverage(state,spec,{'start_ms':1000,'end_ms':5000})['state'],'complete')

    def test_reserved_witness_never_selects_or_decodes_its_payload(self):
        self.contract['addresses']=[self.reserved]
        oid=self.save('userFundings',self.funding(address=self.reserved),entity=self.reserved)
        # A real reserved plan is fixture metadata only. The payload is corrupt
        # intentionally; touching it must fail this test before any decoder.
        from tamtam_again.validation import initialize
        initialize(self.store)
        self.store.connection.execute('insert into validation_plans values(?,?,?,?,?,?,?)',
            ('reserved',self.network,self.reserved,'BTC','{}',0,0))
        self.store.connection.execute("update raw_observations set response_json='CORRUPT' where observation_id=?",(oid,))
        self.store.connection.commit();queries=[]
        self.store.connection.set_trace_callback(queries.append)
        events,_=self.read()
        self.store.connection.set_trace_callback(None)
        self.assertEqual(events,[])
        self.assertFalse(any(q.lower().startswith('select * from raw_observations where observation_id='+str(oid)) for q in queries))

    def test_duplicate_witnesses_do_not_double_debit_and_conflicts_remain_unknown(self):
        self.contract['addresses']=[self.witness,self.other]
        self.save('userFundings',self.funding())
        self.save('userFundings',self.funding(address=self.other),entity=self.other,stamp=2200)
        spec=synthetic_spec();spec['market']='BTC';spec['execution']['funding_observation_interval_ms']=1000
        state=initial_state(spec);_fill(state,Decimal(1),Decimal(100),Decimal(0),1500)
        for event in self.read()[0]:reduce_event(state,spec,event)
        self.assertEqual(state['funding_events'],1);self.assertEqual(Decimal(state['funding']),Decimal('-0.1'))
        self.save('userFundings',self.funding(address=self.other,usdc='-0.4'),entity=self.other,stamp=2300)
        reduce_event(state,spec,self.read()[0][-1])
        self.assertIn('conflicting_funding_settlement_coefficients',state['diagnostics'])
        self.assertEqual(funding_coverage(state,spec,{'start_ms':1000,'end_ms':2500})['state'],'incomplete')

    def test_foreign_sender_zero_size_future_and_outside_window_never_supply_rate(self):
        values=[self.funding(address=self.other),self.funding(szi='0'),
                self.funding(stamp=2200),self.funding(stamp=500)]
        for index,value in enumerate(values):self.save('userFundings',value,stamp=2100+index)
        self.assertEqual(self.read()[0],[])

    def test_untracked_late_added_or_corrupted_market_proof_refuses_payload(self):
        oid=self.save('userFundings',self.funding())
        self.store.connection.execute("update candidates set status='candidate' where address=?",(self.witness,));self.store.connection.commit()
        self.assertEqual(self.read()[0],[])
        self.store.connection.execute("update candidates set status='tracked',added_at=? where address=?",(iso(200),self.witness));self.store.connection.commit()
        self.assertEqual(self.read()[0],[])
        self.store.connection.execute("update raw_observations set response_sha256='bad' where observation_id=1");self.store.connection.commit()
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.read()

    def test_contract_freeze_network_market_and_capacity_are_enforced(self):
        for change in ({'addresses':[self.source]}, {'market':'ETH'}, {'network':'other'},
                {'available_ms':2000},{'currency':'USDH'},{'addresses':[self.witness]*10}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.read({**self.contract,**change})


class FundingWitnessMemoryTests(unittest.TestCase):
    def test_evaluation_feedback_and_child_memory_retain_witness_union(self):
        import json
        from tests import test_population_experiments as fixtures
        from tamtam_again.population_experiments import register_experiment
        from tamtam_again.recipe import synthetic_events
        from tamtam_again.validation import evaluate
        from tamtam_again.research_evaluation import poll, export_memory
        from tamtam_again.research_memory import release_period, save_knowledge
        from tamtam_again.population_memory import remember
        fixture=fixtures.PopulationExperimentTests();fixture.setUp()
        store=fixture.s;witness='0x'+'2'*40
        try:
            spec=fixture.result['proposal']['hypothesis']['executable_spec']
            spec['execution']['funding_witnesses']={'version':'settled-funding-witnesses-v1',
                'network':'synthetic','market':'SYNTH','currency':'USDC','available_ms':100,
                'addresses':[witness],'evidence_refs':['raw_observations:1','raw_observations:2']}
            store.connection.execute('update population_research_jobs set result_json=?',
                (json.dumps(fixture.result),));store.connection.commit()
            family=register_experiment(store,'request',fixture.plan,fixture.profile)
            variant=family['attempts'][0]['variant_id']
            result=evaluate(store,variant,'comparison',synthetic_events(10000),provenance='synthetic')
            period={'network':'synthetic','address':witness,'market':'*','start_ms':0,'end_ms':16000}
            self.assertEqual(result['source_periods'],[period])
            self.assertEqual(json.loads(store.connection.execute(
                'select period_json from validation_evaluation_source_periods').fetchone()[0]),period)
            with patch('tamtam_again.research_evaluation.now_ms',return_value=16500):poll(store)
            with patch('tamtam_again.research_memory.clock',return_value=17000):
                release_period(store,result['evaluation_id'],{'version':'fixture','justification':'fixture only','grace_ms':0})
            feedback=export_memory(store,'synthetic','fixture-only',17001)
            self.assertIn(period,feedback[0]['periods'])
            child_result={'proposal':{'hypothesis':{'mechanism':'fixture association','markets':['SYNTH'],
                'required_data':[],'rejection_criteria':'fixture','execution_constraints':'none','risk':'unknown'}},
                'critique':{'decision':'consistent'},'promotion_authorized':False,'profitability_proven':False}
            child_packet={'available_ms':17001,'research_evaluation_memory':feedback}
            store.connection.execute('insert into population_research_jobs values(?,?,?,?,?,?,?)',
                ('child','synthetic','fixture-only','hypothesis_recorded',json.dumps(child_result),17002,json.dumps(child_packet)))
            store.connection.commit()
            with patch('tamtam_again.research_memory.clock',return_value=18000),patch('tamtam_again.population_memory.now_ms',return_value=18000):
                saved=remember(store,'child')
                item=json.loads(store.connection.execute('select item_json from research_knowledge where knowledge_id=?',
                    (saved['knowledge_id'],)).fetchone()[0])
                self.assertIn(period,item['periods']);self.assertIn(witness,item['origin_accounts'])
                item['periods'].remove(period)
                with self.assertRaisesRegex(ValueError,'complete|union|explicit'):save_knowledge(store,item)
            # A later reservation of a witness must block the derived memory
            # before its outcome payload is selected, even for another market.
            reserved=synthetic_plan_for_memory()
            store.connection.execute('insert into validation_plans values(?,?,?,?,?,?,?)',
                ('witness-reserve','synthetic',witness,'OTHER',json.dumps(reserved),0,0))
            store.connection.commit();queries=[];store.connection.set_trace_callback(queries.append)
            self.assertEqual(export_memory(store,'synthetic','fixture-only',18000),[])
            store.connection.set_trace_callback(None)
            self.assertFalse(any(q.lower().startswith('select memory_json') for q in queries))
        finally:fixture.tearDown()


def synthetic_plan_for_memory():
    from tamtam_again.recipe import synthetic_plan
    plan=synthetic_plan();plan['comparison']={'start_ms':1000,'end_ms':16000}
    return plan


if __name__=='__main__':unittest.main()

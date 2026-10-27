"""Actual archive preparation and lossless contextual projection, no inference."""
import gzip
import json
import unittest
from pathlib import Path
from tests import test_population_descriptive as fixtures
from tamtam_again.engine import canonical, fingerprint
from tamtam_again.continuous_research import initialize, prepare_packet, _project_other_markets


class ContinuousPreparationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PopulationDescriptiveTests();self.fixture.setUp()
        self.store=self.fixture.store;initialize(self.store)
        self.policy=json.loads((Path(__file__).resolve().parents[1]/'config/continuous-research-policy.json').read_text())

    def tearDown(self):self.fixture.tearDown()

    def test_actual_archives_produce_scoped_packet_and_conservative_availability(self):
        report={'address':self.fixture.address,'markets':['COIN','OTHER'],
            'activity':{'observed_unique_fills':2,'observed_fill_content_fingerprint':'archive'}}
        self.store.connection.execute('update account_scope_reports set payload_json=?',(canonical(report),));self.store.connection.commit()
        self.fixture._raw(1,'userFillsByTime',[
            {'coin':'COIN','tid':'o','time':100,'startPosition':'0','side':'B','sz':'1','px':'10','fee':'0.01','feeToken':'USDC','crossed':False},
            {'coin':'COIN','tid':'c','time':150,'startPosition':'1','side':'A','sz':'1','px':'12','fee':'0.02','feeToken':'USDC','crossed':True}])
        item={'address':self.fixture.address,'candidate':'fixture:COIN','market':'COIN',
            'descriptive_markets':['COIN'],'cutoff_ms':200,'period_start_ms':0,'source_ref':'fixture:selection',
            'question':'Describe the observed mechanism.'}
        result=prepare_packet(self.store,self.policy,item)
        self.assertEqual(result['status'],'packet_ready')
        packet=result['packet']
        self.assertEqual(packet['available_ms'],200)
        self.assertEqual(packet['observations']['markets'],['COIN'])
        self.assertEqual(packet['observations']['account_context_markets'],['COIN','OTHER'])
        context=packet['execution_research_context']
        self.assertEqual(context['classification'],'chosen_simulation_scenario_not_measured_capacity')
        self.assertFalse(context['market_evidence'])
        self.assertFalse(context['paper_authorized'])
        self.assertNotIn('signal',context['scenario'])
        detail=packet['observations']['market_execution_detail_v1']['COIN']
        self.assertEqual(detail['execution_activity']['fill_count'],2)
        self.assertEqual(packet['fingerprint'],fingerprint({k:v for k,v in packet.items() if k!='fingerprint'}))
        self.assertEqual(self.store.connection.execute('select count(*) from population_research_jobs').fetchone()[0],0)

    def test_projection_keeps_selected_statistics_and_full_source_recoverable(self):
        packet={'observations':{'descriptive_history_v1':{'markets':{
            'COIN':{'activity':{'count':23},'price':{'result':'12.5'}},
            'OTHER':{'activity':{'count':100},'price':{'result':'9000'},'segments':list(range(1000))}},
            'summary_fingerprint':'original'}},'evidence_refs':['raw:1']}
        original=json.loads(canonical(packet));source=fingerprint(packet)
        _project_other_markets(self.store,packet,'COIN',200)
        history=packet['observations']['descriptive_history_v1']
        self.assertEqual(history['markets']['COIN'],original['observations']['descriptive_history_v1']['markets']['COIN'])
        self.assertNotIn('OTHER',history['markets'])
        row=self.store.connection.execute('select body_gzip from continuous_research_projections where source_fingerprint=?',(source,)).fetchone()
        self.assertEqual(json.loads(gzip.decompress(row[0])),original)
        self.assertIn('continuous_research_projections:'+source,packet['evidence_refs'])

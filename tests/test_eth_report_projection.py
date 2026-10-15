import copy
import unittest

from tamtam_again.eth_report_projection import project


class EthReportProjectionTests(unittest.TestCase):
    def report(self):
        fills=[]
        for index in range(16):
            action=('opens','reduces','inverts','unknown')[index%4]
            crossed=(index%2==0)
            fills.append({'tid':f'tid-{index:03d}','event_ms':1791936000000+(index//8)*86400000+index*1000,
                'crossed':crossed,'action':action,'side':'A','size':'0.5','price':'2500',
                'fee':'-0.01' if not crossed else '0.02','fee_token':'USDC','close_quantity':'0.2',
                'open_quantity':'0.3','start_position':'1','event_time_markout_60s_bps':float(index-8),
                'post_receipt_markout_60s_bps':float(index-4),
                'prefill_quote':{'age_ms':50,'bid':'2499.9','bid_size':'2','ask':'2500.1','ask_size':'3',
                    'ref':f'raw_observations:{index}#0'},
                'future_quote':{'ref':f'raw_observations:{index+100}#0'},
                'fill_page_observation_id':1000+index//4,'fill_page_sha256':'a'*64})
        return {'protocol_id':'eth-test','protocol_fingerprint':'protocol-fp','stage':'final_24h',
            'input_fingerprint':'source-fp','decision':'indeterminate','fills':fills,
            'summary':{'report':'aggregate fingerprint only'},'coverage':{'fills':{
                'page_count':4,'complete_page_count':4,'incomplete_page_count':0,
                'duplicate_fill_instances':2,'conflicting_fill_ids':[],'unique_eth_fills':16,
                'source_fingerprint':'fills-fp','pages':[]},'market':{'quotes':{'bbo':{'event_count':32}},
                    'rejected_events':{},'source_fingerprint':'quotes-fp','source_refs':[
                        {'observation_id':n,'sha256':str(n)} for n in range(10)]}},
            'quote_latency_ms':{'bbo':{'event_to_receive_ms':{'count':3}}},
            'limits':['sample warning']}

    def test_projection_keeps_population_statistics_and_bounds_identity_samples(self):
        report=self.report(); projection=project(report)
        stats=projection['population_statistics']
        self.assertEqual(stats['fill_count'],16)
        self.assertEqual(len(stats['by_utc_day']),2)
        self.assertEqual(stats['by_execution_and_position_effect']['maker']['reduces']['fills'],4)
        self.assertEqual(stats['by_execution_and_position_effect']['maker']['reduces']['observed_fees_by_token']['signed_amounts']['USDC'],'-0.04')
        self.assertEqual(projection['coverage_and_gaps']['market']['source_reference_count'],10)
        self.assertEqual(projection['coverage_and_gaps']['fills']['duplicate_fill_instances'],2)
        self.assertEqual(projection['source']['full_report_ref'],
            'eth_observation_reports:eth-test:final_24h#sha256:'+projection['source']['semantic_fingerprint'])
        self.assertEqual(projection['examples']['population_count'],stats['fill_count'])
        self.assertEqual(projection['examples']['selected_count'],len(projection['examples']['rows']))

    def test_example_selection_does_not_depend_on_outcomes(self):
        report=self.report(); first=project(report)
        changed=copy.deepcopy(report)
        for row in changed['fills']:
            row['event_time_markout_60s_bps']=-1e9
            row['post_receipt_markout_60s_bps']=1e9
            row['fee']='999999'
            row['price']='0.0001'
        second=project(changed)
        first_ids=[(row['day_utc'],row['stratum'],row['fill_id']) for row in first['examples']['rows']]
        second_ids=[(row['day_utc'],row['stratum'],row['fill_id']) for row in second['examples']['rows']]
        self.assertEqual(first_ids,second_ids)
        self.assertNotEqual(first['projection_fingerprint'],second['projection_fingerprint'])


if __name__=='__main__':
    unittest.main()

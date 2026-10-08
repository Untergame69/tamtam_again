import unittest
from tamtam_again.account_coverage import pagination_coverage


def page(start,end,status='pagination_exhausted',available=1000):
    return {'start_ms':start,'end_ms':end,'pagination_status':status,
            'available_ms':available,'evidence_ref':f'fixture:{start}:{end}'}


class CoverageTests(unittest.TestCase):
    def report(self,pages):
        return pagination_coverage(pages,start_ms=100,end_ms=900,as_of_ms=1000)

    def test_union_overlapping_windows_not_retention_proof(self):
        result=self.report([page(0,500),page(400,1000)])
        self.assertEqual(result['pagination_status'],'covered')
        self.assertEqual(result['pagination_intervals_ms'],[[100,900]])
        self.assertEqual(result['status'],'unknown')
        self.assertFalse(result['retention_proven'])

    def test_saturated_page_not_complete_window(self):
        result=self.report([page(0,500),page(400,1000,'page_budget_exhausted')])
        self.assertEqual(result['pagination_gaps_ms'],[[500,900]])

    def test_full_page_prefix_beyond_requested_end_covers_its_boundary(self):
        full={**page(0,1000,'page_budget_exhausted'),'covered_until_ms':950}
        self.assertEqual(self.report([full])['pagination_status'],'covered')
        full['covered_until_ms']=900
        self.assertEqual(self.report([full])['pagination_gaps_ms'],[[900,900]])

    def test_unavailable_page_cannot_close_gap(self):
        result=self.report([page(0,500),page(500,1000,available=1001)])
        self.assertEqual(result['pagination_gaps_ms'],[[500,900]])
        self.assertEqual(len(result['evidence_refs']),1)

    def test_internal_gap_preserved(self):
        self.assertEqual(self.report([page(100,200),page(300,900)])['pagination_gaps_ms'],[[200,300]])

class RetentionTests(unittest.TestCase):
    def witness(self,oldest=100):
        return {'request':{'type':'userFills','aggregateByTime':False},
                'requested_ms':900,'available_ms':950,'evidence_ref':'fixture:latest',
                'fills':[{'coin':'BTC','time':oldest,'tid':1}]}

    def run_report(self,witness,pages=None):
        from tamtam_again.account_coverage import retained_fill_coverage
        pagination=pagination_coverage([page(100,900)] if pages is None else pages,
            start_ms=100,end_ms=900,as_of_ms=1000)
        return retained_fill_coverage(pagination,[witness],start_ms=100,end_ms=900,as_of_ms=1000)

    def test_witness_can_prove_recent_window_without_lifetime_claim(self):
        r=self.run_report(self.witness())
        self.assertEqual(r['status'],'complete');self.assertTrue(r['retention_proven'])
        self.assertIn('fixture:latest',r['evidence_refs'])

    def test_witness_does_not_close_pagination_gap(self):
        self.assertEqual(self.run_report(self.witness(),[page(100,500)])['status'],'unknown')

    def test_short_or_empty_response_alone_does_not_prove_start_retained(self):
        w=self.witness(101)
        self.assertFalse(self.run_report(w)['retention_proven'])
        w['fills']=[]
        self.assertFalse(self.run_report(w)['retention_proven'])

    def test_causality_and_request_contract(self):
        for key,value in [('requested_ms',899),('available_ms',1001)]:
            w=self.witness();w[key]=value
            self.assertEqual(self.run_report(w)['status'],'unknown')
        w=self.witness();w['request']['aggregateByTime']=True
        self.assertEqual(self.run_report(w)['status'],'unknown')

    def test_duplicate_or_future_event_rejected(self):
        w=self.witness();w['fills']*=2
        self.assertEqual(self.run_report(w)['status'],'unknown')
        w=self.witness();w['fills'][0]['time']=951
        self.assertEqual(self.run_report(w)['status'],'unknown')

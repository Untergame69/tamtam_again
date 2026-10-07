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

    def test_unavailable_page_cannot_close_gap(self):
        result=self.report([page(0,500),page(500,1000,available=1001)])
        self.assertEqual(result['pagination_gaps_ms'],[[500,900]])
        self.assertEqual(len(result['evidence_refs']),1)

    def test_internal_gap_preserved(self):
        self.assertEqual(self.report([page(100,200),page(300,900)])['pagination_gaps_ms'],[[200,300]])

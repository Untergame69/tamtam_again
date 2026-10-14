import unittest
import sqlite3
import tempfile
from decimal import Decimal

from tamtam_again.population_eth_execution_contribution import measure_fill_consequences, summarize_consequences, persist_artifact
from tamtam_again.engine import fingerprint


class EthExecutionContributionTests(unittest.TestCase):
    def test_strict_prior_future_horizons_and_inversion_split(self):
        fills=[{'tid':'f1','time':1000,'segment':1,'utc_day':'2026-10-06','crossed':True,
            'startPosition':'-1','side':'B','sz':'1.5','px':'101','fee':'0.1','feeToken':'USDC'}]
        quotes=[(1000,'99','101',{'id':'equal'}),(900,'99','101',{'id':'prior'}),
            (2000,'100','102',{'id':'h1'}),(61000,'102','104',{'id':'h60'})]
        rows=measure_fill_consequences(fills,quotes,horizons_ms=(1000,60000))
        row=rows[0]
        self.assertEqual(row['action'],'inverts')
        self.assertEqual(Decimal(row['close_quantity']),Decimal('1'))
        self.assertEqual(Decimal(row['open_quantity']),Decimal('.5'))
        self.assertEqual(row['strict_prior_quote']['event_ms'],900)
        self.assertEqual(row['strict_prior_quote']['ref']['id'],'prior')
        self.assertEqual(row['future_midpoints_outcome_only']['1000']['quote_event_ms'],2000)
        self.assertEqual(row['future_midpoints_outcome_only']['60000']['quote_event_ms'],61000)
        self.assertEqual(Decimal(row['future_midpoints_outcome_only']['1000']['mid_change_bps']),Decimal('100'))

    def test_reductions_and_missing_quote_coverage_remain_explicit(self):
        fills=[{'tid':'f','time':10,'segment':1,'utc_day':'d','crossed':False,'startPosition':'2',
            'side':'A','sz':'1','px':'100','fee':'-0.01','feeToken':'USDC'}]
        rows=measure_fill_consequences(fills,[(9,'99','101',{})],horizons_ms=(1000,))
        self.assertEqual(rows[0]['action'],'reduces')
        self.assertIsNone(rows[0]['future_midpoints_outcome_only']['1000'])
        summary=summarize_consequences(rows)
        maker=next(x for x in summary['behavior'] if x['key']=='maker')
        self.assertEqual(maker['strict_prior_matched'],1)
        self.assertEqual(maker['prior_coverage_by_max_age']['100'],1)

    def test_persistence_survives_reopen_without_duplicate(self):
        with tempfile.NamedTemporaryFile() as db:
            con=sqlite3.connect(db.name);con.row_factory=sqlite3.Row
            art={'schema_version':'test','value':1};art['analysis_fingerprint']=fingerprint(art)
            self.assertEqual(persist_artifact(con,'task','base',art)[0],'prepared')
            con.close()
            con=sqlite3.connect(db.name);con.row_factory=sqlite3.Row
            status,fp,loaded=persist_artifact(con,'task','base',art)
            self.assertEqual(status,'unchanged');self.assertEqual(fp,art['analysis_fingerprint'])
            self.assertEqual(loaded['value'],1)
            self.assertEqual(con.execute('select count(*) from population_eth_execution_contributions').fetchone()[0],1)
            con.close()


if __name__=='__main__':unittest.main()

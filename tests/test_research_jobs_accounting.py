"""Shared historical quota excludes independent immutable research allowances."""
import sqlite3
import unittest
from types import SimpleNamespace
from tamtam_again.research_jobs import request_count


class SharedAccountingTests(unittest.TestCase):
    def test_minimal_legacy_registry_cannot_refund_unknown_attempts(self):
        connection=sqlite3.connect(':memory:');self.addCleanup(connection.close)
        connection.execute('create table paper_research_jobs(request_id text)')
        connection.executemany('insert into paper_research_jobs values(?)',[('unknown-1',),('unknown-2',)])
        self.assertEqual(request_count(SimpleNamespace(connection=connection)),2)

    def store(self, *, pilot=False, continuous=False, activation=True):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.execute('create table population_research_jobs(request_id text primary key,status text)')
        # Terminal, interrupted and failed attempts remain historical usage.
        conn.executemany('insert into population_research_jobs values(?,?)',
            [('shared', 'hypothesis_recorded'), ('failed', 'suspended'),
             ('pilot', 'interrupted'), ('continuous', 'failed')])
        if pilot:
            conn.execute('create table population_research_pilot_tasks(request_id text primary key)')
            conn.execute("insert into population_research_pilot_tasks values('pilot')")
        if continuous:
            conn.execute('create table continuous_research_tasks(request_id text primary key)')
            conn.execute("insert into continuous_research_tasks values('continuous')")
        conn.execute('create table paper_research_jobs(request_id text primary key,status text' +
            (',activated_ms integer)' if activation else ')'))
        return SimpleNamespace(connection=conn)

    def test_independent_dedicated_schema_combinations_preserve_history(self):
        for pilot, continuous in [(False,False),(True,False),(False,True),(True,True)]:
            with self.subTest(pilot=pilot,continuous=continuous):
                store = self.store(pilot=pilot,continuous=continuous)
                before = store.connection.execute('select * from population_research_jobs order by request_id').fetchall()
                self.assertEqual(request_count(store), 4-int(pilot)-int(continuous))
                self.assertEqual(store.connection.execute('select * from population_research_jobs order by request_id').fetchall(), before)

    def test_activated_and_failed_paper_count_but_prepared_does_not(self):
        store = self.store(pilot=True,continuous=True)
        store.connection.executemany('insert into paper_research_jobs values(?,?,?)',
            [('prepared', 'budget_required', None), ('archived_prepared', 'archived', None),
             ('failed_activated', 'failed', 5), ('archived_activated', 'archived', 5),
             ('historical_failed', 'failed', None), ('old_sealed', 'sealed', None)])
        self.assertEqual(request_count(store), 6)

    def test_legacy_paper_schema_preserves_engaged_failures(self):
        store = self.store(continuous=True,activation=False)
        store.connection.executemany('insert into paper_research_jobs values(?,?)',
            [('prepared', 'budget_required'), ('archived', 'archived'),
             ('failed', 'failed'), ('interrupted', 'interrupted')])
        self.assertEqual(request_count(store), 5)

    def test_same_job_in_both_dedicated_tables_is_excluded_once(self):
        store = self.store(pilot=True,continuous=True)
        store.connection.execute("insert into population_research_pilot_tasks values('continuous')")
        self.assertEqual(request_count(store), 2)

    def test_existing_over_limit_eleven_shared_attempts_are_not_reset(self):
        store = self.store(pilot=True,continuous=True)
        store.connection.executemany('insert into population_research_jobs values(?,?)',
            [('old-'+str(i), 'interrupted') for i in range(9)])
        self.assertEqual(request_count(store), 11)
        historical_limit = 8
        self.assertGreater(request_count(store), historical_limit)
        store.connection.execute("insert into population_research_jobs values('new-daily','needs_data')")
        store.connection.execute("insert into continuous_research_tasks values('new-daily')")
        self.assertEqual(request_count(store), 11)
        self.assertEqual(store.connection.execute('select count(*) from population_research_jobs').fetchone()[0], 14)

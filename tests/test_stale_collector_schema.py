"""Reproduce the pre-R1 collector's index recreation against receipt storage."""
import sqlite3,tempfile,unittest
from pathlib import Path
from tamtam_again.storage import Store

LEGACY_INDEX='''CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_observation
 ON raw_observations(network,source,entity_type,entity_id,endpoint,
 ifnull(window_start_ms,-1),ifnull(window_end_ms,-1),response_sha256)'''

class StaleCollectorSchemaTests(unittest.TestCase):
 def test_legacy_index_build_blocks_writer_then_fails_without_losing_receipts(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'db'
   with Store(path) as store:
    for i in [*range(100),0]:
     store.save_observation(network='fixture',source='hyperliquid-population-rest-v1',
      entity_type='account',entity_id='fixture',endpoint='clearinghouseState',payload={'fixture':i})
    with sqlite3.connect(path) as other:
     other.execute('pragma busy_timeout=1')
     failures=[]
     def probe():
      if not failures:
       try:other.execute('begin immediate')
       except sqlite3.OperationalError as exc:failures.append(exc.sqlite_errorname)
       else:other.rollback()
      return 0
     store.connection.set_progress_handler(probe,100)
     with self.assertRaises(sqlite3.IntegrityError):store.connection.execute(LEGACY_INDEX)
     store.connection.set_progress_handler(None,0);store.connection.rollback()
     self.assertEqual(failures,['SQLITE_BUSY'])
     self.assertEqual(store.connection.execute('select count(*) from raw_observations').fetchone()[0],101)
     other.execute('begin immediate');other.rollback()
   with Store(path) as reopened:
    self.assertFalse(reopened.connection.execute("select 1 from sqlite_master where name='uq_raw_observation'").fetchone())
    self.assertEqual(reopened.connection.execute('select count(*) from raw_observations').fetchone()[0],101)

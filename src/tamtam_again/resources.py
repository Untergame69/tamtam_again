"""Metadata-only storage and Linux process resource observations."""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import sqlite3
import time


def sample_resources(db: Path, *, pid: int | None=None):
    stat=db.stat()
    with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True,timeout=5) as c:
        pages=c.execute('pragma page_count').fetchone()[0]
        free=c.execute('pragma freelist_count').fetchone()[0]
        size=c.execute('pragma page_size').fetchone()[0]
    files={suffix:Path(str(db)+suffix).stat().st_size if Path(str(db)+suffix).exists() else 0
           for suffix in ('','-wal','-shm')}
    process=None
    if pid:
        try:
            # Stat fields after ')' start at field 3; command names may contain spaces.
            fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
            process={'pid':pid,'start_ticks':int(fields[19]),
                     'cpu_seconds':(int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK'),
                     'resident_bytes':int(fields[21])*os.sysconf('SC_PAGE_SIZE')}
        except (OSError,ValueError,IndexError):pass
    return {'sampled_at':time.time(),'database_identity':[stat.st_dev,stat.st_ino],
            'logical_allocated_bytes':pages*size,'logical_live_page_bytes':(pages-free)*size,
            'file_bytes':files,'disk_free_bytes':shutil.disk_usage(db.parent).free,
            'process':process,'limits':['process sample excludes children and other workers',
                                       'live pages include indexes; not payload bytes',
                                       'WAL/file sizes can fluctuate during checkpoints']}


def resource_change(before,after):
    elapsed=after['sampled_at']-before['sampled_at']
    if elapsed<=0:raise ValueError('Resource samples must advance in time')
    same_db=before['database_identity']==after['database_identity']
    first,last=before.get('process'),after.get('process')
    same_process=bool(first and last and first['pid']==last['pid'] and first['start_ticks']==last['start_ticks'])
    return {'elapsed_seconds':elapsed,'same_database':same_db,
            'logical_live_growth_bytes_per_second':(after['logical_live_page_bytes']-before['logical_live_page_bytes'])/elapsed if same_db else None,
            'process_cpu_cores_used':(last['cpu_seconds']-first['cpu_seconds'])/elapsed if same_process else None,
            'same_process':same_process,'extrapolation_status':'window_only_not_capacity_forecast'}

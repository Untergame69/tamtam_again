"""Public collector measurements in a separate additive SQLite database.

No response bodies, addresses or reserved samples are written here. Budgeted
weight is a conservative local reservation, never claimed as server billing.
"""
from __future__ import annotations
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

SCHEMA = '''
CREATE TABLE IF NOT EXISTS quota_clock (
 scope TEXT PRIMARY KEY, next_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS collection_attempts (
 attempt_id INTEGER PRIMARY KEY, started_at REAL NOT NULL, completed_at REAL NOT NULL,
 task TEXT NOT NULL, endpoint TEXT NOT NULL, network TEXT NOT NULL,
 reserved_weight INTEGER NOT NULL, response_weight_bound INTEGER,
 retry INTEGER NOT NULL, outcome TEXT NOT NULL, http_status INTEGER,
 elapsed_seconds REAL NOT NULL, wait_seconds REAL NOT NULL,
 response_bytes INTEGER NOT NULL, response_items INTEGER);
CREATE INDEX IF NOT EXISTS idx_attempts_time ON collection_attempts(started_at);
CREATE TABLE IF NOT EXISTS collector_measurements (
 measurement_id INTEGER PRIMARY KEY, recorded_at REAL NOT NULL,
 collector TEXT NOT NULL, metrics_json TEXT NOT NULL);
'''
class Telemetry:
    def __init__(self, path: Path):
        self.path=path; path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c: c.executescript(SCHEMA)
    def connect(self):
        c=sqlite3.connect(self.path,timeout=10);c.execute('pragma busy_timeout=10000');return c
    def reserve(self, weight: int, *, budget_per_minute: int=900, now: float | None=None) -> float:
        if weight<=0 or budget_per_minute<=0: raise ValueError('Positive weight and budget required')
        now=time.time() if now is None else now
        with self.connect() as c:
            c.execute('begin immediate')
            row=c.execute("select next_at from quota_clock where scope='rest-public-ip'").fetchone()
            scheduled=max(now,row[0] if row else now)
            c.execute("insert into quota_clock values('rest-public-ip',?) on conflict(scope) do update set next_at=excluded.next_at",(scheduled+weight*60/budget_per_minute,))
        return scheduled-now
    def defer(self, seconds: float):
        with self.connect() as c:
            c.execute('begin immediate')
            c.execute("insert into quota_clock values('rest-public-ip',?) on conflict(scope) do update set next_at=max(next_at,excluded.next_at)",(time.time()+max(0,seconds),))
    def attempt(self, **values: Any):
        columns=('started_at','completed_at','task','endpoint','network','reserved_weight','response_weight_bound','retry','outcome','http_status','elapsed_seconds','wait_seconds','response_bytes','response_items')
        with self.connect() as c:
            c.execute('insert into collection_attempts ('+','.join(columns)+') values ('+','.join('?' for _ in columns)+')',tuple(values.get(k) for k in columns))
    def measure(self,collector: str,metrics: dict[str,Any]):
        with self.connect() as c: c.execute('insert into collector_measurements(recorded_at,collector,metrics_json) values (?,?,?)',(time.time(),collector,json.dumps(metrics,sort_keys=True)))
    def report(self, since: float, *, now: float | None=None) -> dict[str,Any]:
        now=time.time() if now is None else now
        with self.connect() as c:
            c.row_factory=sqlite3.Row
            groups=[dict(r) for r in c.execute('''select task,endpoint,network,count(*) attempts,
              sum(reserved_weight) reserved_weight,sum(response_weight_bound) response_weight_bound,
              sum(retry>0) retry_attempts,sum(outcome='http_error') http_errors,
              sum(http_status=429) rate_limits,sum(response_bytes) response_bytes,
              avg(elapsed_seconds) mean_request_seconds,max(elapsed_seconds) max_request_seconds,
              sum(wait_seconds) wait_seconds,sum(response_items) response_items
              from collection_attempts where started_at>=? and started_at<=? group by task,endpoint,network''',(since,now))]
        minutes=max((now-since)/60,1e-9)
        return {'since':since,'until':now,'window_minutes':minutes,'groups':groups,
                'reserved_weight_per_minute':sum(g['reserved_weight'] for g in groups)/minutes,
                'charged_weight':'unknown: server does not return charged weight',
                'response_weight_bound':'documented response-item formula, rounded conservatively; not server measurement'}

import json
import sqlite3
import unittest

from tamtam_again.archive_coverage import (
    _fill_rows, _position_boundary_check, _summarize_stream_health,
    build_manifest, iso_ms, parse_selection_addresses,
)


ADDR = "0x" + "1" * 40
OTHER = "0x" + "2" * 40


def row_payload(payload):
    return {"response_encoding": "json", "response_json": json.dumps(payload)}


def fixture_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
      create table candidates(network text,address text,status text,discovery_source text,label text,added_at text,primary key(network,address));
      create table raw_observations(observation_id integer primary key,network text,source text,entity_type text,entity_id text,endpoint text,request_json text,requested_at text,observed_at text,window_start_ms integer,window_end_ms integer,record_count integer,complete integer,response_encoding text,response_sha256 text,response_json text);
      create table validation_plans(plan_id text primary key,network text,address text,coin text,plan_json text,created_ms integer,synthetic integer);
      create table research_window_releases(plan_id text,stage text,released_ms integer);
      create table research_period_releases(evaluation_id text primary key,released_ms integer,policy_json text,network text,address text,market text,start_ms integer,end_ms integer);
      create table consumed_holdouts(evaluation_id text primary key,network text,address text,coin text,start_ms integer,end_ms integer,consumed_at text);
      create table validation_evaluations(evaluation_id text primary key,variant_id text,plan_id text,stage text,status text,input_fingerprint text,result_json text,created_at text);
      create table research_targets(network text,address text,coin text,status text);
      create table population_history_cursors(network text,address text,endpoint text,cursor_ms integer,target_end_ms integer,status text,updated_at text,evidence_json text);
      create table population_accounts(network text,address text,status text);
      create table account_scope_reports(report_id text,network text,address text,available_ms integer,payload_json text);
    """)
    conn.execute("insert into candidates values(?,?,?,?,?,?)", (
        "hyperliquid-mainnet", ADDR, "tracked", "fixture", "", "2026-10-01T00:00:00Z"))
    return conn


def insert_obs(conn, ident, *, address=ADDR, source="hyperliquid-population-rest-v1",
               endpoint="userFillsByTime", payload=None, request=None,
               observed="2026-10-26T12:00:00.000+00:00", window=(1793010000000, 1793010100000),
               entity_type="account", entity=None):
    body = json.dumps(payload if payload is not None else [])
    conn.execute("insert into raw_observations values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        ident, "hyperliquid-mainnet", source, entity_type, entity or address, endpoint,
        json.dumps(request or {"startTime": window[0], "endTime": window[1], "pagination_status": "pagination_exhausted"}),
        "2026-10-26T11:59:59.000+00:00", observed, window[0], window[1], 1, 1,
        "json", "fixture", body))


class ArchiveCoverageTests(unittest.TestCase):
    def test_selection_parser_uses_only_prescreen_rows(self):
        text = "\n".join([
            f"| `{ADDR}` | présélection courbes + activité (économie non validée) |",
            f"| `{OTHER}` | documentation insuffisante |",
        ])
        self.assertEqual(parse_selection_addresses(text), [ADDR])

    def test_nested_events_are_flattened_and_batch_counted(self):
        fill = {"coin": "ETH", "time": 1793010000001, "tid": 3, "side": "B", "sz": "1"}
        got, batches = _fill_rows({"events": [{"channel": "userFills", "data": [fill]}]})
        self.assertEqual(len(got), 1)
        self.assertEqual(batches, 1)

    def test_position_boundary_match_stays_short_of_completeness_proof(self):
        snapshots = [
            {"available_ms": 10, "dex": "", "positions": {"ETH": "1"}, "evidence_ref": "state:1"},
            {"available_ms": 100, "dex": "", "positions": {"ETH": "2"}, "evidence_ref": "state:2"},
        ]
        fills = [{"event_ms": 20, "available_ms": 21, "source": "websocket", "side": "B", "sz": "1"}]
        result = _position_boundary_check("ETH", fills, snapshots)
        self.assertEqual(result["status"], "arithmetic_match_on_observed_interval")
        self.assertFalse(result["coherent_position_proven"])

    def test_stream_health_counts_heartbeat_gaps_and_explicit_disconnects(self):
        result = _summarize_stream_health([
            {"kind": "connection", "connected": True, "available_ms": 1000, "evidence_ref": "health:1"},
            {"kind": "heartbeat", "connected": True, "available_ms": 2000, "evidence_ref": "health:2"},
            {"kind": "heartbeat", "connected": True, "available_ms": 68001, "evidence_ref": "health:3"},
            {"kind": "connection", "connected": False, "available_ms": 69000, "evidence_ref": "health:4"},
        ])
        self.assertEqual(result["heartbeat_gaps_over_threshold"], 1)
        self.assertEqual(result["explicit_disconnect_count"], 1)
        self.assertFalse(result["right_censored_at_cutoff"])

    def test_manifest_links_observed_fill_session_to_bounded_health_rows(self):
        conn = fixture_db()
        start, cutoff = 1793000000000, 1793020000000
        session = "fixture-session"
        insert_obs(conn, 1, source="hyperliquid-websocket-v1", endpoint="userFills",
            payload=[{"coin": "ETH", "time": start + 1000, "tid": 7, "side": "B", "sz": "1"}],
            request={"user_fills_stream": {"connection_id": session}},
            observed=iso_ms(start + 2000), window=(start, cutoff))
        for ident, stamp, kind, connected in [
            (2, start + 3000, "connection", True),
            (3, start + 6000, "heartbeat", True),
            (4, start + 9000, "connection", False),
        ]:
            insert_obs(conn, ident, source="hyperliquid-websocket-v1", endpoint="streamHealth",
                entity_type="stream", entity=session,
                payload={"kind": kind, "connected": connected, "session": session},
                observed=iso_ms(stamp), window=(start, cutoff))
        result = build_manifest(conn, [ADDR], since_ms=start, cutoff_ms=cutoff,
            max_book_rows_per_endpoint=1)
        self.assertEqual(result["stream_health"]["sessions_observed"], 1)
        health = result["stream_health"]["sessions"][session]
        self.assertEqual(health["events_observed"], 3)
        self.assertEqual(health["explicit_disconnect_count"], 1)
        self.assertIn(ADDR, health["associated_account_refs"])
        self.assertEqual(result["accounts"][0]["pairs"]["ETH"]["websocket_connection_ids"], [session])
        conn.close()

    def test_repeated_fill_is_deduplicated_and_conflicting_identity_is_reported(self):
        conn = fixture_db()
        fill = {"coin": "ETH", "time": 1793010000001, "tid": 3, "side": "B", "sz": "1", "fee": "0.01"}
        insert_obs(conn, 1, payload=[fill])
        insert_obs(conn, 2, payload=[fill])
        changed = {**fill, "sz": "2"}
        insert_obs(conn, 3, payload=[changed])
        result = build_manifest(conn, [ADDR], since_ms=1793000000000,
            cutoff_ms=1793020000000, max_book_rows_per_endpoint=1)
        pair = result["accounts"][0]["pairs"]["ETH"]
        self.assertEqual(pair["fills"]["unique_events"], 1)
        self.assertEqual(result["accounts"][0]["scan"]["duplicate_events"], 1)
        self.assertEqual(result["accounts"][0]["scan"]["conflicting_events"], 1)
        self.assertEqual(pair["fees"]["fee_field_present"], 1)
        conn.close()

    def test_protected_address_payload_is_not_included_in_manifest(self):
        conn = fixture_db()
        conn.execute("insert into validation_plans values(?,?,?,?,?,?,?)", (
            "pilot", "hyperliquid-mainnet", ADDR, "ETH", json.dumps({"windows": {}}), 0, 0))
        insert_obs(conn, 1, address=ADDR, payload=[{"coin": "ETH", "time": 1793010000001, "tid": 1, "side": "B", "sz": "1"}])
        result = build_manifest(conn, [ADDR], since_ms=1793000000000,
            cutoff_ms=1793020000000, max_book_rows_per_endpoint=1)
        self.assertEqual(result["accounts"], [])
        self.assertEqual(result["selection"]["protected_addresses_excluded"], [ADDR])
        conn.close()

    def test_reserved_window_page_is_skipped_without_decoding(self):
        conn = fixture_db()
        plan = {"population_origin": "test", "windows": {"final": {"start_ms": 1793010000000, "end_ms": 1793010200000}}}
        conn.execute("insert into validation_plans values(?,?,?,?,?,?,?)", (
            "released", "hyperliquid-mainnet", ADDR, "ETH", json.dumps(plan), 0, 0))
        conn.executemany("insert into research_window_releases values(?,?,?)", [
            ("released", "comparison", 1), ("released", "final", 1)])
        insert_obs(conn, 1, payload=[{"coin": "ETH", "time": 1793010000001, "tid": 1, "side": "B", "sz": "1"}],
                   window=(1793010000000, 1793010200000))
        result = build_manifest(conn, [ADDR], since_ms=1793000000000,
            cutoff_ms=1793020000000, max_book_rows_per_endpoint=1)
        account = result["accounts"][0]
        self.assertEqual(account["scan"]["observations_decoded"], 0)
        self.assertEqual(account["scan"]["skipped_reserved_pages"], ["raw_observations:1"])
        self.assertEqual(account["pairs"]["ETH"]["fills"]["unique_events"], 0)
        conn.close()


if __name__ == "__main__":
    unittest.main()

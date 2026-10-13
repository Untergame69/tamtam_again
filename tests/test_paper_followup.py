import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tamtam_again.engine import canonical
from tamtam_again.paper_followup import choose_route, present_report, reconstruct_lineage
from tamtam_again.paper_research import seal, packet as research_packet
from tamtam_again.population_routing import route
from tamtam_again.research_jobs import request_count


class FollowupTests(unittest.TestCase):
    def test_route_depends_on_evidence_and_not_duration(self):
        report = {"next_action": "new_version_suggested"}
        self.assertEqual(choose_route("completed", report)["route"], "wait")
        report.update(feed={"connected": True}, signals={"live_non_snapshot_fills": 1},
                      results_after_simulated_costs={"net_pnl_observed_usdc": "0",
                          "fees_usdc": "0", "funding_events_observed": 0})
        self.assertEqual(choose_route("completed", report)["route"], "strategic_analysis")
        report["feed"] = {"connected": False}
        self.assertEqual(choose_route("completed", report)["route"], "targeted_collection")
        report["feed"] = {"connected": True}
        report["execution_diagnosis"] = {"category": "priority_exit_failure"}
        self.assertEqual(choose_route("completed", report)["route"], "execution_correction")
        self.assertEqual(choose_route("active", report)["route"], "wait")
        report.pop("execution_diagnosis")
        self.assertEqual(choose_route("abandoned", report)["route"], "abandon")

    def test_lineage_keeps_unknown_and_multiple_candidates(self):
        links = reconstruct_lineage(
            [{"tid": "a", "received_ms": 100}, {"tid": "b", "received_ms": 1000}],
            [{"signal_decision_ms": 110, "execution_decision_ms": 120,
              "outcome": "executed", "fill_size": "1", "intent": "entry"},
             {"signal_decision_ms": 120, "execution_decision_ms": 130,
              "outcome": "partial", "fill_size": "0.5", "intent": "entry"}],
            [{"received_ms": 120, "size": "1"}, {"received_ms": 120, "size": "1"}],
            max_receipt_lag_ms=50)
        self.assertEqual(links["source_signal_to_decision"][0]["status"], "multiple_candidates")
        self.assertEqual(links["source_signal_to_decision"][1]["status"], "unknown")
        self.assertEqual(links["order_to_paper_fill"][0]["fill_link"]["status"], "multiple_exact_attribute_matches")
        self.assertEqual(links["order_to_paper_fill"][1]["fill_link"]["status"], "unknown")

    def test_report_handoff_is_persistent_idempotent_and_budget_gated(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "followup.sqlite3"
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            con.executescript("""
                create table validation_plans(plan_id text,network text,address text,coin text,plan_json text);
                create table strategy_variants(variant_id text,plan_id text,spec_json text,frozen_ms integer);
                create table paper_sessions(session_id text,network text,address text,coin text,started_ms integer,
                    status text,variant_id text,state_json text,last_observation_id integer);
                create table paper_experimental_sessions(session_id text,status text,review_index integer);
                create table paper_experimental_reports(report_id text,session_id text,review_index integer,
                    observed_through_ms integer,report_json text);
                create table paper_suspensions(session_id text,suspended_ms integer,diagnostics_json text);
                create table paper_snapshots(snapshot_id text,session_id text,available_ms integer);
                create table raw_observations(observation_id integer primary key,network text,source text,
                    entity_type text,entity_id text,endpoint text,request_json text,requested_at text,observed_at text,
                    window_start_ms integer,window_end_ms integer,record_count integer,complete integer,
                    response_encoding text,response_json text);
                create table population_research_jobs(request_id text primary key);
                insert into validation_plans values('p','hyperliquid-mainnet','0xabc','HYPE',
                    '{"comparison":{"start_ms":100,"end_ms":200},"final":{"start_ms":300,"end_ms":400}}');
                insert into strategy_variants values('v','p','{"market":"HYPE","fees":{},"slippage":{}}',1);
                insert into paper_sessions values('s','hyperliquid-mainnet','0xabc','HYPE',10,'suspended','v',
                    '{"last_ms":20,"position":"0","pending":[],"fills":[]}',0);
                insert into paper_experimental_sessions values('s','completed',1);
                insert into paper_experimental_reports values('r','s',1,20,
                    '{"feed":{"connected":true},"signals":{"live_non_snapshot_fills":1},
                      "results_after_simulated_costs":{"net_pnl_observed_usdc":"-1","fees_usdc":"0.1","funding_events_observed":0},
                      "execution_opportunities":{"records":[],"miss_reasons":{}},"scheduler":{},"observations_limits":[]}');
                insert into paper_suspensions values('s',20,'[]');
                insert into paper_snapshots values('snap','s',20);
            """)
            store = SimpleNamespace(connection=con)
            first = present_report(store, "s", "r", clock_ms=30)
            con.execute("insert into paper_research_jobs(request_id,adaptation_request_id,session_id,created_ms,"
                "packet_json,policy_json,status,network,address,updated_ms,parent_request_id) "
                "values(?,?,?,?,?,?,?,?,?,?,NULL)", ("prior-immutable", first["request_id"], "s", 25,
                    '{"historical":true}', "{}", "archived", "hyperliquid-mainnet", "0xabc", 25))
            con.commit()
            second = present_report(store, "s", "r", clock_ms=31)
            self.assertEqual(first["request_id"], second["request_id"])
            self.assertEqual(first["job_id"], second["job_id"])
            self.assertEqual(second["status"], "unchanged")
            self.assertEqual(con.execute("select count(*) from paper_adaptation_requests").fetchone()[0], 1)
            self.assertEqual(con.execute("select count(*) from paper_research_jobs").fetchone()[0], 2)
            self.assertEqual(con.execute("select status from paper_research_jobs where request_id='prior-immutable'").fetchone()[0], "archived")
            self.assertEqual(request_count(store), 1)
            task_packet = research_packet(store, first["request_id"], clock_ms=31, max_chars=225_000)
            self.assertEqual(task_packet["status"], "packet_ready")
            self.assertEqual(task_packet["packet"]["fingerprint"], first["packet_fingerprint"])
            routed = route(store, first["job_id"], kind="paper")
            self.assertEqual(routed["state"], "budget_required")
            self.assertEqual(routed["route"], "strategic_analysis")

            for i in range(8):
                con.execute("insert into population_research_jobs values(?)", (f"p{i}",))
            con.commit()
            self.assertEqual(request_count(store), 9)
            policy = {"version": "paper-adaptation-research-v1", "justification": "test only",
                "max_requests": 8, "max_packet_chars": 225000, "max_prompt_chars": 260000,
                "minimum_interval_ms": 86400000, "timeout_seconds": 120,
                "max_output_tokens": 5000, "max_request_age_ms": 3600000,
                "model": "gpt-6.1-sol",
                "call_reservation_usd": 1.0}
            self.assertEqual(seal(store, first["request_id"], policy, clock_ms=31)["status"], "budget_exhausted")
            self.assertEqual(con.execute("select status from paper_research_jobs").fetchone()[0], "budget_required")
            con.close()


if __name__ == "__main__":
    unittest.main()

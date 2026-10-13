import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tamtam_again.engine import canonical
from tamtam_again.paper_followup import choose_route, present_report, reconstruct_lineage
from tamtam_again.paper_research import authorize_task, seal, packet as research_packet
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
            self.assertEqual(request_count(store), 0)
            con.execute("insert into paper_research_jobs(request_id,adaptation_request_id,session_id,created_ms,"
                "packet_json,policy_json,status,network,address,updated_ms,parent_request_id) "
                "values(?,?,?,?,?,?,?,?,?,?,NULL)", ("attempt-interrupted", first["request_id"], "s", 26,
                    "{}", "{}", "interrupted", "hyperliquid-mainnet", "0xabc", 26))
            con.commit()
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

    def _runtime_fixture(self):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "paper.sqlite3"
        con = sqlite3.connect(path)
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
                response_encoding text,response_sha256 text,response_json text);
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
        return tmp, SimpleNamespace(connection=con, path=path)

    @staticmethod
    def _policy():
        return {"version": "paper-adaptation-research-v1", "justification": "integration fixture only",
            "model": "fixture", "max_requests": 8, "max_packet_chars": 225000,
            "max_prompt_chars": 260000, "minimum_interval_ms": 86400000,
            "timeout_seconds": 120, "max_output_tokens": 5000,
            "max_request_age_ms": 50, "call_reservation_usd": "1"}

    def _runtime_response(self, job_id, packet, missing=False):
        from tamtam_again.engine import canonical
        if missing:
            return [(canonical({"decision": "needs_data", "diagnostic": "specific observations required",
                "wake": {"kind": "named_data"}}), {"cost_usd": "0.2", "cost_status": "included"})]
        hypothesis = {key: "fixture falsifiable description" for key in
            ("mechanism", "signal", "entry", "exit", "sizing", "risk", "horizon_justification",
             "execution_constraints", "rejection_criteria")}
        hypothesis.update(type="follower", markets=["HYPE"], required_data=[],
            evidence_refs=[packet["evidence_refs"][0]])
        proposal = {"decision": "hypothesis", "diagnostic": "causal description only", "wake": {},
            "hypothesis": hypothesis}
        critique = {"decision": "consistent", "diagnostic": "internally testable, not profitable proof", "wake": {}}
        usage = {"cost_usd": "0.25", "cost_status": "included"}
        return [(canonical(proposal), usage), (canonical(critique), usage)]

    def test_integration_hypothesis_traverses_handoff_activation_runtime_and_route_after_long_wait(self):
        from tamtam_again.paper_runtime import run
        from tamtam_again.engine import canonical
        tmp, store = self._runtime_fixture()
        try:
            task = present_report(store, "s", "r", clock_ms=30)
            preparatory = route(store, task["job_id"], kind="paper")
            self.assertEqual(preparatory["state"], "budget_required")
            store.connection.execute("create table population_research_jobs(request_id text primary key)")
            store.connection.executemany("insert into population_research_jobs values(?)",
                [(f"historical-{i}",) for i in range(8)])
            store.connection.commit()
            self.assertEqual(request_count(store), 8)
            source_packet = json.loads(store.connection.execute(
                "select packet_json from paper_research_jobs where request_id=?", (task["job_id"],)).fetchone()[0])
            self.assertEqual(authorize_task(store, task["job_id"], authorization_ref="one-task-approval",
                authorized_ms=100, packet_fingerprint_value=source_packet["fingerprint"],
                max_calls=2, max_reserved_cost_usd="2")["status"], "authorized")
            activated_ms = 200_000  # far beyond max_request_age from preparation/data receipt
            activation = seal(store, task["request_id"], self._policy(), clock_ms=activated_ms)
            self.assertEqual(activation["status"], "sealed")
            adaptation = json.loads(store.connection.execute(
                "select packet_json from paper_research_packet_adaptations where request_id=?",
                (task["job_id"],)).fetchone()[0])
            self.assertTrue({"network", "address", "observations", "evidence_refs"}<=adaptation.keys())
            self.assertEqual(adaptation["schema_version"], "paper-diagnostic-research-v2")
            self.assertEqual(adaptation["prepared_ms"], 30)
            self.assertEqual(adaptation["activated_ms"], activated_ms)
            self.assertEqual(adaptation["data_available_ms"], 20)
            self.assertEqual(adaptation["data_age_ms_at_activation"], activated_ms-20)
            original = json.loads(store.connection.execute(
                "select packet_json from paper_research_jobs where request_id=?",
                (task["job_id"],)).fetchone()[0])
            self.assertEqual(original["schema_version"], "paper-outcome-research-v1")
            from tamtam_again.population_runtime import execute_job
            saved_adapted = adaptation
            response = self._runtime_response(task["job_id"], saved_adapted)
            with patch("tamtam_again.population_runtime.verify"), \
                 patch("tamtam_again.population_runtime.call", side_effect=response) as caller, \
                 patch("tamtam_again.population_runtime.now_ms", return_value=activated_ms+10):
                result = run(store, task["job_id"])
            self.assertEqual(caller.call_count, 2)
            self.assertEqual(result["status"], "hypothesis_recorded")
            self.assertEqual(request_count(store), 9)
            auth = store.connection.execute("select state,calls_started,reserved_cost_usd,actual_cost_usd,result_status "
                "from paper_research_task_authorizations where request_id=?", (task["job_id"],)).fetchone()
            self.assertEqual(tuple(auth), ("completed", 2, "2", None, "hypothesis_recorded"))
            final_route = route(store, task["job_id"], kind="paper")
            self.assertEqual(final_route["state"], "specification_required")
            self.assertEqual(final_route["supersedes_route_fingerprint"], __import__(
                "tamtam_again.engine", fromlist=["fingerprint"]).fingerprint(preparatory))
            self.assertEqual(route(store, task["job_id"], kind="paper"), final_route)
            self.assertEqual(store.connection.execute(
                "select route_json from population_hypothesis_routes where request_id=?",
                (task["job_id"],)).fetchone()[0], canonical(preparatory))
            self.assertEqual(store.connection.execute(
                "select count(*) from population_hypothesis_route_history where request_id=?",
                (task["job_id"],)).fetchone()[0], 1)
            self.assertEqual(route(store, task["job_id"], kind="paper"), final_route)
            self.assertEqual(store.connection.execute(
                "select count(*) from population_hypothesis_route_history where request_id=?",
                (task["job_id"],)).fetchone()[0], 1)
            with patch("tamtam_again.population_runtime.call") as caller:
                self.assertEqual(run(store, task["job_id"])["status"], "unchanged_no_inference")
            caller.assert_not_called()
            self.assertEqual(present_report(store, "s", "r", clock_ms=activated_ms+20)["job_id"], task["job_id"])
            self.assertEqual(store.connection.execute(
                "select count(*) from paper_outcome_packets where session_id='s' and report_id='r'").fetchone()[0], 1)
        finally:
            store.connection.close()
            tmp.cleanup()

    def test_integration_needs_data_and_no_budget_refusal_leave_handoff_dormant(self):
        tmp, store = self._runtime_fixture()
        try:
            task = present_report(store, "s", "r", clock_ms=30)
            old_route = route(store, task["job_id"], kind="paper")
            self.assertEqual(old_route["state"], "budget_required")
            store.connection.execute("create table population_research_jobs(request_id text primary key)")
            store.connection.executemany("insert into population_research_jobs values(?)",
                [(f"spent-{i}",) for i in range(8)])
            store.connection.commit()
            with patch("tamtam_again.population_runtime.call") as caller:
                refused = seal(store, task["request_id"], self._policy(), clock_ms=30+200_000)
            caller.assert_not_called()
            self.assertEqual(refused["status"], "budget_exhausted")
            self.assertEqual(store.connection.execute(
                "select status from paper_research_jobs where request_id=?", (task["job_id"],)).fetchone()[0],
                "budget_required")
            self.assertEqual(store.connection.execute(
                "select count(*) from paper_research_packet_adaptations").fetchone()[0], 0)
        finally:
            store.connection.close()
            tmp.cleanup()

    def test_integration_missing_data_response_creates_new_route_not_overwriting_preparation(self):
        from tamtam_again.paper_runtime import run
        from tamtam_again.engine import canonical
        tmp, store = self._runtime_fixture()
        try:
            task = present_report(store, "s", "r", clock_ms=30)
            preparatory = route(store, task["job_id"], kind="paper")
            activated_ms = 50_000
            self.assertEqual(seal(store, task["request_id"], self._policy(), clock_ms=activated_ms)["status"], "sealed")
            adapted = json.loads(store.connection.execute(
                "select packet_json from paper_research_packet_adaptations where request_id=?",
                (task["job_id"],)).fetchone()[0])
            response = self._runtime_response(task["job_id"], adapted, missing=True)
            with patch("tamtam_again.population_runtime.verify"), \
                 patch("tamtam_again.population_runtime.call", side_effect=response) as caller, \
                 patch("tamtam_again.population_runtime.now_ms", return_value=activated_ms+10):
                result = run(store, task["job_id"])
            self.assertEqual(caller.call_count, 1)
            self.assertEqual(result["status"], "needs_data")
            final_route = route(store, task["job_id"], kind="paper")
            self.assertEqual(final_route["state"], "needs_data")
            self.assertEqual(final_route["wake"]["kind"], "named_data")
            self.assertEqual(store.connection.execute(
                "select route_json from population_hypothesis_routes where request_id=?",
                (task["job_id"],)).fetchone()[0], canonical(preparatory))
            self.assertEqual(store.connection.execute(
                "select count(*) from population_hypothesis_route_history where request_id=?",
                (task["job_id"],)).fetchone()[0], 1)
        finally:
            store.connection.close()
            tmp.cleanup()

    def test_authorized_runtime_preflight_failure_is_persisted_and_never_retried(self):
        from tamtam_again.paper_runtime import run
        tmp, store = self._runtime_fixture()
        try:
            task = present_report(store, "s", "r", clock_ms=30)
            source_packet = json.loads(store.connection.execute(
                "select packet_json from paper_research_jobs where request_id=?", (task["job_id"],)).fetchone()[0])
            authorize_task(store, task["job_id"], authorization_ref="one-task-error-test",
                authorized_ms=40, packet_fingerprint_value=source_packet["fingerprint"],
                max_calls=2, max_reserved_cost_usd="2")
            self.assertEqual(seal(store, task["request_id"], self._policy(), clock_ms=50)["status"], "sealed")
            with patch("tamtam_again.population_runtime.now_ms", return_value=60), \
                 patch("tamtam_again.population_runtime.verify", side_effect=RuntimeError("probe failure")), \
                 patch("tamtam_again.population_runtime.call") as caller:
                failed = run(store, task["job_id"])
                replay = run(store, task["job_id"])
            caller.assert_not_called()
            self.assertEqual(failed["status"], "suspended")
            self.assertEqual(replay["status"], "unchanged_no_inference")
            authorization = store.connection.execute(
                "select state,calls_started,result_status from paper_research_task_authorizations where request_id=?",
                (task["job_id"],)).fetchone()
            self.assertEqual(tuple(authorization), ("completed", 0, "suspended"))
        finally:
            store.connection.close()
            tmp.cleanup()

    def test_subscription_authorization_uses_calls_tokens_duration_without_usd_reservation(self):
        tmp,store=self._runtime_fixture()
        try:
            task=present_report(store,'s','r',clock_ms=30)
            source=json.loads(store.connection.execute('select packet_json from paper_research_jobs where request_id=?',
                (task['job_id'],)).fetchone()[0])
            caps={'max_input_tokens_per_call':80000,'max_total_input_tokens':160000,
                'max_total_output_tokens':10000,'max_total_duration_ms':240000}
            authorized=authorize_task(store,task['job_id'],authorization_ref='subscription-task-approval',
                authorized_ms=40,packet_fingerprint_value=source['fingerprint'],max_calls=2,
                usage_mode='subscription',**caps)
            self.assertEqual(authorized['max_reserved_cost_usd'],None)
            auth=store.connection.execute('select usage_mode,max_calls,max_reserved_cost_usd,reserved_cost_usd from paper_research_task_authorizations where request_id=?',
                (task['job_id'],)).fetchone()
            self.assertEqual(tuple(auth),('subscription',2,'0',None))
            policy={**self._policy(),'usage_mode':'subscription','max_model_calls':2,**caps}
            policy.pop('call_reservation_usd')
            result=seal(store,task['request_id'],policy,clock_ms=50)
            self.assertEqual(result['status'],'sealed')
            job=store.connection.execute('select status,reserved_cost_usd from paper_research_jobs where request_id=?',
                (task['job_id'],)).fetchone()
            auth=store.connection.execute('select state,reserved_cost_usd from paper_research_task_authorizations where request_id=?',
                (task['job_id'],)).fetchone()
            self.assertEqual(tuple(job),('sealed',None))
            self.assertEqual(tuple(auth),('activated',None))
        finally:
            store.connection.close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()

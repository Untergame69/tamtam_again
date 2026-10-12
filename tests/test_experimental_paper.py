from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tamtam_again.experimental_paper import add_rectification, report_due, start as start_experimental, status
from tamtam_again.paper import paper_tick, retire_paper, start_paper
from tamtam_again.paper_adaptation import recover as recover_adaptation
from tamtam_again.engine import initial_state, reduce_event
from tamtam_again.recipe import synthetic_spec
from tamtam_again.storage import Store
from tamtam_again.validation import create_plan, evaluate, now_ms, register_variant
from tamtam_again.websocket import MAX_USER_SUBSCRIPTIONS, _subscriptions, _sync_account_subscriptions


ADDRESS = "0xa880d6cc607a05ea617307ab3b0d335e8d8424ee"


def real_plan():
    current = now_ms()
    return {
        "network": "hyperliquid-mainnet", "address": ADDRESS, "coin": "HYPE",
        "synthetic": False, "experiment_mode": "experimental_paper_only",
        "exploration": {"start_ms": current - 2_000, "end_ms": current - 1_000},
        "comparison": {"start_ms": current + 600_000, "end_ms": current + 86_400_000},
        "final": {"start_ms": current + 86_700_000, "end_ms": current + 172_500_000},
        "embargo_ms": 300_000, "isolation": "unavailable",
        "criteria": {"block_ms": 1_800_000, "min_blocks": 2, "min_regimes": 2,
            "max_positive_block_share": "0.8", "min_net_pnl": "0", "max_drawdown_usdc": "10",
            "min_block_lower_bound": "0", "stress_multiplier": "2", "min_stress_net_pnl": "0",
            "require_funding": True, "dependence_justification": "Exploratory paper only; no N1 inference.",
            "regime_threshold_bps": "10", "regime_window_ms": 60_000, "confidence_alpha": "0.05"},
        "budget": {"max_runs": 1, "max_same_input_corrections": 1,
            "max_duration_ms": 604_800_000, "max_cost_usd": "0"},
    }


def spec():
    result = synthetic_spec()
    result.update(market="HYPE", starting_capital_usdc="1000", latency_ms=5_000,
                  horizon_ms=120_000)
    result["sizing"]["scale"] = "0.001"
    result["max_exposure"].update(notional_usdc="100", max_drawdown_usdc="10", max_leverage="1")
    result["fees"].update(taker_bps="4.5")
    result["slippage"]["bps"] = "5"
    result["execution"].update(heartbeat_timeout_ms=65_000, unknown_quote_max_age_ms=1_000,
        order_ttl_ms=10_000, displayed_size_fraction="0.1",
        funding_interval_ms=3_600_000,
        market_rules={"version": 1, "instrument": "HYPE", "currency": "USDC",
            "available_ms": 0, "evidence_refs": ["fixture:meta", "fixture:lot-rules"],
            "sz_decimals": 2, "minimum_order_usdc": "10", "max_leverage": "10"})
    return result


def hypothesis():
    return {"schema_version": 1, "hypothesis_id": "a880-hype-live-delta-follow-v1",
        "observations": ["32,921 of 178,438 archived fills were HYPE in the incomplete 2026-10-07–11 sample.",
            "A lower-bound reconstruction found short observed flat-to-flat HYPE cycles; it does not identify the account's program."],
        "interpretation": "High turnover and short observed HYPE cycles motivate testing timely incremental flow; they do not establish directional predictability.",
        "claim": "After an a880 HYPE live fill is received, a small scaled position in that fill direction may persist for two minutes with positive simulated net PnL after costs.",
        "signal": "Only a non-snapshot userFills HYPE event after the active WebSocket subscription; use its signed size delta, never REST or the leader's entry price.",
        "entry": "Target the cumulative signed live HYPE fill delta scaled by 0.001, capped by a 100 USDC gross notional limit; quote and health must be causally current.",
        "exit": "Return to flat after 120 seconds from opening or when a later leader delta changes the target; no unobserved leader inventory is copied.",
        "execution": "Paper market IOC at received ask/bid plus 5 bps slippage, 4.5 bps taker fee, 5 second processing latency, 10% visible-size cap, 1 second quote age, 10 second order TTL, 2 decimal size precision and 10 USDC minimum.",
        "risk": {"starting_capital_usdc": "1000", "max_exposure_usdc": "100", "max_loss_usdc": "10",
            "max_leverage": "1", "no_live_orders": True, "economic_validation": False},
        "decision_rules": {"healthy_feed_and_within_limits": "continue",
            "missing_signal_or_continuity": "collect_data", "loss_limit_or_risk_halt": "abandon",
            "duration_end": "propose_new_version_after_review"},
        "evidence_refs": ["docs/continuous-research/economic-qualification-cards-20261012-g2.md#a880",
            "data:tamtam.sqlite3/raw_observations:userFillsByTime/a880/HYPE",
            "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size"],
        "review_interval_ms": 21_600_000, "max_duration_ms": 604_800_000}


class ExperimentalPaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "experiment.sqlite3"
        self.store = Store(self.db)
        plan = create_plan(self.store, real_plan())
        self.variant = register_variant(self.store, plan["plan_id"], spec())["variant_id"]

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_start_is_explicitly_experimental_and_never_evaluated(self):
        with self.assertRaisesRegex(ValueError, "N2 requires real passed N1"):
            start_paper(self.store, self.variant)
        started = start_experimental(self.store, self.variant, hypothesis())
        self.assertEqual(started["experiment_status"], "experimental_paper")
        self.assertFalse(started["economic_validation"])
        with self.assertRaisesRegex(ValueError, "not eligible for economic evaluation"):
            evaluate(self.store, self.variant, "exploration", [], provenance="local_archive")
        self.assertEqual(self.store.connection.execute("select count(*) from validation_evaluations").fetchone()[0], 0)
        state = status(self.store, started["session_id"])[0]
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["review_index"], 0)

    def test_automatic_report_records_specific_next_action(self):
        started = start_experimental(self.store, self.variant, hypothesis())
        run = self.store.connection.execute("select next_review_ms from paper_experimental_sessions where session_id=?",
                                            (started["session_id"],)).fetchone()
        session = self.store.connection.execute("select state_json from paper_sessions where session_id=?",
                                                (started["session_id"],)).fetchone()
        state = json.loads(session[0])
        state.update(connected=True, healthy_at_ms=run[0])
        self.store.connection.execute("update paper_sessions set state_json=? where session_id=?",
                                      (json.dumps(state), started["session_id"]))
        self.store.connection.commit()
        report = report_due(self.store, started["session_id"], clock_ms=run[0])
        self.assertEqual(report["report"]["next_action"], "collect_data")
        self.assertIn("non-snapshot HYPE fill", report["report"]["next_action_detail"])
        self.assertEqual(self.store.connection.execute("select count(*) from paper_experimental_reports").fetchone()[0], 1)

    def test_rectification_is_linked_append_only_and_preserves_original_report(self):
        started = start_experimental(self.store, self.variant, hypothesis())
        run = self.store.connection.execute("select next_review_ms from paper_experimental_sessions where session_id=?",
                                            (started["session_id"],)).fetchone()
        report = report_due(self.store, started["session_id"], clock_ms=run[0])
        original = self.store.connection.execute(
            "select report_json from paper_experimental_reports where report_id=?",(report["report_id"],)
        ).fetchone()[0]
        correction={"corrects_report_id":report["report_id"],"cause":"lot-rounded-zero adjustment",
                    "residual_position":"-0.31","final_round_trip_result":"unknown"}
        first=add_rectification(self.store,report["report_id"],correction)
        second=add_rectification(self.store,report["report_id"],correction)
        self.assertEqual(first["rectification_id"],second["rectification_id"])
        self.assertEqual(first["corrects_report_id"],report["report_id"])
        self.assertEqual(self.store.connection.execute(
            "select report_json from paper_experimental_reports where report_id=?",(report["report_id"],)
        ).fetchone()[0],original)
        self.assertEqual(self.store.connection.execute(
            "select count(*) from paper_experimental_rectifications where corrects_report_id=?",(report["report_id"],)
        ).fetchone()[0],1)

    def test_initial_subscription_grace_is_an_explicit_wait_not_a_false_suspension(self):
        started = start_experimental(self.store, self.variant, hypothesis())
        result = paper_tick(self.store, started["session_id"])
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["waiting_for"], ["awaiting_initial_live_websocket_heartbeat"])

    def test_retired_flat_experiment_restarts_only_with_reason_and_new_ledger(self):
        first = start_experimental(self.store, self.variant, hypothesis())
        self.store.connection.execute("update paper_sessions set status='suspended' where session_id=?",
                                      (first["session_id"],))
        self.store.connection.commit()
        retire_paper(self.store, first["session_id"], reason="Preserve interrupted flat session")
        with self.assertRaisesRegex(ValueError, "explicit reason"):
            start_experimental(self.store, self.variant, hypothesis())
        second = start_experimental(self.store, self.variant, hypothesis(),
                                    restart_reason="Fresh prospective episode after collector stream interruption; prior flat ledger retained")
        self.assertNotEqual(second["session_id"], first["session_id"])
        state = self.store.connection.execute("select state_json from paper_sessions where session_id=?",
                                              (second["session_id"],)).fetchone()
        self.assertEqual(json.loads(state[0])["position"], "0")
        policy = self.store.connection.execute("select restart_reason from paper_session_policy where session_id=?",
                                               (second["session_id"],)).fetchone()
        self.assertIn("prior flat ledger retained", policy[0])

    def test_feed_failure_suspends_with_experiment_report_and_never_queues_ai(self):
        started = start_experimental(self.store, self.variant, hypothesis())
        cutoff = started["started_ms"] + 181_000
        with patch("tamtam_again.paper.now_ms", return_value=cutoff):
            result = paper_tick(self.store, started["session_id"])
        self.assertEqual(result["status"], "suspended")
        self.assertEqual(recover_adaptation(self.store, clock_ms=cutoff), [])
        self.assertEqual(self.store.connection.execute("select count(*) from paper_adaptation_requests").fetchone()[0], 0)
        report = report_due(self.store, started["session_id"], clock_ms=cutoff)
        self.assertEqual(report["report"]["next_action"], "collect_data")

    def test_under_minimum_order_is_an_explicit_nonexecution(self):
        strategy = spec()
        state = initial_state(strategy)
        events = [
            {"id":"conn","kind":"connection","event_ms":1_000,"received_ms":1_000,
             "session":"s1","connected":True},
            {"id":"bbo","kind":"bbo","event_ms":1_010,"received_ms":1_010,
             "session":"s1","bid":"100","ask":"100.1","bid_size":"100","ask_size":"100"},
            {"id":"hb","kind":"heartbeat","event_ms":1_020,"received_ms":1_020,"session":"s1"},
            {"id":"fill","kind":"leader_fill","event_ms":1_030,"received_ms":1_030,
             "session":"s1","is_snapshot":False,"delta":"10"},
            {"id":"timer","kind":"timer","event_ms":6_031,"received_ms":6_031},
        ]
        for event in events:
            reduce_event(state, strategy, event)
        self.assertEqual(state["nonexecution_reasons"]["below_venue_minimum_order_value"], 1)
        self.assertEqual(state["fills"], [])

    def test_position_horizon_crossing_funding_boundary_is_not_entered(self):
        strategy = spec()
        state = initial_state(strategy)
        base = 3_598_000
        for event in [
            {"id":"conn-hour","kind":"connection","event_ms":base,"received_ms":base,
             "session":"hour","connected":True},
            {"id":"bbo-hour","kind":"bbo","event_ms":base+10,"received_ms":base+10,
             "session":"hour","bid":"100","ask":"100.1","bid_size":"100","ask_size":"100"},
            {"id":"hb-hour","kind":"heartbeat","event_ms":base+20,"received_ms":base+20,"session":"hour"},
            {"id":"fill-hour","kind":"leader_fill","event_ms":3_599_000,"received_ms":3_599_000,
             "session":"hour","is_snapshot":False,"delta":"100"},
        ]:
            reduce_event(state, strategy, event)
        self.assertEqual(state["nonexecution_reasons"]["position_horizon_overlaps_funding_boundary"], 1)
        self.assertEqual(state["leader_target"], "0")
        self.assertEqual(state["pending"], [])

    def test_initial_stream_can_rebind_before_any_signal_only(self):
        strategy = spec()
        state = initial_state(strategy)
        state["experimental_initial_feed"] = True
        for event in [
            {"id":"old","kind":"connection","event_ms":1_000,"received_ms":1_000,
             "session":"s0","connected":True},
            {"id":"drop","kind":"connection","event_ms":1_100,"received_ms":1_100,
             "session":"s0","connected":False},
            {"id":"new","kind":"heartbeat","event_ms":1_200,"received_ms":1_200,
             "session":"s1"},
        ]:
            reduce_event(state, strategy, event)
        self.assertTrue(state["connected"])
        self.assertEqual(state["session"], "s1")
        self.assertNotIn("connection_interrupted", state["diagnostics"])
        self.assertNotIn("connection_changed_without_reconciliation", state["diagnostics"])
        self.assertIn("initial_stream_reconnected_before_signal", state["wait_conditions"])

        for event in [
            {"id":"quote","kind":"bbo","event_ms":1_210,"received_ms":1_210,
             "session":"s1","bid":"100","ask":"100.1","bid_size":"100","ask_size":"100"},
            {"id":"health","kind":"heartbeat","event_ms":1_220,"received_ms":1_220,"session":"s1"},
            {"id":"signal","kind":"leader_fill","event_ms":1_230,"received_ms":1_230,
             "session":"s1","is_snapshot":False,"delta":"1000"},
            {"id":"execute","kind":"timer","event_ms":6_231,"received_ms":6_231},
            {"id":"later-rebind","kind":"heartbeat","event_ms":6_240,"received_ms":6_240,"session":"s2"},
        ]:
            reduce_event(state, strategy, event)
        self.assertGreater(state["signals_received"], 0)
        self.assertTrue(state["fills"])
        self.assertFalse(state["experimental_initial_feed"])
        self.assertIn("connection_changed_without_reconciliation", state["diagnostics"])

    def test_paper_subscription_uses_existing_account_cap_and_prioritizes_experiment(self):
        for i in range(MAX_USER_SUBSCRIPTIONS):
            address = f"0x{i+1:040x}"
            self.store.add_candidate("hyperliquid-mainnet", address, "fixture")
            self.store.connection.execute("update candidates set status='tracked' where address=?", (address,))
        self.store.add_candidate("hyperliquid-mainnet", ADDRESS, "fixture")
        started = start_experimental(self.store, self.variant, hypothesis())
        accounts, markets, depth = _subscriptions(self.store, "hyperliquid-mainnet", 2, 1)
        self.assertEqual(len(accounts), MAX_USER_SUBSCRIPTIONS)
        self.assertEqual(accounts[0], ADDRESS)
        self.assertEqual(markets[0], "HYPE")
        self.assertEqual(len(depth), 1)
        self.assertEqual(self.store.connection.execute("select count(*) from validation_evaluations").fetchone()[0], 0)

    def test_account_slot_is_released_before_new_user_is_subscribed(self):
        previous=[f"0x{i+1:040x}" for i in range(MAX_USER_SUBSCRIPTIONS)]
        current=[ADDRESS,*previous[:-1]]
        active={json.dumps({"type":kind,"user":address},sort_keys=True,separators=(",",":"))
                for address in previous for kind in ("userFills","userFundings")}
        class FakeSocket:
            def __init__(self):
                self.users=set(previous)
                self.max_users=len(self.users)
            def send(self,raw):
                message=json.loads(raw);sub=message["subscription"];address=sub["user"]
                if message["method"]=="unsubscribe":
                    active.discard(json.dumps(sub,sort_keys=True,separators=(",",":")))
                else:
                    active.add(json.dumps(sub,sort_keys=True,separators=(",",":")))
                self.users={json.loads(item)["user"] for item in active}
                self.max_users=max(self.max_users,len(self.users))
        socket=FakeSocket();times={}
        _sync_account_subscriptions(socket,previous,current,active,times)
        self.assertLessEqual(socket.max_users,MAX_USER_SUBSCRIPTIONS)
        self.assertEqual(len(socket.users),MAX_USER_SUBSCRIPTIONS)
        self.assertIn(ADDRESS,socket.users)
        self.assertNotIn(previous[-1],socket.users)
        self.assertIn(ADDRESS,times)


if __name__ == "__main__":
    unittest.main()

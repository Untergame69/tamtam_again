from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tamtam_again.analysis import _pair_maturity
from tamtam_again.engine import initial_state, number, quote_status, reduce_event, replay, validate_spec
from tamtam_again.paper import archive_events, paper_tick, start_paper
from tamtam_again.providers.hyperliquid import Page, retained_recent_windows
from tamtam_again.recipe import synthetic_events, synthetic_plan, synthetic_spec, run_recipe
from tamtam_again.storage import Store, decode_observation_payload
from tamtam_again.validation import create_plan, evaluate, initialize, register_variant
from tamtam_again.workflow import complete_paper, workflow_tick


class EngineTests(unittest.TestCase):
    def test_future_quote_and_out_of_order_receipt_rejected(self):
        spec = synthetic_spec()
        state = initial_state(spec)
        with self.assertRaises(ValueError):
            reduce_event(state,spec,{"id":"future","kind":"timer","event_ms":2,"received_ms":1})
        reduce_event(state,spec,{"id":"now","kind":"timer","event_ms":5,"received_ms":5})
        with self.assertRaises(ValueError):
            reduce_event(state,spec,{"id":"past","kind":"timer","event_ms":4,"received_ms":4})

    def test_old_unchanged_bbo_valid_with_heartbeat_but_disconnect_invalidates(self):
        spec = synthetic_spec()
        state = initial_state(spec)
        for e in synthetic_events(1000)[:2]:
            reduce_event(state,spec,e)
        reduce_event(state,spec,{"id":"pong","kind":"heartbeat","session":"fixture-session","event_ms":9000,"received_ms":9000})
        self.assertEqual(quote_status(state,9001,spec["execution"]),"continuous")
        reduce_event(state,spec,{"id":"down","kind":"connection","session":"fixture-session","connected":False,"event_ms":9002,"received_ms":9002})
        self.assertEqual(quote_status(state,9003,spec["execution"]),"interrupted")

    def test_no_future_leader_variables_in_autonomous_contract(self):
        spec = synthetic_spec()
        spec["type"] = "autonomous"
        with self.assertRaises(ValueError):
            validate_spec(spec)

    def test_same_ms_quote_not_available_for_execution(self):
        spec = synthetic_spec()
        events = synthetic_events(1000)[:2]
        state = initial_state(spec)
        for e in events:
            reduce_event(state,spec,e)
        reduce_event(state,spec,{"id":"signal","kind":"leader_fill","is_snapshot":False,"delta":"1","event_ms":1010,"received_ms":1010})
        reduce_event(state,spec,{"id":"timer","kind":"timer","event_ms":1011,"received_ms":1011})
        self.assertEqual(len(state["fills"]),1)  # available only one ms later
        self.assertGreater(number(state["fills"][0]["price"]),number("100.1"))

    def test_processing_availability_is_not_backdated_to_receipt(self):
        spec = synthetic_spec()
        state = initial_state(spec)
        for event in synthetic_events(1000)[:2]:
            reduce_event(state,spec,event)
        reduce_event(state,spec,{"id":"delayed","kind":"leader_fill","event_ms":1020,"received_ms":1020,"available_ms":2000,"is_snapshot":False,"delta":"1"})
        self.assertEqual(state["pending"][0]["due_ms"],2001)
        self.assertEqual(state["processing_lags_ms"][-1],980)
        self.assertEqual(state["fills"],[])

    def test_autonomous_momentum_uses_only_past_received_quotes(self):
        spec = synthetic_spec()
        spec["type"] = "autonomous"
        spec["data_sources"] = ["bbo","streamHealth"]
        spec["signal"] = {"kind":"momentum","lookback_ms":50,"threshold_bps":"10"}
        spec["sizing"]["units"] = "1"
        state = initial_state(spec)
        events = synthetic_events(1000)
        for event in [events[0],events[1],events[5]]:
            reduce_event(state,spec,event)
        self.assertEqual(state["pending"][0]["target"],"1")
        before = deepcopy(state)
        reduce_event(state,spec,{"id":"leader_ignored","kind":"leader_fill","is_snapshot":False,"delta":"1000","event_ms":1100,"received_ms":1100})
        self.assertEqual(state["pending"],before["pending"])

    def test_per_unit_settled_funding_uses_our_size(self):
        spec = synthetic_spec()
        events = synthetic_events(1000)[:5]
        events.append({"id":"settled","kind":"funding","event_ms":1040,"received_ms":1050,"unit_funding_usdc":"-0.5"})
        result = replay(spec,events,block_ms=1000)
        self.assertEqual(number(result["state"]["funding"]),number("-0.5"))

    def test_quote_touched_does_not_fill_passive(self):
        spec = synthetic_spec()
        spec["execution"]["kind"] = "passive_conservative"
        result = replay(spec,synthetic_events(1000),block_ms=1000)
        self.assertEqual(result["metrics"]["fills"],0)
        self.assertGreater(result["metrics"]["missed_orders"],0)

    def test_partial_execution_uses_displayed_size_fraction(self):
        events = synthetic_events(1000)
        for e in events:
            if e["kind"] == "bbo":
                e["ask_size"] = e["bid_size"] = "0.5"
        result = replay(synthetic_spec(),events,block_ms=1000)
        self.assertGreater(result["metrics"]["partial_orders"],0)
        self.assertEqual(result["state"]["fills"][0]["size"],"0.25")
        self.assertTrue(result["metrics"]["flat_end"])

    def test_costs_reduce_pnl_and_perp_cash_reconciles(self):
        spec = synthetic_spec()
        result = replay(spec,synthetic_events(1000),block_ms=1000)
        state = result["state"]
        self.assertEqual(number(state["cash"]),number(spec["starting_capital_usdc"])+number(state["realized_pnl"])-number(state["fees"])+number(state["funding"]))
        stress = replay(spec,synthetic_events(1000),block_ms=1000,stress=2)
        self.assertLess(number(stress["metrics"]["net_pnl"]),number(result["metrics"]["net_pnl"]))

    def test_funding_applies_to_our_effective_position_not_leader_payment(self):
        spec = synthetic_spec()
        events = synthetic_events(1000)[:5]
        events.append({"id":"funding","kind":"funding","event_ms":1040,"received_ms":1050,"mark":"100","rate":"0.01"})
        result = replay(spec,events,block_ms=1000)
        self.assertEqual(number(result["state"]["funding"]),number("-1"))

    def test_risk_limit_halts_new_exposure(self):
        spec = synthetic_spec()
        spec["max_exposure"]["max_drawdown_usdc"] = "0.01"
        result = replay(spec,synthetic_events(1000),block_ms=1000)
        self.assertTrue(result["state"]["risk_halted"])
        self.assertIn("risk_drawdown_limit",result["metrics"]["diagnostics"])

    def test_duplicate_events_do_not_duplicate_pnl(self):
        events = synthetic_events(1000)
        a = replay(synthetic_spec(),events,block_ms=1000)
        b = replay(synthetic_spec(),events+events,block_ms=1000)
        self.assertEqual(a["state"],b["state"])


class RegistryTests(unittest.TestCase):
    def test_predeclared_handover_preserves_old_session_and_is_idempotent(self):
        self.evaluate('comparison');self.evaluate('final')
        with patch('tamtam_again.paper.now_ms',return_value=1000):
            first=start_paper(self.store,self.variant,synthetic_recipe=True)
        plan=synthetic_plan()
        for stage in ('exploration','comparison','final'):
            for bound in ('start_ms','end_ms'):plan[stage][bound]+=100000
        plan['paper_replacement']={'version':'suspended-flat-handover-v1',
            'predecessor_variant_id':self.variant,'minimum_session_age_ms':500,
            'justification':'fixture replacement following prospective validation'}
        new_plan=create_plan(self.store,plan)
        target=register_variant(self.store,new_plan['plan_id'],synthetic_spec())['variant_id']
        for stage in ('comparison','final'):
            self.assertEqual(evaluate(self.store,target,stage,synthetic_events(plan[stage]['start_ms']),provenance='synthetic')['status'],'passed')
        self.store.connection.execute("update paper_sessions set status='suspended' where session_id=?",(first['session_id'],))
        self.store.connection.commit()
        with patch('tamtam_again.paper.now_ms',return_value=1499):
            with self.assertRaises(ValueError):start_paper(self.store,target,synthetic_recipe=True)
        before=self.store.connection.execute('select state_json from paper_sessions where session_id=?',(first['session_id'],)).fetchone()[0]
        opened=json.loads(before);opened['position']='1'
        self.store.connection.execute('update paper_sessions set state_json=? where session_id=?',(json.dumps(opened),first['session_id']));self.store.connection.commit()
        with patch('tamtam_again.paper.now_ms',return_value=1500):
            with self.assertRaises(ValueError):start_paper(self.store,target,synthetic_recipe=True)
        self.assertEqual(self.store.connection.execute('select count(*) from paper_retirements').fetchone()[0],0)
        self.store.connection.execute('update paper_sessions set state_json=? where session_id=?',(before,first['session_id']));self.store.connection.commit()
        self.store.connection.execute("create trigger fixture_handover_failure before insert on paper_sessions begin select raise(abort,'fixture incident'); end")
        self.store.connection.commit()
        import sqlite3
        with patch('tamtam_again.paper.now_ms',return_value=1500):
            with self.assertRaises(sqlite3.IntegrityError):start_paper(self.store,target,synthetic_recipe=True)
        self.assertEqual(self.store.connection.execute('select status from paper_sessions where session_id=?',(first['session_id'],)).fetchone()[0],'suspended')
        self.assertEqual(self.store.connection.execute('select count(*) from paper_retirements').fetchone()[0],0)
        self.store.connection.execute('drop trigger fixture_handover_failure');self.store.connection.commit()
        with patch('tamtam_again.paper.now_ms',return_value=1500):
            new=start_paper(self.store,target,synthetic_recipe=True)
            self.assertEqual(start_paper(self.store,target,synthetic_recipe=True)['session_id'],new['session_id'])
        old=self.store.connection.execute('select status,state_json from paper_sessions where session_id=?',(first['session_id'],)).fetchone()
        self.assertEqual(old['status'],'retired');self.assertEqual(old['state_json'],before)
        self.assertEqual(self.store.connection.execute('select count(*) from paper_handovers').fetchone()[0],1)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name)/"test.sqlite3")
        self.plan = create_plan(self.store,synthetic_plan())
        self.variant = register_variant(self.store,self.plan["plan_id"],synthetic_spec())["variant_id"]

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def evaluate(self,stage,events=None):
        return evaluate(self.store,self.variant,stage,events or synthetic_events(synthetic_plan()[stage]["start_ms"]),provenance="synthetic")

    def test_requires_comparison_before_final(self):
        with self.assertRaises(ValueError):
            self.evaluate("final")

    def test_no_cross_boundary_feature_or_position_windows(self):
        spec = synthetic_spec()
        spec["horizon_ms"] = 1001
        with self.assertRaises(ValueError):
            register_variant(self.store,self.plan["plan_id"],spec)
        events = synthetic_events(20000)
        events[1]["event_ms"] = 15999
        self.evaluate("comparison")
        with self.assertRaises(ValueError):
            self.evaluate("final",events)

    def test_final_idempotent_and_changed_input_cannot_reuse_period(self):
        self.evaluate("comparison")
        first = self.evaluate("final")
        self.assertEqual(first,self.evaluate("final"))
        changed = synthetic_events(20000)
        changed[1]["ask_size"] = "99"
        with self.assertRaises(ValueError):
            self.evaluate("final",changed)
        spec = synthetic_spec()
        spec["slippage"]["bps"] = "2"
        new = register_variant(self.store,self.plan["plan_id"],spec)["variant_id"]
        evaluate(self.store,new,"comparison",synthetic_events(10000),provenance="synthetic")
        with self.assertRaises(ValueError):
            evaluate(self.store,new,"final",synthetic_events(20000),provenance="synthetic")

    def test_error_consumes_final_before_computation(self):
        self.evaluate("comparison")
        with patch("tamtam_again.validation.replay",side_effect=ValueError("broken")):
            with self.assertRaises(ValueError):
                self.evaluate("final")
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM consumed_holdouts").fetchone()[0],1)
        error_event=self.store.connection.execute("select t.evaluation_id,t.available_ms from evaluation_terminal_events t join validation_evaluations e using(evaluation_id) where e.stage='final' and t.status='error'").fetchone()
        self.assertIsNotNone(error_event)
        self.assertEqual(self.evaluate("final")["status"],"error")
        self.assertEqual(self.store.connection.execute('select available_ms from evaluation_terminal_events where evaluation_id=?',(error_event[0],)).fetchone()[0],error_event[1])

    def test_synthetic_fixture_cannot_promote_real_n2(self):
        self.evaluate("comparison")
        result = self.evaluate("final")
        self.assertTrue(result["synthetic"])
        self.assertFalse(result["promotable"])
        with self.assertRaises(ValueError):
            start_paper(self.store,self.variant)
        session = start_paper(self.store,self.variant,synthetic_recipe=True)
        with self.assertRaises(ValueError):
            paper_tick(self.store,session["session_id"])

    def test_paper_restart_requires_flat_retirement_and_preserves_ledger(self):
        from tamtam_again.paper import retire_paper
        self.evaluate("comparison");self.evaluate("final")
        first=start_paper(self.store,self.variant,synthetic_recipe=True)
        row=self.store.connection.execute('select state_json from paper_sessions where session_id=?',(first['session_id'],)).fetchone()
        state=json.loads(row[0]);state['position']='1'
        self.store.connection.execute("update paper_sessions set status='suspended',state_json=? where session_id=?",(json.dumps(state),first['session_id']));self.store.connection.commit()
        with self.assertRaises(ValueError):start_paper(self.store,self.variant,synthetic_recipe=True)
        with self.assertRaises(ValueError):retire_paper(self.store,first['session_id'],reason='fixture switch')
        state['position']='0';state['cash']='97'
        self.store.connection.execute('update paper_sessions set state_json=? where session_id=?',(json.dumps(state),first['session_id']));self.store.connection.commit()
        with self.assertRaises(ValueError):start_paper(self.store,self.variant,synthetic_recipe=True)
        retire_paper(self.store,first['session_id'],reason='fixture flat retirement')
        second=start_paper(self.store,self.variant,synthetic_recipe=True,restart_reason='fixture explicit restart')
        self.assertNotEqual(first['session_id'],second['session_id'])
        old=self.store.connection.execute('select state_json from paper_sessions where session_id=?',(first['session_id'],)).fetchone()
        self.assertEqual(json.loads(old[0])['cash'],'97')

    def test_suspension_is_journaled_with_state_atomically(self):
        from tamtam_again.validation import get_variant
        from tamtam_again.procedure_trace import registry_trace
        self.evaluate('comparison');self.evaluate('final')
        with patch('tamtam_again.paper.now_ms',return_value=900):
            session=start_paper(self.store,self.variant,synthetic_recipe=True)
        row,spec,plan=get_variant(self.store,self.variant)
        # Exercise the real scheduler branch without allowing any archive reads.
        row={**dict(row),'synthetic':False}
        plan={**plan,'paper_monitoring':{'version':'paper-loss-budget-v1',
            'max_net_loss_usdc':'5','justification':'fixture risk budget'}}
        with patch('tamtam_again.paper.get_variant',return_value=(row,spec,plan)), \
             patch('tamtam_again.paper.archive_events',return_value=([],0)), \
             patch('tamtam_again.paper.metrics',return_value={'net_pnl':'-5'}), \
             patch('tamtam_again.paper.now_ms',return_value=1000):
            result=paper_tick(self.store,session['session_id'])
        self.assertEqual(result['status'],'suspended')
        journal=self.store.connection.execute('select * from paper_suspensions').fetchone()
        self.assertEqual(journal['suspended_ms'],1000)
        self.assertIn('missing_live_heartbeat',journal['diagnostics_json'])
        self.assertIn('paper_net_loss_budget_exhausted',journal['diagnostics_json'])
        snapshots=self.store.connection.execute('select available_ms,metrics_json from paper_snapshots order by available_ms').fetchall()
        self.assertEqual([r['available_ms'] for r in snapshots],[900,1000])
        self.assertEqual(json.loads(snapshots[-1]['metrics_json'])['net_pnl'],'-5')
        self.assertNotIn('paper_session_suspended',[e['kind'] for e in registry_trace(self.store,as_of_ms=999)['events']])
        self.assertIn('paper_session_suspended',[e['kind'] for e in registry_trace(self.store,as_of_ms=1000)['events']])
        from tamtam_again.paper import synthetic_recipe_tick
        with self.assertRaises(ValueError):synthetic_recipe_tick(self.store,session['session_id'],[])

    def test_negative_cost_edge_rejected(self):
        spec = synthetic_spec()
        spec["fees"]["taker_bps"] = "500"
        variant = register_variant(self.store,self.plan["plan_id"],spec)["variant_id"]
        result = evaluate(self.store,variant,"comparison",synthetic_events(10000),provenance="synthetic")
        self.assertIn("net_edge_after_costs",result["failures"])
        self.assertEqual(result["status"],"failed")

    def test_prospective_real_plan_required(self):
        plan = synthetic_plan()
        plan["synthetic"] = False
        with self.assertRaises(ValueError):
            create_plan(self.store,plan)

    def test_iteration_budget_enforced(self):
        plan = synthetic_plan()
        plan["budget"]["max_runs"] = 1
        record = create_plan(self.store,plan)
        spec = synthetic_spec()
        variant = register_variant(self.store,record["plan_id"],spec)["variant_id"]
        evaluate(self.store,variant,"exploration",synthetic_events(1000),provenance="synthetic")
        with self.assertRaises(ValueError):
            evaluate(self.store,variant,"comparison",synthetic_events(10000),provenance="synthetic")

    def test_no_legacy_textual_paper_promotion(self):
        with self.assertRaises(ValueError):
            complete_paper(self.store,"run",Path("missing.json"))

    def test_unisolated_agents_do_not_receive_new_or_queued_runs(self):
        with patch("tamtam_again.workflow.cohort_research_status",return_value={"accounts":[]}):
            for _ in range(2):
                result = workflow_tick(self.store,"synthetic")
                self.assertEqual(result["pending"],[])
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM automation_runs").fetchone()[0],0)


class QualityTests(unittest.TestCase):
    def test_retention_unknown_prefix_does_not_discard_recent_suffix(self):
        pages = [Page("userFillsByTime",{"type":"userFillsByTime"},[{"time":100,"startPosition":"2"}],0,200,True,200)]
        result = retained_recent_windows(pages,0)
        self.assertFalse(result[0].complete)
        self.assertEqual(result[0].end_ms,99)
        self.assertTrue(result[1].complete)
        self.assertEqual(result[1].start_ms,100)

    def test_nonzero_baseline_is_separate_from_portfolio_pnl(self):
        fills = [{"coin":"BTC","time":100,"tid":1,"oid":1,"dir":"Open Long","side":"B","sz":"1","px":"100","fee":"0","closedPnl":"0","startPosition":"2"},
                 {"coin":"BTC","time":200,"tid":2,"oid":2,"dir":"Close Long","side":"A","sz":"1","px":"101","fee":"0","closedPnl":"1","startPosition":"3"}]
        result = _pair_maturity(fills,"BTC",[100,200],[(100,200)],False,1)
        cycle = result["exploitable_cycle_summaries"][0]
        self.assertEqual(cycle["cycle_kind"],"baseline_excursion")
        self.assertEqual(cycle["ending_position"],"2")
        self.assertEqual(result["flat_to_flat_cycles_with_complete_context"],0)
        self.assertFalse(result["validation_is_statistical_proof"])

    def test_recent_window_valid_despite_old_history_gap(self):
        fills = [{"coin":"BTC","time":100,"tid":1,"oid":1,"dir":"Open Long","side":"B","sz":"1","px":"100","fee":"0","closedPnl":"0","startPosition":"0"},
                 {"coin":"BTC","time":200,"tid":2,"oid":2,"dir":"Close Long","side":"A","sz":"1","px":"101","fee":"0","closedPnl":"1","startPosition":"1"}]
        result = _pair_maturity(fills,"BTC",[100,200],[(100,200)],False,1)
        self.assertTrue(result["hypothesis_gate_ready"])
        self.assertFalse(result["account_history_complete_at_collection"])

    def test_continuity_matures_cycles_without_recent_bbo_change(self):
        fills = [{"coin":"BTC","time":10000,"tid":1,"oid":1,"dir":"Open Long","side":"B","sz":"1","px":"100","fee":"0","closedPnl":"0","startPosition":"0"},
                 {"coin":"BTC","time":20000,"tid":2,"oid":2,"dir":"Close Long","side":"A","sz":"1","px":"101","fee":"0","closedPnl":"1","startPosition":"1"}]
        result = _pair_maturity(fills,"BTC",[1],[(10000,20000)],True,1,continuity_times=[10000,20000])
        self.assertTrue(result["hypothesis_gate_ready"])
        self.assertEqual(result["closing_fills_with_bbo_within_1s"],0)

    def test_archive_excludes_snapshots_and_future_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            with Store(Path(directory)/"a.sqlite3") as store:
                for flag,tid in ((True,1),(False,2)):
                    with patch("tamtam_again.storage.utc_now",return_value="1970-01-01T00:00:01.100+00:00"):
                        store.save_observation(network="net",source="hyperliquid-websocket-v1",entity_type="account",entity_id="account",endpoint="userFills",
                        payload={"data":{"isSnapshot":flag,"fills":[{"coin":"BTC","time":1000,"tid":tid,"side":"B","sz":"1"}]}},requested_at="1970-01-01T00:00:01.100+00:00")
                events,_ = archive_events(store,"net","account","BTC",1000,2000)
                self.assertEqual(len(events),1)
                self.assertEqual(events[0]["id"],"leader:BTC:1000:2")

    def test_availability_after_window_cannot_enter_archive_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            with Store(Path(directory)/"availability.sqlite3") as store:
                with patch("tamtam_again.storage.utc_now",return_value="1970-01-01T00:00:03.000+00:00"):
                    store.save_observation(network="net",source="hyperliquid-websocket-v1",entity_type="account",entity_id="account",endpoint="userFills",payload={"data":{"isSnapshot":False,"fills":[{"coin":"BTC","time":1000,"tid":1,"side":"B","sz":"1"}]}},requested_at="1970-01-01T00:00:01.100+00:00")
                events,_ = archive_events(store,"net","account","BTC",1000,2000)
                self.assertEqual(events,[])

    def test_recipe_cannot_validate_real_strategy(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_recipe(Path(directory))
            self.assertFalse(report["real_strategy_validated"])
            self.assertTrue(all(stage["status"] == "passed" for stage in report["stages"]))
            self.assertEqual(report["paper_metrics"]["fills"],8)


if __name__ == "__main__":
    unittest.main()

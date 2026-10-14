import json
import tempfile
import unittest
from pathlib import Path

from tamtam_again.eth_prospective_observation import (
    VERSION, _action, _measure, init, tick,
)
from tamtam_again.storage import Store


class FakeInfo:
    def __init__(self, response=None):
        self.response = [] if response is None else response
        self.calls = []

    def post_info(self, payload):
        self.calls.append(payload)
        return self.response


def protocol(start=1_000_000):
    value={"protocol_id":"fixture-eth-24h","version":VERSION,"network":"hyperliquid-mainnet",
        "address":"0x67f7aa8fb95c47e6ea9c517b623e0701cbf9d9ba","market":"ETH",
        "start_ms":start,"checkpoint_ms":start+21_600_000,"end_ms":start+86_400_000,
        "poll_interval_ms":300_000,"horizon_ms":60_000,"prefill_age_ms":1_000,"target_overshoot_ms":5_000}
    return value


class EthProspectiveObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"observer.sqlite3"
        self.store=Store(self.path)
        self.p=protocol()

    def tearDown(self):
        self.store.close();self.tmp.cleanup()

    def test_strict_prior_and_post_receipt_are_separate_and_inversion_is_split(self):
        fill={"tid":"invert","time":1_000,"side":"B","sz":"1.5","startPosition":"-1",
            "crossed":True,"px":"101","fee":"0.1","feeToken":"USDC",
            "fill_page_observation_id":9,"fill_page_sha256":"page","fill_page_received_at":"1970-01-01T00:00:02.000+00:00",
            "fill_page_requested_at":"1970-01-01T00:00:01.500+00:00",
            "fill_page_archived_at":"1970-01-01T00:00:02.010+00:00"}
        prior={"event_ms":900,"received_ms":950,"archived_ms":960,"bid":"99","bid_size":"2","ask":"101","ask_size":"3","channel":"bbo","connection_id":"c1","observation_id":1,"sha256":"a","event_index":0}
        equal={**prior,"event_ms":1_000,"observation_id":2}
        future={**prior,"event_ms":61_000,"received_ms":62_001,"archived_ms":62_100,"bid":"101","ask":"103","observation_id":3,"sha256":"b"}
        post={**prior,"event_ms":62_010,"received_ms":62_010,"archived_ms":62_050,"bid":"102","ask":"104","observation_id":4,"sha256":"d"}
        rows=_measure([fill],[prior,equal,future,post],70_000)
        r=rows[0]
        self.assertEqual(_action(fill),("inverts",1.0,0.5))
        self.assertEqual(r["prefill_quote"]["event_ms"],900)
        self.assertIsNotNone(r["event_time_markout_60s_bps"])
        self.assertIsNotNone(r["post_receipt_markout_60s_bps"])
        self.assertNotEqual(r["future_quote"]["ref"],r["receipt_future_quote_ref"])
        late={**prior,"event_ms":850,"received_ms":62_000,"archived_ms":62_050,"observation_id":5,"sha256":"late"}
        delayed=_measure([fill],[prior,late],70_000)[0]
        self.assertIsNone(delayed["post_receipt_markout_60s_bps"])

    def test_polls_are_bounded_durable_and_replay_does_not_call_again(self):
        client=FakeInfo([])
        first=tick(self.store,self.p,info=client,now=self.p["start_ms"]+1)
        self.assertEqual(first["status"],"observing")
        self.assertEqual(first["poll"]["status"],"complete")
        self.assertEqual(len(client.calls),1)
        self.store.close();self.store=Store(self.path)
        replay=tick(self.store,self.p,info=client,now=self.p["start_ms"]+30_000)
        self.assertEqual(replay["status"],"observing")
        self.assertIsNone(replay["poll"])
        self.assertEqual(len(client.calls),1)
        row=self.store.connection.execute("select protocol_fingerprint,status from eth_observation_runs where protocol_id=?",
            (self.p["protocol_id"],)).fetchone()
        self.assertEqual(row["status"],"observing")

    def test_checkpoint_and_final_persist_even_when_data_insufficient(self):
        client=FakeInfo([])
        tick(self.store,self.p,info=client,now=self.p["start_ms"])
        checkpoint=tick(self.store,self.p,info=client,now=self.p["checkpoint_ms"]+1)
        self.assertEqual(checkpoint["report_status"],"prepared")
        self.assertEqual(checkpoint["decision"],"data_insufficient")
        replay=tick(self.store,self.p,info=client,now=self.p["checkpoint_ms"]+60_000)
        self.assertEqual(replay["report_status"],"unchanged")
        final=tick(self.store,self.p,info=client,now=self.p["end_ms"]+1)
        self.assertEqual(final["status"],"finalised")
        self.assertEqual(final["decision"],"data_insufficient")
        self.assertEqual(self.store.connection.execute("select count(*) from eth_observation_reports where protocol_id=?",
            (self.p["protocol_id"],)).fetchone()[0],2)
        self.assertEqual(self.store.connection.execute("select count(*) from eth_observation_routes where protocol_id=?",
            (self.p["protocol_id"],)).fetchone()[0],2)
        again=tick(self.store,self.p,info=client,now=self.p["end_ms"]+60_000)
        self.assertEqual(again["status"],"finalised")
        self.assertEqual(again["report_status"],"unchanged")

    def test_protocol_identity_cannot_be_reused_for_different_window(self):
        init(self.store,self.p)
        altered={**self.p,"end_ms":self.p["end_ms"]-1}
        with self.assertRaisesRegex(ValueError,"another immutable protocol"):
            init(self.store,altered)

    def test_poll_failure_is_persisted_without_a_second_same_tick_request(self):
        class BrokenInfo:
            def __init__(self):self.calls=0
            def post_info(self,payload):
                self.calls+=1
                raise RuntimeError("fixture transport failure")
        client=BrokenInfo()
        result=tick(self.store,self.p,info=client,now=self.p["start_ms"]+1)
        self.assertEqual(result["poll"]["status"],"error")
        row=self.store.connection.execute("select status,error_code,error_detail from eth_observation_polls").fetchone()
        self.assertEqual(tuple(row),("error","RuntimeError","fixture transport failure"))
        run=self.store.connection.execute("select diagnostic_json,next_poll_ms from eth_observation_runs").fetchone()
        self.assertEqual(json.loads(run["diagnostic_json"])["stage"],"fill_poll")
        self.assertGreater(run["next_poll_ms"],self.p["start_ms"]+1)
        self.assertEqual(client.calls,1)


if __name__=="__main__": unittest.main()

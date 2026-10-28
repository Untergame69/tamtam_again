"""Replay indexes event identities without changing the persisted reducer state."""
import unittest
from unittest.mock import patch
from tamtam_again.engine import initial_state, reduce_event, replay
from tamtam_again.recipe import synthetic_spec


class ReplayMembershipTests(unittest.TestCase):
    def events(self):
        return [{'id':str(i),'kind':'timer','event_ms':i,'received_ms':i} for i in range(2000)]

    def test_transient_index_keeps_duplicate_and_ledger_semantics(self):
        spec=synthetic_spec();events=self.events()
        events.insert(1100,dict(events[100]))
        expected=initial_state(spec)
        for event in sorted(events,key=lambda e:(e['received_ms'],str(e['id']))):
            reduce_event(expected,spec,event)
        actual=replay(spec,events,block_ms=1000)
        self.assertEqual(actual['state'],expected)
        self.assertEqual(len(actual['state']['seen']),2000)

    def test_replay_never_scans_growing_persisted_identity_list(self):
        class NoMembershipList(list):
            def __contains__(self,value):
                raise AssertionError('Replay must use its transient identity index')
        spec=synthetic_spec();state=initial_state(spec);state['seen']=NoMembershipList()
        with patch('tamtam_again.engine.initial_state',return_value=state):
            result=replay(spec,self.events(),block_ms=1000)
        self.assertEqual(len(result['state']['seen']),2000)

from copy import deepcopy
import unittest

from tamtam_again.episodes import complete_episodes
from tamtam_again.research import load_policy,packet_for

def fixtures():
    events=[]
    for t in range(1000,1001000,1000):
        events.append({'id':f'b{t}','kind':'bbo','event_ms':t,'received_ms':t+1,'available_ms':t+2,
                       'bid':'99','ask':'100','bid_size':'10','ask_size':'20','session':'one'})
        if t%30000==0:
            events.append({'id':f'h{t}','kind':'heartbeat','event_ms':t,'received_ms':t+1,'available_ms':t+2,
                           'session':'one','connected':True,'markets':['BTC']})
        if t in [250000,500000,750000]:
            events.append({'id':f'f{t}','kind':'leader_fill','event_ms':t,'received_ms':t+1,'available_ms':t+2,
                           'delta':'1','leader_start_position':'5','session':'one'})
    return events

class EpisodeTests(unittest.TestCase):
    def test_entire_paths_retained_with_inventory_and_causal_times(self):
        events=fixtures();episodes=complete_episodes(events,load_policy(),'BTC')
        self.assertEqual(len(episodes),3)
        for ep in episodes:
            source=[e for e in events if ep['start_ms']<=e['available_ms']<ep['end_ms']]
            self.assertEqual(ep['event_count'],len(source))
            self.assertEqual(len(ep['rows']),len(source)+ep['seed_count'])
            self.assertEqual(ep['leader_inventory_before_first_fill'],'5')
            self.assertFalse(ep['funding_observed'])
            for r in ep['rows']:self.assertLessEqual(r[1],r[2]);self.assertLessEqual(r[2],r[3])
        for a,b in zip(episodes,episodes[1:]):self.assertLessEqual(a['end_ms'],b['start_ms'])

    def test_budget_drops_whole_episodes_never_rows(self):
        policy=load_policy();policy['max_packet_chars']=45000
        plan={'coin':'BTC','exploration':{'start_ms':0,'end_ms':1100000}}
        cycles=[{'cycle_id':'fixture','opened_at_ms':1,'closed_at_ms':2}]
        packet=packet_for(plan,cycles,fixtures(),policy)
        self.assertGreaterEqual(len(packet['episodes']),2)
        for ep in packet['episodes']:
            self.assertEqual(len(ep['rows']),ep['event_count']+ep['seed_count'])
        policy['max_packet_chars']=1000
        with self.assertRaises(ValueError):packet_for(plan,cycles,fixtures(),policy)

    def test_no_future_horizon_is_inferred(self):
        events=fixtures()[:100]
        self.assertEqual(complete_episodes(events,load_policy(),'BTC'),[])

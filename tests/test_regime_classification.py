"""Reference implementation preserved to establish identical pilot semantics."""
import random,unittest
from tamtam_again.engine import number
from tamtam_again.paper import classify_regimes

def original(events,criteria):
 threshold=number(criteria['regime_threshold_bps']);window=criteria['regime_window_ms']
 history=[];result=list(events)
 for e in sorted(events,key=lambda x:(x['received_ms'],str(x['id']))):
  if e['kind']!='bbo':continue
  mid=(number(e['bid'])+number(e['ask']))/2
  prior=[p for p in history if p[0]<=e['received_ms']-window]
  if prior:
   change=(mid/prior[-1][1]-1)*10000
   result.append({'id':'regime:'+e['id'],'kind':'regime','event_ms':e['event_ms'],
    'received_ms':e['received_ms'],'available_ms':e.get('available_ms',e['received_ms']),
    'label':'up' if change>threshold else 'down' if change < -threshold else 'quiet'})
  history.append((e['received_ms'],mid))
  older=[p for p in history if p[0]<=e['received_ms']-window]
  history=older[-1:]+[p for p in history if p[0]>e['received_ms']-window]
 return sorted(result,key=lambda e:(e.get('available_ms',e['received_ms']),e['received_ms'],str(e['id'])))

def fixtures(n):
 rng=random.Random(42);stamp=0;events=[]
 for i in range(n):
  stamp+=rng.choice([0,1,10,200]);mid=rng.randint(50,150)
  events.append({'id':str(i),'kind':'bbo','event_ms':stamp,'received_ms':stamp,
   'available_ms':stamp+rng.randint(0,20),'bid':str(mid),'ask':str(mid+1)})
 return events
class RegimeClassificationTests(unittest.TestCase):
 def test_identical_reference_with_equal_times_gaps_and_reordered_availability(self):
  events=fixtures(600)
  for window in (0,1,100,60000):
   criteria={'regime_threshold_bps':'5','regime_window_ms':window}
   self.assertEqual(classify_regimes(list(reversed(events)),criteria),original(events,criteria))
 def test_empty_single_and_nonquote_inputs(self):
  for events in ([],fixtures(1),[{'id':'heartbeat','kind':'heartbeat','event_ms':0,'received_ms':0}]):
   criteria={'regime_threshold_bps':'5','regime_window_ms':100}
   self.assertEqual(classify_regimes(events,criteria),original(events,criteria))

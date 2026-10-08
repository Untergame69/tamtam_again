"""Group only explicitly linked account acquisitions, never infer legacy batches."""
from .observation_windows import acquisition_window,acquisition_span


def group_acquisitions(records):
    groups={};unlinked=[]
    required={'userAbstraction','spotClearinghouseState','clearinghouseState'}
    for row,payload,query in records:
        if row['endpoint'] not in required:continue
        identity=query.get('acquisition_id');ref='raw_observations:'+str(row['observation_id'])
        if not isinstance(identity,str) or not identity:
            unlinked.append(ref);continue
        groups.setdefault(identity,[]).append((row,payload,query))
    result=[]
    for identity,items in sorted(groups.items()):
        modes=[p for r,p,q in items if r['endpoint']=='userAbstraction']
        spots=[(r,p,q) for r,p,q in items if r['endpoint']=='spotClearinghouseState']
        margins=[(r,p,q) for r,p,q in items if r['endpoint']=='clearinghouseState']
        windows=[acquisition_window(r['requested_at'],r['observed_at']) for r,p,q in items]
        reasons=[]
        if len(modes)!=1 or not isinstance(modes[0],str):reasons.append('one explicit account mode observation required')
        if len(spots)!=1 or not isinstance(spots[0][1],dict):reasons.append('one explicit spot observation required')
        expected=[q.get('expected_dexes') for r,p,q in margins]
        refs=[q.get('inventory_evidence_ref') for r,p,q in margins]
        dexes=[q.get('dex','') for r,p,q in margins]
        inventory=(bool(expected) and all(isinstance(e,list) and e and all(isinstance(d,str) for d in e) for e in expected)
                   and all(e==expected[0] for e in expected) and len(set(expected[0]))==len(expected[0])
                   and all(isinstance(ref,str) and ref for ref in refs) and len(set(refs))==1)
        if not inventory:reasons.append('consistent declared DEX inventory and provenance required')
        elif len(set(dexes))!=len(dexes) or set(dexes)!=set(expected[0]):reasons.append('missing or duplicate DEX state in acquisition')
        if any(not isinstance(p,dict) for r,p,q in margins):reasons.append('malformed DEX state')
        span=acquisition_span(windows)
        if span['status']=='unknown':reasons.append('local acquisition chronology unavailable')
        stamps=[p.get('time') for r,p,q in spots+margins if isinstance(p,dict)]
        economic_aligned=(len(stamps)==len(spots)+len(margins) and bool(stamps)
                          and all(type(t) is int and t>=0 for t in stamps) and len(set(stamps))==1
                          and all(t<=w['available_ms'] for t,w in zip(stamps,
                              [acquisition_window(r['requested_at'],r['observed_at']) for r,p,q in spots+margins])) ) if all(w['available_ms'] is not None for w in windows) else False
        result.append({'acquisition_id':identity,'mode':modes[0] if len(modes)==1 else None,
          'dexes_observed':dexes,'expected_dexes':expected[0] if inventory else None,
          'inventory_evidence_ref':refs[0] if inventory else None,
          'status':'linked_inventory' if not reasons else 'incomplete_linked_inventory',
          'missing_or_conflicting':reasons,'local_span':span,
          'economic_components_aligned':economic_aligned,
          'economic_event_ms':stamps[0] if economic_aligned else None,
          'equity':None,'economic_qualification':False,
          'evidence_refs':['raw_observations:'+str(r['observation_id']) for r,p,q in items],
          'next_action':'supply verified mode-specific valuation and currency mapping' if economic_aligned and not reasons else 'establish complete component inventory and economic alignment or justified interval valuation',
          'limits':['linked calls are sequential, not an atomic account state',
                    'DEX inventory provenance declared here still requires independent verification',
                    'mode was observed once; changes during acquisition are not excluded',
                    'no legacy batch inferred from proximity; no receipt substituted for economic time']})
    return {'groups':result,'unlinked_legacy_evidence_refs':unlinked}

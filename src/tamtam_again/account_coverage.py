"""Separate archived pagination coverage from proof of retained event history."""
from __future__ import annotations


def pagination_coverage(pages, *, start_ms, end_ms, as_of_ms):
    if not 0<=start_ms<end_ms<=as_of_ms:
        raise ValueError('Explicit available coverage interval required')
    intervals=[];refs=[];incomplete=[]
    for page in pages:
        if page['available_ms']>as_of_ms:continue
        left,right=page.get('start_ms'),page.get('end_ms')
        if type(left) is not int or type(right) is not int or not 0<=left<=right:
            incomplete.append({'evidence_ref':page['evidence_ref'],'reason':'window bounds unavailable'})
            continue
        if right<start_ms or left>end_ms:continue
        refs.append(page['evidence_ref'])
        if page.get('pagination_status')!='pagination_exhausted':
            incomplete.append({'evidence_ref':page['evidence_ref'],
                               'reason':page.get('pagination_status','unknown')})
            continue
        intervals.append((max(start_ms,left),min(end_ms,right)))
    merged=[]
    for left,right in sorted(intervals):
        if merged and left<=merged[-1][1]:
            merged[-1][1]=max(merged[-1][1],right)
        else:merged.append([left,right])
    gaps=[];cursor=start_ms
    for left,right in merged:
        if left>cursor:gaps.append([cursor,left])
        cursor=max(cursor,right)
    if cursor<end_ms:gaps.append([cursor,end_ms])
    return {'status':'unknown','pagination_status':'covered' if not gaps else 'gaps',
            'pagination_intervals_ms':merged,'pagination_gaps_ms':gaps,
            'evidence_refs':sorted(set(refs)),'incomplete_pages':incomplete,
            'retention_proven':False,
            'reason':'exhausted API pages do not establish retention or economic scope completeness',
            'next_action':'finish missing pagination windows' if gaps else
                          'establish retained-history coverage and accounting scope independently'}

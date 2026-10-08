"""Reported portfolio samples, separate from reconstructed account accounting."""
from .accounting import decimal

WINDOWS={'day','week','month','allTime','perpDay','perpWeek','perpMonth','perpAllTime'}


def summarize(payload,*,available_ms,as_of_ms,start_ms,end_ms,evidence_ref):
    if not 0<=start_ms<end_ms<=as_of_ms or type(available_ms) is not int or not 0<=available_ms<=as_of_ms or not evidence_ref:
        raise ValueError('Available explicit portfolio evidence required')
    output={'evidence_ref':evidence_ref,'available_ms':available_ms,'windows':[],
            'economic_qualification':False,
            'limits':['provider samples are not reconstructed accounting',
                      'no interpolation at requested boundaries',
                      'window names do not establish spot/HIP-3/debt/vault completeness for every account mode',
                      'reported PnL sign convention and net-flow semantics not independently reconciled',
                      'sampled curve cannot prove intraperiod drawdown or flow-adjusted return']}
    if not isinstance(payload,list):return {**output,'status':'malformed_portfolio_response'}
    seen=set()
    for entry in payload:
        if not isinstance(entry,list) or len(entry)!=2 or not isinstance(entry[0],str) or entry[0] not in WINDOWS or not isinstance(entry[1],dict):
            output['windows'].append({'status':'malformed_window'});continue
        window,data=entry
        if window in seen:
            for prior in output['windows']:
                if prior.get('window')==window and 'series' in prior:
                    prior['status']='duplicate_window'
                    for values in prior['series'].values():
                        values['reported_change']=None;values['status']='ambiguous_duplicate_window'
            output['windows'].append({'window':window,'status':'duplicate_window'});continue
        seen.add(window);series={};errors=[]
        for key in ('accountValueHistory','pnlHistory'):
            rows=data.get(key);points={};conflicts=set();rejected=0
            if not isinstance(rows,list):errors.append('missing '+key);rows=[]
            for point in rows:
                try:
                    if not isinstance(point,list) or len(point)!=2:raise ValueError('Invalid sample')
                    stamp=point[0]
                    if type(stamp) is not int or not 0<=stamp<=available_ms:raise ValueError('Unavailable sample')
                    value=decimal(point[1])
                    if stamp in points and points[stamp]!=value:conflicts.add(stamp)
                    points[stamp]=value
                except (ValueError,TypeError):rejected+=1
            clean={t:v for t,v in points.items() if t not in conflicts}
            if conflicts:errors.append('conflicting '+key+' timestamps')
            if rejected:errors.append('malformed or future '+key+' samples')
            exact=(start_ms in clean and end_ms in clean and not conflicts and not rejected)
            series[key]={'sample_count':len(clean),'rejected_samples':rejected,
               'conflicting_times':sorted(conflicts),
               'first_sample_ms':min(clean) if clean else None,'last_sample_ms':max(clean) if clean else None,
               'requested_start_value':str(clean[start_ms]) if start_ms in clean else None,
               'requested_end_value':str(clean[end_ms]) if end_ms in clean else None,
               'reported_change':str(clean[end_ms]-clean[start_ms]) if exact else None,
               'status':'exact_reported_boundaries' if exact else 'requested_boundaries_unproven'}
        output['windows'].append({'window':window,'status':'reported_samples' if not errors else 'sample_quality_unknown',
            'series':series,'quality_diagnostics':errors})
    output['status']='reported_samples_only'
    return output

"""A predeclared replacement may retire a suspended, flat predecessor only."""
import json
from .engine import number


def validate_policy(policy):
    if not isinstance(policy,dict) or policy.get('version')!='suspended-flat-handover-v1':
        raise ValueError('Supported paper replacement policy required')
    if policy.get('capital_policy','independent_paper_session') not in {'independent_paper_session','carry_flat_cash'}:
        raise ValueError('Unsupported handover capital policy')
    if not isinstance(policy.get('predecessor_variant_id'),str) or not policy['predecessor_variant_id'].strip():
        raise ValueError('Explicit predecessor variant required')
    if type(policy.get('minimum_session_age_ms')) is not int or policy['minimum_session_age_ms']<1:
        raise ValueError('Positive paper replacement cooldown required')
    if not isinstance(policy.get('justification'),str) or not policy['justification'].strip():
        raise ValueError('Paper replacement justification required')


def eligible(policy,session,now_ms):
    validate_policy(policy)
    state=json.loads(session['state_json'])
    return (session['variant_id']==policy['predecessor_variant_id']
            and session['status']=='suspended'
            and now_ms-session['started_ms']>=policy['minimum_session_age_ms']
            and number(state['position'])==0 and not state['pending'])


def carry_flat_cash(store,session,now_ms):
    """Transfer only an observed flat model cash balance, never infer missing equity."""
    from .engine import fingerprint
    state=json.loads(session['state_json'])
    if number(state['position'])!=0 or state['pending'] or number(state['cash'])<=0:
        raise ValueError('Positive flat cash without pending orders required')
    row=store.connection.execute('select snapshot_id,state_fingerprint,available_ms from paper_snapshots where session_id=? order by available_ms desc,snapshot_id limit 1',(session['session_id'],)).fetchone()
    if not row or row['available_ms']>now_ms or row['state_fingerprint']!=fingerprint(state):
        raise ValueError('Current predecessor state lacks an available immutable snapshot')
    return str(number(state['cash'])),row['snapshot_id']

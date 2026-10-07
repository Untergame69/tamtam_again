"""A predeclared replacement may retire a suspended, flat predecessor only."""
import json
from .engine import number


def validate_policy(policy):
    if not isinstance(policy,dict) or policy.get('version')!='suspended-flat-handover-v1':
        raise ValueError('Supported paper replacement policy required')
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

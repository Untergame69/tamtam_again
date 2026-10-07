"""Predeclared paper loss budget; no profitability claim or automatic replacement."""
from .engine import number


def validate_policy(policy):
    if not isinstance(policy, dict) or policy.get('version') != 'paper-loss-budget-v1':
        raise ValueError('Supported paper monitoring policy required')
    if not isinstance(policy.get('justification'), str) or not policy['justification'].strip():
        raise ValueError('Paper loss budget justification required')
    limit = number(policy.get('max_net_loss_usdc'))
    if not limit.is_finite() or limit <= 0:
        raise ValueError('Positive finite paper loss budget required')


def diagnose(policy, observed_metrics):
    validate_policy(policy)
    net = number(observed_metrics['net_pnl'])
    if not net.is_finite():
        raise ValueError('Finite observed paper result required')
    return ['paper_net_loss_budget_exhausted'] if net <= -number(policy['max_net_loss_usdc']) else []

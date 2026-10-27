"""Explicit, source-linked simulation assumptions for research proposals.

These are chosen parameters from the existing pilot configuration, never venue
measurements or permission to trade. They supply a counterfactual execution
scenario without supplying an entry signal, sizing rule or holding horizon.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .engine import fingerprint, number


SOURCE = 'config/research-policy.json'
REFERENCE = 'packet.execution_research_context'
SCENARIO_FIELDS = ('max_exposure', 'fees', 'slippage', 'latency_ms',
                   'starting_capital_usdc', 'execution')


def attach_execution_context(packet, repo_root):
    """Attach existing parameters before sealing; do not mutate observations.

    Absence or invalidity fails explicitly, rather than creating defaults. The
    source hash binds the exact configuration even if a future revision changes
    it. References to this context may justify scenario axes, but cannot alone
    support a hypothesis about market behaviour.
    """
    path = Path(repo_root) / SOURCE
    raw = path.read_bytes()
    policy = json.loads(raw)
    template = policy.get('strategy_template')
    if (not isinstance(template, dict) or template.get('schema_version') != 2
            or not isinstance(policy.get('version'), str) or not policy['version']):
        raise ValueError('Existing versioned pilot strategy template required')
    scenario = {key: deepcopy(template[key]) for key in SCENARIO_FIELDS}
    if (set(scenario['fees']) != {'maker_bps', 'taker_bps'}
            or any(number(value) < 0 for value in scenario['fees'].values())
            or number(scenario['slippage']['bps']) < 0
            or type(scenario['latency_ms']) is not int or scenario['latency_ms'] < 0
            or number(scenario['starting_capital_usdc']) <= 0
            or any(number(scenario['max_exposure'][key]) <= 0 for key in
                   ('notional_usdc', 'max_drawdown_usdc', 'max_leverage'))
            or scenario['execution'].get('kind') != 'market_ioc'):
        raise ValueError('Explicit nonnegative costs and bounded IOC pilot scenario required')
    context = {
        'schema_version': 'execution-research-context-v1',
        'source': {'path': SOURCE, 'policy_version': policy['version'],
                   'sha256': hashlib.sha256(raw).hexdigest()},
        'classification': 'chosen_simulation_scenario_not_measured_capacity',
        'scope': 'Our single-perpetual IOC counterfactual only; not the source trader execution policy.',
        'scenario': scenario,
        'parameter_status': {
            'fees': 'Configured debit scenario, not our verified venue fee schedule or a maker rebate entitlement.',
            'slippage': 'Configured additional cost scenario, not measured impact.',
            'latency_ms': 'Configured simulated delay, not measured decision-to-execution latency.',
            'starting_capital_usdc': 'Chosen virtual capital, not source account equity.',
            'max_exposure': 'Chosen virtual risk limits, not evidence of source account risk.',
            'execution': 'Configured conservative visible-liquidity simulation; no guaranteed fill or passive queue model.',
        },
        'research_use': [
            'A falsifiable policy for our own decisions may be tested without identifying the trader private intentions.',
            'A follower policy begins only at locally received public fills; REST event time is not signal availability.',
            'Entry trigger, exit horizon and sizing remain hypotheses requiring market evidence and explicit justification.',
            'Use measurement_status=simulated for scenario axes; do not cite this context as measured_reference.',
            'A result applies to the declared scenario; it is not a demonstrated live execution return.',
        ],
        'market_evidence': False,
        'economic_validation': False,
        'paper_authorized': False,
        'real_orders_authorized': False,
    }
    context['fingerprint'] = fingerprint(context)
    packet['execution_research_context'] = context
    return context


def validate_scenario_spec(context, spec):
    """Keep configured assumptions explicit when the packet supplies them.

    Hypothesis axes may vary a declared simulated delay; the base specification
    remains the source scenario. No risk expansion or cheaper fee assumption is
    inferred merely because a model cites the configuration.
    """
    original = deepcopy(context)
    claimed = original.pop('fingerprint', None)
    if (claimed != fingerprint(original)
            or context.get('schema_version') != 'execution-research-context-v1'
            or context.get('classification') != 'chosen_simulation_scenario_not_measured_capacity'
            or any(context.get(key) is not False for key in
                   ('market_evidence', 'economic_validation', 'paper_authorized', 'real_orders_authorized'))):
        raise ValueError('Verified non-promotional execution scenario required')
    scenario = context['scenario']
    if spec.get('engine') not in (None, 'single_perp_v2'):
        # A portfolio or passive model needs a separately supplied scenario,
        # rather than inheriting single-perp assumptions without accounting.
        raise ValueError('Execution context covers only the declared single-perp IOC scenario')
    if any(spec.get(key) != scenario[key] for key in
           ('latency_ms', 'starting_capital_usdc', 'execution')):
        raise ValueError('Executable base specification must preserve the supplied simulation assumptions')
    costs = spec.get('fees', {})
    if (set(costs) != set(scenario['fees'])
            or any(number(costs[key]) < number(value) for key, value in scenario['fees'].items())
            or number(spec.get('slippage', {}).get('bps', '-1')) < number(scenario['slippage']['bps'])):
        raise ValueError('Configured costs may be stressed upward, never reduced without separate evidence')
    risk = spec.get('max_exposure', {})
    if any(key not in risk or number(risk[key]) > number(limit) or number(risk[key]) <= 0
           for key, limit in scenario['max_exposure'].items()):
        raise ValueError('Executable risk limits must remain within the supplied virtual scenario')

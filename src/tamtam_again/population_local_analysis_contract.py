"""Sealed, finite contract for deterministic local fill/market analysis.

The contract is data carried by an immutable research packet. It never parses
required-data prose into executable operations.
"""
from __future__ import annotations

import re

from .engine import fingerprint

VERSION = 'population-local-analysis-contract-v1'
PROFILE = 'hyperliquid.fill-market-context-v1'
OPERATIONS = (
    'position_effect_from_start_position',
    'strict_prior_bbo_l2_context',
    'event_and_local_receipt_markouts',
    'order_and_time_groupings',
    'market_condition_and_freshness_sensitivity',
)
PARAMETERS = {
    'outcome_horizon_ms': 60_000,
    'movement_horizons_ms': [5_000, 30_000, 60_000],
    'freshness_ages_ms': [100, 1_000, 5_000, 30_000, 60_000, 300_000],
    'time_block_ms': 300_000,
    'primary_context_max_age_ms': 30_000,
    'condition_context_max_age_ms': 30_000,
    'condition_movement_horizon_ms': 30_000,
    'condition_movement_max_lookback_ms': 60_000,
    'movement_direction_threshold_bps': 1,
    'condition_tertile_percentiles': [33, 67],
    'same_event_time_predecessor_policy': 'exclude_as_context_and_record_tie_count',
}
SOURCE_TYPES = {'eth_observation_report'}
FILL_SOURCES = {'hyperliquid-prospective-observation-v1'}
QUOTE_SOURCES = {'hyperliquid-websocket-v1'}
SAFE_MARKET = re.compile(r'^[A-Z0-9][A-Z0-9._-]{0,31}$')
SAFE_ADDRESS = re.compile(r'^0x[0-9a-f]{40}$')


class LocalAnalysisContractError(ValueError):
    def __init__(self, code: str, field: str, observed, limit: str):
        self.diagnostic = {'stage': 'local_analysis_contract', 'code': code,
            'field': field, 'observed': observed, 'limit': limit}
        super().__init__(code + ': ' + field)


def report_reference(source: dict) -> str:
    return (f"eth_observation_reports:{source['protocol_id']}:{source['stage']}"
        f"#sha256:{source['semantic_fingerprint']}")


def validate_contract(packet: dict, contract: dict) -> dict:
    """Validate the exact closed v1 shape and its binding to a sealed packet."""
    if not isinstance(packet, dict) or not isinstance(contract, dict):
        raise LocalAnalysisContractError('contract_shape_invalid', 'contract', type(contract).__name__,
            'object bound to immutable task packet')
    required_top = {'schema_version', 'profile', 'source', 'scope', 'cutoff',
        'operations', 'parameters', 'authorization'}
    if set(contract) != required_top:
        raise LocalAnalysisContractError('contract_fields_invalid', 'contract', sorted(contract),
            sorted(required_top).__repr__())
    if contract['schema_version'] != VERSION or contract['profile'] != PROFILE:
        raise LocalAnalysisContractError('analysis_profile_unsupported', 'profile',
            contract.get('profile'), PROFILE + ' / ' + VERSION)
    source = contract['source']
    if not isinstance(source, dict) or set(source) != {'kind', 'protocol_id', 'stage',
            'input_fingerprint', 'semantic_fingerprint', 'report_ref', 'fill_source', 'quote_source',
            'fill_reference_fingerprint', 'quote_reference_fingerprint'}:
        raise LocalAnalysisContractError('source_contract_invalid', 'source', source,
            'kind, protocol_id, stage and both fingerprints with exact report_ref')
    if source['kind'] not in SOURCE_TYPES:
        raise LocalAnalysisContractError('source_type_unsupported', 'source.kind', source.get('kind'),
            sorted(SOURCE_TYPES).__repr__())
    if any(not isinstance(source.get(key), str) or not source[key].strip()
            for key in ('protocol_id', 'stage', 'input_fingerprint', 'semantic_fingerprint')):
        raise LocalAnalysisContractError('source_identity_invalid', 'source', source,
            'nonempty source identity and fingerprints')
    for key in ('input_fingerprint', 'semantic_fingerprint'):
        if not re.fullmatch(r'[0-9a-f]{64}', source[key]):
            raise LocalAnalysisContractError('source_fingerprint_invalid', 'source.' + key,
                source[key], 'lowercase SHA-256 fingerprint')
    if source.get('report_ref') != report_reference(source):
        raise LocalAnalysisContractError('source_reference_invalid', 'source.report_ref',
            source.get('report_ref'), report_reference(source))
    refs = packet.get('evidence_refs')
    if not isinstance(refs, list) or source['report_ref'] not in refs:
        raise LocalAnalysisContractError('source_not_sealed', 'source.report_ref', source['report_ref'],
            'exact reference present in sealed packet evidence_refs')
    if source.get('fill_source') not in FILL_SOURCES:
        raise LocalAnalysisContractError('fill_source_unsupported', 'source.fill_source', source.get('fill_source'),
            sorted(FILL_SOURCES).__repr__())
    if source.get('quote_source') not in QUOTE_SOURCES:
        raise LocalAnalysisContractError('quote_source_unsupported', 'source.quote_source', source.get('quote_source'),
            sorted(QUOTE_SOURCES).__repr__())
    if any(not isinstance(source.get(key), str) or not source[key]
            for key in ('fill_reference_fingerprint', 'quote_reference_fingerprint')):
        raise LocalAnalysisContractError('source_reference_fingerprint_missing', 'source', source,
            'fingerprints of the exact fill-page and quote-lot inventories in the referenced report')
    for key in ('fill_reference_fingerprint', 'quote_reference_fingerprint'):
        if not re.fullmatch(r'[0-9a-f]{64}', source[key]):
            raise LocalAnalysisContractError('source_reference_fingerprint_invalid', 'source.' + key,
                source[key], 'lowercase SHA-256 fingerprint')

    scope = contract['scope']
    required_scope = {'network', 'address', 'market', 'start_ms', 'end_ms', 'interval'}
    if not isinstance(scope, dict) or set(scope) != required_scope:
        raise LocalAnalysisContractError('scope_contract_invalid', 'scope', scope,
            sorted(required_scope).__repr__())
    if not isinstance(scope.get('network'), str) or not scope['network']:
        raise LocalAnalysisContractError('scope_network_invalid', 'scope.network', scope.get('network'),
            'nonempty network in sealed packet')
    if not isinstance(scope.get('address'), str) or not SAFE_ADDRESS.fullmatch(scope['address']):
        raise LocalAnalysisContractError('scope_address_invalid', 'scope.address', scope.get('address'),
            'normalized lower-case identity matching sealed packet')
    if not isinstance(scope.get('market'), str) or not SAFE_MARKET.fullmatch(scope['market']):
        raise LocalAnalysisContractError('scope_market_invalid', 'scope.market', scope.get('market'),
            'uppercase market identifier matching the sealed observation')
    if (type(scope.get('start_ms')) is not int or type(scope.get('end_ms')) is not int
            or scope['start_ms'] >= scope['end_ms'] or scope.get('interval') != '[start_ms,end_ms)'):
        raise LocalAnalysisContractError('scope_window_invalid', 'scope', scope,
            'integer half-open [start_ms,end_ms) interval with start < end')
    if packet.get('network') != scope['network'] or str(packet.get('address', '')).lower() != scope['address']:
        raise LocalAnalysisContractError('scope_packet_mismatch', 'scope',
            {'network': scope['network'], 'address': scope['address']},
            'exact network and account bound to sealed packet')
    observations = packet.get('observations')
    markets = observations.get('markets') if isinstance(observations, dict) else None
    if not isinstance(markets, list) or scope['market'] not in markets:
        raise LocalAnalysisContractError('scope_market_mismatch', 'scope.market', scope['market'],
            'market present in sealed packet observations.markets list')

    cutoff = contract['cutoff']
    if cutoff != {'source': 'eth_observation_runs.finalised_ms'}:
        raise LocalAnalysisContractError('cutoff_source_unsupported', 'cutoff', cutoff,
            "{'source':'eth_observation_runs.finalised_ms'}")
    operations = contract['operations']
    if (not isinstance(operations, list) or not all(isinstance(item, str) for item in operations)
            or len(operations) != len(set(operations))
            or tuple(operations) != OPERATIONS):
        raise LocalAnalysisContractError('calculation_set_unsupported', 'operations', operations,
            list(OPERATIONS).__repr__())
    if contract['parameters'] != PARAMETERS:
        raise LocalAnalysisContractError('calculation_parameters_unsupported', 'parameters',
            contract['parameters'], PARAMETERS.__repr__())
    authorization = contract['authorization']
    expected_auth = {'source': 'sealed_task_packet', 'archive_only': True,
        'allow_collection': False, 'model_calls': 0}
    if authorization != expected_auth:
        raise LocalAnalysisContractError('authorization_contract_invalid', 'authorization',
            authorization, expected_auth.__repr__())
    return {'contract': contract, 'contract_fingerprint': fingerprint(contract)}


def contract_for_scope(*, packet: dict, protocol_id: str, stage: str, input_fingerprint: str,
        semantic_fingerprint: str, network: str, address: str, market: str,
        start_ms: int, end_ms: int, fill_reference_fingerprint: str,
        quote_reference_fingerprint: str, fill_source: str = 'hyperliquid-prospective-observation-v1',
        quote_source: str = 'hyperliquid-websocket-v1') -> dict:
    """Build the finite profile from explicit evidence metadata, not request prose."""
    source = {'kind': 'eth_observation_report', 'protocol_id': protocol_id, 'stage': stage,
        'input_fingerprint': input_fingerprint, 'semantic_fingerprint': semantic_fingerprint,
        'fill_source': fill_source, 'quote_source': quote_source,
        'fill_reference_fingerprint': fill_reference_fingerprint,
        'quote_reference_fingerprint': quote_reference_fingerprint}
    source['report_ref'] = report_reference(source)
    contract = {'schema_version': VERSION, 'profile': PROFILE, 'source': source,
        'scope': {'network': network, 'address': address.lower(), 'market': market,
            'start_ms': start_ms, 'end_ms': end_ms, 'interval': '[start_ms,end_ms)'},
        'cutoff': {'source': 'eth_observation_runs.finalised_ms'},
        'operations': list(OPERATIONS), 'parameters': PARAMETERS.copy(),
        'authorization': {'source': 'sealed_task_packet', 'archive_only': True,
            'allow_collection': False, 'model_calls': 0}}
    validate_contract(packet, contract)
    return contract


def contract_for_report(*, packet: dict, report: dict, network: str, address: str,
        market: str, start_ms: int, end_ms: int,
        fill_source: str = 'hyperliquid-prospective-observation-v1',
        quote_source: str = 'hyperliquid-websocket-v1') -> dict:
    """Bind the finite profile to a report's exact archived reference inventories."""
    from .eth_report_projection import semantic_fingerprint

    if not isinstance(report, dict):
        raise LocalAnalysisContractError('source_report_invalid', 'report', type(report).__name__, 'persisted observation report object')
    coverage = report.get('coverage')
    fills = coverage.get('fills') if isinstance(coverage, dict) else None
    market_coverage = coverage.get('market') if isinstance(coverage, dict) else None
    fill_refs = fills.get('pages') if isinstance(fills, dict) else None
    quote_refs = market_coverage.get('source_refs') if isinstance(market_coverage, dict) else None
    if not isinstance(fill_refs, list) or not isinstance(quote_refs, list):
        raise LocalAnalysisContractError('source_reference_inventory_unavailable', 'report.coverage',
            {'fills.pages': type(fill_refs).__name__, 'market.source_refs': type(quote_refs).__name__},
            'both exact reference inventories must be explicit lists before sealing')
    return contract_for_scope(packet=packet, protocol_id=report.get('protocol_id'),
        stage=report.get('stage'), input_fingerprint=report.get('input_fingerprint'),
        semantic_fingerprint=semantic_fingerprint(report), network=network, address=address,
        market=market, start_ms=start_ms, end_ms=end_ms,
        fill_reference_fingerprint=fingerprint(fill_refs),
        quote_reference_fingerprint=fingerprint(quote_refs),
        fill_source=fill_source, quote_source=quote_source)

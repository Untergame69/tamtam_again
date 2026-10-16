import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tamtam_again.engine import canonical, fingerprint
from tamtam_again.eth_report_projection import semantic_fingerprint
from tamtam_again.population_local_analysis_contract import contract_for_report
from tamtam_again.population_local_archive_resolution import execute
from tamtam_again.population_research import initialize as initialize_population
from tamtam_again.population_routing import route
from tamtam_again.population_scheduler import tick
from tamtam_again.storage import Store
from tamtam_again.validation import now_ms
from tests.test_eth_existing_window_resolution import START_MS, END_MS, fixture_data


ROOT = Path(__file__).resolve().parents[1]


def shift_fixture(offset, market):
    fills, report_fills, quotes, fill_cov, quote_cov, report = fixture_data()
    for row in fills:
        row['coin'] = market
        row['time'] += offset
        row['fill_page_received_at'] = row['fill_page_received_at']
        row['fill_page_archived_at'] = row['fill_page_archived_at']
    for row in report_fills:
        row['event_ms'] += offset
    for quote in quotes:
        quote['market'] = market
        quote['event_ms'] += offset
        quote['received_ms'] += offset
        quote['event_received_ms'] += offset
        quote['archived_ms'] += offset
    report['stage'] = 'final_24h'
    report['fills'] = report_fills
    fill_refs = [{'observation_id': row['fill_page_observation_id'], 'sha256': row['fill_page_sha256'],
        'record_count': 1, 'complete': True} for row in report_fills]
    quote_refs = [{'observation_id': row['observation_id'], 'sha256': row['sha256'],
        'endpoint': row['channel']} for row in quotes]
    fill_cov['pages'] = fill_refs
    fill_cov['page_count'] = len(fill_refs)
    fill_cov['reference_coverage'] = {'expected_ref_count': len(fill_refs),
        'matched_ref_count': len(fill_refs), 'missing_ref_count': 0,
        'sha256_mismatch_count': 0, 'unreferenced_archive_page_count': 0}
    quote_cov['source_refs'] = quote_refs
    quote_cov['reference_coverage'] = {'expected_ref_count': len(quote_refs),
        'matched_ref_count': len(quote_refs), 'missing_ref_count': 0,
        'sha256_mismatch_count': 0, 'unreferenced_archive_lot_count': 0}
    report['coverage']['fills']['pages'] = fill_refs
    report['coverage']['fills']['page_count'] = len(fill_refs)
    report['coverage']['market']['source_refs'] = quote_refs
    report['coverage']['market']['quotes'] = {
        channel: {'event_count': sum(q['channel'] == channel for q in quotes), 'max_received_gap_ms': 30_000}
        for channel in ('bbo', 'l2Book')}
    return fills, report_fills, quotes, fill_cov, quote_cov, report


def add_task(store, *, suffix, address, market, offset=0, missing_source=False, unsupported=False):
    protocol_id = 'protocol-' + suffix
    request_id = fingerprint({'request': suffix, 'network': 'hyperliquid-mainnet', 'address': address})
    start_ms, end_ms = START_MS + offset, END_MS + offset
    protocol = {'protocol_id': protocol_id, 'network': 'hyperliquid-mainnet', 'address': address.lower(),
        'market': market, 'start_ms': start_ms, 'end_ms': end_ms}
    protocol_fp = fingerprint(protocol)
    fills, rows, quotes, fill_cov, quote_cov, report = shift_fixture(offset, market)
    report['protocol_id'] = protocol_id
    report['protocol_fingerprint'] = protocol_fp
    report['input_fingerprint'] = fingerprint({'report-input': suffix})
    report['generated_at_ms'] = end_ms + 4_000
    report['coverage']['fills']['source_fingerprint'] = 'fill-source-' + suffix
    report['coverage']['market']['source_fingerprint'] = 'quote-source-' + suffix
    report['coverage']['fills']['unique_eth_fills'] = len(rows)
    report['window'] = {'start_ms': START_MS + offset, 'end_ms': END_MS + offset,
        'interval': '[start_ms,end_ms)'}
    semantic = semantic_fingerprint(report)
    ref = f'eth_observation_reports:{protocol_id}:final_24h#sha256:{semantic}'
    contract_packet = {'network': 'hyperliquid-mainnet', 'address': address.lower(),
        'evidence_refs': [ref], 'observations': {'markets': [market]}}
    contract = contract_for_report(packet=contract_packet, report=report, network='hyperliquid-mainnet',
        address=address, market=market, start_ms=start_ms, end_ms=end_ms)
    if unsupported:
        contract['operations'][-1] = 'infer_private_trader_intent'
    packet = {'schema_version': 'population-descriptive-v1', 'network': 'hyperliquid-mainnet',
        'address': address.lower(), 'available_ms': start_ms - 1,
        'research_input_fingerprint': fingerprint({'research-input': suffix}), 'evidence_refs': [ref],
        'observations': {'markets': [market]}, 'local_analysis_contract_v1': contract,
        'qualification': {}, 'limits': []}
    packet['fingerprint'] = fingerprint(packet)
    result = {'proposal': {'decision': 'hypothesis', 'hypothesis': {
            'mechanism': 'a descriptive comparison only', 'required_data': [
                'untrusted prose does not define operations for this test'], 'markets': [market],
            'rejection_criteria': 'the comparison is unsupported', 'execution_constraints': 'no orders',
            'risk': 'exploratory only'}},
        'critique': {'decision': 'consistent', 'diagnostic': 'descriptive only', 'wake': {}},
        'promotion_authorized': False, 'profitability_proven': False,
        'local_eth_existing_window_resolution': {'state': 'historical-and-immutable', 'fingerprint': 'keep-me'}}
    store.connection.execute('insert into population_research_jobs '
        '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,result_json,updated_ms) '
        'values(?,?,?,?,?,?,?,\'hypothesis_recorded\',?,?)',
        (request_id, packet['network'], packet['address'], packet['research_input_fingerprint'],
            canonical(packet), '{}', start_ms, canonical(result), start_ms))
    store.connection.execute('insert into eth_observation_runs '
        '(protocol_id,protocol_fingerprint,protocol_json,status,finalised_ms) values(?,?,?,?,?)',
        (protocol_id, protocol_fp, canonical(protocol), 'finalised', end_ms + 5_000))
    store.connection.execute('insert into eth_observation_reports values(?,?,?,?,?)',
        (protocol_id, 'final_24h', report['input_fingerprint'], canonical(report), end_ms + 5_000))
    if missing_source:
        store.connection.execute('delete from eth_observation_reports where protocol_id=?', (protocol_id,))
    store.connection.commit()
    return {'request_id': request_id, 'protocol_id': protocol_id, 'market': market,
        'start_ms': start_ms, 'end_ms': end_ms, 'fills': fills, 'rows': rows, 'quotes': quotes,
        'fill_cov': fill_cov, 'quote_cov': quote_cov, 'contract': contract,
        'report_refs': {'fills': report['coverage']['fills']['pages'],
            'quotes': report['coverage']['market']['source_refs']},
        'unsupported': unsupported, 'missing_source': missing_source, 'semantic': semantic}


class PopulationLocalArchiveResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'local.sqlite3')
        initialize_population(self.store)
        self.store.connection.execute('''create table eth_observation_runs (
            protocol_id text primary key,protocol_fingerprint text,protocol_json text,status text,finalised_ms integer)''')
        self.store.connection.execute('''create table eth_observation_reports (
            protocol_id text,stage text,input_fingerprint text,report_json text,created_ms integer,
            primary key(protocol_id,stage))''')
        self.store.connection.commit()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_contract_executes_two_identities_and_periods_and_replay_is_cached(self):
        first = add_task(self.store, suffix='a', address='0x' + 'a' * 40, market='ETH')
        second = add_task(self.store, suffix='b', address='0x' + 'b' * 40, market='BTC', offset=10 * 86_400_000)
        self.assertNotEqual(first['contract'], second['contract'])
        policy = json.loads((ROOT / 'config/population-research-policy.json').read_text())

        def load_fills(store, protocol, cutoff, *, allowed_source_refs=None):
            record = first if protocol['protocol_id'] == first['protocol_id'] else second
            self.assertEqual(protocol['market'], record['market'])
            self.assertEqual(allowed_source_refs, record['report_refs']['fills'])
            return record['fills'], record['fill_cov']

        def load_quotes(store, protocol, cutoff, *, allowed_source_refs=None):
            record = first if protocol['protocol_id'] == first['protocol_id'] else second
            self.assertEqual(protocol['market'], record['market'])
            self.assertEqual(allowed_source_refs, record['report_refs']['quotes'])
            return record['quotes'], record['quote_cov']

        real_execute = execute
        def execute_in_temp(store, request_id):
            return real_execute(store, request_id, repo_root=self.temp.name)

        with patch('tamtam_again.population_local_archive_resolution.execute', side_effect=execute_in_temp), \
                patch('tamtam_again.population_local_archive_resolution._fills', side_effect=load_fills) as fills_loader, \
                patch('tamtam_again.population_local_archive_resolution._quotes', side_effect=load_quotes) as quotes_loader:
            first_tick = tick(self.store, 'hyperliquid-mainnet', policy, dispatch=False, max_jobs=1)
            first_resolution = next(item for item in first_tick['local_resolutions']
                if item['request_id'] == first['request_id'])
            self.assertEqual(first_resolution['status'], 'prepared')
            self.assertEqual(first_resolution['resolution']['coverage']['classification'], 'complete')
            self.assertEqual(first_tick['processed'], [])
            self.assertEqual(first_tick['sealed'], [])
            second_tick = tick(self.store, 'hyperliquid-mainnet', policy, dispatch=False, max_jobs=1)
            second_resolution = next(item for item in second_tick['local_resolutions']
                if item['request_id'] == second['request_id'])
            self.assertEqual(second_resolution['status'], 'prepared')
            self.assertEqual(second_resolution['resolution']['coverage']['classification'], 'complete')
            replay = next(item for item in second_tick['local_resolutions'] if item['request_id'] == first['request_id'])
            self.assertEqual(replay['status'], 'unchanged')
            self.assertEqual(fills_loader.call_count, 2)
            self.assertEqual(quotes_loader.call_count, 2)
        with patch('tamtam_again.population_local_archive_resolution._fills', side_effect=AssertionError('recalculated')), \
                patch('tamtam_again.population_local_archive_resolution._quotes', side_effect=AssertionError('recalculated')):
            replay = execute(self.store, first['request_id'], repo_root=self.temp.name)
        self.assertEqual(replay['status'], 'unchanged')
        self.assertFalse(replay['recalculated'])
        for record in (first, second):
            saved = self.store.connection.execute('select result_json,status from population_research_jobs where request_id=?',
                (record['request_id'],)).fetchone()
            value = json.loads(saved['result_json'])
            self.assertEqual(saved['status'], 'hypothesis_recorded')
            self.assertEqual(value['proposal']['hypothesis']['required_data'],
                ['untrusted prose does not define operations for this test'])
            self.assertEqual(value['local_eth_existing_window_resolution'],
                {'state': 'historical-and-immutable', 'fingerprint': 'keep-me'})
            route_value = route(self.store, record['request_id'])
            self.assertEqual(route_value['state'], 'local_archive_analysis_complete')
            self.assertEqual(route_value['followup_task']['kind'], 'population_local_archive_analysis')

    def test_partial_archive_uses_all_report_fills_and_marks_missing_raw_or_quotes(self):
        task = add_task(self.store, suffix='partial', address='0x' + 'c' * 40, market='ETH')
        partial_fills = task['fills'][:1]
        partial_cov = dict(task['fill_cov'], unique_eth_fills=1, page_count=1, complete_page_count=1,
            duplicate_fill_instances=0, conflicting_fill_ids=[])
        partial_cov['reference_coverage'] = {'expected_ref_count': len(task['report_refs']['fills']),
            'matched_ref_count': 1, 'missing_ref_count': len(task['report_refs']['fills'])-1,
            'sha256_mismatch_count': 0, 'unreferenced_archive_page_count': 0}
        no_quotes = {'quotes': {'bbo': {'event_count': 0}, 'l2Book': {'event_count': 0}},
            'source_refs': [], 'source_fingerprint': fingerprint([]), 'rejected_events': {},
            'reference_coverage': {'expected_ref_count': len(task['report_refs']['quotes']),
                'matched_ref_count': 0, 'missing_ref_count': len(task['report_refs']['quotes']),
                'sha256_mismatch_count': 0, 'unreferenced_archive_lot_count': 0}}
        with patch('tamtam_again.population_local_archive_resolution._fills', return_value=(partial_fills, partial_cov)), \
                patch('tamtam_again.population_local_archive_resolution._quotes', return_value=([], no_quotes)):
            outcome = execute(self.store, task['request_id'], repo_root=self.temp.name)
        self.assertEqual(outcome['status'], 'prepared')
        self.assertEqual(outcome['resolution']['coverage']['classification'], 'partial')
        self.assertEqual(outcome['resolution']['coverage']['fills']['exact_join_rows'], 1)
        self.assertEqual(outcome['resolution']['coverage']['quotes']['classification'], 'absent')
        artifact = json.loads(self.store.connection.execute('select artifact_json from population_local_archive_resolutions '
            'where request_id=?', (task['request_id'],)).fetchone()[0])
        self.assertEqual(artifact['schema_version'], 'population-local-archive-resolution-v1')
        self.assertEqual(artifact['calculation_contract']['scope']['market'], 'ETH')
        self.assertEqual(artifact['reconciliation']['fills_used_for_calculations'], 4)
        self.assertEqual(artifact['reconciliation']['statistics_include_all_fills'], True)
        self.assertTrue(all(row['order_id'] is None for row in artifact['fills'][1:]))
        self.assertEqual(artifact['inventory_matrix'][0]['classification'], 'partially_covered_exploitable')
        self.assertEqual(artifact['inventory_matrix'][1]['classification'], 'absent')
        self.assertEqual(artifact['inventory_matrix'][5]['classification'],
            'requires_new_prospective_evidence_not_in_this_archive')

    def test_missing_source_is_data_wait_and_unknown_calculation_is_precise_technical_diagnostic(self):
        missing = add_task(self.store, suffix='missing', address='0x' + 'd' * 40, market='ETH', missing_source=True)
        missing_route = route(self.store, missing['request_id'])
        self.assertEqual(missing_route['state'], 'local_archive_data_required')
        self.assertEqual(missing_route['validation_diagnostic']['code'], 'source_report_unavailable')
        unsupported = add_task(self.store, suffix='unsupported', address='0x' + 'e' * 40, market='BTC', unsupported=True)
        route_value = route(self.store, unsupported['request_id'])
        self.assertEqual(route_value['state'], 'technical_required')
        self.assertEqual(route_value['validation_diagnostic']['code'], 'calculation_set_unsupported')
        self.assertEqual(route_value['validation_diagnostic']['field'], 'operations')

    def test_reference_fingerprint_mismatch_is_technical_and_pilot_scope_needs_authorization(self):
        bad_refs = add_task(self.store, suffix='bad-refs', address='0x' + 'f' * 40, market='ETH')
        packet = json.loads(self.store.connection.execute('select packet_json from population_research_jobs where request_id=?',
            (bad_refs['request_id'],)).fetchone()[0])
        packet['local_analysis_contract_v1']['source']['quote_reference_fingerprint'] = 'f' * 64
        packet.pop('fingerprint'); packet['fingerprint'] = fingerprint(packet)
        self.store.connection.execute('update population_research_jobs set packet_json=? where request_id=?',
            (canonical(packet), bad_refs['request_id'])); self.store.connection.commit()
        routed = route(self.store, bad_refs['request_id'])
        self.assertEqual(routed['state'], 'technical_required')
        self.assertEqual(routed['validation_diagnostic']['code'], 'source_reference_fingerprint_mismatch')

        pilot = add_task(self.store, suffix='pilot-no-auth', address='0x' + '9' * 40, market='ETH')
        packet = json.loads(self.store.connection.execute('select packet_json from population_research_jobs where request_id=?',
            (pilot['request_id'],)).fetchone()[0])
        packet['pilot_research'] = {'candidate': 'authorized-pilot'}
        packet.pop('fingerprint'); packet['fingerprint'] = fingerprint(packet)
        self.store.connection.execute('update population_research_jobs set packet_json=? where request_id=?',
            (canonical(packet), pilot['request_id'])); self.store.connection.commit()
        with self.assertRaisesRegex(PermissionError, 'authorization is missing'):
            execute(self.store, pilot['request_id'], repo_root=self.temp.name)

    def test_archive_readers_apply_reference_allowlists_and_preserve_cutoff_and_window(self):
        from tamtam_again.eth_prospective_observation import _fills, _quotes, _iso

        now = now_ms()
        start_ms, end_ms, cutoff_ms = now - 60_000, now + 60_000, now + 120_000
        address = '0x' + '1' * 40
        protocol = {'protocol_id': 'reader-contract', 'network': 'hyperliquid-mainnet',
            'address': address, 'market': 'ETH', 'start_ms': start_ms, 'end_ms': end_ms,
            'fill_source': 'hyperliquid-prospective-observation-v1',
            'quote_source': 'hyperliquid-websocket-v1'}

        def save(source, entity_type, entity_id, endpoint, payload):
            self.store.save_observation(network='hyperliquid-mainnet', source=source,
                entity_type=entity_type, entity_id=entity_id, endpoint=endpoint, payload=payload,
                request_payload={'fixture': endpoint}, requested_at=_iso(now), record_count=1, complete=True)
            row = self.store.connection.execute('select observation_id,response_sha256 from raw_observations '
                'order by observation_id desc limit 1').fetchone()
            return {'observation_id': row['observation_id'], 'sha256': row['response_sha256']}

        fill_ref = save(protocol['fill_source'], 'account', address, 'userFillsByTime', [
            {'coin': 'ETH', 'tid': 'allowlisted', 'time': now-10_000, 'side': 'B',
                'startPosition': '0', 'sz': '0.1', 'px': '100', 'fee': '0', 'feeToken': 'USDC'}])
        save(protocol['fill_source'], 'account', address, 'userFillsByTime', [
            {'coin': 'ETH', 'tid': 'unreferenced', 'time': now-9_000, 'side': 'B',
                'startPosition': '0', 'sz': '0.1', 'px': '100', 'fee': '0', 'feeToken': 'USDC'}])

        def bbo(event_ms):
            return {'channel': 'bbo', 'data': {'coin': 'ETH', 'time': event_ms,
                'bbo': [{'px': '99', 'sz': '2'}, {'px': '101', 'sz': '3'}]}}

        valid_quote = save(protocol['quote_source'], 'market', 'ETH', 'bbo', bbo(now-20_000))
        before_window = save(protocol['quote_source'], 'market', 'ETH', 'bbo', bbo(start_ms-1_000))
        late_quote = save(protocol['quote_source'], 'market', 'ETH', 'bbo', bbo(now-5_000))
        unreferenced_quote = save(protocol['quote_source'], 'market', 'ETH', 'bbo', bbo(now-4_000))
        self.store.connection.execute('update raw_observations set observed_at=? where observation_id=?',
            (_iso(cutoff_ms+1_000), late_quote['observation_id']))
        self.store.connection.commit()

        fills, fill_cov = _fills(self.store, protocol, cutoff_ms, allowed_source_refs=[fill_ref])
        self.assertEqual([row['tid'] for row in fills], ['allowlisted'])
        self.assertEqual(fill_cov['reference_coverage']['matched_ref_count'], 1)
        self.assertEqual(fill_cov['reference_coverage']['unreferenced_archive_page_count'], 1)

        refs = [valid_quote, before_window, late_quote]
        quotes, quote_cov = _quotes(self.store, protocol, cutoff_ms, allowed_source_refs=refs)
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0]['observation_id'], valid_quote['observation_id'])
        self.assertEqual(quote_cov['rejected_events']['event_time_before_window'], 1)
        self.assertEqual(quote_cov['reference_coverage']['missing_ref_count'], 1)
        self.assertEqual(quote_cov['reference_coverage']['unreferenced_archive_lot_count'], 1)
        self.assertEqual(quote_cov['reference_coverage']['sha256_mismatch_count'], 0)

    def test_a_blocked_resolution_does_not_consume_the_next_scheduler_slot(self):
        blocked = add_task(self.store, suffix='blocked-first', address='0x' + '2' * 40, market='ETH')
        ready = add_task(self.store, suffix='ready-second', address='0x' + '3' * 40, market='BTC',
            offset=10 * 86_400_000)
        policy = json.loads((ROOT / 'config/population-research-policy.json').read_text())

        def load_fills(store, protocol, cutoff, *, allowed_source_refs=None):
            if protocol['protocol_id'] == blocked['protocol_id']:
                raise ValueError('fixture decode failure')
            self.assertEqual(allowed_source_refs, ready['report_refs']['fills'])
            return ready['fills'], ready['fill_cov']

        def load_quotes(store, protocol, cutoff, *, allowed_source_refs=None):
            self.assertEqual(protocol['protocol_id'], ready['protocol_id'])
            self.assertEqual(allowed_source_refs, ready['report_refs']['quotes'])
            return ready['quotes'], ready['quote_cov']

        real_execute = execute
        def execute_in_temp(store, request_id):
            return real_execute(store, request_id, repo_root=self.temp.name)

        with patch('tamtam_again.population_local_archive_resolution.execute', side_effect=execute_in_temp), \
                patch('tamtam_again.population_local_archive_resolution._fills', side_effect=load_fills), \
                patch('tamtam_again.population_local_archive_resolution._quotes', side_effect=load_quotes):
            result = tick(self.store, 'hyperliquid-mainnet', policy, dispatch=False, max_jobs=1)
        by_request = {item['request_id']: item for item in result['local_resolutions']}
        self.assertEqual(by_request[blocked['request_id']]['status'], 'blocked')
        self.assertEqual(by_request[ready['request_id']]['status'], 'prepared')
        saved = self.store.connection.execute('select result_json from population_research_jobs where request_id=?',
            (ready['request_id'],)).fetchone()
        self.assertIn('local_archive_resolutions_v1', json.loads(saved['result_json']))


if __name__ == '__main__':
    unittest.main()

"""Representation changes cannot buy another continuous research inference."""
from decimal import Decimal, localcontext
import unittest

from tests import test_population_descriptive as fixtures
from tamtam_again.population_descriptive import (
    _load_fills, load_research_fill_evidence, prepare_candidate_market_detail)
from tamtam_again.continuous_research_identity import semantic_identity


class WSFillSemanticProjectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PopulationDescriptiveTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def evidence(self):
        f = self.fixture
        return load_research_fill_evidence(f.store, f.network, f.address, f.cutoff,
            ws_start_ms=100)

    def identity(self):
        f = self.fixture
        detail = prepare_candidate_market_detail(f.store, f.network, f.address,
            market='COIN', cutoff_ms=f.cutoff, include_ws=True, ws_start_ms=100)
        return semantic_identity({'network': f.network, 'address': f.address,
            'observations': {'market_execution_detail_v1': {'COIN': detail}}}, 'COIN')

    def test_equivalent_ws_and_rest_receipts_do_not_change_inference_identity(self):
        f = self.fixture
        f._ws_raw(1, [f._execution(oid=123)], observed=192, received=190)
        initial = self.identity()
        # Decimal notation, ID transport type and nonfinancial metadata change.
        duplicate = f._execution(px='10.0', sz='1.000', fee='0.010', oid='123',
            transport_note={'received_again': True}, liquidation='unverified prose')
        f._ws_raw(2, [duplicate], observed=195, received=194)
        self.assertEqual(initial, self.identity())
        f._raw(3, 'userFillsByTime', [duplicate], observed=196)
        self.assertEqual(initial, self.identity())
        fills, coverage, _, proofs = self.evidence()
        self.assertEqual(coverage['conflicting_fill_identity_count'], 0)
        self.assertEqual(len(proofs['one']), 3)
        self.assertEqual(fills[0]['oid'], '123')
        self.assertEqual(fills[0]['time'], 150)
        self.assertNotIn('transport_note', fills[0])
        self.assertNotIn('liquidation', fills[0])

    def test_new_fee_conflict_and_new_execution_change_identity(self):
        f = self.fixture
        f._ws_raw(1, [f._execution()], observed=192, received=190)
        initial = self.identity()
        f._ws_raw(2, [f._execution('two')], observed=194, received=193)
        self.assertNotEqual(initial, self.identity())
        two_fills = self.identity()
        f._ws_raw(3, [f._execution(fee='0.02')], observed=196, received=195)
        self.assertNotEqual(two_fills, self.identity())
        fills, coverage, _, _ = self.evidence()
        self.assertEqual([fill['tid'] for fill in fills], ['two'])
        self.assertEqual(coverage['conflicting_fill_id_examples'], ['one'])

    def test_default_rest_loader_remains_lossless_and_unchanged(self):
        f = self.fixture
        rest = f._execution(px='10.000', sz='1.00', tid=7,
            transport_note='legacy representation')
        f._raw(1, 'userFillsByTime', [rest])
        f._ws_raw(2, [f._execution('ws-only')])
        fills, _, _ = _load_fills(f.store, f.network, f.address, f.cutoff)
        self.assertEqual(fills, [rest])
        self.assertEqual(type(fills[0]['tid']), int)

    def test_high_precision_decimal_projection_never_rounds(self):
        f = self.fixture
        price = '123456789012345678901234567890.12345678901234567890123456789100'
        size = '0.0000000000000000000000000001234567890123456789012345678900'
        f._ws_raw(1, [f._execution(px=price, sz=size, fee='-0.000')])
        # Even an intentionally low caller precision cannot affect identity.
        with localcontext() as context:
            context.prec = 6
            projected = self.evidence()[0][0]
        self.assertEqual(projected['px'], price.rstrip('0'))
        self.assertEqual(Decimal(projected['sz']), Decimal(size))
        self.assertEqual(projected['fee'], '0')
        self.assertEqual(type(projected['time']), int)

    def test_structured_liquidation_financial_fields_are_canonical(self):
        f = self.fixture
        liquidation = {'liquidatedUser': '0x' + 'A' * 40, 'markPx': '10.00', 'method': 'market'}
        f._ws_raw(1, [f._execution(liquidation=liquidation)])
        projected = self.evidence()[0][0]['liquidation']
        self.assertEqual(projected, {**liquidation,
            'liquidatedUser': liquidation['liquidatedUser'].lower(), 'markPx': '10'})


if __name__ == '__main__':
    unittest.main()

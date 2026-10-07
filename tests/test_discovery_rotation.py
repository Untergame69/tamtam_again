import unittest
from tamtam_again.discovery_rotation import select_markets


class RotationTests(unittest.TestCase):
    def catalog(self):
        return {'available_ms': 0, 'instruments': {
            name: {'dex': dex, 'is_delisted': name == 'OLD'}
            for name, dex in [('BTC', ''), ('ETH', ''), ('SOL', ''),
                              ('xyz:GOLD', 'xyz'), ('xyz:CL', 'xyz'),
                              ('OLD', '')]}}

    def test_rotation_covers_all_eligible_markets(self):
        seen = set()
        for epoch in range(4):
            result = select_markets(self.catalog(), now_ms=epoch * 900000,
                                    protected={'xyz:CL'}, limit=2)
            self.assertEqual(len(set(result['markets'])), 2)
            seen.update(result['markets'])
        self.assertEqual(seen, {'BTC', 'ETH', 'SOL', 'xyz:GOLD'})

    def test_repeat_and_catalog_order_independent(self):
        catalog = self.catalog()
        other = {**catalog, 'instruments': dict(reversed(list(catalog['instruments'].items())))}
        self.assertEqual(select_markets(catalog, now_ms=900000, protected=set()),
                         select_markets(other, now_ms=900000, protected=set()))

    def test_future_catalog_rejected(self):
        with self.assertRaises(ValueError):
            select_markets({**self.catalog(), 'available_ms': 10},
                           now_ms=9, protected=set())

    def test_empty_and_small_universe(self):
        self.assertEqual(select_markets({'available_ms': 0, 'instruments': {}},
                                       now_ms=0, protected=set())['markets'], [])
        self.assertEqual(len(select_markets(self.catalog(), now_ms=0,
                                           protected=set(), limit=10)['markets']), 5)

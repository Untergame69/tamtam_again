import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tamtam_again.isolation import command, verify

class IsolationTests(unittest.TestCase):
    def test_actual_runtime_cannot_read_host_canary(self):
        with tempfile.TemporaryDirectory(prefix='reserved-canary-') as directory:
            path = Path(directory)/'reserved.json'
            path.write_text('FINAL_DATA_MUST_NOT_BE_VISIBLE')
            result = verify(probe_paths=[str(path)])
            self.assertTrue(result['isolation_verified'])
            self.assertEqual(result['tools'], 0)
            self.assertEqual(path.read_text(), 'FINAL_DATA_MUST_NOT_BE_VISIBLE')

    def test_missing_isolator_fails_closed(self):
        with patch('tamtam_again.isolation.shutil.which', return_value=None):
            with self.assertRaises(RuntimeError):
                command(Path('/tmp'))

    def test_environment_and_mounts_are_explicit(self):
        args = command(Path('/tmp/fresh-home'), offline=True)
        self.assertIn('--clearenv', args)
        self.assertIn('--unshare-net', args)
        self.assertNotIn('/home/Untergame', args)
        self.assertNotIn('/home/Untergame/tamtam_again', args)
        self.assertNotIn('/home/Untergame/.hermes', args)

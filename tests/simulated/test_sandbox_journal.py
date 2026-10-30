
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sandbox"))
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sandbox_cleanup import PATHS, sandbox_auth
from sandbox_journal import add, create, load


class JournalTests(unittest.TestCase):
    def test_run_journal_round_trip_and_duplicate_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run.json'
            journal = create(path, 'TESTUSER_seller')
            add(path, journal, 'offer', '123')
            self.assertEqual(load(path)['resources'][0]['id'], '123')
            with self.assertRaises(ValueError):
                add(path, journal, 'offer', '123')
            with self.assertRaises(ValueError):
                create(path, 'TESTUSER_seller')

    def test_cleanup_refuses_production_before_fetching_token(self):
        with patch('sandbox_cleanup.load_settings', return_value={'EBAY_ENV': 'production'}), patch('sandbox_cleanup.get_seller_auth') as auth:
            with self.assertRaises(ValueError):
                sandbox_auth()
            auth.assert_not_called()

    def test_cleanup_routes_are_fixed_sandbox_resource_types(self):
        self.assertEqual(set(PATHS), {'offer', 'inventory_item', 'location', 'fulfillment_policy', 'payment_policy', 'return_policy'})
        self.assertTrue(all(path.startswith('/sell/') for path in PATHS.values()))

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sandbox'))
import verify_canadian_reads as checks
from sandbox_journal import create


class VerificationTests(unittest.TestCase):
    def test_contains_finds_nested_ids_without_substring_matches(self):
        self.assertTrue(checks.contains({'items': [{'id': '123'}]}, '123'))
        self.assertFalse(checks.contains({'items': [{'id': '1234'}]}, '123'))

    def test_rejects_unidentified_marketplace_before_fetching_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run.json'
            create(path, 'seller')
            with patch.object(checks, 'get_seller_auth') as auth:
                with self.assertRaisesRegex(ValueError, 'Canadian journal'):
                    asyncio.run(checks.verify(path))
                auth.assert_not_called()

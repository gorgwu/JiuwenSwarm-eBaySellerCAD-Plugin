"""Keep the live Sandbox case inventory in sync with registered actions."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sandbox"))
import unittest
from unittest.mock import patch

from sandbox_cases import CASES, resolve
from sandbox_tools import actions, check_sandbox


class SandboxCasesTests(unittest.TestCase):
    def test_every_registered_action_has_one_case(self):
        self.assertEqual(set(CASES), set(actions()))
        self.assertTrue(all(case['verify'] for case in CASES.values()))

    def test_fixture_resolution_and_missing_values(self):
        self.assertEqual(resolve({'params': {'sku': '$sku'}}, {'sku': 'test'}), {'params': {'sku': 'test'}})
        with self.assertRaisesRegex(ValueError, 'Missing fixture: sku'):
            resolve('$sku', {})
        with self.assertRaisesRegex(ValueError, 'Missing fixture: body'):
            resolve('$body', {'body': None})

    def test_production_refused_before_authentication(self):
        with patch('sandbox_tools.load_settings', return_value={'EBAY_ENV': 'production'}), patch('sandbox_tools.get_seller_auth') as auth:
            with self.assertRaisesRegex(ValueError, 'sandbox'):
                check_sandbox()
            auth.assert_not_called()

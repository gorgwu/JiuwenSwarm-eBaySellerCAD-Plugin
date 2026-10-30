"""Sandbox marketplace selection must never silently use the wrong site."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sandbox'))
import sandbox_marketplace
from sandbox_tools import marketplace_input


class MarketplaceTests(unittest.TestCase):
    def test_canadian_seller_counteroffer_preserves_listing_currency(self):
        for currency in ('CAD', 'USD'):
            with self.subTest(currency=currency):
                result = marketplace_input('respond_to_best_offer', {'params': {'currency': currency}}, 'EBAY_CA')
                self.assertEqual(result['params']['currency'], currency)
                self.assertEqual(result['params']['site_id'], 2)
    def test_config_and_override(self):
        with patch.object(sandbox_marketplace, 'load_settings', return_value={'EBAY_MARKETPLACE_ID': 'EBAY_CA'}):
            self.assertEqual(sandbox_marketplace.test_marketplace(), 'EBAY_CA')
            self.assertEqual(sandbox_marketplace.test_marketplace('EBAY_CA'), 'EBAY_CA')

    def test_unknown_marketplace_is_rejected(self):
        with patch.object(sandbox_marketplace, 'load_settings', return_value={'EBAY_MARKETPLACE_ID': 'EBAY_GB'}):
            with self.assertRaises(ValueError):
                sandbox_marketplace.test_marketplace()

    def test_missing_setting_defaults_to_canada(self):
        with patch.object(sandbox_marketplace, 'load_settings', return_value={}):
            self.assertEqual(sandbox_marketplace.test_marketplace(), 'EBAY_CA')

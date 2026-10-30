"""Offline contract tests for the live fixture bootstrap."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sandbox'))
import sandbox_bootstrap as bootstrap
from ebayseller_common.oauth import EbayAuth


class FakeRead:
    async def invoke(self, payload):
        action = payload['action']
        if action == 'get_seller_account':
            return {'success': True, 'response': {'User': {'UserID': 'TESTUSER_seller'}}}
        if action in {'get_inventory_location', 'get_inventory_item'}:
            return {'success': False, 'http_status': 404}
        if action == 'list_fulfillment_policies':
            return {'success': True, 'data': {'fulfillmentPolicies': [{'fulfillmentPolicyId': 'existing',
                'marketplaceId': 'EBAY_CA', 'categoryTypes': [{'name': 'ALL_EXCLUDING_MOTORS_VEHICLES'}]}]}}
        raise AssertionError(action)


class FakeWrite:
    async def invoke(self, payload):
        action = payload['action']
        ids = {'create_fulfillment_policy': ('fulfillmentPolicyId', 'shipping'),
               'create_payment_policy': ('paymentPolicyId', 'payment'),
               'create_return_policy': ('returnPolicyId', 'return'),
               'create_inventory_offer': ('offerId', 'offer'),
               'publish_inventory_offer': ('listingId', '200')}
        key, value = ids.get(action, (None, None))
        return {'success': True, 'data': {key: value} if key else {}}


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_creates_journal_and_generated_fixture_ids(self):
        def fake_trading(call, fields, site_id=0):
            return {'success': True, 'response': {'ItemID': '300'} if call == 'AddFixedPriceItem' else {}}
        with tempfile.TemporaryDirectory() as directory:
            journal_path = Path(directory) / 'run.json'
            with patch.object(bootstrap, 'load_settings', return_value={'EBAY_ENV': 'sandbox'}), \
                 patch.object(bootstrap, 'get_seller_auth', return_value=EbayAuth('sandbox', 'https://api.sandbox.ebay.com', 'fake')), \
                 patch.object(bootstrap, 'EbaySellerReadTool', FakeRead), patch.object(bootstrap, 'EbaySellerListingWriteTool', FakeWrite), \
                 patch.object(bootstrap, 'opt_in_if_needed'), patch.object(bootstrap, '_trading', side_effect=fake_trading):
                fixture_path = asyncio.run(bootstrap.bootstrap(journal_path, marketplace='EBAY_CA'))
            from sandbox_journal import load
            journal = load(journal_path)
            self.assertEqual(len(journal['resources']), 7)
            self.assertEqual(journal['fixtures']['listing_id'], '300')
            self.assertEqual(journal['fixtures']['inventory_listing_id'], '200')
            self.assertEqual(journal['unresolved'], [])
            self.assertTrue(fixture_path.exists())

    def test_refuses_production_before_access(self):
        with patch.object(bootstrap, 'load_settings', return_value={'EBAY_ENV': 'production'}), patch.object(bootstrap, 'get_seller_auth') as auth:
            with self.assertRaises(ValueError):
                asyncio.run(bootstrap.bootstrap(Path('unused')))
            auth.assert_not_called()

    def test_reused_policy_is_not_recorded_for_cleanup(self):
        def fake_trading(call, fields, site_id=0):
            return {'success': True, 'response': {'ItemID': '300'} if call == 'AddFixedPriceItem' else {}}
        with tempfile.TemporaryDirectory() as directory:
            journal_path = Path(directory) / 'run.json'
            with patch.object(bootstrap, 'load_settings', return_value={'EBAY_ENV': 'sandbox'}), \
                 patch.object(bootstrap, 'get_seller_auth', return_value=EbayAuth('sandbox', 'https://api.sandbox.ebay.com', 'fake')), \
                 patch.object(bootstrap, 'EbaySellerReadTool', FakeRead), patch.object(bootstrap, 'EbaySellerListingWriteTool', FakeWrite), \
                 patch.object(bootstrap, 'opt_in_if_needed'), patch.object(bootstrap, '_trading', side_effect=fake_trading):
                asyncio.run(bootstrap.bootstrap(journal_path, reuse_fulfillment_policy_id='existing', marketplace='EBAY_CA'))
            from sandbox_journal import load
            journal = load(journal_path)
            self.assertFalse(any(r['kind'] == 'fulfillment_policy' for r in journal['resources']))
            self.assertTrue(any(r['id'] == 'existing' for r in journal['reused']))

    def test_canadian_fixture_fields_and_trading_site(self):
        calls = []
        def fake_trading(call, fields, site_id=0):
            calls.append((call, fields, site_id))
            return {'success': True, 'response': {'ItemID': '300'} if call == 'AddFixedPriceItem' else {}}
        with tempfile.TemporaryDirectory() as directory:
            journal_path = Path(directory) / 'run.json'
            with patch.object(bootstrap, 'load_settings', return_value={'EBAY_ENV': 'sandbox'}), \
                 patch.object(bootstrap, 'get_seller_auth', return_value=EbayAuth('sandbox', 'https://api.sandbox.ebay.com', 'fake')), \
                 patch.object(bootstrap, 'EbaySellerReadTool', FakeRead), patch.object(bootstrap, 'EbaySellerListingWriteTool', FakeWrite), \
                 patch.object(bootstrap, 'opt_in_if_needed'), patch.object(bootstrap, '_trading', side_effect=fake_trading):
                asyncio.run(bootstrap.bootstrap(journal_path, marketplace='EBAY_CA'))
            from sandbox_journal import load
            journal = load(journal_path)
            self.assertEqual(journal['site_id'], 2)
            self.assertEqual(journal['fixtures']['inventory_offer_body']['marketplaceId'], 'EBAY_CA')
            self.assertEqual(journal['fixtures']['inventory_offer_body']['pricingSummary']['price']['currency'], 'CAD')
            self.assertEqual(journal['fixtures']['fulfillment_policy_body']['shippingOptions'][0]['shippingServices'][0]['shippingCarrierCode'], 'CPC')
            self.assertEqual(calls[0][2], 2)
            self.assertEqual(calls[0][1]['Item']['Country'], 'CA')

    def test_canadian_usd_listing_fixtures_keep_currency(self):
        def fake_trading(call, fields, site_id=2):
            self.assertEqual(fields['Item']['Currency'], 'USD')
            return {'success': True, 'response': {'ItemID': '300'} if call == 'AddFixedPriceItem' else {}}
        with tempfile.TemporaryDirectory() as directory:
            journal_path = Path(directory) / 'run.json'
            with patch.object(bootstrap, 'load_settings', return_value={'EBAY_ENV': 'sandbox'}), \
                 patch.object(bootstrap, 'get_seller_auth', return_value=EbayAuth('sandbox', 'https://api.sandbox.ebay.com', 'fake')), \
                 patch.object(bootstrap, 'EbaySellerReadTool', FakeRead), patch.object(bootstrap, 'EbaySellerListingWriteTool', FakeWrite), \
                 patch.object(bootstrap, 'opt_in_if_needed'), patch.object(bootstrap, '_trading', side_effect=fake_trading):
                asyncio.run(bootstrap.bootstrap(journal_path, currency='USD'))
            from sandbox_journal import load
            self.assertEqual(load(journal_path)['fixtures']['inventory_offer_body']['pricingSummary']['price']['currency'], 'USD')

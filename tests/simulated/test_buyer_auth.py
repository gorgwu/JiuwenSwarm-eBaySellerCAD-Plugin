"""Verify sandbox buyer token selection without contacting eBay."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sandbox'))
from ebayseller_common import oauth
import sandbox_buyer_offer


class BuyerAuthTests(unittest.TestCase):
    def test_listing_currency_is_read_from_item(self):
        from ebayseller_common.oauth import EbayAuth
        auth = EbayAuth('sandbox', 'https://api.sandbox.ebay.com', 'fake')
        class Response:
            def __init__(self, value): self.value = value
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return f'<GetItemResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Success</Ack><Item><Currency>{self.value}</Currency></Item></GetItemResponse>'.encode()
        for currency in ('CAD', 'USD'):
            with self.subTest(currency=currency), patch('urllib.request.urlopen', return_value=Response(currency)):
                self.assertEqual(sandbox_buyer_offer.listing_currency(auth, '123'), currency)
        with patch('urllib.request.urlopen', return_value=Response('')):
            with self.assertRaisesRegex(ValueError, 'Could not verify'):
                sandbox_buyer_offer.listing_currency(auth, '123')
    def test_identity_request_has_xml_encoding_and_uses_sandbox(self):
        from ebayseller_common.oauth import EbayAuth
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'<GetUserResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Success</Ack><User><UserID>buyer</UserID></User></GetUserResponse>'
        with patch('urllib.request.urlopen', return_value=Response()) as request:
            self.assertEqual(sandbox_buyer_offer.sandbox_user_id(EbayAuth('sandbox', 'https://api.sandbox.ebay.com', 'fake')), 'buyer')
        self.assertTrue(request.call_args.args[0].data.startswith(b'<?xml version="1.0" encoding="utf-8"?>'))

    def test_refresh_uses_buyer_not_seller(self):
        settings = {'EBAY_ENV': 'sandbox', 'EBAY_SANDBOX_USER_REFRESH_TOKEN': 'seller',
                    'EBAY_SANDBOX_BUYER_REFRESH_TOKEN': 'buyer', 'EBAY_SANDBOX_USER_ACCESS_TOKEN': 'seller-access'}
        with patch.object(oauth, 'load_settings', return_value=settings), patch.object(oauth, 'user_access_token', return_value='buyer-access') as refresh:
            auth = oauth.get_sandbox_buyer_auth()
        self.assertEqual(auth.access_token, 'buyer-access')
        selected = refresh.call_args.args[2]
        self.assertEqual(selected['EBAY_SANDBOX_USER_REFRESH_TOKEN'], 'buyer')
        self.assertNotIn('EBAY_SANDBOX_USER_ACCESS_TOKEN', selected)
        self.assertEqual(settings['EBAY_SANDBOX_USER_REFRESH_TOKEN'], 'seller')

    def test_buyer_must_have_separate_token_and_sandbox_environment(self):
        for settings in ({'EBAY_ENV': 'sandbox', 'EBAY_SANDBOX_USER_REFRESH_TOKEN': 'seller'},
                         {'EBAY_ENV': 'production', 'EBAY_SANDBOX_BUYER_REFRESH_TOKEN': 'buyer'}):
            with self.subTest(settings=settings), patch.object(oauth, 'load_settings', return_value=settings), patch.object(oauth, 'user_access_token') as refresh:
                with self.assertRaises(ValueError):
                    oauth.get_sandbox_buyer_auth()
                refresh.assert_not_called()

    def test_same_buyer_and_seller_rejected_before_offer_submission(self):
        from ebayseller_common.oauth import EbayAuth
        auth = EbayAuth('sandbox', 'https://api.sandbox.ebay.com', 'fake')
        with patch.object(sys, 'argv', ['sandbox_buyer_offer.py', '--listing-id', '123']), \
             patch.object(sandbox_buyer_offer, 'get_sandbox_buyer_auth', return_value=auth), \
             patch.object(sandbox_buyer_offer, 'get_seller_auth', return_value=auth), \
             patch.object(sandbox_buyer_offer, 'sandbox_user_id', return_value='same-user'), \
             patch('builtins.input') as confirm:
            with self.assertRaisesRegex(ValueError, 'same account'):
                sandbox_buyer_offer.main()
            confirm.assert_not_called()

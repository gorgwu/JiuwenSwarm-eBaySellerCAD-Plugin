"""Offline contract coverage of each registered seller action; no eBay calls."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sandbox"))
import asyncio
import json
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, patch

from common.oauth import EbayAuth
from tools import ebay_seller_tools as seller
from sandbox_cases import CASES, resolve
from sandbox_tools import actions, marketplace_input
from test_seller_tools import Response

AUTH = EbayAuth('sandbox', 'https://api.sandbox.ebay.com', 'fake-token')
REST = {
    'list_inventory_items': ('GET', '/sell/inventory/v1/inventory_item'),
    'get_inventory_item': ('GET', '/sell/inventory/v1/inventory_item/test-sku'),
    'list_inventory_offers': ('GET', '/sell/inventory/v1/offer'),
    'get_inventory_offer': ('GET', '/sell/inventory/v1/offer/42'),
    'list_inventory_locations': ('GET', '/sell/inventory/v1/location'),
    'get_inventory_location': ('GET', '/sell/inventory/v1/location/test-location'),
    'list_orders': ('GET', '/sell/fulfillment/v1/order'),
    'list_fulfillment_policies': ('GET', '/sell/account/v1/fulfillment_policy'),
    'list_payment_policies': ('GET', '/sell/account/v1/payment_policy'),
    'list_return_policies': ('GET', '/sell/account/v1/return_policy'),
    'find_eligible_items': ('GET', '/sell/negotiation/v1/find_eligible_items'),
    'get_default_category_tree': ('GET', '/commerce/taxonomy/v1/get_default_category_tree_id'),
    'get_category_suggestions': ('GET', '/commerce/taxonomy/v1/category_tree/2/get_category_suggestions'),
    'get_category_aspects': ('GET', '/commerce/taxonomy/v1/category_tree/2/get_item_aspects_for_category'),
    'create_fulfillment_policy': ('POST', '/sell/account/v1/fulfillment_policy'),
    'create_payment_policy': ('POST', '/sell/account/v1/payment_policy'),
    'create_return_policy': ('POST', '/sell/account/v1/return_policy'),
    'create_inventory_location': ('POST', '/sell/inventory/v1/location/test-location'),
    'put_inventory_item': ('PUT', '/sell/inventory/v1/inventory_item/test-sku'),
    'create_inventory_offer': ('POST', '/sell/inventory/v1/offer'),
    'update_inventory_offer': ('PUT', '/sell/inventory/v1/offer/42'),
    'publish_inventory_offer': ('POST', '/sell/inventory/v1/offer/42/publish'),
    'withdraw_inventory_offer': ('POST', '/sell/inventory/v1/offer/42/withdraw'),
    'update_price_quantity': ('POST', '/sell/inventory/v1/bulk_update_price_quantity'),
    'send_offer_to_interested_buyers': ('POST', '/sell/negotiation/v1/send_offer_to_interested_buyers'),
}
TRADING = {'get_seller_account': 'GetUser', 'get_seller_feedback': 'GetFeedback',
           'list_listings': 'GetMyeBaySelling', 'get_listing': 'GetItem',
           'revise_listing': 'ReviseItem', 'end_listing': 'EndItem',
           'respond_to_best_offer': 'RespondToBestOffer'}
FIXTURES = {'listing_id': '123', 'trading_listing_id': '123', 'sku': 'test-sku',
            'inventory_offer_id': '42', 'location_key': 'test-location', 'order_id': 'order-1',
            'currency': 'CAD', 'fulfillment_id': 'shipment-1', 'best_offer_id': '456', 'revised_title': 'Test title'}
for field in ('fulfillment_policy_body', 'payment_policy_body', 'return_policy_body',
              'inventory_item_body', 'location_body', 'inventory_offer_body', 'bulk_update_body',
              'shipping_body', 'refund_body', 'interested_offer_body'):
    FIXTURES[field] = {'test': 'fixture'}


class ActionContracts(unittest.TestCase):
    def test_each_action_accepts_canadian_test_inputs(self):
        for name, cls in actions().items():
            with self.subTest(action=name):
                calls = []
                def fake_open(request, timeout):
                    calls.append(request)
                    call = request.get_header('X-ebay-api-call-name')
                    if call:
                        user = '<User><UserID>seller</UserID></User>' if call == 'GetUser' else ''
                        return Response(f'<{call}Response xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Success</Ack>{user}</{call}Response>'.encode())
                    return Response(b'{}')
                data = marketplace_input(name, resolve(CASES[name]['input'], FIXTURES), 'EBAY_CA')
                with patch.object(seller, 'get_seller_auth', return_value=AUTH), patch.object(seller, 'get_application_auth', return_value=AUTH), patch('urllib.request.urlopen', side_effect=fake_open), patch.object(seller.EbayBestOffersTool, 'invoke', new_callable=AsyncMock, return_value={'success': True}) as offers:
                    result = asyncio.run(cls().invoke({'action': name, **data, 'confirm': True}))
                self.assertTrue(result.get('success'), result)
                if name == 'get_best_offers':
                    self.assertEqual(data['params']['site_id'], 2)
                    offers.assert_awaited_once_with(data['params'])
                elif name in TRADING:
                    self.assertEqual(calls[-1].get_header('X-ebay-api-siteid'), '2')
                elif 'body' in data:
                    self.assertEqual(calls[-1].get_header('Content-language'), 'en-CA')
                if name in {'list_fulfillment_policies', 'list_payment_policies', 'list_return_policies', 'get_default_category_tree'}:
                    self.assertIn('marketplace_id=EBAY_CA', calls[-1].full_url)
                if name in {'find_eligible_items', 'send_offer_to_interested_buyers'}:
                    self.assertEqual(calls[-1].get_header('X-ebay-c-marketplace-id'), 'EBAY_CA')

    def test_each_action_sends_expected_request(self):
        registry = actions()
        self.assertEqual(set(registry), set(REST) | set(TRADING) | {'get_best_offers'})
        for name, cls in registry.items():
            with self.subTest(action=name):
                calls = []
                def fake_open(request, timeout):
                    calls.append(request)
                    call = request.get_header('X-ebay-api-call-name')
                    if call:
                        user = '<User><UserID>seller</UserID></User>' if call == 'GetUser' else ''
                        payload = f'<{call}Response xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Success</Ack>{user}</{call}Response>'.encode()
                        return Response(payload)
                    return Response(b'{}')
                data = resolve(CASES[name]['input'], FIXTURES)
                payload = {'action': name, **data, 'confirm': True}
                with patch.object(seller, 'get_seller_auth', return_value=AUTH), patch.object(seller, 'get_application_auth', return_value=AUTH), patch('urllib.request.urlopen', side_effect=fake_open), patch.object(seller.EbayBestOffersTool, 'invoke', new_callable=AsyncMock, return_value={'success': True, 'offers': []}) as offer_read:
                    result = asyncio.run(cls().invoke(payload))
                self.assertTrue(result.get('success'), result)
                if name == 'get_best_offers':
                    offer_read.assert_awaited_once_with(data['params'])
                elif name in REST:
                    self.assertEqual(len(calls), 1)
                    expected_method, expected_path = REST[name]
                    self.assertEqual(calls[0].get_method(), expected_method)
                    self.assertEqual(calls[0].full_url.split('?', 1)[0], AUTH.api_base + expected_path)
                    if 'body' in data:
                        self.assertEqual(json.loads(calls[0].data), data['body'])
                else:
                    self.assertEqual(calls[-1].get_header('X-ebay-api-call-name'), TRADING[name])
                    self.assertEqual(ET.fromstring(calls[-1].data).tag, seller.NS + TRADING[name] + 'Request')


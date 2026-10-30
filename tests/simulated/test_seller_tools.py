"""Offline API contract and permission-boundary tests."""

import asyncio
import io
import json
import socket
import ssl
import unittest
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from ebayseller_common.oauth import EbayAuth
from tools import ebay_seller_tools as seller

AUTH = EbayAuth("sandbox", "https://api.sandbox.ebay.com", "test-token")


class Response:
    def __init__(self, data=b"{}", status=200, headers=None):
        self.data, self.status, self.headers = data, status, headers or {}
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self):
        return self.data


def invoke(tool, action, params=None, **kwargs):
    return asyncio.run(tool.invoke({"action": action, "params": params or {}, **kwargs}))


class SellerToolTests(unittest.TestCase):
    def test_canadian_defaults(self):
        requests = []
        def fake_open(req, timeout):
            requests.append(req)
            if req.get_header('X-ebay-api-call-name'):
                return Response(b'<GetItemResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Success</Ack></GetItemResponse>')
            return Response(b'{}')
        with patch.object(seller, 'get_seller_auth', return_value=AUTH), patch('urllib.request.urlopen', side_effect=fake_open):
            self.assertTrue(invoke(seller.EbaySellerReadTool(), 'get_listing', {'item_id': '123'})['success'])
            self.assertTrue(invoke(seller.EbaySellerReadTool(), 'list_fulfillment_policies')['success'])
            self.assertTrue(invoke(seller.EbaySellerListingWriteTool(), 'create_return_policy', body={'marketplaceId': 'EBAY_CA'}, confirm=True)['success'])
        self.assertEqual(requests[0].get_header('X-ebay-api-siteid'), '2')
        self.assertIn('marketplace_id=EBAY_CA', requests[1].full_url)
        self.assertEqual(requests[2].get_header('Content-language'), 'en-CA')

    def test_rejects_other_marketplace_and_sites_before_network(self):
        with patch.object(seller, 'get_seller_auth', side_effect=AssertionError('auth called')), \
             patch.object(seller, 'get_application_auth', side_effect=AssertionError('auth called')), \
             patch('urllib.request.urlopen', side_effect=AssertionError('network called')):
            for payload in [
                {'action': 'get_listing', 'params': {'item_id': '123', 'site_id': 0}},
                {'action': 'get_listing', 'params': {'item_id': '123', 'site_id': 210}},
                {'action': 'get_best_offers', 'params': {'item_id': '123', 'site_id': 0}},
                {'action': 'get_best_offers', 'params': {'item_id': '123', 'site_id': 210}},
                {'action': 'find_eligible_items', 'params': {'content_language': 'fr-CA'}},
                {'action': 'list_fulfillment_policies', 'params': {'marketplace_id': 'EBAY_US'}},
            ]:
                result = asyncio.run(seller.EbaySellerReadTool().invoke(payload))
                self.assertFalse(result['success'], result)
            result = invoke(seller.EbaySellerListingWriteTool(), 'create_return_policy',
                            body={'marketplaceId': 'EBAY_US'}, confirm=True)
            self.assertFalse(result['success'])

    def test_manifest_loads_all_tool_classes(self):
        from openjiuwen.harness.resources.extension_loader import load_plugin_package
        from openjiuwen.harness.manifest.meta_elements import _load_class_from_file
        root = Path(__file__).resolve().parents[2]
        spec = load_plugin_package(root / "manifest.json")
        self.assertEqual(len(spec.tools), 3)
        path = root / "tools" / "ebay_seller_tools.py"
        names = ("EbaySellerReadTool", "EbaySellerListingWriteTool", "EbaySellerOfferWriteTool")
        tools = [_load_class_from_file(path, name, package_root=root)() for name in names]
        self.assertEqual([tool.card.name for tool in tools], ["ebayseller_read", "ebayseller_listing_write", "ebayseller_offer_write"])
        self.assertTrue(all(invoke(tool, "describe_actions")["actions"] for tool in tools))

    def test_all_writes_require_confirmation_before_auth_or_network(self):
        for cls in (seller.EbaySellerListingWriteTool, seller.EbaySellerOfferWriteTool):
            tool = cls()
            for action in list(tool.actions) + list(tool.extra_actions):
                with self.subTest(action=action), patch.object(seller, "get_seller_auth", side_effect=AssertionError("auth called")), patch("urllib.request.urlopen", side_effect=AssertionError("network called")):
                    result = invoke(tool, action)
                self.assertTrue(result["approval_required"])
                self.assertFalse(result["success"])

    def test_read_routes_use_fixed_host_escaped_path_and_query(self):
        requests = []
        def fake_open(req, timeout):
            requests.append(req)
            return Response(json.dumps({"orders": [], "total": 0, "offset": 0, "limit": 10}).encode())
        with patch.object(seller, "get_seller_auth", return_value=AUTH), patch("urllib.request.urlopen", side_effect=fake_open):
            result = invoke(seller.EbaySellerReadTool(), "get_inventory_item", {"sku": "abc/../123"})
            orders = invoke(seller.EbaySellerReadTool(), "list_orders", {"limit": 10, "offset": 0})
        self.assertTrue(result["success"])
        self.assertEqual(requests[0].full_url, "https://api.sandbox.ebay.com/sell/inventory/v1/inventory_item/abc%2F..%2F123")
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(requests[1].full_url).query), {"limit": ["10"], "offset": ["0"]})
        self.assertEqual(orders["data"]["total"], 0)

    def test_category_action_uses_application_auth(self):
        with patch.object(seller, "get_application_auth", return_value=AUTH) as app, patch.object(seller, "get_seller_auth", side_effect=AssertionError("seller token used")), patch("urllib.request.urlopen", return_value=Response(b'{"categoryTreeId":"0"}')):
            result = invoke(seller.EbaySellerReadTool(), "get_default_category_tree", {"marketplace_id": "EBAY_CA"})
        self.assertTrue(result["success"])
        app.assert_called_once()

    def test_get_listing_requests_item_specifics(self):
        requests = []
        def fake_open(req, timeout):
            requests.append(req)
            return Response(b'<GetItemResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Success</Ack><Item><ItemID>123</ItemID></Item></GetItemResponse>')
        with patch.object(seller, "get_seller_auth", return_value=AUTH), patch("urllib.request.urlopen", side_effect=fake_open):
            result = invoke(seller.EbaySellerReadTool(), "get_listing", {"item_id": "123"})
        self.assertTrue(result["success"])
        root = ET.fromstring(requests[0].data)
        self.assertEqual(root.findtext(seller.NS + "IncludeItemSpecifics"), "true")

    def test_trading_serializes_repeated_item_specifics(self):
        requests = []
        def fake_open(request, timeout):
            requests.append(request)
            return Response(b'<VerifyAddFixedPriceItemResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Success</Ack></VerifyAddFixedPriceItemResponse>')
        specifics = [{'Name': 'Brand', 'Value': 'Unbranded'}, {'Name': 'Color', 'Value': 'White'}]
        with patch.object(seller, 'get_seller_auth', return_value=AUTH), patch('urllib.request.urlopen', side_effect=fake_open):
            result = seller._trading('VerifyAddFixedPriceItem', {'Item': {'ItemSpecifics': {'NameValueList': specifics}}})
        self.assertTrue(result['success'])
        root = ET.fromstring(requests[0].data)
        nodes = root.findall('.//' + seller.NS + 'NameValueList')
        self.assertEqual([node.findtext(seller.NS + 'Name') for node in nodes], ['Brand', 'Color'])

    def test_seller_feedback_resolves_user_then_requests_seller_feedback_page(self):
        requests = []
        def fake_open(req, timeout):
            requests.append(req)
            if req.get_header("X-ebay-api-call-name") == "GetUser":
                return Response(b'<GetUserResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Success</Ack><User><UserID>seller123</UserID></User></GetUserResponse>')
            return Response(b'<GetFeedbackResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Success</Ack><PaginationResult><TotalNumberOfPages>0</TotalNumberOfPages></PaginationResult></GetFeedbackResponse>')
        with patch.object(seller, "get_seller_auth", return_value=AUTH), patch("urllib.request.urlopen", side_effect=fake_open):
            result = invoke(seller.EbaySellerReadTool(), "get_seller_feedback", {"page": 2, "per_page": 50})
        self.assertTrue(result["success"])
        self.assertEqual([r.get_header("X-ebay-api-call-name") for r in requests], ["GetUser", "GetFeedback"])
        root = ET.fromstring(requests[1].data)
        self.assertEqual(root.findtext(seller.NS + "UserID"), "seller123")
        self.assertEqual(root.findtext(seller.NS + "FeedbackType"), "FeedbackReceivedAsSeller")
        self.assertEqual(root.findtext(seller.NS + "Pagination/" + seller.NS + "PageNumber"), "2")
        self.assertEqual(root.findtext(seller.NS + "DetailLevel"), "ReturnAll")

    def test_feedback_does_not_claim_empty_when_account_lookup_fails(self):
        failed = b'<GetUserResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Failure</Ack></GetUserResponse>'
        with patch.object(seller, "get_seller_auth", return_value=AUTH), patch("urllib.request.urlopen", return_value=Response(failed)) as request:
            result = invoke(seller.EbaySellerReadTool(), "get_seller_feedback")
        self.assertFalse(result["success"])
        self.assertEqual(request.call_count, 1)

    def test_business_policy_creation_requests_and_approval(self):
        requests = []
        def fake_open(req, timeout):
            requests.append(req)
            return Response(b'{"policyId":"123"}', 201)
        body = {"name": "Sandbox policy", "marketplaceId": "EBAY_CA", "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}]}
        actions = ("create_fulfillment_policy", "create_payment_policy", "create_return_policy")
        with patch.object(seller, "get_seller_auth", return_value=AUTH), patch("urllib.request.urlopen", side_effect=fake_open):
            results = [invoke(seller.EbaySellerListingWriteTool(), name, body=body, confirm=True) for name in actions]
        self.assertTrue(all(result["success"] for result in results))
        self.assertEqual([request.full_url.rsplit("/", 1)[-1] for request in requests], ["fulfillment_policy", "payment_policy", "return_policy"])
        self.assertTrue(all(request.get_method() == "POST" and json.loads(request.data) == body for request in requests))

    def test_end_listing_rejects_invalid_reason_and_uses_end_item(self):
        requests = []
        def fake_open(req, timeout):
            requests.append(req)
            return Response(b'<EndItemResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Success</Ack></EndItemResponse>')
        with patch.object(seller, "get_seller_auth", return_value=AUTH), patch("urllib.request.urlopen", side_effect=fake_open):
            invalid = invoke(seller.EbaySellerListingWriteTool(), "end_listing", {"item_id":"123", "ending_reason":"ProductDeleted"}, confirm=True)
            success = invoke(seller.EbaySellerListingWriteTool(), "end_listing", {"item_id":"123", "ending_reason":"NotAvailable"}, confirm=True)
        self.assertFalse(invalid["success"])
        self.assertTrue(success["success"])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].get_header("X-ebay-api-call-name"), "EndItem")
        root = ET.fromstring(requests[0].data)
        self.assertEqual(root.findtext(seller.NS + "ItemID"), "123")
        self.assertEqual(root.findtext(seller.NS + "EndingReason"), "NotAvailable")

    def test_inventory_write_request_and_location_response(self):
        requests = []
        def fake_open(req, timeout):
            requests.append(req)
            return Response(b"", 201, {"Location": "https://api.sandbox.ebay.com/example"})
        body = {"product": {"title": "test"}, "condition": "NEW"}
        with patch.object(seller, "get_seller_auth", return_value=AUTH), patch("urllib.request.urlopen", side_effect=fake_open):
            result = invoke(seller.EbaySellerListingWriteTool(), "put_inventory_item", {"sku": "sku 1"}, body=body, confirm=True)
        self.assertTrue(result["success"])
        self.assertEqual(requests[0].get_method(), "PUT")
        self.assertTrue(requests[0].full_url.endswith("/inventory_item/sku%201"))
        self.assertEqual(json.loads(requests[0].data), body)
        self.assertEqual(result["http_status"], 201)

    def test_offer_request_uses_expected_endpoint_and_payload(self):
        requests = []
        def fake_open(req, timeout):
            requests.append(req)
            return Response(b"{}", 200)
        offer = {"offeredItems": [{"listingId": "123", "quantity": 1, "price": {"value": "20", "currency": "CAD"}}], "offerDuration": {"value": 2, "unit": "DAY"}}
        with patch.object(seller, "get_seller_auth", return_value=AUTH), patch("urllib.request.urlopen", side_effect=fake_open):
            offer_result = invoke(seller.EbaySellerOfferWriteTool(), "send_offer_to_interested_buyers", {"marketplace_id": "EBAY_CA"}, body=offer, confirm=True)
        self.assertTrue(offer_result["success"])
        self.assertTrue(requests[0].full_url.endswith("/send_offer_to_interested_buyers"))
        self.assertEqual(requests[0].get_header("X-ebay-c-marketplace-id"), "EBAY_CA")
        self.assertEqual(json.loads(requests[0].data), offer)

    def test_bulk_updates_report_partial_failures(self):
        payload = {"responses": [{"statusCode": 204}, {"statusCode": 400, "errors": [{"message": "invalid SKU"}]}]}
        with patch.object(seller, "get_seller_auth", return_value=AUTH), patch("urllib.request.urlopen", return_value=Response(json.dumps(payload).encode())):
            result = invoke(seller.EbaySellerListingWriteTool(), "update_price_quantity", body={"requests": [{"sku": "a"}, {"sku": "b"}]}, confirm=True)
        self.assertFalse(result["success"])
        self.assertTrue(result["partial_failure"])

    def test_unknown_action_and_extra_query_do_not_call_ebay(self):
        with patch.object(seller, "get_seller_auth", side_effect=AssertionError("auth called")):
            unknown = invoke(seller.EbaySellerReadTool(), "arbitrary_request", {"url": "https://example.com"})
            extra = invoke(seller.EbaySellerReadTool(), "get_inventory_item", {"sku": "1", "url": "https://example.com"})
        self.assertFalse(unknown["success"])
        self.assertFalse(extra["success"])

    def test_http_errors_are_not_reported_as_empty_success(self):
        error = urllib.error.HTTPError("https://api.sandbox.ebay.com", 403, "Forbidden", {}, io.BytesIO(b'{"errors":[{"errorId":1,"message":"Insufficient scope"}]}'))
        with patch.object(seller, "get_seller_auth", return_value=AUTH), patch("urllib.request.urlopen", side_effect=error):
            result = invoke(seller.EbaySellerReadTool(), "list_orders")
        self.assertFalse(result["success"])
        self.assertEqual(result["http_status"], 403)
        self.assertEqual(result['errors'][0]['code'], 1)
        self.assertEqual(result['errors'][0]['message'], 'Insufficient scope')

    def test_connection_failures_are_distinguished_without_leaking_details(self):
        failures = [
            (urllib.error.URLError(socket.gaierror('secret hostname')), 'DNS_FAILURE'),
            (urllib.error.URLError(TimeoutError('private')), 'CONNECTION_TIMEOUT'),
            (urllib.error.URLError(ssl.SSLError('private')), 'TLS_FAILURE'),
            (urllib.error.URLError(ConnectionRefusedError('private')), 'CONNECTION_FAILURE'),
        ]
        for error, expected in failures:
            with self.subTest(expected=expected), patch.object(seller, 'get_seller_auth', return_value=AUTH), patch('urllib.request.urlopen', side_effect=error):
                result = invoke(seller.EbaySellerReadTool(), 'list_orders')
            self.assertFalse(result['success'])
            self.assertEqual(result['errors'][0]['plugin_code'], expected)
            self.assertIsNone(result['errors'][0]['code'])
            self.assertNotIn('private', str(result))
            self.assertNotIn('secret hostname', str(result))

    def test_unexpected_plugin_error_and_invalid_response_are_distinct(self):
        with patch.object(seller, 'get_seller_auth', side_effect=RuntimeError('secret token')):
            result = invoke(seller.EbaySellerReadTool(), 'list_orders')
        self.assertEqual(result['errors'][0]['plugin_code'], 'PLUGIN_FAILURE')
        self.assertNotIn('secret token', str(result))
        with patch.object(seller, 'get_seller_auth', return_value=AUTH), patch('urllib.request.urlopen', return_value=Response(b'not json')):
            result = invoke(seller.EbaySellerReadTool(), 'list_orders')
        self.assertEqual(result['errors'][0]['plugin_code'], 'INVALID_RESPONSE')

    def test_failed_write_warns_outcome_may_be_unknown(self):
        with patch.object(seller, 'get_seller_auth', return_value=AUTH), patch('urllib.request.urlopen', side_effect=TimeoutError()):
            result = invoke(seller.EbaySellerListingWriteTool(), 'put_inventory_item', {'sku': 'test'}, body={'product': {'title': 'test'}}, confirm=True)
        self.assertEqual(result['errors'][0]['plugin_code'], 'CONNECTION_TIMEOUT')
        self.assertIn('may have been applied', result['error'])

    def test_trading_error_contains_code_and_explanation(self):
        body = b'<GetItemResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Failure</Ack><Errors><ErrorCode>10007</ErrorCode><ShortMessage>System error</ShortMessage><LongMessage>Unable to process your request.</LongMessage></Errors></GetItemResponse>'
        with patch.object(seller, 'get_seller_auth', return_value=AUTH), patch('urllib.request.urlopen', return_value=Response(body)):
            result = invoke(seller.EbaySellerReadTool(), 'get_listing', {'item_id': '123'})
        self.assertFalse(result['success'])
        self.assertEqual(result['errors'][0]['code'], '10007')
        self.assertEqual(result['errors'][0]['message'], 'Unable to process your request.')

    def test_bulk_errors_identify_failed_item(self):
        payload = {'responses': [{'sku': 'ok', 'statusCode': 200}, {'sku': 'bad', 'statusCode': 400, 'errors': [{'errorId': 25604, 'message': 'Invalid SKU'}]}]}
        with patch.object(seller, 'get_seller_auth', return_value=AUTH), patch('urllib.request.urlopen', return_value=Response(json.dumps(payload).encode())):
            result = invoke(seller.EbaySellerListingWriteTool(), 'update_price_quantity', body={'requests': [{'sku': 'ok'}, {'sku': 'bad'}]}, confirm=True)
        self.assertFalse(result['success'])
        self.assertTrue(result['partial_failure'])
        self.assertEqual((result['errors'][0]['sku'], result['errors'][0]['code'], result['errors'][0]['message']), ('bad', 25604, 'Invalid SKU'))

    def test_http_error_without_ebay_details_is_explicit(self):
        error = urllib.error.HTTPError('https://api.sandbox.ebay.com', 500, 'Internal', {}, io.BytesIO(b'not json'))
        with patch.object(seller, 'get_seller_auth', return_value=AUTH), patch('urllib.request.urlopen', side_effect=error):
            result = invoke(seller.EbaySellerReadTool(), 'list_orders')
        self.assertEqual(result['http_status'], 500)
        self.assertIsNone(result['errors'][0]['code'])
        self.assertIn('did not provide', result['errors'][0]['message'])

    def test_trading_offer_failure_not_hidden_by_success_ack(self):
        body = b'<RespondToBestOfferResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Warning</Ack><RespondToBestOffer><BestOffer><CallStatus>Failure</CallStatus></BestOffer></RespondToBestOffer></RespondToBestOfferResponse>'
        with patch.object(seller, "get_seller_auth", return_value=AUTH), patch("urllib.request.urlopen", return_value=Response(body)):
            result = invoke(seller.EbaySellerOfferWriteTool(), "respond_to_best_offer", {"item_id":"123", "offer_id":"456", "response":"Accept"}, confirm=True)
        self.assertFalse(result["success"])

    def test_counteroffer_xml_uses_currency_and_quantity(self):
        requests = []
        def fake_open(req, timeout):
            requests.append(req)
            return Response(b'<RespondToBestOfferResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Success</Ack><RespondToBestOffer><BestOffer><CallStatus>Success</CallStatus></BestOffer></RespondToBestOffer></RespondToBestOfferResponse>')
        with patch.object(seller, "get_seller_auth", return_value=AUTH), patch("urllib.request.urlopen", side_effect=fake_open):
            result = invoke(seller.EbaySellerOfferWriteTool(), "respond_to_best_offer", {"item_id":"123", "offer_id":"456", "response":"Counter", "counter_price":"12.50", "currency":"CAD", "counter_quantity":1}, confirm=True)
        self.assertTrue(result["success"])
        root = ET.fromstring(requests[0].data)
        self.assertEqual(root.find(seller.NS + "CounterOfferPrice").attrib["currencyID"], "CAD")
        self.assertEqual(root.findtext(seller.NS + "CounterOfferQuantity"), "1")


if __name__ == "__main__":
    unittest.main()

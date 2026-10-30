"""Offline contract tests for the read-only Best Offer tool."""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent / "agent-core"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from common.oauth import user_access_token  # noqa: E402
from common.best_offers import EbayBestOffersTool, _parse_response, _request_xml  # noqa: E402


def response_xml(offers: str, page_count: int = 1) -> bytes:
    return (
        '<GetBestOffersResponse xmlns="urn:ebay:apis:eBLBaseComponents">'
        '<Ack>Success</Ack><ItemBestOffersArray><ItemBestOffers>'
        '<Role>Seller</Role><Item><ItemID>12345</ItemID></Item>'
        f'<BestOfferArray>{offers}</BestOfferArray>'
        '</ItemBestOffers></ItemBestOffersArray>'
        f'<PaginationResult><TotalNumberOfPages>{page_count}</TotalNumberOfPages></PaginationResult>'
        '</GetBestOffersResponse>'
    ).encode("utf-8")


def offer_xml(offer_id: str, kind: str, status: str) -> str:
    return (
        '<BestOffer>'
        f'<BestOfferID>{offer_id}</BestOfferID><BestOfferCodeType>{kind}</BestOfferCodeType>'
        f'<Status>{status}</Status><Price currencyID="CAD">23.50</Price>'
        '<ExpirationTime>2026-10-30T00:00:00.000Z</ExpirationTime>'
        '</BestOffer>'
    )


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class BestOffersTests(unittest.TestCase):
    def test_best_offers_connection_failure_is_classified(self):
        import urllib.error
        with patch('common.best_offers.get_seller_auth') as auth, patch('urllib.request.urlopen', side_effect=urllib.error.URLError(TimeoutError())):
            auth.return_value.environment = 'sandbox'
            auth.return_value.access_token = 'fake'
            result = asyncio.run(EbayBestOffersTool().invoke({}))
        self.assertEqual(result['errors'][0]['plugin_code'], 'CONNECTION_TIMEOUT')

    def test_best_offers_trading_error_is_structured(self):
        raw = b'<GetBestOffersResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Failure</Ack><Errors><ErrorCode>10007</ErrorCode><LongMessage>System error</LongMessage></Errors></GetBestOffersResponse>'
        with patch('common.best_offers.get_seller_auth') as auth, patch('urllib.request.urlopen', return_value=FakeResponse(raw)):
            auth.return_value.environment = 'sandbox'
            auth.return_value.access_token = 'fake'
            result = asyncio.run(EbayBestOffersTool().invoke({}))
        self.assertFalse(result['success'])
        self.assertEqual(result['errors'][0]['code'], '10007')
        self.assertEqual(result['errors'][0]['message'], 'System error')

    def test_refreshes_access_token_only_when_near_expiry(self):
        settings = {
            "EBAY_SANDBOX_CLIENT_ID": "test-client",
            "EBAY_SANDBOX_CLIENT_SECRET": "test-secret",
            "EBAY_SANDBOX_USER_REFRESH_TOKEN": "test-refresh",
        }
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request)
            return FakeResponse(json.dumps({"access_token": f"access-{len(calls)}", "expires_in": 3600}).encode())

        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("common.oauth.time.monotonic", side_effect=[100, 100, 3600, 3600]):
            first = user_access_token("https://api.sandbox.ebay.com", "sandbox", settings)
            cached = user_access_token("https://api.sandbox.ebay.com", "sandbox", settings)
            renewed = user_access_token("https://api.sandbox.ebay.com", "sandbox", settings)
        self.assertEqual((first, cached, renewed), ("access-1", "access-1", "access-2"))
        self.assertEqual(len(calls), 2)

    def test_classifies_buyer_counteroffer_and_seller_counteroffer(self):
        raw = response_xml(
            offer_xml("a", "BuyerCounterOffer", "Active")
            + offer_xml("b", "SellerCounterOffer", "Active")
            + offer_xml("c", "BuyerBestOffer", "Declined")
        )
        offers, pages, warnings = _parse_response(raw)
        self.assertEqual(pages, 1)
        self.assertEqual(warnings, [])
        self.assertEqual([o["needs_seller_response"] for o in offers], [True, False, False])
        self.assertEqual(offers[0]["item_id"], "12345")
        self.assertEqual(offers[0]["currency"], "CAD")

    def test_all_statuses_are_only_requested_for_one_item(self):
        self.assertIn(b"<ns0:BestOfferStatus>All</ns0:BestOfferStatus>", _request_xml("12345", 1, 20))
        self.assertIn(b"<ns0:BestOfferStatus>Active</ns0:BestOfferStatus>", _request_xml(None, 1, 20))

    def test_item_response_without_item_id_reports_pending_buyer_offer(self):
        raw = ('<GetBestOffersResponse xmlns="urn:ebay:apis:eBLBaseComponents">'
               '<Ack>Success</Ack><BestOfferArray>'
               + offer_xml('2239714', 'BuyerBestOffer', 'Pending')
               + '</BestOfferArray></GetBestOffersResponse>').encode()
        from common.oauth import EbayAuth
        with patch('common.best_offers.get_seller_auth', return_value=EbayAuth('sandbox', 'https://api.sandbox.ebay.com', 'fake')):
            with patch('urllib.request.urlopen', return_value=FakeResponse(raw)):
                result = asyncio.run(EbayBestOffersTool.invoke(object.__new__(EbayBestOffersTool), {'item_id': '110591475879'}))
        self.assertTrue(result['offers'][0]['needs_seller_response'])
        self.assertEqual(result['offers'][0]['item_id'], '110591475879')

    def test_bounded_pages_report_incomplete_scan(self):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request)
            return FakeResponse(response_xml(offer_xml(str(len(calls)), "BuyerBestOffer", "Active"), page_count=3))

        from common.oauth import EbayAuth
        with patch("common.best_offers.get_seller_auth", return_value=EbayAuth("sandbox", "https://api.sandbox.ebay.com", "fake")):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                tool = object.__new__(EbayBestOffersTool)
                result = asyncio.run(EbayBestOffersTool.invoke(tool, {"max_pages": 2}))
        self.assertTrue(result["success"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["next_page"], 3)
        self.assertEqual(result["pages_scanned"], 2)
        self.assertEqual(len(result["offers"]), 2)
        self.assertTrue(all(request.full_url == "https://api.sandbox.ebay.com/ws/api.dll" for request in calls))

    def test_missing_credentials_do_not_look_like_no_offers(self):
        with patch.dict(os.environ, {"EBAY_ENV": "sandbox", "EBAY_SELLER_ENV_FILE": str(ROOT / "missing-test-file")}, clear=True):
            tool = object.__new__(EbayBestOffersTool)
            result = asyncio.run(EbayBestOffersTool.invoke(tool, {}))
        self.assertFalse(result["success"])
        self.assertNotIn("offers", result)

    def test_env_file_selects_production_credentials_only(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".env", dir=ROOT, delete=False) as temporary:
            temporary.write(
                "EBAY_ENV=production\n"
                "EBAY_SANDBOX_USER_ACCESS_TOKEN=sandbox-fake\n"
                "EBAY_PRODUCTION_USER_ACCESS_TOKEN=production-fake\n"
            )
            env_file = Path(temporary.name)
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(request)
            return FakeResponse(response_xml(offer_xml("a", "BuyerBestOffer", "Active")))

        try:
            with patch.dict(os.environ, {"EBAY_SELLER_ENV_FILE": str(env_file)}, clear=True):
                with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    tool = object.__new__(EbayBestOffersTool)
                    result = asyncio.run(EbayBestOffersTool.invoke(tool, {}))
        finally:
            env_file.unlink(missing_ok=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["environment"], "production")
        self.assertEqual(requests[0].full_url, "https://api.ebay.com/ws/api.dll")
        self.assertEqual(requests[0].get_header("X-ebay-api-iaf-token"), "production-fake")


if __name__ == "__main__":
    unittest.main()

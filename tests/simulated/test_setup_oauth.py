"""Offline checks for the one-time OAuth setup flow."""

import base64
import io
import json
import tempfile
import unittest
import sys
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from common import setup_oauth


class SetupOAuthTests(unittest.TestCase):
    def test_buyer_authorization_requests_only_base_scope(self):
        url = setup_oauth.authorization_url('sandbox', 'app-id', 'runame', 'state', account='buyer')
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(query['scope'], ['https://api.ebay.com/oauth/api_scope'])
        self.assertEqual(query['prompt'], ['login'])

    def test_buyer_setup_preserves_existing_seller_token_and_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('EBAY_ENV=production\nEBAY_SANDBOX_USER_REFRESH_TOKEN=seller-token\n', encoding='utf-8')
            settings = {'EBAY_SANDBOX_CLIENT_ID': 'app', 'EBAY_SANDBOX_CLIENT_SECRET': 'secret', 'EBAY_SANDBOX_RUNAME': 'runame'}
            with patch.object(sys, 'argv', ['setup_oauth.py', '--environment', 'sandbox', '--account', 'buyer']), \
                 patch.object(setup_oauth, 'load_settings', return_value=settings), \
                 patch.object(setup_oauth, 'settings_file_path', return_value=path), \
                 patch.object(setup_oauth.secrets, 'token_urlsafe', return_value='test-state'), \
                 patch.object(setup_oauth.webbrowser, 'open', return_value=True), \
                 patch.object(setup_oauth.getpass, 'getpass', return_value='https://example.com/?code=test&state=test-state'), \
                 patch.object(setup_oauth, 'exchange_code', return_value='buyer-token'):
                self.assertEqual(setup_oauth.main(), 0)
            saved = path.read_text(encoding='utf-8')
            self.assertIn('EBAY_ENV=production', saved)
            self.assertIn('EBAY_SANDBOX_USER_REFRESH_TOKEN=seller-token', saved)
            self.assertIn('EBAY_SANDBOX_BUYER_REFRESH_TOKEN=buyer-token', saved)

    def test_authorization_url_and_callback_state(self):
        url = setup_oauth.authorization_url("sandbox", "app-id", "my-runame", "random-state")
        parsed = urllib.parse.urlsplit(url)
        params = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "auth.sandbox.ebay.com")
        self.assertEqual(params["redirect_uri"], ["my-runame"])
        self.assertEqual(params["state"], ["random-state"])
        scopes = params["scope"][0].split()
        self.assertTrue(all("https://api.ebay.com/oauth/api_scope/" + scope in scopes for scope in ("sell.account", "sell.inventory", "sell.fulfillment")))
        callback = "https://example.com/accepted?code=v%2B1%2F2&state=random-state"
        self.assertEqual(setup_oauth.authorization_code(callback, "random-state"), "v+1/2")
        with self.assertRaisesRegex(ValueError, "state did not match"):
            setup_oauth.authorization_code(callback, "other-state")

    def test_exchange_posts_decoded_code_once_and_saves_refresh_token(self):
        class Response:
            def __enter__(self):
                return io.BytesIO(json.dumps({"refresh_token": "private-refresh"}).encode())

            def __exit__(self, *_):
                pass

        def fake_open(request, timeout):
            self.assertEqual(timeout, 20)
            self.assertEqual(request.full_url, "https://api.sandbox.ebay.com/identity/v1/oauth2/token")
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.get_header("Authorization"), "Basic " + base64.b64encode(b"app:secret").decode())
            self.assertEqual(urllib.parse.parse_qs(request.data.decode())["code"], ["v+1/2"])
            return Response()

        with patch.object(setup_oauth.urllib.request, "urlopen", side_effect=fake_open):
            token = setup_oauth.exchange_code("sandbox", "app", "secret", "runame", "v+1/2")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("# keep this comment\nEBAY_ENV=production\nEBAY_SANDBOX_USER_ACCESS_TOKEN=old\nOTHER_SETTING=keep\n")
            setup_oauth.save_settings(path, {
                "EBAY_ENV": "sandbox",
                "EBAY_SANDBOX_USER_REFRESH_TOKEN": token,
                "EBAY_SANDBOX_USER_ACCESS_TOKEN": "",
            })
            saved = path.read_text()
            self.assertIn("# keep this comment", saved)
            self.assertIn("OTHER_SETTING=keep", saved)
            self.assertIn("EBAY_SANDBOX_USER_REFRESH_TOKEN=private-refresh", saved)
            self.assertIn("EBAY_SANDBOX_USER_ACCESS_TOKEN=\n", saved)
            self.assertNotIn("old", saved)


if __name__ == "__main__":
    unittest.main()

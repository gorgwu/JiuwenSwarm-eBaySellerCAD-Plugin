"""Test local JiuwenSwarm import and agent-core plugin loading without eBay access."""
import asyncio
import shutil
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT.parent
CORE = DESKTOP / 'agent-core'
SWARM = DESKTOP / 'jiuwenswarm'
for path in (ROOT / 'tests' / 'sandbox', ROOT, SWARM, CORE):
    sys.path.insert(0, str(path))

from ebayseller_common.oauth import EbayAuth
from sandbox_cases import CASES, resolve
from openjiuwen.harness.resources import load_plugin_package
from openjiuwen.harness.resources.extension_resolver import resolve_plugin_parts
from openjiuwen.harness.schema.build_context import BuildContext

AUTH = EbayAuth('sandbox', 'https://api.sandbox.ebay.com', 'fake-token')
FIXTURES = {'listing_id': '123', 'trading_listing_id': '123', 'sku': 'test-sku',
            'inventory_offer_id': '42', 'location_key': 'test-location', 'currency': 'CAD',
            'best_offer_id': '456', 'revised_title': 'Test title'}
for field in ('fulfillment_policy_body', 'payment_policy_body', 'return_policy_body',
              'inventory_item_body', 'location_body', 'inventory_offer_body',
              'bulk_update_body', 'interested_offer_body'):
    FIXTURES[field] = {'test': 'fixture'}


class FakeResponse:
    status = 200
    headers = {}
    def __init__(self, data):
        self.data = data
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.data


def fake_ebay(request, timeout):
    call = request.get_header('X-ebay-api-call-name')
    if call:
        user = '<User><UserID>seller</UserID></User>' if call == 'GetUser' else ''
        return FakeResponse(f'<{call}Response xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Success</Ack>{user}</{call}Response>'.encode())
    return FakeResponse(b'{}')


def load_tools():
    spec = load_plugin_package(ROOT / 'manifest.json')
    parts = resolve_plugin_parts(spec, BuildContext(language='en', extras={'source_root': str(ROOT)}))
    return {tool.card.name: tool for tool in parts.tools}


class FrameworkIntegrationTests(unittest.TestCase):
    def test_import_from_jiuwenswarm_catalog_into_isolated_workspace(self):
        from jiuwenswarm.server.runtime import extension_package_manager as catalog
        self.assertTrue(Path(catalog.__file__).resolve().is_relative_to(SWARM.resolve()))
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            local, builtin = base / 'local', base / 'built_in'
            # Stage public package files only: never copy local .env or run journals.
            source = base / 'source'
            source.mkdir()
            for name in ('manifest.json', 'README.md'):
                (source / name).write_bytes((ROOT / name).read_bytes())
            for name in ('tools', 'ebayseller_common'):
                shutil.copytree(ROOT / name, source / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            with patch.object(catalog, '_local_root', return_value=local), \
                 patch.object(catalog, '_built_in_root', return_value=builtin), \
                 patch.object(catalog, '_resources_root', return_value=None), \
                 patch.object(catalog, 'upsert_plugin_marketplace_entry'):
                result = catalog.import_plugin_package({'path': str(source)})
            self.assertEqual(result['id'], 'ebayseller')
            installed = local / 'ebayseller'
            self.assertTrue((installed / 'manifest.json').is_file())
            spec = load_plugin_package(installed / 'manifest.json')
            parts = resolve_plugin_parts(spec, BuildContext(language='en', extras={'source_root': str(installed)}))
            self.assertEqual({tool.card.name for tool in parts.tools},
                             {'ebayseller_read', 'ebayseller_listing_write', 'ebayseller_offer_write'})

    def test_all_33_actions_through_agent_core_manifest_resolution(self):
        import openjiuwen
        self.assertTrue(any(Path(path).resolve().is_relative_to(CORE.resolve()) for path in openjiuwen.__path__))
        tools = load_tools()
        self.assertEqual(set(tools), {'ebayseller_read', 'ebayseller_listing_write', 'ebayseller_offer_write'})
        registry = {}
        for name, tool in tools.items():
            details = asyncio.run(tool.invoke({'action': 'describe_actions'}))
            for action in details['actions']:
                self.assertNotIn(action, registry)
                registry[action] = tool
        self.assertEqual(set(registry), set(CASES))
        self.assertEqual(len(registry), 33)
        for action, tool in registry.items():
            with self.subTest(action=action):
                invoke_fn = next(base.__dict__['invoke'] for base in type(tool).__mro__ if 'invoke' in base.__dict__)
                tool_globals = invoke_fn.__globals__
                best_offer_globals = tool_globals['EbayBestOffersTool']._read.__globals__
                data = resolve(CASES[action]['input'], FIXTURES)
                request = {'action': action, **data}
                with patch.dict(tool_globals, {'get_seller_auth': lambda: AUTH, 'get_application_auth': lambda: AUTH}), \
                     patch.dict(best_offer_globals, {'get_seller_auth': lambda: AUTH}), \
                     patch.object(urllib.request, 'urlopen', side_effect=fake_ebay):
                    if tool.card.name != 'ebayseller_read':
                        denied = asyncio.run(tool.invoke(request))
                        self.assertTrue(denied.get('approval_required'), denied)
                        request['confirm'] = True
                    result = asyncio.run(tool.invoke(request))
                self.assertTrue(result.get('success'), result)


if __name__ == '__main__':
    unittest.main()

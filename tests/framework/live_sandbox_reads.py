"""Run real read-only eBay Sandbox requests through agent-core's plugin resolver."""
import asyncio
import argparse
import json
from pathlib import Path

from test_framework_integration import load_tools
from sandbox_tools import DEFAULTS, check_sandbox, marketplace_input
from sandbox_cases import CASES, resolve


async def run(fixtures_path=None):
    check_sandbox()
    reader = load_tools()['ebayseller_read']
    failures = 0
    fixtures = json.loads(fixtures_path.read_text(encoding='utf-8')) if fixtures_path else {}
    if not isinstance(fixtures, dict) or fixtures.get('marketplace_id', 'EBAY_CA') != 'EBAY_CA':
        raise ValueError('Fixtures must be a Canadian Sandbox JSON object.')
    actions = list(DEFAULTS)
    if fixtures_path:
        actions.extend(['get_listing', 'get_inventory_item', 'list_inventory_offers',
                        'get_inventory_offer', 'get_inventory_location'])
    for action in actions:
        try:
            data = {'params': DEFAULTS[action]} if action in DEFAULTS else resolve(CASES[action]['input'], fixtures)
        except ValueError:
            failures += 1
            print(json.dumps({'action': action, 'status': 'blocked: missing fixture'}), flush=True)
            continue
        data = marketplace_input(action, data, 'EBAY_CA')
        result = await reader.invoke({'action': action, **data})
        success = bool(result.get('success'))
        failures += not success
        # Do not print seller records or credentials.
        print(json.dumps({'action': action, 'call_succeeded': success,
                          'http_status': result.get('http_status'),
                          'error_codes': [entry.get('code') or entry.get('plugin_code')
                                          for entry in result.get('errors', [])]}), flush=True)
    print(f'{len(actions) - failures}/{len(actions)} read calls succeeded; contents were not independently verified.')
    return bool(failures)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, help='Private Canadian Sandbox fixture file for five additional reads.')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.fixtures)))

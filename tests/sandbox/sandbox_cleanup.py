"""Remove supported, journaled resources from one Sandbox test run."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.oauth import get_seller_auth, load_settings
from tools.ebay_seller_tools import EbaySellerReadTool, EbaySellerListingWriteTool
from sandbox_journal import load, save

PATHS = {
    'offer': '/sell/inventory/v1/offer/',
    'inventory_item': '/sell/inventory/v1/inventory_item/',
    'location': '/sell/inventory/v1/location/',
    'fulfillment_policy': '/sell/account/v1/fulfillment_policy/',
    'payment_policy': '/sell/account/v1/payment_policy/',
    'return_policy': '/sell/account/v1/return_policy/',
}
ORDER = {name: i for i, name in enumerate(PATHS)}
ORDER['trading_listing'] = -1


def sandbox_auth():
    if load_settings().get('EBAY_ENV', 'sandbox').strip().lower() != 'sandbox':
        raise ValueError('Cleanup refuses non-Sandbox configuration.')
    auth = get_seller_auth()
    if auth.environment != 'sandbox' or auth.api_base != 'https://api.sandbox.ebay.com':
        raise ValueError('Cleanup refuses an unexpected API host.')
    return auth


def request(auth, method: str, path: str) -> tuple[int, list]:
    req = urllib.request.Request(auth.api_base + path, method=method,
        headers={'Authorization': 'Bearer ' + auth.access_token, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, []
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read())
            errors = [{key: item[key] for key in ('errorId', 'message', 'longMessage') if key in item}
                      for item in data.get('errors', []) if isinstance(item, dict)]
        except (ValueError, AttributeError, TypeError):
            errors = []
        return exc.code, errors


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('journal', type=Path, help='Run journal created by the test runner')
    parser.add_argument('--apply', action='store_true', help='Delete journaled Sandbox records after confirmation')
    args = parser.parse_args()
    journal = load(args.journal)
    if journal.get('marketplace_id') != 'EBAY_CA' or journal.get('site_id') != 2:
        raise ValueError('Cleanup requires a journal explicitly identifying English Canada (EBAY_CA, site 2).')
    auth = sandbox_auth()
    result = await EbaySellerReadTool().invoke({'action': 'get_seller_account', 'params': {}})
    user = ((result.get('response') or {}).get('User') or {}).get('UserID')
    if not result.get('success') or not user or user != journal['seller_id']:
        raise ValueError('Authorized Sandbox seller does not match the journal; refusing cleanup.')
    resources = journal['resources']
    for entry in resources:
        if not isinstance(entry, dict) or entry.get('kind') not in ORDER or not isinstance(entry.get('id'), str) or not entry['id'].strip():
            raise ValueError('Invalid journal resource; refusing cleanup.')
    print(f"Sandbox run {journal['run_id']}: {len(resources)} journaled resources")
    for entry in sorted(resources, key=lambda e: ORDER[e['kind']]):
        print(f"  {entry['kind']} {entry['id']} ({entry.get('status', 'unknown')})")
    print('Orders, buyer transaction history, ended listings, and unknown resources are not deleted by this script.')
    if not args.apply:
        print('Dry run only. Add --apply to request deletion.')
        return 0
    if input('Type CLEANUP to delete only the listed Sandbox resources: ').strip() != 'CLEANUP':
        print('Cancelled.')
        return 1
    failed = False
    for entry in sorted(resources, key=lambda e: ORDER[e['kind']]):
        if entry.get('status') == 'deleted':
            continue
        if entry['kind'] == 'trading_listing':
            if entry.get('status') == 'ended':
                continue
            item_id = entry['id']
            site_id = journal['site_id']
            read = await EbaySellerReadTool().invoke({'action': 'get_listing', 'params': {'item_id': item_id, 'site_id': site_id}})
            state = (((read.get('response') or {}).get('Item') or {}).get('SellingStatus') or {}).get('ListingStatus')
            if state == 'Active':
                ended = await EbaySellerListingWriteTool().invoke({'action': 'end_listing', 'params': {'item_id': item_id, 'ending_reason': 'NotAvailable', 'site_id': site_id}, 'confirm': True})
                if ended.get('success'):
                    read = await EbaySellerReadTool().invoke({'action': 'get_listing', 'params': {'item_id': item_id, 'site_id': site_id}})
                    state = (((read.get('response') or {}).get('Item') or {}).get('SellingStatus') or {}).get('ListingStatus')
            entry['status'] = 'ended' if state in {'Ended', 'Completed'} else 'unverified'
            failed |= entry['status'] != 'ended'
            save(args.journal, journal)
            print(f"trading_listing {item_id}: {entry['status']} (eBay status {state})")
            continue
        path = PATHS[entry['kind']] + urllib.parse.quote(entry['id'], safe='')
        status, errors = request(auth, 'DELETE', path)
        if status in (200, 202, 204, 404):
            check, _ = request(auth, 'GET', path)
            if check in (404, 410):
                entry['status'] = 'deleted'
            else:
                entry['status'] = 'unverified'
                failed = True
        else:
            entry['status'] = 'failed'
            failed = True
        entry['delete_http_status'] = status
        entry['delete_errors'] = errors
        save(args.journal, journal)
        print(f"{entry['kind']} {entry['id']}: {entry['status']} (DELETE HTTP {status})")
        if errors:
            print('eBay errors:', json.dumps(errors))
    if journal.get('unresolved'):
        print('Unresolved creation attempts remain in the journal; inspect them before claiming cleanup.')
        failed = True
    return int(failed)


if __name__ == '__main__':
    try:
        raise SystemExit(asyncio.run(main()))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f'Cleanup stopped: {exc}', file=sys.stderr)
        raise SystemExit(1)

"""Compare Canadian Sandbox reads with a journaled run's known fixture IDs.

Run from the plugin root. Results contain no account data or credentials. A
missing item on a limited page is inconclusive, not proof that it is absent.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.oauth import get_seller_auth, load_settings
from tools.ebay_seller_tools import EbaySellerReadTool
from sandbox_journal import load


def contains(value, target):
    if isinstance(value, dict):
        return any(contains(v, target) for v in value.values())
    if isinstance(value, list):
        return any(contains(v, target) for v in value)
    return str(value) == str(target)


async def verify(path):
    j = load(path)
    if j.get('marketplace_id') != 'EBAY_CA' or j.get('site_id') != 2:
        raise ValueError('A Canadian journal is required.')
    auth = get_seller_auth()
    if load_settings().get('EBAY_ENV', '').lower() != 'sandbox' or auth.environment != 'sandbox' or auth.api_base != 'https://api.sandbox.ebay.com':
        raise ValueError('Sandbox credentials required.')
    f, tool, results = j['fixtures'], EbaySellerReadTool(), {}
    account = await tool.invoke({'action': 'get_seller_account', 'params': {}})
    user = ((account.get('response') or {}).get('User') or {}).get('UserID')
    if not account.get('success') or user != j['seller_id']:
        raise ValueError('Seller identity does not match the journal.')
    results['get_seller_account'] = 'verified'
    reused = {entry['kind']: entry['id'] for entry in j.get('reused', [])}
    checks = [
        ('list_listings', {}, f['trading_listing_id']),
        ('get_listing', {'item_id': f['trading_listing_id']}, f['trading_listing_id']),
        ('list_inventory_items', {'limit': 100}, f['sku']),
        ('get_inventory_item', {'sku': f['sku']}, f['sku']),
        ('list_inventory_offers', {'sku': f['sku'], 'limit': 100}, f['inventory_offer_id']),
        ('get_inventory_offer', {'offer_id': f['inventory_offer_id']}, f['inventory_offer_id']),
        ('list_inventory_locations', {'limit': 100}, f['location_key']),
        ('get_inventory_location', {'location_key': f['location_key']}, f['location_key']),
        ('list_fulfillment_policies', {}, reused.get('fulfillment_policy')),
        ('list_payment_policies', {}, reused.get('payment_policy')),
        ('list_return_policies', {}, reused.get('return_policy')),
        ('get_default_category_tree', {}, '2'),
        ('get_category_aspects', {'category_tree_id': '2', 'category_id': '20695'}, 'Brand'),
    ]
    for action, params, expected in checks:
        result = await tool.invoke({'action': action, 'params': params})
        if not result.get('success'):
            results[action] = 'call_failed'
        elif expected is None:
            results[action] = 'inconclusive: no expected policy ID recorded'
        elif contains(result.get('data') or result.get('response') or {}, expected):
            results[action] = 'verified: expected value found'
        else:
            results[action] = 'inconclusive: expected value not found in returned page'
        data = result.get('data') or {}
        if result.get('success') and action == 'get_inventory_item':
            expected_product = f.get('inventory_item_body', {}).get('product', {})
            actual_product = data.get('product', {})
            if actual_product.get('title') != expected_product.get('title'):
                results[action] = 'inconclusive: item title differs from fixture'
        elif result.get('success') and action == 'get_inventory_offer':
            expected_offer = f.get('inventory_offer_body', {})
            if data.get('marketplaceId') != expected_offer.get('marketplaceId'):
                results[action] = 'inconclusive: offer marketplace differs from fixture'
            elif (data.get('pricingSummary') or {}).get('price', {}).get('currency') != f.get('currency'):
                results[action] = 'inconclusive: offer currency differs from fixture'
        elif result.get('success') and action == 'get_inventory_location':
            expected_address = f.get('location_body', {}).get('location', {}).get('address', {})
            actual_address = data.get('location', {}).get('address', {})
            if any(actual_address.get(k) != expected_address.get(k) for k in ('country', 'postalCode')):
                results[action] = 'inconclusive: location address differs from fixture'
        print(action, results[action], flush=True)
    for action, params in [('get_seller_feedback', {}), ('list_orders', {}),
                           ('find_eligible_items', {'limit': 10}),
                           ('get_category_suggestions', {'category_tree_id': '2', 'q': 'coffee mug'})]:
        result = await tool.invoke({'action': action, 'params': params})
        results[action] = 'call_succeeded: no independent expected record' if result.get('success') else 'call_failed'
        print(action, results[action], flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Choose a new output file; refusing overwrite.')
    results = asyncio.run(verify(args.journal))
    args.output.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    print('Results saved to', args.output)


if __name__ == '__main__':
    main()

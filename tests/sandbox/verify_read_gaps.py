"""Check remaining seller reads against a Canadian Sandbox journal, without printing account data."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sandbox_journal import load
from verify_canadian_reads import contains
from common.oauth import get_seller_auth, load_settings
from tools.ebay_seller_tools import EbaySellerReadTool


async def run(path):
    journal = load(path)
    if load_settings().get('EBAY_ENV', '').lower() != 'sandbox':
        raise ValueError('Sandbox credentials required')
    auth = get_seller_auth()
    if auth.environment != 'sandbox' or auth.api_base != 'https://api.sandbox.ebay.com':
        raise ValueError('Sandbox credentials required')
    if journal.get('marketplace_id') != 'EBAY_CA' or journal.get('site_id') != 2:
        raise ValueError('An English Canadian journal is required')
    tool = EbaySellerReadTool()
    async def read(action, params):
        result = await tool.invoke({'action': action, 'params': params})
        if not result.get('success'):
            raise ValueError(f'{action} failed: {result.get("errors") or result.get("error")}')
        return result.get('data') or result.get('response') or {}
    account = await read('get_seller_account', {})
    if (account.get('User') or {}).get('UserID') != journal['seller_id']:
        raise ValueError('Seller identity does not match journal')
    feedback = await read('get_seller_feedback', {})
    orders = await read('list_orders', {'limit': 100})
    eligible = await read('find_eligible_items', {'limit': 15})
    suggestions = await read('get_category_suggestions', {'category_tree_id': '2', 'q': 'coffee mug'})
    fixtures = journal['fixtures']
    order_list = orders.get('orders', [])
    canadian_orders = [o for o in order_list if any(x.get('listingMarketplaceId') == 'EBAY_CA' for x in o.get('lineItems', []))]
    category_list = suggestions.get('categorySuggestions', [])
    categories = [c.get('category', {}).get('categoryName', '') for c in category_list]
    result = {
        'get_seller_feedback': {'status': 'inconclusive', 'reason': 'No independently known feedback record; successful call alone cannot verify its content.', 'returned_feedback_details': bool(feedback.get('FeedbackDetailArray'))},
        'list_orders': {'status': 'inconclusive', 'reason': 'No independently known Canadian purchase to compare.', 'canadian_orders_in_first_page': len(canadian_orders)},
        'find_eligible_items': {'status': 'verified' if any(contains(eligible, fixtures[k]) for k in ('trading_listing_id', 'inventory_listing_id') if fixtures.get(k)) else 'inconclusive', 'reason': 'Check whether a freshly created listing ID is returned; Sandbox eligibility is simulated.'},
        'get_category_suggestions': {'status': 'verified' if any('mug' in str(c).lower() for c in categories) else 'inconclusive', 'reason': 'Check whether coffee mug suggestions include a mug category; this does not evaluate ranking quality.'},
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Choose a new output file')
    result = asyncio.run(run(args.journal))
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

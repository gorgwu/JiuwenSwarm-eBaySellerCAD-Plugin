"""Exercise registered seller actions against Sandbox; never targets Production."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from sandbox_cases import CASES, resolve
from sandbox_journal import add as add_resource, create as create_journal, load as load_journal, save as save_journal

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.oauth import get_seller_auth, load_settings
from sandbox_marketplace import test_marketplace
from tools.ebay_seller_tools import (EbaySellerReadTool, EbaySellerListingWriteTool,
                                    EbaySellerOfferWriteTool)

CLASSES = (EbaySellerReadTool, EbaySellerListingWriteTool, EbaySellerOfferWriteTool)
DEFAULTS = {
    'get_seller_account': {}, 'get_seller_feedback': {}, 'list_listings': {},
    'get_best_offers': {}, 'list_inventory_items': {'limit': 10},
    'list_inventory_locations': {'limit': 10},
    'list_orders': {'limit': 10}, 'list_fulfillment_policies': {'marketplace_id': 'EBAY_CA'},
    'list_payment_policies': {'marketplace_id': 'EBAY_CA'},
    'list_return_policies': {'marketplace_id': 'EBAY_CA'},
    'find_eligible_items': {'limit': 10, 'marketplace_id': 'EBAY_CA'}, 'get_default_category_tree': {'marketplace_id': 'EBAY_CA'},
    'get_category_suggestions': {'category_tree_id': '2', 'q': 'coffee mug'},
    'get_category_aspects': {'category_tree_id': '2', 'category_id': '20695'},
}


def actions():
    return {name: cls for cls in CLASSES for name in (*cls.actions, *cls.extra_actions)}


def check_sandbox():
    if load_settings().get('EBAY_ENV', 'sandbox').strip().lower() != 'sandbox':
        raise ValueError('EBAY_ENV must be sandbox; refusing to run.')
    auth = get_seller_auth()
    if auth.environment != 'sandbox' or auth.api_base != 'https://api.sandbox.ebay.com':
        raise ValueError('Unexpected environment or API host; refusing to run.')


def marketplace_input(action, data, marketplace):
    """Apply the selected test marketplace without modifying fixture bodies."""
    params = dict(data.get('params') or {})
    if 'marketplace_id' in params:
        params['marketplace_id'] = marketplace
    if action in {'get_category_suggestions', 'get_category_aspects'} and params.get('category_tree_id') == '0' and marketplace == 'EBAY_CA':
        params['category_tree_id'] = '2'
    if action in {'get_seller_account', 'get_seller_feedback', 'list_listings', 'get_listing',
                  'get_best_offers', 'revise_listing', 'end_listing', 'respond_to_best_offer'}:
        params['site_id'] = 2
    if 'body' in data and marketplace == 'EBAY_CA':
        params['content_language'] = 'en-CA'
    return {**data, 'params': params}


async def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='List supported actions and their tool.')
    parser.add_argument('--read-suite', action='store_true', help='Run the read-only checks that need no record IDs.')
    parser.add_argument('--live-suite', action='store_true', help='Attempt all action cases, prompting before each write and reporting missing fixtures.')
    parser.add_argument('--action', choices=sorted(actions()), help='Run a single named action.')
    parser.add_argument('--case', choices=sorted(CASES), help='Run the named action with its test case and fixture file.')
    parser.add_argument('--cases', action='store_true', help='List every test case and its prerequisites.')
    parser.add_argument('--fixtures', help='Path to a private JSON object containing fixture values for --case.')
    parser.add_argument('--marketplace', choices=['EBAY_CA'], help='Override EBAY_MARKETPLACE_ID; fixtures must match.')
    parser.add_argument('--journal', type=Path, help='Optional private run journal for tracking newly created Sandbox resources in --live-suite.')
    parser.add_argument('--input', default='{}', help='JSON object containing params and optional body, or @path to a JSON file.')
    args = parser.parse_args()
    args.marketplace = test_marketplace(args.marketplace)
    registry = actions()
    if args.list:
        for name, cls in sorted(registry.items()):
            print(f'{name}: {cls.__name__}')
        return 0
    if args.cases:
        for name, case in sorted(CASES.items()):
            print(f'{name}: {case["requires"] or "No special prerequisite"} Verify: {case["verify"]}')
        return 0
    if sum(bool(value) for value in (args.read_suite, args.live_suite, args.action, args.case)) != 1:
        parser.error('choose exactly one of --list, --cases, --read-suite, --live-suite, --action or --case')
    check_sandbox()
    if args.live_suite:
        fixtures = json.loads(Path(args.fixtures).read_text(encoding='utf-8')) if args.fixtures else {}
        if not isinstance(fixtures, dict):
            raise ValueError('Fixtures must be a JSON object.')
        if fixtures.get('marketplace_id', args.marketplace) != args.marketplace:
            raise ValueError('Fixtures do not match the selected marketplace.')
        journal = None
        if args.journal:
            account = await EbaySellerReadTool().invoke({'action': 'get_seller_account', 'params': {}})
            seller = ((account.get('response') or {}).get('User') or {}).get('UserID')
            if not account.get('success') or not seller:
                raise ValueError('Cannot identify Sandbox seller for run journal.')
            if args.journal.exists():
                journal = load_journal(args.journal)
                if journal['seller_id'] != seller:
                    raise ValueError('Journal belongs to another Sandbox seller.')
            else:
                journal = create_journal(args.journal, seller)
                journal['marketplace_id'], journal['site_id'] = 'EBAY_CA', 2
                save_journal(args.journal, journal)
            if journal.get('marketplace_id') != 'EBAY_CA' or journal.get('site_id') != 2:
                raise ValueError('Journal must identify English Canada (EBAY_CA, site 2).')
            print(f"Sandbox run journal: {args.journal} (run {journal['run_id']})")
        results = []
        write_order = ('create_fulfillment_policy', 'create_payment_policy', 'create_return_policy',
                       'create_inventory_location', 'put_inventory_item', 'create_inventory_offer',
                       'update_inventory_offer', 'publish_inventory_offer', 'update_price_quantity',
                       'withdraw_inventory_offer', 'revise_listing', 'end_listing',
                       'respond_to_best_offer',
                       'send_offer_to_interested_buyers')
        ordered_actions = [name for name in CASES if registry[name] is EbaySellerReadTool] + list(write_order)
        if set(ordered_actions) != set(registry) or len(ordered_actions) != len(registry):
            raise ValueError('Live suite action order is out of sync with the registered tools.')
        for action in ordered_actions:
            case = CASES[action]
            try:
                data = resolve(case['input'], fixtures)
            except ValueError as exc:
                results.append((action, 'BLOCKED', str(exc)))
                print(f'{action}: BLOCKED ({exc})', flush=True)
                continue
            data = marketplace_input(action, data, args.marketplace)
            cls = registry[action]
            payload = {'action': action, **data}
            if cls is not EbaySellerReadTool:
                print(f'\n{action}: {case["requires"]}', flush=True)
                print('Sandbox write:', json.dumps(payload, ensure_ascii=False), flush=True)
                if input('Type YES to execute, or press Enter to skip: ').strip() != 'YES':
                    results.append((action, 'SKIPPED', 'Write not confirmed'))
                    continue
                payload['confirm'] = True
            creation_types = {'create_fulfillment_policy': ('fulfillment_policy', 'fulfillmentPolicyId'),
                              'create_payment_policy': ('payment_policy', 'paymentPolicyId'),
                              'create_return_policy': ('return_policy', 'returnPolicyId'),
                              'create_inventory_offer': ('offer', 'offerId'),
                              'create_inventory_location': ('location', None),
                              'put_inventory_item': ('inventory_item', None)}
            if journal is not None and action in {'put_inventory_item', 'create_inventory_location'}:
                read_action = 'get_inventory_item' if action == 'put_inventory_item' else 'get_inventory_location'
                read_params = {'sku': data['params']['sku']} if action == 'put_inventory_item' else {'location_key': data['params']['location_key']}
                prior = await EbaySellerReadTool().invoke({'action': read_action, 'params': read_params})
                if prior.get('http_status') != 404:
                    print(f'{action}: BLOCKED (could not establish that the target does not exist)')
                    results.append((action, 'BLOCKED', 'Target exists or lookup did not return 404'))
                    continue
            intent = None
            if journal is not None and action in creation_types:
                intent = {'action': action, 'status': 'outcome_unknown', 'params': data.get('params', {}),
                          'name': (data.get('body') or {}).get('name') if isinstance(data.get('body'), dict) else None}
                journal['unresolved'].append(intent)
                save_journal(args.journal, journal)
            result = await cls().invoke(payload)
            if intent is not None:
                kind, field = creation_types[action]
                resource_id = ((result.get('data') or {}).get(field) if field else
                               data['params'].get('sku' if kind == 'inventory_item' else 'location_key'))
                if result.get('success') and resource_id:
                    add_resource(args.journal, journal, kind, str(resource_id))
                    journal['unresolved'].remove(intent)
                    save_journal(args.journal, journal)
            outcome = 'CALL_SUCCEEDED_UNVERIFIED' if result.get('success') else 'CALL_FAILED'
            print(json.dumps({'action': action, 'outcome': outcome, 'http_status': result.get('http_status'), 'error': result.get('error'), 'errors': result.get('errors'), 'verify': case['verify']}, ensure_ascii=False), flush=True)
            results.append((action, outcome, ''))
        print('\nLive suite summary:')
        for outcome in ('CALL_SUCCEEDED_UNVERIFIED', 'CALL_FAILED', 'BLOCKED', 'SKIPPED'):
            print(f'{outcome}: {sum(row[1] == outcome for row in results)}')
        print('Successful calls still need the displayed read-back checks; blocked and skipped cases were not tested.')
        return 1 if any(outcome != 'CALL_SUCCEEDED_UNVERIFIED' for _, outcome, _ in results) else 0
    if args.read_suite:
        failures = 0
        for action, params in DEFAULTS.items():
            data = marketplace_input(action, {'params': params}, args.marketplace)
            result = await EbaySellerReadTool().invoke({'action': action, **data})
            print(json.dumps({'action': action, 'success': result.get('success'), 'error': result.get('error'), 'errors': result.get('errors'), 'http_status': result.get('http_status')}))
            failures += not result.get('success')
        print(f'Read checks: {len(DEFAULTS) - failures} succeeded, {failures} failed. Success does not verify record contents or completeness.')
        return int(bool(failures))
    if args.case:
        fixtures = json.loads(Path(args.fixtures).read_text(encoding='utf-8')) if args.fixtures else {}
        if not isinstance(fixtures, dict):
            raise ValueError('Fixtures must be a JSON object.')
        data = resolve(CASES[args.case]['input'], fixtures)
        if fixtures.get('marketplace_id', args.marketplace) != args.marketplace:
            raise ValueError('Fixtures do not match the selected marketplace.')
        data = marketplace_input(args.case, data, args.marketplace)
        print('Prerequisites:', CASES[args.case]['requires'] or 'None beyond authorized Sandbox access.')
        print('Verify:', CASES[args.case]['verify'])
        args.action = args.case
    else:
        raw = Path(args.input[1:]).read_text(encoding='utf-8') if args.input.startswith('@') else args.input
        data = json.loads(raw)
    if not isinstance(data, dict) or set(data) - {'params', 'body'}:
        raise ValueError('Input must be an object containing only params and/or body.')
    if args.action:
        params = data.get('params') or {}
        body = data.get('body') or {}
        if params.get('marketplace_id', 'EBAY_CA') != 'EBAY_CA' or str(params.get('site_id', 2)) != '2':
            raise ValueError('Sandbox tests target English Canada only.')
        if isinstance(body, dict) and body.get('marketplaceId', 'EBAY_CA') != 'EBAY_CA':
            raise ValueError('Sandbox test request body must target EBAY_CA.')
    cls = registry[args.action]
    payload = {'action': args.action, **data}
    if cls is not EbaySellerReadTool:
        print('Sandbox write:', json.dumps(payload, ensure_ascii=False))
        if input('Type YES to run this exact Sandbox write: ').strip() != 'YES':
            print('Cancelled.')
            return 1
        payload['confirm'] = True
    result = await cls().invoke(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('success') else 1


if __name__ == '__main__':
    try:
        raise SystemExit(asyncio.run(run()))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f'Test stopped: {exc}', file=sys.stderr)
        raise SystemExit(1)

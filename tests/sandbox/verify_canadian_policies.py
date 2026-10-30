"""Attempt Canadian policy creation and record owned resources in a run journal."""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.ebay_seller_tools import EbaySellerReadTool, EbaySellerListingWriteTool
from sandbox_cleanup import sandbox_auth
from sandbox_journal import add, load, save


async def run(path, kind_filter='all', immediate_pay=False):
    journal = load(path)
    if journal.get('marketplace_id') != 'EBAY_CA' or journal.get('site_id') != 2:
        raise ValueError('Canadian journal required.')
    sandbox_auth()
    reader, writer = EbaySellerReadTool(), EbaySellerListingWriteTool()
    seller = await reader.invoke({'action': 'get_seller_account', 'params': {}})
    if not seller.get('success') or ((seller.get('response') or {}).get('User') or {}).get('UserID') != journal['seller_id']:
        raise ValueError('Seller identity does not match the journal.')
    common = {'marketplaceId': 'EBAY_CA', 'categoryTypes': [{'name': 'ALL_EXCLUDING_MOTORS_VEHICLES'}]}
    suffix = journal['run_id'][:12]
    cases = [
        ('payment', {'name': 'jiuwen-verify-payment-' + suffix, 'description': 'Sandbox test policy.', 'immediatePay': immediate_pay}),
        ('return', {'name': 'jiuwen-verify-return-' + suffix, 'returnsAccepted': True,
                    'returnPeriod': {'value': 30, 'unit': 'DAY'}, 'returnShippingCostPayer': 'BUYER'}),
    ]
    all_verified = True
    for kind, values in cases:
        if kind_filter != 'all' and kind != kind_filter:
            continue
        action = 'create_' + kind + '_policy'
        body = {**common, **values}
        intent = {'action': action, 'name': body['name'], 'status': 'outcome_unknown'}
        journal['unresolved'].append(intent)
        save(path, journal)
        result = await writer.invoke({'action': action, 'params': {}, 'body': body, 'confirm': True})
        policy_id = (result.get('data') or {}).get(kind + 'PolicyId')
        if result.get('success') and policy_id:
            add(path, journal, kind + '_policy', str(policy_id))
            journal['unresolved'].remove(intent)
            save(path, journal)
            listed = await reader.invoke({'action': 'list_' + kind + '_policies', 'params': {}})
            policies = (listed.get('data') or {}).get(kind + 'Policies', [])
            matched = any(str(p.get(kind + 'PolicyId')) == str(policy_id) and p.get('name') == body['name'] for p in policies)
            print(action, 'created; read-back match:', matched, flush=True)
            all_verified &= matched
        else:
            all_verified = False
            # A response with eBay validation errors is a known failure; transport
            # failures or an incomplete success remain unresolved in the journal.
            errors = result.get('errors') or []
            if result.get('http_status') in (400, 403, 409) and errors:
                journal['unresolved'].remove(intent)
                save(path, journal)
            print(action, 'not verified:', result.get('http_status'), errors or result.get('error'), flush=True)
    return all_verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--kind', choices=('all', 'payment', 'return'), default='all')
    parser.add_argument('--immediate-pay', action='store_true', help='Try a payment policy requiring immediate payment.')
    args = parser.parse_args()
    if input('Type YES to create disposable Canadian Sandbox policies: ').strip() != 'YES':
        return 1
    return 0 if asyncio.run(run(args.journal, args.kind, args.immediate_pay)) else 1


if __name__ == '__main__':
    raise SystemExit(main())

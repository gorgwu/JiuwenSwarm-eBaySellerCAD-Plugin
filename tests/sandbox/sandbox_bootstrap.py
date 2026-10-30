"""Create isolated, journaled Sandbox inventory fixtures for an end-to-end run."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.oauth import get_seller_auth, load_settings
from tools.ebay_seller_tools import EbaySellerReadTool, EbaySellerListingWriteTool, _trading
from sandbox_journal import add, create, save
from sandbox_marketplace import test_marketplace

# CC0 image: https://commons.wikimedia.org/wiki/File:Small_coffee_mug_on_a_blue_napkin_in_a_restaurant.jpg
IMAGE = 'https://upload.wikimedia.org/wikipedia/commons/d/dc/Small_coffee_mug_on_a_blue_napkin_in_a_restaurant.jpg'


def opt_in_if_needed(auth, journal, path):
    base = auth.api_base + '/sell/account/v1/program/'
    headers = {'Authorization': 'Bearer ' + auth.access_token, 'Accept': 'application/json'}
    request = urllib.request.Request(base + 'get_opted_in_programs', headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    programs = data.get('programs', [])
    if any(p.get('programType') == 'SELLING_POLICY_MANAGEMENT' for p in programs):
        journal['business_policy_opt_in'] = 'already_active'
        save(path, journal)
        return
    journal['business_policy_opt_in'] = 'request_pending_or_unknown'
    save(path, journal)
    headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(base + 'opt_in', method='POST', headers=headers,
        data=json.dumps({'programType': 'SELLING_POLICY_MANAGEMENT'}).encode())
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status not in (200, 201, 204):
            raise ValueError(f'Opt-in returned HTTP {response.status}')
    journal['business_policy_opt_in'] = 'enabled_by_run'
    save(path, journal)


async def bootstrap(path: Path, image_url: str = IMAGE, reuse_fulfillment_policy_id: str | None = None, marketplace: str = 'EBAY_CA', currency: str = 'CAD'):
    if marketplace != 'EBAY_CA':
        raise ValueError('Test bootstrap supports EBAY_CA only.')
    canada = marketplace == 'EBAY_CA'
    if currency not in {'CAD', 'USD'}:
        raise ValueError('Canadian listing test currency must be CAD or USD.')
    site_id, country, postal = 2, 'CA', 'M5V 3A8'
    if load_settings().get('EBAY_ENV', 'sandbox').strip().lower() != 'sandbox':
        raise ValueError('Sandbox configuration required.')
    auth = get_seller_auth()
    if auth.environment != 'sandbox' or auth.api_base != 'https://api.sandbox.ebay.com':
        raise ValueError('Unexpected API host.')
    reader, writer = EbaySellerReadTool(), EbaySellerListingWriteTool()
    account = await reader.invoke({'action': 'get_seller_account', 'params': {}})
    seller_id = ((account.get('response') or {}).get('User') or {}).get('UserID')
    if not account.get('success') or not seller_id:
        raise ValueError('Could not identify Sandbox seller.')
    journal = create(path, seller_id)
    journal['marketplace_id'], journal['site_id'] = marketplace, site_id
    suffix = journal['run_id'][:12]
    sku, location = 'jiuwen-' + suffix, 'jiuwen-' + suffix
    fixtures = {'sku': sku, 'location_key': location, 'revised_title': 'Jiuwen Sandbox revised ' + suffix, 'marketplace_id': marketplace, 'site_id': site_id, 'currency': currency}
    journal['fixtures'] = fixtures
    save(path, journal)
    opt_in_if_needed(auth, journal, path)

    async def write(action, kind, field=None, params=None, body=None):
        payload = {'action': action, 'params': params or {}, 'confirm': True}
        if body is not None:
            payload['body'] = body
            if canada:
                payload['params'] = {**payload['params'], 'content_language': 'en-CA'}
        intent = {'action': action, 'params': params or {}, 'name': body.get('name') if isinstance(body, dict) else None, 'status': 'outcome_unknown'}
        journal['unresolved'].append(intent)
        save(path, journal)
        result = await writer.invoke(payload)
        if not result.get('success'):
            errors = result.get('errors') or []
            duplicate = result.get('http_status') == 400 and any('duplicate' in str(e.get('longMessage', '')).lower() or 'already exists' in str(e.get('longMessage', '')).lower() for e in errors)
            if duplicate and kind in {'payment_policy', 'return_policy'}:
                listed = await reader.invoke({'action': 'list_' + kind.replace('_policy', '') + '_policies', 'params': {'marketplace_id': marketplace}})
                key = 'paymentPolicies' if kind == 'payment_policy' else 'returnPolicies'
                policies = (listed.get('data') or {}).get(key, [])
                candidates = [p for p in policies if p.get(field) and any(c.get('name') == 'ALL_EXCLUDING_MOTORS_VEHICLES' for c in p.get('categoryTypes', []))]
                if candidates:
                    value = str(candidates[0][field])
                    journal['unresolved'].remove(intent)
                    journal.setdefault('reused', []).append({'kind': kind, 'id': value, 'reason': 'eBay rejected duplicate policy'})
                    save(path, journal)
                    print(f'{action}: duplicate rejected; reusing existing {kind} {value} (not owned by this run)', flush=True)
                    return value
            raise ValueError(f"{action} failed: HTTP {result.get('http_status')}, errors {result.get('errors') or result.get('error')}")
        value = (result.get('data') or {}).get(field) if field else (params or {}).get('sku' if kind == 'inventory_item' else 'location_key')
        if not value:
            raise ValueError(f'{action} succeeded without its expected ID; inspect the unresolved journal entry.')
        add(path, journal, kind, str(value))
        journal['unresolved'].remove(intent)
        save(path, journal)
        print(f'{action}: created {kind} {value}', flush=True)
        return str(value)

    base = {'marketplaceId': marketplace, 'categoryTypes': [{'name': 'ALL_EXCLUDING_MOTORS_VEHICLES'}]}
    # Distinct shipping terms avoid eBay's duplicate-policy rejection on repeat runs.
    shipping_cents = int(suffix[:4], 16) % 900 + 100
    shipping_price = f'{shipping_cents // 100}.{shipping_cents % 100:02d}'
    ship = {**base, 'name': 'jiuwen-ship-' + suffix, 'handlingTime': {'value': 1, 'unit': 'DAY'},
            'shippingOptions': [{'optionType': 'DOMESTIC', 'costType': 'FLAT_RATE', 'shippingServices': [
                {'sortOrder': 1, 'shippingCarrierCode': 'CPC', 'shippingServiceCode': 'CA_PostExpeditedParcel',
                 'shippingCost': {'value': shipping_price, 'currency': currency},
                 'additionalShippingCost': {'value': '0.00', 'currency': currency}, 'freeShipping': False}]}]}
    pay = {**base, 'name': 'jiuwen-pay-' + suffix}
    returns = {**base, 'name': 'jiuwen-return-' + suffix, 'returnsAccepted': False}
    if reuse_fulfillment_policy_id:
        listed = await reader.invoke({'action': 'list_fulfillment_policies', 'params': {'marketplace_id': marketplace}})
        policies = (listed.get('data') or {}).get('fulfillmentPolicies', [])
        matching = [p for p in policies if str(p.get('fulfillmentPolicyId')) == reuse_fulfillment_policy_id
                    and p.get('marketplaceId') == marketplace
                    and any(c.get('name') == 'ALL_EXCLUDING_MOTORS_VEHICLES' for c in p.get('categoryTypes', []))]
        if not listed.get('success') or not matching:
            raise ValueError('Requested fulfillment policy was not found or is not eligible for the selected marketplace.')
        fulfillment_id = reuse_fulfillment_policy_id
        journal.setdefault('reused', []).append({'kind': 'fulfillment_policy', 'id': fulfillment_id,
                                                  'reason': 'explicitly selected by tester'})
        save(path, journal)
        print(f'Reusing fulfillment policy {fulfillment_id}; it will not be deleted by this run.', flush=True)
    else:
        fulfillment_id = await write('create_fulfillment_policy', 'fulfillment_policy', 'fulfillmentPolicyId', body=ship)
    payment_id = await write('create_payment_policy', 'payment_policy', 'paymentPolicyId', body=pay)
    return_id = await write('create_return_policy', 'return_policy', 'returnPolicyId', body=returns)
    location_body = {'name': 'jiuwen-location-' + suffix, 'location': {'address': {'postalCode': postal, 'country': country}}, 'locationTypes': ['WAREHOUSE']}
    # Unique generated key is checked before the replacing inventory write.
    for action, params in [('get_inventory_location', {'location_key': location}), ('get_inventory_item', {'sku': sku})]:
        prior = await reader.invoke({'action': action, 'params': params})
        if prior.get('http_status') != 404:
            raise ValueError(f'{action}: generated key exists or absence could not be verified.')
    await write('create_inventory_location', 'location', params={'location_key': location}, body=location_body)
    inventory = {'availability': {'shipToLocationAvailability': {'quantity': 3}}, 'condition': 'NEW',
                 'product': {'title': 'Sandbox test mug ' + suffix, 'description': 'Fictional Sandbox test item.',
                             'aspects': {'Brand': ['Unbranded'], 'Type': ['Coffee Mug'], 'Color': ['White']}, 'imageUrls': [image_url]}}
    await write('put_inventory_item', 'inventory_item', params={'sku': sku}, body=inventory)
    offer = {'sku': sku, 'marketplaceId': marketplace, 'format': 'FIXED_PRICE', 'availableQuantity': 3,
             'categoryId': '20695', 'listingDescription': 'Fictional Sandbox test item.', 'merchantLocationKey': location,
             'pricingSummary': {'price': {'value': '20.00', 'currency': currency}},
             'listingPolicies': {'fulfillmentPolicyId': fulfillment_id, 'paymentPolicyId': payment_id, 'returnPolicyId': return_id}}
    offer_id = await write('create_inventory_offer', 'offer', 'offerId', body=offer)
    fixtures.update({'inventory_offer_id': offer_id, 'inventory_offer_body': offer, 'inventory_item_body': inventory,
                     'location_body': location_body, 'fulfillment_policy_body': ship, 'payment_policy_body': pay,
                     'return_policy_body': returns})
    save(path, journal)
    intent = {'action': 'publish_inventory_offer', 'offer_id': offer_id, 'status': 'outcome_unknown'}
    journal['unresolved'].append(intent)
    save(path, journal)
    published = await writer.invoke({'action': 'publish_inventory_offer', 'params': {'offer_id': offer_id}, 'confirm': True})
    listing_id = (published.get('data') or {}).get('listingId')
    if not published.get('success') or not listing_id:
        raise ValueError(f"publish_inventory_offer failed: {published.get('errors') or published.get('error')}")
    fixtures['inventory_listing_id'] = str(listing_id)
    journal['unresolved'].remove(intent)
    save(path, journal)
    print(f'publish_inventory_offer: listing {listing_id}', flush=True)

    trading_item = {
        'Title': 'Sandbox test mug ' + suffix, 'Description': 'Fictional Sandbox test listing.',
        'PrimaryCategory': {'CategoryID': '20695'}, 'StartPrice': '22.00',
        'CategoryMappingAllowed': 'true', 'ConditionID': '1000', 'Country': country, 'Currency': currency,
        'DispatchTimeMax': '1', 'ListingDuration': 'GTC', 'ListingType': 'FixedPriceItem',
        'PictureDetails': {'PictureURL': image_url}, 'PostalCode': postal, 'Quantity': '1',
        'BestOfferDetails': {'BestOfferEnabled': 'true'},
        'ItemSpecifics': {'NameValueList': [{'Name': 'Brand', 'Value': 'Unbranded'},
                                           {'Name': 'Type', 'Value': 'Coffee Mug'},
                                           {'Name': 'Color', 'Value': 'White'}]},
        'SellerProfiles': {'SellerShippingProfile': {'ShippingProfileID': fulfillment_id},
                           'SellerReturnProfile': {'ReturnProfileID': return_id},
                           'SellerPaymentProfile': {'PaymentProfileID': payment_id}},
    }
    verified = await asyncio.to_thread(_trading, 'VerifyAddFixedPriceItem', {'Item': trading_item}, site_id)
    if not verified.get('success'):
        raise ValueError(f"Trading listing verification failed: {(verified.get('response') or {}).get('Errors')}")
    intent = {'action': 'AddFixedPriceItem', 'title': trading_item['Title'], 'status': 'outcome_unknown'}
    journal['unresolved'].append(intent)
    save(path, journal)
    created = await asyncio.to_thread(_trading, 'AddFixedPriceItem', {'Item': trading_item}, site_id)
    trading_id = (created.get('response') or {}).get('ItemID')
    if not created.get('success') or not trading_id:
        raise ValueError(f"Trading listing creation failed: {(created.get('response') or {}).get('Errors')}")
    add(path, journal, 'trading_listing', str(trading_id))
    fixtures.update({'listing_id': str(trading_id), 'trading_listing_id': str(trading_id)})
    journal['unresolved'].remove(intent)
    save(path, journal)
    print(f'Created Trading listing {trading_id} with Best Offer enabled.', flush=True)
    fixture_path = path.with_name(path.stem + '-fixtures.json')
    fixture_path.write_text(json.dumps(fixtures, indent=2) + '\n', encoding='utf-8')
    print(f'Fixture inputs saved to {fixture_path}. Journal: {path}')
    return fixture_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--journal', type=Path, required=True, help='New private journal path under tests/runs')
    parser.add_argument('--image-url', default=IMAGE, help='Public HTTPS test image URL (defaults to a CC0 Wikimedia image).')
    parser.add_argument('--reuse-fulfillment-policy-id', help='Reuse an eligible shipping policy for the selected marketplace.')
    parser.add_argument('--marketplace', choices=['EBAY_CA'], help='Override EBAY_MARKETPLACE_ID for this run.')
    parser.add_argument('--currency', choices=['CAD', 'USD'], default='CAD', help='Currency for Canadian test listing prices.')
    args = parser.parse_args()
    if not args.image_url.startswith('https://'):
        raise ValueError('Image URL must use HTTPS.')
    marketplace = test_marketplace(args.marketplace)
    print(f'Target: Sandbox {marketplace}. This creates business policies, a location, inventory item and offer.')
    if input('Type YES to create Sandbox fixtures: ').strip() != 'YES':
        return 1
    asyncio.run(bootstrap(args.journal, args.image_url, args.reuse_fulfillment_policy_id, marketplace, args.currency))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f'Fixture setup stopped: {exc}. Inspect the private journal before retrying.', file=sys.stderr)
        raise SystemExit(1)

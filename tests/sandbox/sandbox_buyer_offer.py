"""Place a test offer as a separate Sandbox buyer; never modifies seller credentials."""
from __future__ import annotations

import argparse
import getpass
import ipaddress
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.oauth import get_sandbox_buyer_auth, get_seller_auth
from sandbox_marketplace import test_marketplace


def sandbox_user_id(auth, site_id=2):
    if auth.environment != 'sandbox' or auth.api_base != 'https://api.sandbox.ebay.com':
        raise ValueError('Buyer test requires Sandbox credentials.')
    body = b'<?xml version="1.0" encoding="utf-8"?><GetUserRequest xmlns="urn:ebay:apis:eBLBaseComponents"/>'
    request = urllib.request.Request(auth.api_base + '/ws/api.dll', data=body, headers={
        'Content-Type': 'text/xml', 'X-EBAY-API-CALL-NAME': 'GetUser',
        'X-EBAY-API-SITEID': str(site_id), 'X-EBAY-API-COMPATIBILITY-LEVEL': '1477',
        'X-EBAY-API-IAF-TOKEN': auth.access_token})
    with urllib.request.urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())
    ns = '{urn:ebay:apis:eBLBaseComponents}'
    user = root.findtext(ns + 'User/' + ns + 'UserID')
    if root.findtext(ns + 'Ack') not in {'Success', 'Warning'} or not user:
        raise ValueError('Could not verify the Sandbox account identity.')
    return user


def listing_currency(auth, listing_id):
    """Read the listing currency from eBay; do not infer it from the marketplace."""
    if auth.environment != 'sandbox' or auth.api_base != 'https://api.sandbox.ebay.com':
        raise ValueError('Buyer test requires Sandbox credentials.')
    root = ET.Element('GetItemRequest', xmlns='urn:ebay:apis:eBLBaseComponents')
    ET.SubElement(root, 'ItemID').text = listing_id
    req = urllib.request.Request(auth.api_base + '/ws/api.dll', data=ET.tostring(root, encoding='utf-8', xml_declaration=True), headers={
        'Content-Type': 'text/xml', 'X-EBAY-API-CALL-NAME': 'GetItem', 'X-EBAY-API-SITEID': '2',
        'X-EBAY-API-COMPATIBILITY-LEVEL': '1477', 'X-EBAY-API-IAF-TOKEN': auth.access_token})
    with urllib.request.urlopen(req, timeout=30) as response:
        result = ET.fromstring(response.read())
    ns = '{urn:ebay:apis:eBLBaseComponents}'
    currency = result.findtext(ns + 'Item/' + ns + 'Currency', default='').strip().upper()
    if result.findtext(ns + 'Ack') not in {'Success', 'Warning'} or currency not in {'CAD', 'USD'}:
        raise ValueError('Could not verify the Canadian listing currency; no offer was submitted.')
    return currency


def main() -> int:
    parser = argparse.ArgumentParser(description='Test Sandbox buyer offers without changing seller credentials.')
    parser.add_argument('--accept-counter', metavar='OFFER_ID', help='Accept a seller counteroffer by its ID instead of submitting a new offer.')
    parser.add_argument('--listing-id', required=True, help='Sandbox listing ID for this test run.')
    parser.add_argument('--marketplace', choices=['EBAY_CA'], help='Canadian marketplace (the default).')
    parser.add_argument('--offer-price', default='15.00', help='Offer amount in the listing currency.')
    parser.add_argument('--counter-price', default='18.00', help='Counteroffer amount in the listing currency.')
    args = parser.parse_args()
    args.marketplace = test_marketplace(args.marketplace)
    site_id = '2'
    if args.accept_counter and (not args.accept_counter.isascii() or not args.accept_counter.isdigit()):
        raise ValueError('Counteroffer ID must be numeric.')
    if not args.listing_id.isascii() or not args.listing_id.isdigit():
        raise ValueError('Listing ID must be numeric.')
    try:
        amount = Decimal(args.counter_price if args.accept_counter else args.offer_price)
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
            raise ValueError('Price must be positive with at most two decimal places.')
    except InvalidOperation:
        raise ValueError('Price must be a valid amount.') from None
    buyer_auth = get_sandbox_buyer_auth()
    seller_auth = get_seller_auth()
    if sandbox_user_id(buyer_auth, site_id).casefold() == sandbox_user_id(seller_auth, site_id).casefold():
        raise ValueError('Buyer and seller tokens authorize the same account; authorize the separate Sandbox buyer.')
    currency = listing_currency(seller_auth, args.listing_id)
    token = buyer_auth.access_token
    if args.accept_counter:
        print(f'Ready to accept Sandbox seller counteroffer {args.accept_counter} at {currency} {amount:.2f} on listing {args.listing_id}.')
    else:
        print(f'Ready to submit a {currency} {amount:.2f} Best Offer for Sandbox listing {args.listing_id}.')
    if input('Type YES to submit: ').strip() != 'YES':
        print('Cancelled; no offer submitted.')
        return 1
    print('Looking up your public IP via api.ipify.org for eBay’s required EndUserIP field.')
    try:
        with urllib.request.urlopen('https://api.ipify.org', timeout=10) as response:
            address = response.read(100).decode('ascii').strip()
    except (urllib.error.URLError, TimeoutError, UnicodeError):
        address = getpass.getpass('Enter your public IPv4 address (hidden): ').strip()
    ip = ipaddress.ip_address(address)
    if ip.version != 4 or not ip.is_global:
        raise ValueError('A public IPv4 address is required.')
    root = ET.Element('PlaceOfferRequest', xmlns='urn:ebay:apis:eBLBaseComponents')
    ET.SubElement(root, 'EndUserIP').text = str(ip)
    ET.SubElement(root, 'ItemID').text = args.listing_id
    offer = ET.SubElement(root, 'Offer')
    ET.SubElement(offer, 'Action').text = 'Accept' if args.accept_counter else 'Offer'
    if args.accept_counter:
        ET.SubElement(offer, 'BestOfferID').text = args.accept_counter
    ET.SubElement(offer, 'MaxBid', currencyID=currency).text = f'{amount:.2f}'
    ET.SubElement(offer, 'Quantity').text = '1'
    request = urllib.request.Request('https://api.sandbox.ebay.com/ws/api.dll', data=ET.tostring(root, encoding='utf-8', xml_declaration=True), headers={'X-EBAY-API-CALL-NAME': 'PlaceOffer', 'X-EBAY-API-SITEID': site_id, 'X-EBAY-API-COMPATIBILITY-LEVEL': '1209', 'X-EBAY-API-IAF-TOKEN': token, 'Content-Type': 'text/xml'})
    with urllib.request.urlopen(request, timeout=30) as response:
        result = ET.fromstring(response.read())
    ns = '{urn:ebay:apis:eBLBaseComponents}'
    ack = result.findtext(ns + 'Ack', default='Unknown')
    print('eBay response:', ack)
    for error in result.findall(ns + 'Errors'):
        print('Error', error.findtext(ns + 'ErrorCode'), error.findtext(ns + 'LongMessage'))
    if ack in ('Success', 'Warning'):
        print('Offer ID:', result.findtext('.//' + ns + 'BestOfferID', default='not returned'))
        return 0
    return 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, EOFError, KeyboardInterrupt) as exc:
        print('Test stopped:', str(exc) if isinstance(exc, ValueError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)

"""Named Sandbox cases. Values beginning with $ are fixture keys."""

def case(params=None, body=None, verify='', requires=''):
    result = {'input': {'params': params or {}}, 'verify': verify, 'requires': requires}
    if body is not None:
        result['input']['body'] = body
    return result


CASES = {
    'get_seller_account': case(verify='Confirm the returned seller is the Sandbox seller.'),
    'get_seller_feedback': case(verify='Inspect returned feedback and pagination.'),
    'list_listings': case(verify='Find the expected listing and inspect pagination.'),
    'get_listing': case({'item_id': '$listing_id'}, verify='Compare the ID, title and item specifics with the fixture.'),
    'get_best_offers': case({'item_id': '$listing_id'}, verify='Check offer IDs, status and response-needed flag; empty history may return eBay error 20140.'),
    'list_inventory_items': case({'limit': 10}, verify='Find the SKU if it is in this page.'),
    'get_inventory_item': case({'sku': '$sku'}, verify='Compare SKU details with the fixture.'),
    'list_inventory_offers': case({'sku': '$sku', 'limit': 10}, verify='Find the expected offer ID.'),
    'get_inventory_offer': case({'offer_id': '$inventory_offer_id'}, verify='Compare offer details and status.'),
    'list_inventory_locations': case({'limit': 10}, verify='Find the location if it is in this page.'),
    'get_inventory_location': case({'location_key': '$location_key'}, verify='Compare the location details.'),
    'list_orders': case({'limit': 10}, verify='Find the order and inspect status and pagination.'),
    'list_fulfillment_policies': case({'marketplace_id': 'EBAY_CA'}, verify='Check for the expected shipping policy.'),
    'list_payment_policies': case({'marketplace_id': 'EBAY_CA'}, verify='Check for the expected payment policy.'),
    'list_return_policies': case({'marketplace_id': 'EBAY_CA'}, verify='Check for the expected return policy.'),
    'find_eligible_items': case({'marketplace_id': 'EBAY_CA', 'limit': 10}, verify='Inspect returned eligibility; Sandbox data may be simulated.'),
    'get_default_category_tree': case({'marketplace_id': 'EBAY_CA'}, verify='Check category tree ID.'),
    'get_category_suggestions': case({'category_tree_id': '2', 'q': 'coffee mug'}, verify='Inspect suggestions; Sandbox results may be mocked.'),
    'get_category_aspects': case({'category_tree_id': '2', 'category_id': '20695'}, verify='Check returned category aspects.'),
    'create_fulfillment_policy': case(body='$fulfillment_policy_body', verify='Read policies and locate the new policy.', requires='Unique policy name, business-policy opt-in and full valid shipping policy.'),
    'create_payment_policy': case(body='$payment_policy_body', verify='Read payment policies and locate the new policy.', requires='Unique policy name and full valid payment policy.'),
    'create_return_policy': case(body='$return_policy_body', verify='Read return policies and locate the new policy.', requires='Unique policy name and full valid return policy.'),
    'put_inventory_item': case({'sku': '$sku'}, '$inventory_item_body', verify='Use get_inventory_item and compare fields.', requires='Fresh SKU and complete item body; this action replaces existing data.'),
    'create_inventory_location': case({'location_key': '$location_key'}, '$location_body', verify='Use get_inventory_location and compare.', requires='Fresh location key and complete location body.'),
    'create_inventory_offer': case(body='$inventory_offer_body', verify='Save returned offer ID, then call get_inventory_offer.', requires='Inventory item, business policies, location and valid complete offer body.'),
    'update_inventory_offer': case({'offer_id': '$inventory_offer_id'}, '$inventory_offer_body', verify='Read back changed fields with get_inventory_offer.', requires='Full replacement offer body; do not omit existing fields.'),
    'publish_inventory_offer': case({'offer_id': '$inventory_offer_id'}, verify='Read offer and listing; check publication.', requires='Valid unpublished offer with required listing data.'),
    'withdraw_inventory_offer': case({'offer_id': '$inventory_offer_id'}, verify='Read offer and listing independently; report disagreement.', requires='Published disposable offer. Withdrawal changes the listing.'),
    'update_price_quantity': case(body='$bulk_update_body', verify='Read item and offer back and inspect per-item errors.', requires='Disposable SKU/offer and bulk request body.'),
    'revise_listing': case({'item_id': '$trading_listing_id', 'changes': {'Title': '$revised_title'}}, verify='Use get_listing to compare the title.', requires='Active Trading-managed disposable listing.'),
    'end_listing': case({'item_id': '$trading_listing_id', 'ending_reason': 'NotAvailable'}, verify='Use get_listing and confirm the listing ended.', requires='Disposable Trading-managed listing; ending can affect offers.'),
    'respond_to_best_offer': case({'item_id': '$listing_id', 'offer_id': '$best_offer_id', 'response': 'Counter', 'counter_price': '18.00', 'currency': '$currency', 'counter_quantity': '1'}, verify='Read offer history and check counteroffer and original status.', requires='Pending buyer offer and the listing currency; use a fresh offer for accept/decline variants.'),
    'send_offer_to_interested_buyers': case({'marketplace_id': 'EBAY_CA'}, '$interested_offer_body', verify='Inspect API result; Sandbox eligibility may not imply interested buyers.', requires='Eligible listing with interested buyers and full offer body.'),
}


def resolve(value, fixtures):
    if isinstance(value, str) and value.startswith('$'):
        key = value[1:]
        if key not in fixtures or fixtures[key] is None or (isinstance(fixtures[key], str) and fixtures[key].startswith('REPLACE_WITH_')):
            raise ValueError(f'Missing fixture: {key}')
        return fixtures[key]
    if isinstance(value, dict):
        return {key: resolve(item, fixtures) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, fixtures) for item in value]
    return value

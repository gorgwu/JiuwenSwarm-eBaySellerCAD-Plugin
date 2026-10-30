# eBay seller tools

The file `ebay_seller_tools.py` contains the three tools that JiuwenSwarm loads:

- `ebayseller_read` reads seller information, such as listings and orders.
- `ebayseller_listing_write` changes listings, inventory, and business policies.
- `ebayseller_offer_write` responds to buyer offers or sends offers to interested buyers.

Each tool supports several actions. Ask it for `describe_actions` to see their names and inputs, or see the action reference below. The Best Offers reader uses code in `ebayseller_common/best_offers.py`.

The two tools that make changes require `confirm=true`. The agent supplies this value, so it does not prove the seller approved the change. In JiuwenSwarm, turn on permissions and set both write tools to **ask**. If a change times out or its result is unclear, check eBay before trying again.

## eBay seller action reference

Each registered tool accepts an `action` and a `params` object. JSON write actions also accept `body`, which uses eBay's documented field names. Call `describe_actions` on any tool to get the action names and parameter guidance. Listings and orders return one page unless the action documents otherwise; inspect the returned pagination information before describing results as complete.

When a request fails, the tool returns an `errors` list. If eBay provides an error code and explanation, they appear as `code` and `message`; the HTTP status is shown separately. For problems detected by the plugin—such as a timeout, DNS or secure-connection failure, unreadable response, or unexpected error—`plugin_code` identifies what happened and the eBay `code` is null. Bulk updates include errors for individual items. If a change's outcome is uncertain, check eBay before retrying.

### ebayseller_read

| Action | eBay call |
| --- | --- |
| `get_seller_account` | Trading `GetUser` for the currently authorized user |
| `get_seller_feedback` | Trading `GetUser`, then `GetFeedback` for one page of seller feedback |
| `list_listings` | Trading `GetMyeBaySelling`, one page of active, scheduled, or unsold listings |
| `get_listing` | Trading `GetItem` |
| `get_best_offers` | Trading `GetBestOffers`; existing bounded scan with completeness information |
| `list_inventory_items` / `get_inventory_item` | Inventory `getInventoryItems` / `getInventoryItem` |
| `list_inventory_offers` / `get_inventory_offer` | Inventory `getOffers` / `getOffer` |
| `list_inventory_locations` / `get_inventory_location` | Inventory `getInventoryLocations` / `getInventoryLocation` |
| `list_orders` | Fulfillment `getOrders` |
| `list_fulfillment_policies` | Account `getFulfillmentPolicies` |
| `list_payment_policies` | Account `getPaymentPolicies` |
| `list_return_policies` | Account `getReturnPolicies` |
| `find_eligible_items` | Negotiation `findEligibleItems` |
| `get_default_category_tree` | Taxonomy `getDefaultCategoryTreeId` |
| `get_category_suggestions` | Taxonomy `getCategorySuggestions` |
| `get_category_aspects` | Taxonomy `getItemAspectsForCategory` |

For Best Offers, use `{"action":"get_best_offers","params":{"max_pages":2}}`; the result reports whether all pages were scanned.

### ebayseller_listing_write

| Action | eBay call |
| --- | --- |
| `create_fulfillment_policy` / `create_payment_policy` / `create_return_policy` | Account `createFulfillmentPolicy` / `createPaymentPolicy` / `createReturnPolicy` |
| `put_inventory_item` | Inventory `createOrReplaceInventoryItem` |
| `create_inventory_location` | Inventory `createInventoryLocation` |
| `create_inventory_offer` | Inventory `createOffer` |
| `update_inventory_offer` | Inventory `updateOffer` |
| `publish_inventory_offer` | Inventory `publishOffer` |
| `withdraw_inventory_offer` | Inventory `withdrawOffer` |
| `update_price_quantity` | Inventory `bulkUpdatePriceQuantity` |
| `revise_listing` | Trading `ReviseItem` for supported non-Inventory-managed listings |
| `end_listing` | Trading `EndItem` for a listing by ID and seller-selected ending reason |

Example after approval: `{"action":"publish_inventory_offer","params":{"offer_id":"OFFER_ID"},"confirm":true}`. Item and offer replacement operations require the full eBay object; missing fields may be removed. `revise_listing` supports only Title, Description, StartPrice, and Quantity, and does not support multi-variation revisions. eBay validates listing and marketplace requirements.

Ending a listing can cancel bids or result in a sale to a high bidder depending on the reason. For an Inventory-managed listing, use `withdraw_inventory_offer` so eBay's Inventory model is updated consistently. Creating a business policy requires the seller to be opted in to business policies; eBay determines required policy fields by marketplace and category. [eBay account guide](https://developer.ebay.com/develop/guides/sell/account-management-guide)

### ebayseller_offer_write

| Action | eBay call |
| --- | --- |
| `respond_to_best_offer` | Trading `RespondToBestOffer` (accept, decline, or counter) |
| `send_offer_to_interested_buyers` | Negotiation `sendOfferToInterestedBuyers` |

Example after approval: `{"action":"respond_to_best_offer","params":{"item_id":"123456789","offer_id":"987654321","response":"Decline"},"confirm":true}`. Seller-initiated offers are separate from buyer Best Offers.

Use [Inventory](https://developer.ebay.com/develop/api/sell/inventory_api), [Fulfillment](https://developer.ebay.com/develop/api/sell/fulfillment_api), [Negotiation](https://developer.ebay.com/api-docs/sell/static/marketing/offers-to-buyers.html), and [Trading](https://developer.ebay.com/devzone/xml/docs/reference/ebay/index.html) documentation for request bodies and eligibility. API access and Sandbox support vary by operation. An HTTP success indicates the API accepted or processed a request as documented, not necessarily that an asynchronous business process has finished. If a write times out, check eBay before retrying.

# eBay Seller

Manage eBay Canada listings, inventory, orders, policies, and offers through JiuwenSwarm.

## Functionality

For example, ask which Best Offers and buyer counteroffers need a reply. You can also ask the agent to list orders, check inventory, edit supported listings, or respond to offers. The Best Offer results do not cover every offer shown in Seller Hub.

The plugin provides three general tools, which provide 33 actions:

| Tool | Purpose |
| --- | --- |
| `ebayseller_read` | Read account details, feedback, listings, stock, orders, policies, categories, and offers. |
| `ebayseller_listing_write` | Create policies, manage stock and offers, and edit or end supported listings. |
| `ebayseller_offer_write` | Accept, decline, or counter a Best Offer, or send an offer to interested buyers. |

### Available actions

You can ask the agent to perform any of these 33 actions.

**Read seller information**

| Action | What it does |
| --- | --- |
| `get_seller_account` | Show your seller account details. |
| `get_seller_feedback` | Show feedback received as a seller. |
| `list_listings` | List active, scheduled, or unsold listings. |
| `get_listing` | Show the details of a listing. |
| `get_best_offers` | Show Best Offers and their status. |
| `list_inventory_items` | List inventory items. |
| `get_inventory_item` | Show an inventory item by its stock ID. |
| `list_inventory_offers` | List offers for an inventory item. |
| `get_inventory_offer` | Show an inventory offer. |
| `list_inventory_locations` | List inventory locations. |
| `get_inventory_location` | Show one inventory location. |
| `list_orders` | List orders. |
| `list_fulfillment_policies` | List shipping policies. |
| `list_payment_policies` | List payment policies. |
| `list_return_policies` | List return policies. |
| `find_eligible_items` | Find listings eligible for offers to interested buyers. |
| `get_default_category_tree` | Find the eBay Canada category list. |
| `get_category_suggestions` | Suggest categories for an item. |
| `get_category_aspects` | Show the details eBay requests for a category. |

**Change listings and inventory**

| Action | What it does |
| --- | --- |
| `create_fulfillment_policy` | Create a shipping policy. |
| `create_payment_policy` | Create a payment policy. |
| `create_return_policy` | Create a return policy. |
| `put_inventory_item` | Create or replace an inventory item. |
| `create_inventory_location` | Create an inventory location. |
| `create_inventory_offer` | Create an unpublished offer for an inventory item. |
| `update_inventory_offer` | Replace an inventory offer's details. |
| `publish_inventory_offer` | Publish an inventory offer as a listing. |
| `withdraw_inventory_offer` | Withdraw a published inventory offer. |
| `update_price_quantity` | Update price or stock for inventory items. |
| `revise_listing` | Edit supported details of a listing. |
| `end_listing` | End a supported listing. |

**Manage offers**

| Action | What it does |
| --- | --- |
| `respond_to_best_offer` | Accept, decline, or counter a buyer's Best Offer. |
| `send_offer_to_interested_buyers` | Send an offer to eligible interested buyers. |

## Limitations

The plugin is best for users who have already set up a seller account and succesfully sold items before.

The plugin currently focuses on its 33 listed actions; it does not include shipment management, refunds, promotions, disputes, or guided skills. It targets English eBay Canada, not French Canada.

During Canadian Sandbox testing, sending an offer to interested buyers returned HTTP 500 / eBay error 150000, an internal service failure on eBay's side. Delivery was not verified. Check the offer's state before retrying.

eBay has different ways to manage listings. Listings created through its Inventory API must be edited through that API. The plugin's other listing-editing action supports only certain fields and does not support listings with multiple variations. Some actions also depend on eBay granting access to your account. [Inventory API overview](https://developer.ebay.com/api-docs/sell/inventory/overview.html)

## Quickstart

### Prerequisites

- JiuwenSwarm Desktop.
- eBay Developer account.
- eBay Canada seller account.
- Python 3 for the setup script below.

[Register for an eBay Developer account](https://developer.ebay.com/signin?tab=register) and verify your email. Your Developer account provides the application keys; you will also authorize the eBay seller account you want to manage.

In JiuwenSwarm Desktop, import the `ebayseller_1.0.0` folder as a local plugin, then enable it. JiuwenSwarm's current import code creates a separate copy, so changes to the original folder do not update the installed copy.

Open PowerShell in the **installed plugin folder**, not the original download. In the default Windows personal workspace, it is normally at `%USERPROFILE%\.jiuwenswarm\agent\workspace\plugins\plugin_packages\local\ebayseller`. Custom workspaces may use a different location. The setup script creates `.env` from `.env.example` if it is missing, then prompts for any missing values. Alternatively, create and fill in `.env` yourself before setup by running `Copy-Item .env.example .env` in this folder and entering your Production App ID, Cert ID, and RuName. Keep `.env` private.


### Connect your seller account

1. Open [eBay Application Keysets](https://developer.ebay.com/my/keys). Create and copy your **Production App ID** (Client ID) and **Production Cert ID** (Client Secret). Before using the Production keyset, apply for the Marketplace Account Deletion/Closure exemption for your developer application.
2. Open [eBay User Tokens](https://developer.ebay.com/my/auth?index=0) for your Production keyset. Under **Get a Token from eBay via Your Application**, enable OAuth and create or select a Production redirect URL. Enter the information eBay requires and note its **RuName**. The RuName is not the display title or accepted URL; the accepted URL must let you read the final browser address, including its query parameters. You do not need to use **Get a User Token Here** or manually create a token; the setup script below handles seller consent and saves the refresh token.
3. In the terminal at the installed plugin folder, run:

   ```powershell
   python common/setup_oauth.py --environment production
   ```

   The script reads the installed copy's `.env` and prompts for any missing App ID, Cert ID, and RuName without echoing the values. You can fill these in `.env` yourself, but still run the script to authorize the seller and save a renewable refresh token. If the terminal cannot hide input, setup stops. The script opens eBay's permission page; sign in as the **real seller** and approve the requested account, inventory and order permissions. eBay must allow them for your app. If you previously authorized fewer permissions, run the script again and approve the updated request. A buyer account is not needed for normal use.
4. Copy the **entire final browser address** into the hidden script prompt. The address needs `code=` and `state=`. The script exchanges the code and saves the seller refresh token as `EBAY_PRODUCTION_USER_REFRESH_TOKEN` in `.env`. A page saying “Authorization successfully completed” alone is not the code. If its address has no `code=`, check that the RuName's Auth Accepted URL was saved, then rerun the script. Keep the address private because it contains a short-lived authorization code. [eBay's authorization guide](https://developer.ebay.com/develop/guides/sell/authorization)

### Use the plugin

Select the installed plugin in the JiuwenSwarm conversation input and try: "Which of my eBay Best Offers and buyer counteroffers need a response?" To check one listing, include its numeric eBay listing ID. To publish listings through eBay's Inventory API, first set up seller business policies and an inventory location. See [eBay's listing requirements](https://developer.ebay.com/api-docs/sell/static/inventory/publishing-offers.html).

The saved refresh token lets the plugin obtain and renew a short-lived access token automatically. Leave the matching `USER_ACCESS_TOKEN` field blank when using it. If the refresh token expires or is revoked, run setup again. Keep `.env` private. Alternatively, `EBAY_SELLER_ENV_FILE` can point JiuwenSwarm to a private credentials file.

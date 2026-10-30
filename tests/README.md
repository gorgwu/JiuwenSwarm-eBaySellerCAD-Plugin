# Plugin tests

These tests are for developers. Open PowerShell in the `ebayseller_1.0.0` folder before running the commands below. Tests use English eBay Canada; French Canada is not supported.

## Choose a test

There are three kinds of tests:

| Test type | What it checks | eBay account needed? | Can it change data? |
| --- | --- | --- | --- |
| [1. Simulated](#1-simulated-tests) | Plugin actions using made-up eBay responses. | No. | No. |
| [2. Sandbox](#2-ebay-sandbox-tests) | Requests sent to eBay's test environment. | Yes, a Sandbox seller account and buyer account. | the guided suite creates or changes Sandbox data. |
| [3. Framework](#3-framework-integration-tests) | How local JiuwenSwarm and agent-core load the plugin and its actions. | No for simulated checks, yes for optional live checks. | Only when running the optional live write suite. |

All three test types require Python 3:

- **Simulated:** A compatible Python environment with the `openjiuwen` library available. A JiuwenSwarm Desktop installation or local repository checkout is not required.
- **Sandbox:** Most scripts need a compatible Python environment with `openjiuwen` available. Live calls also require Sandbox credentials; some tests need a separate Sandbox buyer account.
- **Framework:** Local `agent-core` and `jiuwenswarm` repository checkouts alongside the plugin, plus a compatible Python environment. The commands below use the environment in the local JiuwenSwarm checkout.

Commands using `python` assume the compatible environment is active. None of these checks runs a conversation in JiuwenSwarm Desktop or verifies its permissions.

`tests/runs/` is not a fourth test type. It holds private Sandbox records, test inputs, and optional result files. Git ignores it. Simulated tests and the simulated framework checks show their results in the terminal; they do not save them there. Keep Sandbox run records until cleanup and any unresolved requests have been investigated.

## Set up Python

### Optional: create an environment for simulated and Sandbox tests

If you don't already have a compatible environment, install Python 3.12 and Git, then run these commands from the plugin folder in PowerShell. Use a new folder name instead of `.venv` if it already exists.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install "openjiuwen @ git+https://gitcode.com/openJiuwen/agent-core.git@e089198835426cd7681761b0cc278670cd83031f"
```

This uses the agent-core revision pinned by the local JiuwenSwarm project. **This standalone installation has not yet been verified in a fresh environment.** It does not set up the local repository checkouts needed for framework integration tests.

Use that environment directly for the simulated suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/simulated -q
```

After completing Sandbox access setup below, use it for the Sandbox read-only suite:

```powershell
.\.venv\Scripts\python.exe tests/sandbox/sandbox_tools.py --read-suite
```

For the other commands below, replace `python` with `.\.venv\Scripts\python.exe`, or activate the environment first. If you used a different folder name, substitute it in the paths.

## 1. Simulated tests

Use these first to check the plugin code without contacting eBay:

```powershell
python -m unittest discover -s tests/simulated -q
```

These tests cover the plugin's 33 actions with pretend responses. They do not prove that eBay accepts a request or that a real account works.

## 2. eBay Sandbox tests

Use these to send real requests to eBay's test environment. Complete the setup below first. The read-only check does not create records; the guided suite creates and changes Sandbox records and requires cleanup.

### Set up Sandbox access

1. Create an [eBay Developer account](https://developer.ebay.com/signin?tab=register), then create a Sandbox application keyset in [Application Keys](https://developer.ebay.com/my/keys). Copy its App ID and Cert ID.
2. Create two separate accounts using [Sandbox user registration](https://developer.ebay.com/sandbox/register): one **seller** and one **buyer**. Use the seller to create and manage listings and the buyer to make test offers; a seller cannot buy its own item. Read-only tests do not require the buyer.
3. In the Sandbox keyset's **User Tokens** page, choose **Get a Token from eBay via Your Application**, enable OAuth, and create or select a redirect URL. Complete the details eBay requests and copy its **RuName**, the name eBay assigns to the redirect. Choose an accepted URL that lets you copy the final browser address, including its query parameters.
4. In PowerShell, copy the example only if you do not already have a `.env` file:

   ```powershell
   Copy-Item .env.example .env
   ```

   Open `.env` and set `EBAY_ENV=sandbox`, `EBAY_SANDBOX_CLIENT_ID` to the Sandbox App ID, `EBAY_SANDBOX_CLIENT_SECRET` to the Sandbox Cert ID, and `EBAY_SANDBOX_RUNAME` to the RuName. Keep `EBAY_MARKETPLACE_ID=EBAY_CA`.
5. Run the seller setup:

   ```powershell
   python ebayseller_common/setup_oauth.py --environment sandbox
   ```

   Sign in as the Sandbox seller and approve access. Copy the **entire address** from the final browser page, including `code=` and `state=`, into the hidden prompt. The script saves the seller's refresh token in `.env`. If the address has no code, check the redirect's accepted URL and run setup again. Keep the address and credentials private.
6. Authorize the separate Sandbox buyer for buyer-offer tests:

   ```powershell
   python ebayseller_common/setup_oauth.py --environment sandbox --account buyer
   ```

   Sign in as the buyer, approve access, and paste the entire final address into the hidden prompt. The script saves a separate buyer refresh token without replacing the seller token. If needed, sign out of the seller account first.

### Check reads without creating data

```powershell
python tests/sandbox/sandbox_tools.py --read-suite
```

This checks 14 actions that do not require a specific listing or other record ID. A successful call only means eBay returned a successful response; compare its contents with a known record to verify the result. Some responses may be empty.

### Create test records and run the guided suite

The suite is not fully automatic: it creates some test records, but other actions need additional data or buyer activity. It asks before each change and skips cases that lack required data. An eBay success response is not proof that the intended change completed; check the result afterward.

1. Create a fresh run. Pick a new file name if this one already exists:

   ```powershell
   python tests/sandbox/sandbox_bootstrap.py --journal tests/runs/my-new-run.json
   ```

   Type `YES` to create the test records. The script may enable eBay business policies for the test seller. It creates or reuses policies, then creates a stock location, an item and listings. It saves the record of the run in `tests/runs/my-new-run.json` and its test inputs in `tests/runs/my-new-run-fixtures.json`. If it stops, inspect the run record before retrying: a request may have succeeded even if its result is unknown.
2. Optional: to reuse a suitable existing Sandbox shipping policy instead of creating another, add `--reuse-fulfillment-policy-id YOUR_POLICY_ID` to the command. Replace the placeholder with a policy ID belonging to the Sandbox seller. Reused policies are not deleted by cleanup.
3. Run the guided suite:

   ```powershell
   python tests/sandbox/sandbox_tools.py --live-suite --fixtures tests/runs/my-new-run-fixtures.json --journal tests/runs/my-new-run.json
   ```

   Review each displayed change and type `YES` to run it, or press Enter to skip it. The suite does not automatically fill every input or update every ID. For example, buyer offers and offers to interested buyers need extra setup; missing data is reported as `BLOCKED`. Check eBay's returned data and the relevant case below. Keep output private.
4. To submit a buyer Best Offer, authorize the buyer as described above, then replace the listing ID and amount in this command:

   ```powershell
   python tests/sandbox/sandbox_buyer_offer.py --listing-id YOUR_LISTING_ID --offer-price 15.00
   ```

   The script checks the listing currency and asks before sending. A separate buyer offer may be needed for each response test. An accepted offer is not necessarily a paid order.
5. When finished, review the cleanup plan, then run cleanup:

   ```powershell
   python tests/sandbox/sandbox_cleanup.py tests/runs/my-new-run.json
   python tests/sandbox/sandbox_cleanup.py tests/runs/my-new-run.json --apply
   ```

   The first command only shows the plan. The second asks you to type `CLEANUP` before changing Sandbox records. Cleanup only handles resources recorded in that run, not separate unrecorded changes or reused policies. eBay may reject deletion of a policy and can retain ended-listing and buyer history; this is not a full account reset. Keep the run record if anything remains unresolved.

For individual action commands and prerequisites, see the [Sandbox action reference](#individual-sandbox-action-reference).

## 3. Framework integration tests

This test imports the local `agent-core` and `jiuwenswarm` folders beside this plugin. It checks all 33 action routes through agent-core's manifest resolver with pretend eBay responses, and imports the public package into an isolated temporary JiuwenSwarm workspace. It does not contact eBay, start JiuwenSwarm Desktop, choose actions with a model, or test Desktop permissions.

Run it with the Python environment from the local JiuwenSwarm checkout:

```powershell
..\jiuwenswarm\.venv\Scripts\python.exe -m unittest discover -s tests/framework -v
```

### Optional: run live Sandbox calls through agent-core

First complete [Sandbox setup](#set-up-sandbox-access). To make safe real Sandbox reads through agent-core's resolved `ebayseller_read` tool:

```powershell
..\jiuwenswarm\.venv\Scripts\python.exe tests/framework/live_sandbox_reads.py
```

After creating a fixture file with the [Sandbox bootstrap steps](#create-test-records-and-run-the-guided-suite), add `--fixtures tests/runs/my-new-run-fixtures.json` to check five additional record-specific reads. The command prints only action names, result status, and eBay error codes.

To run the full fixture-based Sandbox suite through the three tools resolved from `manifest.json`, use:

```powershell
..\jiuwenswarm\.venv\Scripts\python.exe tests/framework/live_sandbox_suite.py --live-suite --fixtures tests/runs/my-new-run-fixtures.json --journal tests/runs/my-new-run.json
```

It asks before every write. Add `--approve-writes` only when you intentionally want to automate those Sandbox writes. It remains Sandbox-only and uses the same journal and cleanup process described below. Missing test data can block cases; an accepted request still needs its result checked.

## Known limits and read-back checks

- eBay returned HTTP 500 / error 150000 when a Sandbox test tried to send an offer to interested buyers. Delivery was not confirmed. Check the result before retrying.
- Sandbox buyer checkout previously failed, and eBay says its Sandbox cart is unsupported. A buyer offer can still be tested separately. [eBay's Sandbox limitations](https://developer.ebay.com/support/knowledge-base/684)
- Sandbox behavior can differ from production. The framework test checks plugin loading, not a running JiuwenSwarm Desktop conversation.

To check known records in a run before cleanup, use a new output file:

```powershell
python tests/sandbox/verify_canadian_reads.py --journal tests/runs/my-new-run.json --output tests/runs/my-new-run-reads.json
python tests/sandbox/verify_read_gaps.py --journal tests/runs/my-new-run.json --output tests/runs/my-new-run-gaps.json
```

Each result describes what was checked; it does not guarantee every field or page is correct. Keep the files private.

## Individual Sandbox action reference

To see all actions and what each test needs:

```powershell
python tests/sandbox/sandbox_tools.py --list
python tests/sandbox/sandbox_tools.py --cases
```

For the commands below that need test data, use the generated `tests/runs/my-new-run-fixtures.json`, or create your own private file:

```powershell
Copy-Item tests/sandbox/sandbox-fixtures.example.json tests/sandbox-fixtures.json
```

Do not overwrite an existing file. Fill in the required IDs and complete request data for the action, as the example contains placeholders not ready-to-use values. The generated file may also need additional fields. If using the generated file, replace `tests/sandbox-fixtures.json` in the command with its path. Write actions ask for `YES`; read the request before confirming. Check the returned data against eBay and mark the result as passed, failed, blocked, or uncertain. An empty result or a successful response alone may not verify the action.

#### Read actions

##### `get_seller_account`

- Run: `python tests/sandbox/sandbox_tools.py --case get_seller_account`
- Fields needed: none
- Verify: Confirm the returned seller is the Sandbox seller.

##### `get_seller_feedback`

- Run: `python tests/sandbox/sandbox_tools.py --case get_seller_feedback`
- Fields needed: none
- Verify: Inspect returned feedback and additional pages.

##### `list_listings`

- Run: `python tests/sandbox/sandbox_tools.py --case list_listings`
- Fields needed: none
- Verify: Find the expected listing and inspect additional pages.

##### `get_listing`

- Run: `python tests/sandbox/sandbox_tools.py --case get_listing --fixtures tests/sandbox-fixtures.json`
- Fields needed: `listing_id`
- Verify: Compare the ID, title and item specifics with the test data.

##### `get_best_offers`

- Run: `python tests/sandbox/sandbox_tools.py --case get_best_offers --fixtures tests/sandbox-fixtures.json`
- Fields needed: `listing_id`
- Verify: Check offer IDs, status and response-needed flag; empty history may return eBay error 20140.

##### `list_inventory_items`

- Run: `python tests/sandbox/sandbox_tools.py --case list_inventory_items`
- Fields needed: none
- Verify: Find the stock ID (SKU) if it is in this page.

##### `get_inventory_item`

- Run: `python tests/sandbox/sandbox_tools.py --case get_inventory_item --fixtures tests/sandbox-fixtures.json`
- Fields needed: `sku`
- Verify: Compare stock ID (SKU) details with the test data.

##### `list_inventory_offers`

- Run: `python tests/sandbox/sandbox_tools.py --case list_inventory_offers --fixtures tests/sandbox-fixtures.json`
- Fields needed: `sku`
- Verify: Find the expected offer ID.

##### `get_inventory_offer`

- Run: `python tests/sandbox/sandbox_tools.py --case get_inventory_offer --fixtures tests/sandbox-fixtures.json`
- Fields needed: `inventory_offer_id`
- Verify: Compare offer details and status.

##### `list_inventory_locations`

- Run: `python tests/sandbox/sandbox_tools.py --case list_inventory_locations`
- Fields needed: none
- Verify: Find the location if it is in this page.

##### `get_inventory_location`

- Run: `python tests/sandbox/sandbox_tools.py --case get_inventory_location --fixtures tests/sandbox-fixtures.json`
- Fields needed: `location_key`
- Verify: Compare the location details.

##### `list_orders`

- Run: `python tests/sandbox/sandbox_tools.py --case list_orders`
- Fields needed: none
- Verify: Find the order and inspect status and additional pages.

##### `list_fulfillment_policies`

- Run: `python tests/sandbox/sandbox_tools.py --case list_fulfillment_policies`
- Fields needed: none
- Verify: Check for the expected shipping policy.

##### `list_payment_policies`

- Run: `python tests/sandbox/sandbox_tools.py --case list_payment_policies`
- Fields needed: none
- Verify: Check for the expected payment policy.

##### `list_return_policies`

- Run: `python tests/sandbox/sandbox_tools.py --case list_return_policies`
- Fields needed: none
- Verify: Check for the expected return policy.

##### `find_eligible_items`

- Run: `python tests/sandbox/sandbox_tools.py --case find_eligible_items`
- Fields needed: none
- Verify: Inspect returned eligibility; Sandbox data may be simulated.

##### `get_default_category_tree`

- Run: `python tests/sandbox/sandbox_tools.py --case get_default_category_tree`
- Fields needed: none
- Verify: Check category tree ID.

##### `get_category_suggestions`

- Run: `python tests/sandbox/sandbox_tools.py --case get_category_suggestions`
- Fields needed: none
- Verify: Inspect suggestions; Sandbox results may be mocked.

##### `get_category_aspects`

- Run: `python tests/sandbox/sandbox_tools.py --case get_category_aspects`
- Fields needed: none
- Verify: Check returned category aspects.

#### Listing and inventory writes

##### `create_fulfillment_policy`

- Run: `python tests/sandbox/sandbox_tools.py --case create_fulfillment_policy --fixtures tests/sandbox-fixtures.json`
- Fields needed: `fulfillment_policy_body`
- Before running: Unique policy name, business-policy opt-in and complete, valid shipping policy.
- Verify: Read policies and locate the new policy.

##### `create_payment_policy`

- Run: `python tests/sandbox/sandbox_tools.py --case create_payment_policy --fixtures tests/sandbox-fixtures.json`
- Fields needed: `payment_policy_body`
- Before running: Unique policy name and complete, valid payment policy.
- Verify: Read payment policies and locate the new policy.

##### `create_return_policy`

- Run: `python tests/sandbox/sandbox_tools.py --case create_return_policy --fixtures tests/sandbox-fixtures.json`
- Fields needed: `return_policy_body`
- Before running: Unique policy name and complete, valid return policy.
- Verify: Read return policies and locate the new policy.

##### `create_inventory_location`

- Run: `python tests/sandbox/sandbox_tools.py --case create_inventory_location --fixtures tests/sandbox-fixtures.json`
- Fields needed: `location_body`, `location_key`
- Before running: Fresh location key and complete location request data.
- Verify: Use get_inventory_location and compare.

##### `put_inventory_item`

- Run: `python tests/sandbox/sandbox_tools.py --case put_inventory_item --fixtures tests/sandbox-fixtures.json`
- Fields needed: `inventory_item_body`, `sku`
- Before running: Fresh stock ID (SKU) and complete item request data; this action replaces existing data.
- Verify: Use get_inventory_item and compare fields.

##### `create_inventory_offer`

- Run: `python tests/sandbox/sandbox_tools.py --case create_inventory_offer --fixtures tests/sandbox-fixtures.json`
- Fields needed: `inventory_offer_body`
- Before running: Inventory item, business policies, location and valid complete offer request data.
- Verify: Save returned offer ID, then call get_inventory_offer.

##### `update_inventory_offer`

- Run: `python tests/sandbox/sandbox_tools.py --case update_inventory_offer --fixtures tests/sandbox-fixtures.json`
- Fields needed: `inventory_offer_body`, `inventory_offer_id`
- Before running: Full replacement offer request data; do not omit existing fields.
- Verify: Read back changed fields with get_inventory_offer.

##### `publish_inventory_offer`

- Run: `python tests/sandbox/sandbox_tools.py --case publish_inventory_offer --fixtures tests/sandbox-fixtures.json`
- Fields needed: `inventory_offer_id`
- Before running: Valid unpublished offer with required listing data.
- Verify: Read offer and listing; check publication.

##### `update_price_quantity`

- Run: `python tests/sandbox/sandbox_tools.py --case update_price_quantity --fixtures tests/sandbox-fixtures.json`
- Fields needed: `bulk_update_body`
- Before running: Disposable stock ID (SKU)/offer and bulk request request data.
- Verify: Read item and offer back and inspect per-item errors.

##### `withdraw_inventory_offer`

- Run: `python tests/sandbox/sandbox_tools.py --case withdraw_inventory_offer --fixtures tests/sandbox-fixtures.json`
- Fields needed: `inventory_offer_id`
- Before running: Published disposable offer. Withdrawal changes the listing.
- Verify: Read offer and listing independently; report disagreement.

##### `revise_listing`

- Run: `python tests/sandbox/sandbox_tools.py --case revise_listing --fixtures tests/sandbox-fixtures.json`
- Fields needed: `revised_title`, `trading_listing_id`
- Before running: Active Trading-managed disposable listing.
- Verify: Use get_listing to compare the title.

##### `end_listing`

- Run: `python tests/sandbox/sandbox_tools.py --case end_listing --fixtures tests/sandbox-fixtures.json`
- Fields needed: `trading_listing_id`
- Before running: Disposable Trading-managed listing; ending can affect offers.
- Verify: Use get_listing and confirm the listing ended.

#### Offer writes

##### `respond_to_best_offer`

- Run: `python tests/sandbox/sandbox_tools.py --case respond_to_best_offer --fixtures tests/sandbox-fixtures.json`
- Fields needed: `best_offer_id`, `listing_id`
- Before running: Pending buyer offer; use a fresh offer for accept/decline variants.
- Verify: Read offer history and check counteroffer and original status.

##### `send_offer_to_interested_buyers`

- Run: `python tests/sandbox/sandbox_tools.py --case send_offer_to_interested_buyers --fixtures tests/sandbox-fixtures.json`
- Fields needed: `interested_offer_body`
- Before running: Eligible listing with interested buyers and full offer request data.
- Verify: Inspect API result; Sandbox eligibility may not imply interested buyers.

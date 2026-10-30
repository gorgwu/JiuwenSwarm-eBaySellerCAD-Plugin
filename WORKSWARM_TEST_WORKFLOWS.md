# WorkSwarm video demo workflows

FILE TO BE REMOVED AFTER COMPLETION.

Use these three short conversations as a video demo of the plugin in WorkSwarm. Each starts with a seller-side checkpoint, then shows a conversation and a final comparison with eBay. Replace anything in `[brackets]` with details from your Sandbox account. Send each message separately so the agent's responses and reasoning are visible.

## Before you start

1. Clone the repository, then import and enable the plugin in WorkSwarm. Follow the [plugin setup instructions](README.md) to connect an eBay Canada seller account. The cloned repository does not contain your private `.env` or credentials; set them up on the new laptop.
2. Use a Sandbox seller and test records if possible. For Sandbox credentials and a separate buyer account, see [Sandbox setup](tests/README.md#set-up-sandbox-access). Configure the installed plugin's credentials for the same environment as your test records. Production actions affect your real account.
3. Enable permissions in WorkSwarm and set `ebayseller_listing_write` and `ebayseller_offer_write` to **ask**. Review the exact action before approving it. The agent's own `confirm` value is not proof of your approval.

These are manual tests: automated framework checks do not establish that a conversation or permission prompt works in your installed WorkSwarm version. An empty account may return no matching records; that is a valid result, not proof that the agent checked a record.

For the checkpoints, sign in as your **Sandbox seller** at [eBay Sandbox](https://www.sandbox.ebay.com/), then use My eBay or Seller Hub to find your listings, offers, and policies. The eBay Developer website is where you manage test users and keys; it is not the seller's listing dashboard. Sandbox pages and navigation can differ from production. If a page or feature fails to load, record that and use the plugin's read actions as a secondary check.

Before recording, prepare a pending buyer offer and an editable test listing, open the relevant seller pages in browser tabs, and rehearse the conversations once. If you respond to an offer during rehearsal, prepare another pending offer for the recording. Keep tokens, passwords, private account data, and buyer information off screen. The third workflow is deliberately read-only, so its result is a plan rather than a visible account change.

## 1. Review a buyer offer

**Demo story:** Show the agent finding an offer, reasoning about a seller's minimum price, and preparing a counteroffer for approval.

**You need:** A listing with a pending Best Offer from a separate buyer. If no offer is available, run the first message and ask the agent to explain what it found without taking an action.

**Seller checkpoint before the conversation:** Sign in to eBay Sandbox as the seller. Find the listing and its pending offer in your selling or offers view, if available. Note the listing ID, amount, currency, and current status for comparison.

**Message 1**

> Check my pending Best Offers and counteroffers. Summarize the listing, offer amount, currency, and status for each one you find. Tell me if the results might be incomplete.

**Message 2**

> For the offer on listing `[listing ID]`, what are my options? Explain the trade-offs without responding to the buyer yet. My minimum price is `[amount and currency]`.

**Message 3**

> Prepare a counteroffer of `[amount in the listing's currency]` for that buyer. Show me the listing, offer ID, and amount before doing anything; wait for my approval.

**Check:** The agent should use seller records rather than invent an offer, respect your minimum, and wait for approval before submitting. If you approve, check the offer status on eBay or ask the agent to read it again. An approval request and a successful response are separate things. The Best Offer scan is bounded and may not cover everything in Seller Hub.

**Seller checkpoint after approval:** Refresh the listing's offer details or offers view in eBay Sandbox. Look for the counteroffer amount and updated status, and compare them with the agent's answer. If the page fails or does not show the update, ask the agent to read the offer again and record that the website check was inconclusive. Do not retry an uncertain submission without checking its state.

## 2. Investigate and improve a listing

**Demo story:** Show the original listing, the agent's proposed improvement, approval, and the updated title on eBay.

**You need:** A known listing ID and, for the optional edit, a disposable single-variation listing that can be edited with eBay's Trading API. Inventory API-managed listings must be edited through the Inventory API instead.

**Seller checkpoint before the conversation:** In the Sandbox seller's active listings, open the test listing and note its current title and listing ID. You can also open `https://www.sandbox.ebay.com/itm/[listing ID]` after replacing the bracketed value.

**Message 1**

> Look up my listing `[listing ID]` and summarize its title, description, price, quantity, and any other details you can actually see. Tell me if any of those fields are unavailable.

**Message 2**

> Suggest a clearer title using only details in the listing. Explain your reasoning, and do not invent product specifications or change anything yet.

**Message 3**

> For this eligible test listing, propose changing the title to `[your chosen title]`. Show the current and proposed titles and wait for my approval before submitting.

**Check:** Compare the first answer and suggested title with the listing. If you approve a supported edit, ask the agent to look up the listing again and compare it with eBay. If the listing is Inventory API-managed, has multiple variations, or cannot be edited by this action, the agent should explain the limitation instead of claiming an edit succeeded.

**Seller checkpoint after approval:** Refresh the Sandbox listing page or active listings view and compare the title with the approved title. If the update is not visible, try an agent read-back and record the discrepancy rather than assuming it succeeded.

## 3. Prepare a new product listing

**Demo story:** Show the agent combining category information and the seller's policies into a practical listing checklist without changing the account.

**You need:** A product you want to list, its verified details, and an eBay Canada seller account. This workflow can be tested without publishing anything.

**Seller checkpoint before the conversation:** In the Sandbox seller account, look at your existing business policies and listings if those views are available. Note which policies already exist so you can compare them with the agent's answer.

**Message 1**

> I want to list `[product description]` on eBay Canada. Suggest an appropriate category and show the item details eBay asks for in that category. Don't create a listing.

**Message 2**

> Check my shipping, payment, and return policies and inventory locations. What information would I still need to prepare this listing? Distinguish what you found in my account from information I need to provide.

**Message 3**

> Using only the details we've confirmed, give me a checklist of the steps needed to create and publish this listing. Tell me which steps would change my eBay account, but don't perform them.

**Check:** The agent should use category and policy data where available, flag missing details and permissions, and avoid claiming that a listing was created. Inventory API publishing requires the necessary policies, location, item and offer; the agent should not invent them.

**Seller checkpoint after the conversation:** Refresh the seller's policies and listings views. This workflow requests advice only, so you should not expect a new listing or policy. If a view is unavailable, record that the website comparison could not be completed.

## Record your results

For each workflow, note the date, environment (Sandbox or production), whether the agent selected the relevant plugin tools, and whether its answers matched eBay. Record whether approval appeared for a write and whether any approved change was confirmed on eBay. Do not include tokens, passwords, buyer information, or private account data in shared notes.

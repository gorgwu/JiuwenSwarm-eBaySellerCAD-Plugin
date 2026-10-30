"""eBay seller actions grouped by JiuwenSwarm permission boundary."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from openjiuwen.core.foundation.tool import Tool, ToolCard
from common.oauth import get_application_auth, get_seller_auth
from common.best_offers import EbayBestOffersTool
from common.errors import InvalidResponseError, ebay_errors, http_error, local_failure, trading_failure

NS = "{urn:ebay:apis:eBLBaseComponents}"

# Each REST route is fixed here. The caller cannot supply an arbitrary host or path.
# Tuple: HTTP method, path, path parameters, accepted query parameters, requires body.
READ = {
    "list_inventory_items": ("GET", "/sell/inventory/v1/inventory_item", (), ("limit", "offset"), False),
    "get_inventory_item": ("GET", "/sell/inventory/v1/inventory_item/{sku}", ("sku",), (), False),
    "list_inventory_offers": ("GET", "/sell/inventory/v1/offer", (), ("sku", "format", "limit", "offset"), False),
    "get_inventory_offer": ("GET", "/sell/inventory/v1/offer/{offer_id}", ("offer_id",), (), False),
    "list_inventory_locations": ("GET", "/sell/inventory/v1/location", (), ("limit", "offset"), False),
    "get_inventory_location": ("GET", "/sell/inventory/v1/location/{location_key}", ("location_key",), (), False),
    "list_orders": ("GET", "/sell/fulfillment/v1/order", (), ("filter", "limit", "offset"), False),
    "list_fulfillment_policies": ("GET", "/sell/account/v1/fulfillment_policy", (), ("marketplace_id",), False),
    "list_payment_policies": ("GET", "/sell/account/v1/payment_policy", (), ("marketplace_id",), False),
    "list_return_policies": ("GET", "/sell/account/v1/return_policy", (), ("marketplace_id",), False),
    "find_eligible_items": ("GET", "/sell/negotiation/v1/find_eligible_items", (), ("limit", "offset"), False),
    "get_default_category_tree": ("GET", "/commerce/taxonomy/v1/get_default_category_tree_id", (), ("marketplace_id",), False),
    "get_category_suggestions": ("GET", "/commerce/taxonomy/v1/category_tree/{category_tree_id}/get_category_suggestions", ("category_tree_id",), ("q",), False),
    "get_category_aspects": ("GET", "/commerce/taxonomy/v1/category_tree/{category_tree_id}/get_item_aspects_for_category", ("category_tree_id",), ("category_id",), False),
}
LISTING_WRITE = {
    "create_fulfillment_policy": ("POST", "/sell/account/v1/fulfillment_policy", (), (), True),
    "create_payment_policy": ("POST", "/sell/account/v1/payment_policy", (), (), True),
    "create_return_policy": ("POST", "/sell/account/v1/return_policy", (), (), True),
    "put_inventory_item": ("PUT", "/sell/inventory/v1/inventory_item/{sku}", ("sku",), (), True),
    "create_inventory_location": ("POST", "/sell/inventory/v1/location/{location_key}", ("location_key",), (), True),
    "create_inventory_offer": ("POST", "/sell/inventory/v1/offer", (), (), True),
    "update_inventory_offer": ("PUT", "/sell/inventory/v1/offer/{offer_id}", ("offer_id",), (), True),
    "publish_inventory_offer": ("POST", "/sell/inventory/v1/offer/{offer_id}/publish", ("offer_id",), (), False),
    "withdraw_inventory_offer": ("POST", "/sell/inventory/v1/offer/{offer_id}/withdraw", ("offer_id",), (), False),
    "update_price_quantity": ("POST", "/sell/inventory/v1/bulk_update_price_quantity", (), (), True),
}
OFFER_WRITE = {
    "send_offer_to_interested_buyers": ("POST", "/sell/negotiation/v1/send_offer_to_interested_buyers", (), (), True),
}

DESCRIPTIONS = {
    "get_seller_account": "Retrieve the currently authorized eBay user through Trading GetUser; params: optional site_id. May contain private account information.",
    "get_seller_feedback": "Retrieve one page of feedback received as a seller; discovers the authorized user via GetUser, then calls GetFeedback. Params: optional page, per_page (25, 50, 100, or 200), site_id. Check PaginationResult.",
    "list_listings": "List one page of active, scheduled, or unsold seller listings using Trading GetMyeBaySelling; params: listing_status (active/scheduled/unsold), page, per_page, site_id. Check pagination before claiming all results.",
    "get_listing": "Retrieve one listing with Trading GetItem; params: item_id, optional site_id.",
    "get_best_offers": "Read Best Offers using the existing paginated tool; params: item_id, per_page, max_pages, start_page, site_id (2 for English Canada).",
    "list_inventory_items": "List a page of Inventory API items; params: limit, offset.",
    "get_inventory_item": "Retrieve an Inventory API item by SKU; params: sku.",
    "list_inventory_offers": "List Inventory API offers; params: sku, format, limit, offset.",
    "get_inventory_offer": "Retrieve an Inventory API offer; params: offer_id.",
    "list_inventory_locations": "List Inventory API locations; params: limit, offset.",
    "get_inventory_location": "Retrieve an Inventory API location; params: location_key.",
    "list_orders": "List completed-checkout orders; params: filter, limit, offset.",
    "list_fulfillment_policies": "List shipping policies; params: marketplace_id (defaults to EBAY_CA).",
    "list_payment_policies": "List payment policies; params: marketplace_id.",
    "list_return_policies": "List return policies; params: marketplace_id.",
    "find_eligible_items": "Find listings eligible for offers to interested buyers; params: marketplace_id, limit, offset.",
    "get_default_category_tree": "Get a marketplace category tree ID; params: marketplace_id.",
    "get_category_suggestions": "Find suggested categories; params: category_tree_id, q.",
    "get_category_aspects": "Get category item specifics; params: category_tree_id, category_id.",
    "put_inventory_item": "Create or REPLACE the complete Inventory API item; params: sku; body: full eBay inventory item. Existing fields omitted may be lost.",
    "create_fulfillment_policy": "Create a shipping/fulfillment business policy; body: eBay fulfillment policy including name, marketplaceId, categoryTypes and shipping settings.",
    "create_payment_policy": "Create a payment business policy; body: eBay payment policy including name, marketplaceId and categoryTypes.",
    "create_return_policy": "Create a returns business policy; body: eBay return policy including name, marketplaceId, categoryTypes and return settings.",
    "create_inventory_location": "Create an inventory location; params: location_key; body: eBay location object.",
    "create_inventory_offer": "Create an unpublished Inventory API offer; body: eBay offer object.",
    "update_inventory_offer": "REPLACE an Inventory API offer; params: offer_id; body: complete eBay offer object. Omitted fields may be lost.",
    "publish_inventory_offer": "Publish an Inventory API offer as a listing; params: offer_id.",
    "withdraw_inventory_offer": "Withdraw a published Inventory API offer; params: offer_id.",
    "update_price_quantity": "Update price/quantity via Inventory bulkUpdatePriceQuantity; body: eBay requests array.",
    "revise_listing": "Revise a non-Inventory-managed active listing using Trading ReviseItem; params: item_id, changes (Title, Description, StartPrice, Quantity), optional site_id. See restrictions.",
    "end_listing": "End a Trading-managed listing early via EndItem; params: item_id, ending_reason (Incorrect, LostOrBroken, NotAvailable, OtherListingError, SellToHighBidder, or Sold), optional site_id. Ending can cancel bids or sell to a high bidder; check current listing and seller intent. For Inventory-managed listings use withdraw_inventory_offer.",
    "respond_to_best_offer": "Accept, decline or counter a buyer Best Offer; params: item_id, offer_id, response (Accept/Decline/Counter), and counter_price, currency, counter_quantity for Counter.",
    "send_offer_to_interested_buyers": "Send a seller-initiated offer; params: marketplace_id; body: eBay offeredItems and offerDuration. In a Canadian Sandbox test, eBay returned HTTP 500 / error 150000 reporting an internal service failure. Delivery was not verified; check the outcome before retrying a failed or timed-out request.",
}


def _text(value: Any, name: str) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value).strip():
        raise ValueError(f"{name} is required")
    result = str(value).strip()
    if len(result) > 500 or any(ord(c) < 32 for c in result):
        raise ValueError(f"invalid {name}")
    return result


def _xml_object(node: ET.Element) -> Any:
    children = list(node)
    if not children and not node.attrib:
        return (node.text or "").strip()
    result: dict[str, Any] = {"@" + key: val for key, val in node.attrib.items()}
    if node.text and node.text.strip():
        result["value"] = node.text.strip()
    for child in children:
        key = child.tag.split("}", 1)[-1]
        value = _xml_object(child)
        if key in result:
            if not isinstance(result[key], list):
                result[key] = [result[key]]
            result[key].append(value)
        else:
            result[key] = value
    return result


def _trading(call: str, fields: dict[str, Any], site_id: int = 2) -> dict[str, Any]:
    auth = get_seller_auth()
    root = ET.Element(NS + call + "Request")
    def add(parent: ET.Element, values: dict[str, Any]) -> None:
        for key, value in values.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        add(ET.SubElement(parent, NS + key), item)
                    else:
                        ET.SubElement(parent, NS + key).text = str(item)
            elif isinstance(value, dict):
                add(ET.SubElement(parent, NS + key), value)
            else:
                ET.SubElement(parent, NS + key).text = str(value)
    add(root, fields)
    request = urllib.request.Request(
        auth.api_base + "/ws/api.dll", data=ET.tostring(root, encoding="utf-8", xml_declaration=True), method="POST",
        headers={"Content-Type": "text/xml", "X-EBAY-API-CALL-NAME": call,
                 "X-EBAY-API-COMPATIBILITY-LEVEL": "1477", "X-EBAY-API-SITEID": str(site_id),
                 "X-EBAY-API-IAF-TOKEN": auth.access_token},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = ET.fromstring(response.read())
    if result.tag != NS + call + "Response":
        raise InvalidResponseError("Unexpected eBay Trading API response")
    ack = result.findtext(NS + "Ack")
    details = _xml_object(result)
    if ack not in {"Success", "Warning"} or any(node.text != "Success" for node in result.findall(".//" + NS + "CallStatus")):
        return {"success": False, "environment": auth.environment, "api_call": call, "response": details, "errors": trading_failure(details)}
    return {"success": True, "environment": auth.environment, "api_call": call, "response": details}


def _rest(action: str, spec: tuple, params: dict[str, Any], body: Any) -> dict[str, Any]:
    method, path, path_fields, query_fields, needs_body = spec
    params = dict(params)
    if action in {"list_fulfillment_policies", "list_payment_policies", "list_return_policies", "get_default_category_tree", "find_eligible_items", "send_offer_to_interested_buyers"}:
        params.setdefault("marketplace_id", "EBAY_CA")
    if "marketplace_id" in params and params["marketplace_id"] != "EBAY_CA":
        raise ValueError("This plugin supports EBAY_CA only")
    if isinstance(body, dict) and "marketplaceId" in body and body["marketplaceId"] != "EBAY_CA":
        raise ValueError("Request marketplaceId must be EBAY_CA")
    if "content_language" in params and params["content_language"] != "en-CA":
        raise ValueError("This plugin supports English Canada (en-CA) only")
    allowed = set(path_fields) | set(query_fields)
    allowed.add("content_language")
    if action in {"find_eligible_items", "send_offer_to_interested_buyers"}:
        allowed.add("marketplace_id")
    unknown = set(params) - allowed
    if unknown:
        raise ValueError("Unsupported params: " + ", ".join(sorted(unknown)))
    for field in path_fields:
        path = path.replace("{" + field + "}", urllib.parse.quote(_text(params.get(field), field), safe=""))
    if needs_body and (not isinstance(body, dict) or not body):
        raise ValueError("body must be a non-empty object containing the eBay request fields")
    if not needs_body and body is not None:
        raise ValueError("this action does not accept a body")
    if action in {"list_fulfillment_policies", "list_payment_policies", "list_return_policies", "get_default_category_tree"}:
        _text(params.get("marketplace_id"), "marketplace_id")
    if action == "list_inventory_offers":
        _text(params.get("sku"), "sku")
    if action == "get_category_suggestions":
        _text(params.get("q"), "q")
    if action == "get_category_aspects":
        _text(params.get("category_id"), "category_id")
    query = {key: _text(params[key], key) for key in query_fields if key in params}
    if query:
        path += "?" + urllib.parse.urlencode(query)
    auth = get_application_auth() if action.startswith("get_category_") or action == "get_default_category_tree" else get_seller_auth()
    headers = {"Authorization": "Bearer " + auth.access_token, "Accept": "application/json"}
    if body is not None:
        headers.update({"Content-Type": "application/json", "Content-Language": _text(params.get("content_language", "en-CA"), "content_language")})
    elif "content_language" in params:
        headers["Content-Language"] = _text(params["content_language"], "content_language")
    if action in {"find_eligible_items", "send_offer_to_interested_buyers"}:
        headers["X-EBAY-C-MARKETPLACE-ID"] = _text(params.get("marketplace_id"), "marketplace_id")
    request = urllib.request.Request(auth.api_base + path, method=method, headers=headers,
                                     data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            status = response.status
            location = response.headers.get("Location")
    except urllib.error.HTTPError as exc:
        result = http_error(exc)
        result.update({"environment": auth.environment, "action": action})
        return result
    result: dict[str, Any] = {"success": True, "environment": auth.environment, "action": action, "http_status": status}
    if raw:
        try:
            result["data"] = json.loads(raw)
        except ValueError:
            raise InvalidResponseError("eBay returned an invalid JSON response") from None
    if action == "update_price_quantity" and isinstance(result.get("data"), dict):
        responses = result["data"].get("responses", [])
        failed = [entry for entry in responses if isinstance(entry, dict) and
                  (entry.get("errors") or str(entry.get("statusCode", "200")).isdigit() and int(entry.get("statusCode", 200)) >= 400)]
        if failed:
            result["success"] = False
            result["partial_failure"] = True
            result["message"] = "One or more requested updates failed; inspect each response before retrying."
            result["errors"] = [dict(error, sku=entry.get("sku")) for entry in failed for error in ebay_errors(entry.get("errors", []))]
            for entry in failed:
                if not ebay_errors(entry.get("errors", [])):
                    result["errors"].append({"code": None, "message": "eBay reported an item failure without an explanation.", "category": None, "domain": None, "sku": entry.get("sku")})
    if location:
        result["location"] = location
    return result


def _site_id(params: dict[str, Any]) -> int:
    value = params.get("site_id", 2)
    if isinstance(value, bool) or str(value) != "2":
        raise ValueError("This plugin supports English Canada site_id 2 only")
    return 2


def _trading_action(action: str, params: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "get_seller_account": {"site_id"},
        "get_seller_feedback": {"page", "per_page", "site_id"},
        "list_listings": {"listing_status", "page", "per_page", "site_id"},
        "get_listing": {"item_id", "site_id"},
        "revise_listing": {"item_id", "changes", "site_id"},
        "end_listing": {"item_id", "ending_reason", "site_id"},
        "respond_to_best_offer": {"item_id", "offer_id", "response", "counter_price", "currency", "counter_quantity", "site_id"},
    }
    if action in allowed and set(params) - allowed[action]:
        raise ValueError("Unsupported params: " + ", ".join(sorted(set(params) - allowed[action])))
    if action == "get_seller_account":
        return _trading("GetUser", {}, _site_id(params))
    if action == "get_seller_feedback":
        page, per_page = params.get("page", 1), params.get("per_page", 25)
        if isinstance(page, bool) or not str(page).isdigit() or int(page) < 1:
            raise ValueError("page must be a positive integer")
        if isinstance(per_page, bool) or str(per_page) not in {"25", "50", "100", "200"}:
            raise ValueError("per_page must be 25, 50, 100, or 200")
        account = _trading("GetUser", {}, _site_id(params))
        if not account.get("success"):
            return account
        user = account.get("response", {}).get("User", {})
        user_id = user.get("UserID") if isinstance(user, dict) else None
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("eBay GetUser did not return a user ID; cannot fetch detailed feedback")
        return _trading("GetFeedback", {"UserID": user_id, "FeedbackType": "FeedbackReceivedAsSeller", "Pagination": {"EntriesPerPage": per_page, "PageNumber": page}, "DetailLevel": "ReturnAll"}, _site_id(params))
    if action == "list_listings":
        statuses = {"active": "ActiveList", "scheduled": "ScheduledList", "unsold": "UnsoldList"}
        status = params.get("listing_status", "active")
        if status not in statuses:
            raise ValueError("listing_status must be active, scheduled, or unsold")
        page, per_page = params.get("page", 1), params.get("per_page", 20)
        if any(isinstance(v, bool) or not str(v).isdigit() or int(v) < 1 for v in (page, per_page)) or int(per_page) > 200:
            raise ValueError("page must be positive and per_page must be from 1 to 200")
        return _trading("GetMyeBaySelling", {statuses[status]: {"Include": "true", "Pagination": {"EntriesPerPage": per_page, "PageNumber": page}}}, _site_id(params))
    if action == "get_listing":
        return _trading("GetItem", {"ItemID": _text(params.get("item_id"), "item_id"), "IncludeItemSpecifics": "true", "DetailLevel": "ReturnAll"}, _site_id(params))
    if action == "revise_listing":
        changes = params.get("changes")
        allowed = {"Title", "Description", "StartPrice", "Quantity"}
        if not isinstance(changes, dict) or not changes or set(changes) - allowed:
            raise ValueError("changes must contain only Title, Description, StartPrice, or Quantity")
        item = {"ItemID": _text(params.get("item_id"), "item_id")}
        for key, value in changes.items():
            if key == "Description":
                if not isinstance(value, str) or not value.strip() or len(value) > 500000:
                    raise ValueError("Description must be non-empty text of at most 500000 characters")
                item[key] = value
            else:
                item[key] = _text(value, key)
        return _trading("ReviseItem", {"Item": item}, _site_id(params))
    if action == "end_listing":
        reason = params.get("ending_reason")
        if reason not in {"Incorrect", "LostOrBroken", "NotAvailable", "OtherListingError", "SellToHighBidder", "Sold"}:
            raise ValueError("ending_reason must be an eBay seller ending reason")
        return _trading("EndItem", {"ItemID": _text(params.get("item_id"), "item_id"), "EndingReason": reason}, _site_id(params))
    if action == "respond_to_best_offer":
        response = params.get("response")
        if response not in {"Accept", "Decline", "Counter"}:
            raise ValueError("response must be Accept, Decline, or Counter")
        fields: dict[str, Any] = {"Action": response, "BestOfferID": _text(params.get("offer_id"), "offer_id"), "ItemID": _text(params.get("item_id"), "item_id")}
        if response == "Counter":
            # Trading API requires the currency attribute on the price element.
            return _respond_counter(fields, params)
        return _trading("RespondToBestOffer", fields, _site_id(params))
    raise ValueError("Unknown Trading API action")


def _respond_counter(fields: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    # Keep the same XML transport and error handling as other Trading calls.
    from decimal import Decimal, InvalidOperation
    price = _text(params.get("counter_price"), "counter_price")
    currency = _text(params.get("currency"), "currency")
    quantity = _text(params.get("counter_quantity"), "counter_quantity")
    try:
        if not Decimal(price).is_finite() or Decimal(price) <= 0 or not quantity.isdigit() or int(quantity) < 1:
            raise ValueError("counter price and quantity must be positive")
    except InvalidOperation:
        raise ValueError("counter_price must be a positive amount") from None
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        raise ValueError("currency must be a three-letter currency code")
    # Trading accepts a price without a currencyID attribute; the listing's currency applies.
    # Do not silently ignore an explicit currency: build the required attribute below.
    auth = get_seller_auth()
    root = ET.Element(NS + "RespondToBestOfferRequest")
    for key in ("Action", "BestOfferID"):
        ET.SubElement(root, NS + key).text = fields[key]
    ET.SubElement(root, NS + "CounterOfferPrice", {"currencyID": currency.upper()}).text = price
    ET.SubElement(root, NS + "CounterOfferQuantity").text = quantity
    ET.SubElement(root, NS + "ItemID").text = fields["ItemID"]
    request = urllib.request.Request(auth.api_base + "/ws/api.dll", data=ET.tostring(root, encoding="utf-8", xml_declaration=True), method="POST", headers={"Content-Type": "text/xml", "X-EBAY-API-CALL-NAME": "RespondToBestOffer", "X-EBAY-API-COMPATIBILITY-LEVEL": "1477", "X-EBAY-API-SITEID": str(_site_id(params)), "X-EBAY-API-IAF-TOKEN": auth.access_token})
    with urllib.request.urlopen(request, timeout=30) as response:
        result = ET.fromstring(response.read())
    if result.tag != NS + "RespondToBestOfferResponse":
        raise InvalidResponseError("Unexpected eBay Trading API response")
    success = result.findtext(NS + "Ack") in {"Success", "Warning"} and all(node.text == "Success" for node in result.findall(".//" + NS + "CallStatus"))
    details = _xml_object(result)
    output = {"success": success, "environment": auth.environment, "api_call": "RespondToBestOffer", "response": details}
    if not success:
        output["errors"] = trading_failure(details)
    return output


class _SellerTool(Tool):
    name = ""
    actions: dict = {}
    extra_actions: tuple[str, ...] = ()
    writes = False

    def __init__(self) -> None:
        names = list(self.actions) + list(self.extra_actions)
        details = " ".join(name + ": " + DESCRIPTIONS[name] for name in names)
        super().__init__(ToolCard(id=self.name, name=self.name, description=(
            "eBay seller actions. Use describe_actions to inspect required inputs. " +
            ("Writes require explicit seller approval and confirm=true; configure JiuwenSwarm permission ask for this tool. " if self.writes else "Read-only. ") + details
        ), input_params={"type": "object", "properties": {
            "action": {"type": "string", "enum": ["describe_actions"] + names, "description": "Select an action."},
            "params": {"type": "object", "description": "Action-specific IDs, filters, and options. Call describe_actions for details. REST content_language is en-CA; Trading site_id is 2."},
            "body": {"type": "object", "description": "eBay JSON request payload for actions requiring a body."},
            "confirm": {"type": "boolean", "description": "For writes, set true only after the seller has reviewed and approved the exact request."},
        }, "required": ["action"]}))

    async def invoke(self, inputs: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        try:
            data = inputs or {}
            action = data.get("action")
            if action == "describe_actions":
                return {"success": True, "tool": self.name, "actions": {n: DESCRIPTIONS[n] for n in list(self.actions) + list(self.extra_actions)}}
            if action not in self.actions and action not in self.extra_actions:
                raise ValueError("Unknown action; use describe_actions to see supported actions")
            params = data.get("params", {})
            if not isinstance(params, dict):
                raise ValueError("params must be an object")
            if self.writes and data.get("confirm") is not True:
                return {"success": False, "approval_required": True, "action": action, "message": "Show the exact action, params, body and environment to the seller and obtain approval before retrying with confirm=true. Configure JiuwenSwarm ask permission for this tool."}
            if action == "get_best_offers":
                if data.get("body") is not None:
                    raise ValueError("this action does not accept a body")
                return await EbayBestOffersTool().invoke(params)
            if action in self.extra_actions:
                if data.get("body") is not None:
                    raise ValueError("this action does not accept a body")
                return await asyncio.to_thread(_trading_action, action, params)
            return await asyncio.to_thread(_rest, action, self.actions[action], params, data.get("body"))
        except urllib.error.HTTPError as exc:
            return http_error(exc)
        except ValueError as exc:
            return {"success": False, "error": str(exc), "errors": [{"code": None, "message": str(exc), "category": "validation", "domain": "plugin"}]}
        except Exception as exc:
            return local_failure(exc, writes=self.writes)

    async def stream(self, inputs: dict[str, Any], **kwargs: Any):
        yield await self.invoke(inputs, **kwargs)


class EbaySellerReadTool(_SellerTool):
    name = "ebayseller_read"
    actions = READ
    extra_actions = ("get_seller_account", "get_seller_feedback", "list_listings", "get_listing", "get_best_offers")


class EbaySellerListingWriteTool(_SellerTool):
    name = "ebayseller_listing_write"
    actions = LISTING_WRITE
    extra_actions = ("revise_listing", "end_listing")
    writes = True


class EbaySellerOfferWriteTool(_SellerTool):
    name = "ebayseller_offer_write"
    actions = OFFER_WRITE
    extra_actions = ("respond_to_best_offer",)
    writes = True

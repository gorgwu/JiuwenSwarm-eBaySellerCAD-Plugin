"""Read a seller's Best Offer negotiations through eBay's Trading API."""

from __future__ import annotations

import asyncio
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from openjiuwen.core.foundation.tool import Tool, ToolCard
from common.oauth import get_seller_auth
from common.errors import InvalidResponseError, http_error, local_failure, trading_failure

_NS = "{urn:ebay:apis:eBLBaseComponents}"
_BUYER_TYPES = {"BuyerBestOffer", "BuyerCounterOffer"}

class TradingError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('eBay GetBestOffers failed')

def _child_text(node: ET.Element, name: str) -> str | None:
    value = node.findtext(_NS + name)
    return value.strip() if value and value.strip() else None


def _positive_int(value: Any, name: str, default: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer from 1 to {maximum}")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer from 1 to {maximum}") from exc
    if number < 1 or number > maximum or str(value).strip() != str(number):
        raise ValueError(f"{name} must be an integer from 1 to {maximum}")
    return number


def _request_xml(item_id: str | None, page: int, per_page: int) -> bytes:
    root = ET.Element(_NS + "GetBestOffersRequest")
    if item_id:
        ET.SubElement(root, _NS + "ItemID").text = item_id
        ET.SubElement(root, _NS + "BestOfferStatus").text = "All"
    else:
        ET.SubElement(root, _NS + "BestOfferStatus").text = "Active"
    pagination = ET.SubElement(root, _NS + "Pagination")
    ET.SubElement(pagination, _NS + "EntriesPerPage").text = str(per_page)
    ET.SubElement(pagination, _NS + "PageNumber").text = str(page)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _parse_offer(node: ET.Element, item_id: str | None, role: str | None) -> dict[str, Any]:
    price = node.find(_NS + "Price")
    offer_type = _child_text(node, "BestOfferCodeType")
    status = _child_text(node, "Status")
    buyer = node.find(_NS + "Buyer")
    return {
        "item_id": item_id,
        "offer_id": _child_text(node, "BestOfferID"),
        "offer_type": offer_type,
        "status": status,
        "buyer_user_id": _child_text(buyer, "UserID") if buyer is not None else None,
        "price": price.text.strip() if price is not None and price.text else None,
        "currency": price.get("currencyID") if price is not None else None,
        "quantity": _child_text(node, "Quantity"),
        "expires_at": _child_text(node, "ExpirationTime"),
        "role": role,
        "needs_seller_response": status in {"Active", "Pending"} and offer_type in _BUYER_TYPES and role != "Buyer",
    }


def _parse_response(raw: bytes) -> tuple[list[dict[str, Any]], int, list[str]]:
    root = ET.fromstring(raw)
    if root.tag != _NS + "GetBestOffersResponse":
        raise InvalidResponseError("Unexpected eBay Trading API response")
    errors = []
    for node in root.findall(_NS + "Errors"):
        code = _child_text(node, "ErrorCode") or "unknown"
        message = _child_text(node, "ShortMessage") or "eBay rejected the request"
        errors.append(f"{code}: {message}")
    ack = _child_text(root, "Ack")
    if ack not in {"Success", "Warning"}:
        details = []
        for node in root.findall(_NS + 'Errors'):
            details.append({child.tag.split('}')[-1]: child.text for child in node})
        raise TradingError(trading_failure({'Errors': details}))
    offers: list[dict[str, Any]] = []
    for group in root.findall(".//" + _NS + "ItemBestOffers"):
        item = group.find(_NS + "Item")
        item_id = _child_text(item, "ItemID") if item is not None else None
        role = _child_text(group, "Role")
        for node in group.findall(_NS + "BestOfferArray/" + _NS + "BestOffer"):
            offers.append(_parse_offer(node, item_id, role))
    if not offers:
        item = root.find(_NS + "Item")
        item_id = _child_text(item, "ItemID") if item is not None else None
        for node in root.findall(_NS + "BestOfferArray/" + _NS + "BestOffer"):
            offers.append(_parse_offer(node, item_id, None))
    page_count_text = root.findtext(_NS + "PaginationResult/" + _NS + "TotalNumberOfPages")
    page_count = int(page_count_text) if page_count_text and page_count_text.isdigit() else 1
    return offers, page_count, errors


class EbayBestOffersTool(Tool):
    """List active account Best Offers or all statuses for one listing."""

    def __init__(self) -> None:
        super().__init__(ToolCard(
            id="ebay_best_offers",
            name="ebay_best_offers",
            description=(
                "Read-only eBay seller Best Offer history. Without item_id, returns active offers "
                "across the account; with item_id, returns all statuses for that listing. "
                "Results identify buyer counteroffers and state scan completeness. "
                "Does not retrieve seller-initiated Offers to Buyers."
            ),
            input_params={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "Optional numeric eBay listing ID; includes closed Best Offers for that listing"},
                    "per_page": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Offers per API page; default 20"},
                    "max_pages": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Maximum pages to scan; default 2"},
                    "start_page": {"type": "integer", "minimum": 1, "maximum": 100, "description": "First API page to scan; default 1"},
                    "site_id": {"type": "integer", "description": "Trading site ID: 2 for English Canada"},
                },
            },
        ))

    async def invoke(self, inputs: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(self._read, inputs or {})
        except urllib.error.HTTPError as exc:
            return http_error(exc)
        except TradingError as exc:
            return {"success": False, "error": str(exc), "errors": exc.errors}
        except ValueError as exc:
            return {"success": False, "error": str(exc), "errors": [{"code": None, "message": str(exc), "category": "validation", "domain": "plugin"}]}
        except Exception as exc:
            return local_failure(exc)

    async def stream(self, inputs: dict[str, Any], **kwargs: Any):
        yield await self.invoke(inputs, **kwargs)

    def _read(self, inputs: dict[str, Any]) -> dict[str, Any]:
        site_id = inputs.get('site_id', 2)
        if isinstance(site_id, bool) or str(site_id) != '2':
            raise ValueError('This plugin supports English Canada site_id 2 only')
        item_id = str(inputs.get("item_id") or "").strip() or None
        if item_id is not None and (not item_id.isascii() or not item_id.isdigit()):
            raise ValueError("item_id must be a numeric eBay listing ID")
        per_page = _positive_int(inputs.get("per_page"), "per_page", 20, 100)
        max_pages = _positive_int(inputs.get("max_pages"), "max_pages", 2, 5)
        start_page = _positive_int(inputs.get("start_page"), "start_page", 1, 100)
        auth = get_seller_auth()
        environment = auth.environment
        access_token = auth.access_token
        records: list[dict[str, Any]] = []
        total_pages = 1
        scanned = 0
        warnings: list[str] = []
        last_page = start_page - 1
        for page in range(start_page, start_page + max_pages):
            request = urllib.request.Request(
                ("https://api.sandbox.ebay.com/ws/api.dll" if environment == "sandbox" else "https://api.ebay.com/ws/api.dll"),
                data=_request_xml(item_id, page, per_page),
                headers={
                    "Content-Type": "text/xml",
                    "X-EBAY-API-CALL-NAME": "GetBestOffers",
                    "X-EBAY-API-COMPATIBILITY-LEVEL": "1477",
                    "X-EBAY-API-SITEID": str(site_id),
                    "X-EBAY-API-IAF-TOKEN": access_token,
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                page_records, total_pages, page_warnings = _parse_response(response.read())
            if item_id:
                for record in page_records:
                    if not record["item_id"]:
                        record["item_id"] = item_id
            records.extend(page_records)
            warnings.extend(page_warnings)
            scanned += 1
            last_page = page
            if page >= total_pages:
                break
        # The account-wide query may include Best Offers submitted by this user as a buyer.
        if item_id is None:
            records = [r for r in records if r["role"] != "Buyer"]
        records.sort(key=lambda r: (not r["needs_seller_response"], r["expires_at"] or "9999"))
        return {
            "success": True,
            "environment": environment,
            "source": "Trading API GetBestOffers",
            "scope": "all_best_offer_statuses_for_one_listing" if item_id else "active_best_offers_account_wide",
            "item_id": item_id,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "offers": records,
            "pages_scanned": scanned,
            "start_page": start_page,
            "last_page": last_page,
            "total_pages": total_pages,
            "complete": start_page == 1 and last_page >= total_pages,
            "next_page": last_page + 1 if last_page < total_pages else None,
            "warnings": warnings,
        }

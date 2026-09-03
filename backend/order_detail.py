"""Order detail for the Orders page modal: order info, customer, per-line-item
profit and the order-level profit calculation, built from a raw Shopify order
dict plus the profit dict from shipping_estimate_service.profit_with_shipping."""
from typing import Any, Dict, Iterable, List, Optional


def profit_snapshot(logs: Iterable[Any]) -> Optional[Dict[str, Any]]:
    """The profit calculation recorded when a profit rule last ran on this order, from
    the newest order log (logs newest first) whose details carry one. The modal
    prefers this over a live recalculation so the numbers match the order log and
    do not drift as the shipping estimate's samples change."""
    for entry in logs:
        details = entry.details if isinstance(entry.details, dict) else {}
        profit = details.get("profit")
        if not isinstance(profit, dict):
            continue
        conditions = details.get("profit_conditions")
        recorded_at = entry.created_at.isoformat() if entry.created_at else None
        return {
            "profit": profit,
            "profit_conditions": conditions if isinstance(conditions, list) else [],
            "recorded_at": recorded_at,
        }
    return None


def _amount(money_set: Any) -> Optional[float]:
    amount = ((money_set or {}).get("shopMoney") or {}).get("amount")
    try:
        return float(amount) if amount not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _address(address: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not address:
        return None
    name = " ".join(part for part in (address.get("firstName"), address.get("lastName")) if part)
    return {
        "name": name or None,
        "address1": address.get("address1"),
        "address2": address.get("address2"),
        "city": address.get("city"),
        "province": address.get("province"),
        "zip": address.get("zip"),
        "country": address.get("country"),
        "phone": address.get("phone"),
    }


def line_item_detail(item: Dict[str, Any]) -> Dict[str, Any]:
    """Revenue, cost, profit and margin for one line item (current quantity, after discounts)"""
    quantity = item.get("currentQuantity")
    if quantity is None:
        quantity = item.get("quantity") or 0
    variant = item.get("variant") or {}
    product = item.get("product") or {}
    unit_cost = _amount({"shopMoney": ((variant.get("inventoryItem") or {}).get("unitCost") or {})})
    unit_price = _amount(item.get("discountedUnitPriceAfterAllDiscountsSet"))
    if unit_price is None:
        unit_price = _amount(item.get("originalUnitPriceSet"))
    gift_card = bool(product.get("isGiftCard"))
    tip_or_fee = variant == {} and item.get("requiresShipping") is False
    missing_cost = not gift_card and not tip_or_fee and quantity > 0 and unit_cost is None

    revenue = round(unit_price * quantity, 2) if unit_price is not None else None
    cost = round(unit_cost * quantity, 2) if unit_cost is not None else (0.0 if quantity > 0 else None)
    profit = round(revenue - cost, 2) if revenue is not None and cost is not None else None
    margin = round(profit / revenue * 100, 2) if profit is not None and revenue else None
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "variant_title": variant.get("title"),
        "sku": variant.get("sku") or item.get("sku"),
        "quantity": quantity,
        "unit_price": unit_price,
        "unit_price_original": _amount(item.get("originalUnitPriceSet")),
        "unit_cost": unit_cost,
        "revenue": revenue,
        "cost": cost,
        "profit": profit,
        "margin_percent": margin,
        "gift_card": gift_card,
        "missing_cost": missing_cost,
        "requires_shipping": item.get("requiresShipping"),
    }


def build_order_detail(order: Dict[str, Any], profit: Dict[str, Any], store: Any,
                       profit_conditions: Optional[List[Dict[str, Any]]] = None,
                       profit_recorded_at: Optional[str] = None) -> Dict[str, Any]:
    customer = order.get("customer") or {}
    shipping_lines = [edge.get("node") or {} for edge in ((order.get("shippingLines") or {}).get("edges") or [])]
    line_items = [line_item_detail((edge or {}).get("node") or {}) for edge in ((order.get("lineItems") or {}).get("edges") or [])]
    subtotal = _amount(order.get("currentSubtotalPriceSet"))
    total_set = order.get("currentTotalPriceSet") or order.get("totalPriceSet")
    currency = ((total_set or {}).get("shopMoney") or {}).get("currencyCode") or profit.get("currency")
    return {
        "store": {"id": getattr(store, "id", None), "name": getattr(store, "shop_name", None), "domain": getattr(store, "shop_domain", None)},
        "order": {
            "id": order.get("id"),
            "name": order.get("name"),
            "created_at": order.get("createdAt"),
            "financial_status": order.get("displayFinancialStatus"),
            "fulfillment_status": order.get("displayFulfillmentStatus"),
            "tags": order.get("tags") or [],
            "note": order.get("note"),
            "currency": currency,
            "subtotal": subtotal,
            "shipping_collected": _amount(order.get("currentShippingPriceSet")),
            "tax": _amount(order.get("currentTotalTaxSet")),
            "total": _amount(total_set),
            "taxes_included": bool(order.get("taxesIncluded")),
            "shipping_method": ", ".join(line.get("title") for line in shipping_lines if line.get("title")) or None,
            "total_weight_grams": order.get("currentTotalWeight"),
            "item_count": sum(item["quantity"] for item in line_items),
            "line_items_truncated": bool(((order.get("lineItems") or {}).get("pageInfo") or {}).get("hasNextPage")),
        },
        "customer": {
            "name": " ".join(part for part in (customer.get("firstName"), customer.get("lastName")) if part) or None,
            "email": customer.get("email") or order.get("email"),
            "phone": customer.get("phone") or order.get("phone"),
            "orders_count": customer.get("numberOfOrders"),
            "shipping_address": _address(order.get("shippingAddress")),
            "billing_address": _address(order.get("billingAddress")),
        },
        "line_items": line_items,
        "shipping_estimate": profit.get("shipping_estimate"),
        "profit": {key: value for key, value in profit.items() if key != "shipping_estimate"},
        "profit_conditions": profit_conditions or [],
        "profit_recorded_at": profit_recorded_at,
    }

"""Session basket. Product names and prices always come from our catalogue."""
from decimal import Decimal

from .content import menu_items

MAX_PER_ITEM = 20
MAX_ITEMS = 30


def catalogue():
    return {item["id"]: item for item in menu_items() if not item["call_to_order"] and item["price"] is not None}


def get_cart(request):
    products = catalogue()
    lines = []
    for product_id, quantity in request.session.get("cart", {}).items():
        if product_id in products and type(quantity) is int and 1 <= quantity <= MAX_PER_ITEM:
            product = products[product_id]
            lines.append({**product, "quantity": quantity, "subtotal": product["price"] * quantity})
    return {"lines": lines, "count": sum(line["quantity"] for line in lines),
            "total": sum((line["subtotal"] for line in lines), Decimal("0.00"))}


def fingerprint(cart):
    return sorted([[line["id"], line["name"], line["quantity"], str(line["price"]), line["order_note_prompt"]] for line in cart["lines"]])


def cart_context(request):
    from django.conf import settings
    cart = get_cart(request)
    return {"basket_count": cart["count"], "basket_total": cart["total"],
            "ordering_enabled": settings.ORDERING_ENABLED}

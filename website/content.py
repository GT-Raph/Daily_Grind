"""Live menu from the database; source menu transcribed from the owner's PDF.

menu_2026_10_05.json records the source and is applied with import_shop_menu.
content.json keeps original menu seeds for migration history, plus shop details
and review excerpts. Phone and hours follow the supplied PDF.
"""
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlencode

from django.utils import timezone
from django.templatetags.static import static

from .models import Discount, MenuPrice

DATA = json.loads((Path(__file__).parent / "data" / "content.json").read_text(encoding="utf-8"))
PERKS = [
    ("Inside", "A cosy, non-smoking room with reliable wifi"),
    ("Outside", "Outdoor seating, where shisha is welcome"),
    ("Parking", "Free parking lot, plus free street parking"),
    ("Paying", "Tap to pay with your phone"),
    ("Kids", "Families and children welcome"),
    ("Working", "Laptop-friendly, with reliable wifi"),
    ("Groups", "Room for a group, or a quiet table for one"),
]


def format_hour(value):
    hour, minute = divmod(round(value * 60), 60)
    return f"{hour % 12 or 12}{f':{minute:02}' if minute else ''} {'pm' if hour >= 12 else 'am'}"


def menu_items():
    """Use the same current, administrator-set prices for display and checkout."""
    # A product rule (including 0%) takes precedence over the all-products rule.
    discounts = dict(Discount.objects.values_list("product_id", "percentage"))
    all_products_discount = discounts.get(None, Decimal("0"))
    items = []
    for product in MenuPrice.objects.filter(is_active=True).order_by("display_order", "name", "product_id"):
        percentage = Decimal("0") if product.call_to_order else discounts.get(product.pk, all_products_discount)
        price = None if product.price is None else (product.price * (Decimal("100") - percentage) / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        # An uploaded photo comes first, then a photo URL, then the supplied menu artwork.
        photo = (product.photo.url if product.photo else "") or product.image_url or (static(product.image_path) if product.image_path else "")
        items.append({"name": product.name, "note": product.note, "id": product.pk, "group": product.category,
                      "price": price, "base_price": product.price, "discount_percentage": percentage,
                      "image": photo, "basket_image": photo or static("images/bean-a.webp"), "featured": product.featured,
                      "call_to_order": product.call_to_order, "price_label": product.price_label or ("Ask for price" if price is None else ""),
                      "order_note_prompt": product.order_note_prompt})
    return items


def page_content():
    today = timezone.localtime().strftime("%A")
    hours = DATA["hours"][1:] + DATA["hours"][:1]
    midpoint = (len(DATA["reviews"]) + 1) // 2
    return {
        "shop": DATA["shop"],
        "maps_url": "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": DATA["shop"]["mapsQuery"]}),
        "filters": [{"id": "all", "label": "All"}] + [
            {"id": value, "label": label} for value, label in MenuPrice.Category.choices],
        "items": menu_items(),
        "review_rows": [DATA["reviews"][:midpoint], DATA["reviews"][midpoint:]],
        "hours": [{**row, "opening": format_hour(row["open"]), "closing": format_hour(row["close"]),
                   "today": row["day"] == today} for row in hours],
        "perks": PERKS,
    }

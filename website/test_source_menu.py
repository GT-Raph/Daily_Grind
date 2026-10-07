import json
import tempfile
import uuid
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from .cart import catalogue
from .content import menu_items
from .management.commands.import_shop_menu import source_products
from .models import Discount, MenuPrice, Order, OrderItem


@override_settings(ORDERING_ENABLED=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SourceMenuTests(TestCase):
    def setUp(self):
        self.backups = tempfile.TemporaryDirectory()
        self.addCleanup(self.backups.cleanup)

    def import_menu(self):
        call_command("import_shop_menu", apply=True, backup_dir=Path(self.backups.name), stdout=StringIO())

    def checkout(self, product_id):
        self.client.post(reverse("website:change_cart"), {"product_id": product_id, "quantity": 1})
        response = self.client.get(reverse("website:checkout"))
        return response, {"checkout_token": self.client.session["checkout_token"], "customer_name": "Menu Guest",
                          "phone": "0241234567"}

    def test_preview_does_not_change_products(self):
        before = list(MenuPrice.objects.values())
        call_command("import_shop_menu", stdout=StringIO())
        self.assertEqual(list(MenuPrice.objects.values()), before)
        self.assertEqual(list(Path(self.backups.name).iterdir()), [])

    def test_import_matches_source_preserves_history_and_is_repeatable(self):
        old = MenuPrice.objects.get(pk="cappuccino")
        Discount.objects.create(scope="product", product=old, percentage=10)
        order = Order.objects.create(checkout_token=uuid.uuid4(), owner_token=uuid.uuid4(),
            customer_name="Previous Guest", phone="+233241234567", total=old.price)
        OrderItem.objects.create(order=order, product_id=old.pk, name=old.name, quantity=1, unit_price=old.price)
        self.import_menu()
        source, expected = source_products()
        self.assertEqual(MenuPrice.objects.filter(is_active=True).count(), len(expected))
        for values in expected:
            product = MenuPrice.objects.get(pk=values["product_id"])
            for key, value in values.items():
                self.assertEqual(getattr(product, key), value, (product.pk, key))
        self.assertEqual(MenuPrice.objects.get(pk="cappuccino").price, Decimal("65.00"))
        self.assertFalse(MenuPrice.objects.get(pk="spanish-latte").is_active)
        self.assertEqual((order.items.get().name, order.items.get().unit_price), ("Cappuccino", Decimal("55.00")))
        self.assertEqual(Discount.objects.get().percentage, Decimal("10.00"))
        snapshot = list(MenuPrice.objects.values("pk", "price", "name", "is_active"))
        self.import_menu()
        self.assertEqual(list(MenuPrice.objects.values("pk", "price", "name", "is_active")), snapshot)
        backup_files = sorted(Path(self.backups.name).glob("*.json"))
        before = json.loads(backup_files[0].read_text(encoding="utf-8"))
        self.assertEqual(len(before), 16)
        self.assertEqual(next(row for row in before if row["pk"] == "cappuccino")["fields"]["price"], "55.00")

    def test_call_items_show_exact_price_labels_but_cannot_be_ordered(self):
        self.import_menu()
        Discount.objects.create(scope="all", percentage=25)
        response = self.client.get("/")
        self.assertContains(response, "GH₵30 / 45")
        self.assertContains(response, "GH₵120–140")
        self.assertContains(response, "Ask for price")
        self.assertContains(response, "tel:+233206229966")
        for item in menu_items():
            if item["call_to_order"]:
                self.assertNotIn(item["id"], catalogue())
                self.assertEqual(item["discount_percentage"], 0)
                result = self.client.post(reverse("website:change_cart"), {"product_id": item["id"], "quantity": 1},
                                          HTTP_ACCEPT="application/json")
                self.assertEqual(result.status_code, 400)
        self.assertFalse(self.client.session.get("cart"))

    def test_fixed_combo_requires_choices_and_keeps_them_with_order(self):
        self.import_menu()
        response, details = self.checkout("street-soul-combo")
        self.assertContains(response, "Choose an iced drink and a panini")
        result = self.client.post(reverse("website:checkout"), details)
        self.assertContains(result, "Tell us your choices", status_code=400)
        self.assertFalse(Order.objects.exists())
        details["notes"] = "Ice Muse and Grilled Halloumi Pesto."
        response = self.client.post(reverse("website:checkout"), details)
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.total, Decimal("180.00"))
        self.assertEqual(order.notes, details["notes"])
        self.assertEqual(order.notifications.count(), 1)

    def test_combo_choice_changes_require_checkout_review(self):
        self.import_menu()
        _, details = self.checkout("grind-and-bite")
        MenuPrice.objects.filter(pk="grind-and-bite").update(order_note_prompt="Choose your hot coffee.")
        details["notes"] = "Afro Cloud"
        response = self.client.post(reverse("website:checkout"), details)
        self.assertContains(response, "Your basket has changed", status_code=400)
        self.assertFalse(Order.objects.exists())

    def test_switching_to_call_only_removes_item_from_existing_basket(self):
        _, details = self.checkout("espresso")
        self.import_menu()
        response = self.client.post(reverse("website:checkout"), details)
        self.assertRedirects(response, reverse("website:basket"))
        self.assertFalse(Order.objects.exists())

    def test_online_items_require_numeric_price_and_no_display_override(self):
        for fields in [{"price": None}, {"price": Decimal("40"), "price_label": "GH₵10"}]:
            product = MenuPrice(name="Invalid item", category="food", **fields)
            with self.assertRaises(ValidationError):
                product.full_clean()
            with self.assertRaises(IntegrityError), transaction.atomic():
                product.save()
        MenuPrice(name="Custom", category="food", call_to_order=True, price=None).full_clean()

    def test_new_fixed_price_items_use_source_prices_at_checkout(self):
        self.import_menu()
        for product_id, total in [("blue-groove", "70.00"), ("dairy-mix", "200.00"), ("cheese-kawarma", "120.00")]:
            _, details = self.checkout(product_id)
            result = self.client.post(reverse("website:checkout"), details)
            self.assertEqual(result.status_code, 302)
            self.assertEqual(Order.objects.latest("created_at").total, Decimal(total))

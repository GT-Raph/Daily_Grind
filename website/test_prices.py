from decimal import Decimal

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Permission, User
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .cart import catalogue
from .content import DATA, menu_items
from .models import MenuPrice, Order


@override_settings(ORDERING_ENABLED=True)
class MenuPriceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrator = User.objects.create_superuser("price-admin", "", "test-only-password")
        cls.staff = User.objects.create_user("regular-staff", password="test-only-password", is_staff=True)
        cls.staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="website"))

    def setUp(self):
        self.price = MenuPrice.objects.get(pk="spanish-latte")
        self.edit_url = reverse("admin:website_menuprice_change", args=[self.price.pk])
        self.list_url = reverse("admin:website_menuprice_changelist")
        self.admin_client = Client()
        self.admin_client.force_login(self.administrator)

    def update_price(self, value="70.50"):
        return self.admin_client.post(self.edit_url, {"price": value, "name": self.price.name,
            "category": self.price.category, "display_order": self.price.display_order,
            "note": self.price.note, "is_active": "on", "_save": "Save"})

    def checkout_details(self):
        self.client.get(reverse("website:checkout"))
        return {"checkout_token": self.client.session["checkout_token"],
                "customer_name": "Price Test", "phone": "0241234567", "notes": ""}

    def test_migration_preserves_all_existing_menu_prices(self):
        source = [item for group in DATA["menu"] for item in group["items"]]
        self.assertEqual(MenuPrice.objects.count(), len(source))
        for item in source:
            self.assertEqual(MenuPrice.objects.get(name=item["name"]).price, Decimal(item["price"]))

    def test_administrator_can_change_price_and_change_is_audited(self):
        self.assertContains(self.admin_client.get(self.list_url), "Spanish latte")
        self.assertRedirects(self.update_price(), self.list_url)
        self.price.refresh_from_db()
        self.assertEqual(self.price.price, Decimal("70.50"))
        log = LogEntry.objects.get(action_flag=CHANGE, object_id=self.price.pk)
        self.assertEqual(log.user_id, self.administrator.pk)
        self.assertIn("price", log.change_message.lower())

    def test_regular_staff_cannot_access_or_submit_price_pages_even_with_all_model_permissions(self):
        self.client.force_login(self.staff)
        self.assertTrue(self.staff.has_perm("website.change_menuprice"))
        self.assertNotContains(self.client.get(reverse("admin:index")), self.list_url)
        for url in [self.list_url, self.edit_url, reverse("admin:website_menuprice_add"),
                    reverse("admin:website_menuprice_delete", args=[self.price.pk])]:
            for method in [self.client.get, self.client.post]:
                with self.subTest(url=url, method=method.__name__):
                    self.assertEqual(method(url, {"price": "0.01"}).status_code, 403)
        self.price.refresh_from_db()
        self.assertEqual(self.price.price, Decimal("60.00"))

    def test_guest_customer_and_inactive_admin_cannot_change_prices(self):
        customer = User.objects.create_user("price-customer")
        inactive = User.objects.create_superuser("inactive-price-admin", "", "test-only-password", is_active=False)
        for user in [None, customer, inactive]:
            browser = Client()
            if user:
                browser.force_login(user)
            response = browser.post(self.edit_url, {"price": "1.00"})
            self.assertEqual(response.status_code, 302)
            self.assertIn("/admin/login/", response.url)
        self.price.refresh_from_db()
        self.assertEqual(self.price.price, Decimal("60.00"))

    def test_price_changes_require_csrf(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.administrator)
        self.assertEqual(browser.post(self.edit_url, {"price": "0.01"}).status_code, 403)
        self.price.refresh_from_db()
        self.assertEqual(self.price.price, Decimal("60.00"))

    def test_invalid_prices_are_rejected_and_database_prevents_nonpositive_values(self):
        for value in ["", "not-money", "-10", "0", "1.234", "100000", "NaN", "Infinity"]:
            with self.subTest(price=value):
                response = self.update_price(value)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["adminform"].form.errors.get("price"))
                self.price.refresh_from_db()
                self.assertEqual(self.price.price, Decimal("60.00"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            MenuPrice.objects.filter(pk=self.price.pk).update(price=Decimal("-1.00"))

    def test_admin_rename_keeps_product_identity(self):
        response = self.admin_client.post(self.edit_url, {
            "price": "61.00", "name": "Renamed by request", "product_id": "wrong-product", "_save": "Save",
            "category": "coffee", "display_order": "1", "is_active": "on",
        })
        self.assertRedirects(response, self.list_url)
        self.price.refresh_from_db()
        self.assertEqual(self.price.name, "Renamed by request")
        self.assertFalse(MenuPrice.objects.filter(pk="wrong-product").exists())
        self.assertEqual(catalogue()["spanish-latte"]["name"], "Renamed by request")

    def test_updated_price_is_used_by_menu_basket_and_checkout_ignoring_client_prices(self):
        self.update_price()
        self.assertEqual(catalogue()["spanish-latte"]["price"], Decimal("70.50"))
        response = self.client.get(reverse("website:home"))
        item = next(item for item in response.context["items"] if item["id"] == "spanish-latte")
        self.assertEqual(item["price"], Decimal("70.50"))
        self.assertContains(response, "GH₵70.50")
        self.client.post(reverse("website:change_cart"), {
            "product_id": "spanish-latte", "quantity": 2, "price": "0.01", "total": "0.02",
        })
        basket = self.client.get(reverse("website:basket"))
        self.assertEqual(basket.context["basket"]["total"], Decimal("141.00"))
        self.client.post(reverse("website:checkout"), {**self.checkout_details(), "total": "0.02"})
        order = Order.objects.get()
        self.assertEqual(order.total, Decimal("141.00"))
        self.assertEqual(order.items.get().unit_price, Decimal("70.50"))

    def test_price_change_after_checkout_open_requires_review(self):
        self.client.post(reverse("website:change_cart"), {"product_id": "spanish-latte", "quantity": 2})
        details = self.checkout_details()
        self.update_price()
        response = self.client.post(reverse("website:checkout"), details)
        self.assertContains(response, "Your basket has changed", status_code=400)
        self.assertContains(response, "141.00", status_code=400)
        self.assertFalse(Order.objects.exists())
        details["checkout_token"] = response.context["checkout_form"]["checkout_token"].value()
        self.assertEqual(self.client.post(reverse("website:checkout"), details).status_code, 302)
        self.assertEqual(Order.objects.get().total, Decimal("141.00"))

    def test_price_change_never_rewrites_existing_order_snapshots(self):
        self.client.post(reverse("website:change_cart"), {"product_id": "spanish-latte", "quantity": 2})
        self.client.post(reverse("website:checkout"), self.checkout_details())
        order = Order.objects.get()
        self.update_price()
        order.refresh_from_db()
        self.assertEqual(order.total, Decimal("120.00"))
        self.assertEqual(order.items.get().unit_price, Decimal("60.00"))
        receipt = self.client.get(reverse("website:receipt", args=[order.id]))
        self.assertContains(receipt, "120.00")

    def test_staff_forged_order_updates_cannot_change_prices_or_totals(self):
        self.client.post(reverse("website:change_cart"), {"product_id": "spanish-latte", "quantity": 2})
        self.client.post(reverse("website:checkout"), self.checkout_details())
        order = Order.objects.get()
        item = order.items.get()
        alert = order.notifications.get()
        self.client.force_login(self.staff)
        response = self.client.post(reverse("staff:order_status", args=[order.pk]), {
            "previous_status": "new", "status": "accepted", "total": "0.01", "unit_price": "0.01", "price": "0.01",
        })
        self.assertRedirects(response, reverse("staff:orders"))
        response = self.client.post(reverse("admin:website_order_change", args=[order.pk]), {
            "status": "accepted", "total": "0.01", "_save": "Save",
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "1",
            "items-0-id": str(item.pk), "items-0-order": str(order.pk), "items-0-unit_price": "0.01",
            "items-0-quantity": "1", "notifications-TOTAL_FORMS": "1", "notifications-INITIAL_FORMS": "1",
            "notifications-0-id": str(alert.pk), "notifications-0-order": str(order.pk),
        })
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        item.refresh_from_db()
        self.price.refresh_from_db()
        self.assertEqual((order.total, item.unit_price, item.quantity, self.price.price),
                         (Decimal("120.00"), Decimal("60.00"), 2, Decimal("60.00")))

    def test_missing_database_price_cannot_fall_back_to_content_file(self):
        self.price.delete()
        self.assertNotIn("spanish-latte", catalogue())
        self.assertNotIn("spanish-latte", [item["id"] for item in menu_items()])
        response = self.client.post(reverse("website:change_cart"), {"product_id": "spanish-latte", "quantity": 1},
                                    HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 400)

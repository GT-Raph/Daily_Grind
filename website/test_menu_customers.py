import importlib
import uuid
from decimal import Decimal
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission, User
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .cart import catalogue
from .models import Customer, Discount, MenuPrice, Order, OrderItem


@override_settings(ORDERING_ENABLED=True)
class MenuProductTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrator = User.objects.create_superuser("menu-owner", "", "test-only-password")

    def setUp(self):
        self.admin_client = Client()
        self.admin_client.force_login(self.administrator)
        self.list_url = reverse("admin:website_menuprice_changelist")
        self.add_url = reverse("admin:website_menuprice_add")

    def product_data(self, **extra):
        return {"name": "New tea", "category": "tea", "price": "42.50", "note": "Freshly brewed",
                "display_order": "20", "is_active": "on", "_save": "Save", **extra}

    def test_add_and_categorize_products_in_all_three_categories(self):
        for category in ["coffee", "tea", "food"]:
            response = self.admin_client.post(self.add_url, self.product_data(name="New " + category, category=category))
            self.assertRedirects(response, self.list_url)
            product = MenuPrice.objects.get(name="New " + category)
            self.assertEqual(len(product.pk), 32)
            item = catalogue()[product.pk]
            self.assertEqual((item["group"], item["note"], item["price"]), (category, "Freshly brewed", Decimal("42.50")))
            self.assertEqual(item["image"], "")
            self.assertContains(self.client.get("/"), product.name)
            self.client.post(reverse("website:change_cart"), {"product_id": product.pk, "quantity": 1})
            self.client.get(reverse("website:checkout"))
            self.assertEqual(self.client.post(reverse("website:checkout"), {
                "checkout_token": self.client.session["checkout_token"], "customer_name": "Menu Tester", "phone": "0241234567",
            }).status_code, 302)
            self.assertEqual(Order.objects.latest("created_at").items.get().name, product.name)

    def test_invalid_or_missing_category_and_unsafe_photo_urls_are_rejected(self):
        for changes in [{"category": ""}, {"category": "other"}, {"image_url": "javascript:alert(1)"},
                        {"image_url": "http://example.com/photo.jpg"}]:
            response = self.admin_client.post(self.add_url, self.product_data(**changes))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["adminform"].form.errors)
        self.assertFalse(MenuPrice.objects.filter(name="New tea").exists())

    def test_optional_https_photo_and_escaped_content_are_rendered(self):
        self.admin_client.post(self.add_url, self.product_data(name="<script>Tea</script>", image_url="https://example.com/tea.jpg"))
        response = self.client.get("/")
        self.assertContains(response, "https://example.com/tea.jpg")
        self.assertContains(response, "&lt;script&gt;Tea&lt;/script&gt;")
        self.assertNotContains(response, "<script>Tea</script>")

    def test_hidden_product_is_unavailable_and_bulk_restore_is_audited(self):
        product = MenuPrice.objects.get(pk="spanish-latte")
        self.client.post(reverse("website:change_cart"), {"product_id": product.pk, "quantity": 1})
        response = self.admin_client.post(self.list_url, {"action": "hide_products", "_selected_action": product.pk})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(product.pk, catalogue())
        self.assertContains(self.client.get(reverse("website:basket")), "no longer available")
        self.assertEqual(self.client.session["cart"], {})
        response = self.client.post(reverse("website:change_cart"), {"product_id": product.pk, "quantity": 1}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 400)
        self.admin_client.post(self.list_url, {"action": "show_products", "_selected_action": product.pk})
        self.assertIn(product.pk, catalogue())
        self.assertEqual(LogEntry.objects.filter(user=self.administrator, object_id=product.pk).count(), 2)

    def test_removing_product_during_checkout_requires_review(self):
        for product_id in ["spanish-latte", "espresso"]:
            self.client.post(reverse("website:change_cart"), {"product_id": product_id, "quantity": 1})
        self.client.get(reverse("website:checkout"))
        details = {"checkout_token": self.client.session["checkout_token"], "customer_name": "Menu Test", "phone": "0241234567"}
        MenuPrice.objects.filter(pk="spanish-latte").update(is_active=False)
        response = self.client.post(reverse("website:checkout"), details)
        self.assertContains(response, "Your basket has changed", status_code=400)
        self.assertContains(response, "35.00", status_code=400)
        self.assertFalse(Order.objects.exists())
        details["checkout_token"] = response.context["checkout_form"]["checkout_token"].value()
        self.client.post(reverse("website:checkout"), details)
        self.assertEqual(Order.objects.get().items.get().product_id, "espresso")

    def test_delete_product_preserves_orders_and_removes_its_discount(self):
        product = MenuPrice.objects.get(pk="spanish-latte")
        Discount.objects.create(scope="product", product=product, percentage=10)
        self.client.post(reverse("website:change_cart"), {"product_id": product.pk, "quantity": 1})
        self.client.get(reverse("website:checkout"))
        response = self.client.post(reverse("website:checkout"), {"checkout_token": self.client.session["checkout_token"],
            "customer_name": "Delete Test", "phone": "0241234567"})
        receipt_url = response.url
        self.assertEqual(self.admin_client.post(reverse("admin:website_menuprice_delete", args=[product.pk]), {"post": "yes"}).status_code, 302)
        self.assertFalse(MenuPrice.objects.filter(pk=product.pk).exists())
        self.assertFalse(Discount.objects.filter(product_id=product.pk).exists())
        order = Order.objects.get()
        self.assertEqual(order.total, Decimal("54.00"))
        self.assertEqual(order.items.get().name, "Spanish latte")
        self.assertContains(self.client.get(receipt_url), "Spanish latte")

    def test_renamed_product_requires_review_of_open_checkout(self):
        self.client.post(reverse("website:change_cart"), {"product_id": "spanish-latte", "quantity": 1})
        self.client.get(reverse("website:checkout"))
        details = {"checkout_token": self.client.session["checkout_token"], "customer_name": "Rename Test", "phone": "0241234567"}
        MenuPrice.objects.filter(pk="spanish-latte").update(name="Updated latte")
        response = self.client.post(reverse("website:checkout"), details)
        self.assertContains(response, "Your basket has changed", status_code=400)
        self.assertContains(response, "Updated latte", status_code=400)
        self.assertFalse(Order.objects.exists())

    def test_new_product_supports_global_and_product_discounts(self):
        self.admin_client.post(self.add_url, self.product_data())
        product = MenuPrice.objects.get(name="New tea")
        Discount.objects.create(scope="all", percentage=10)
        self.assertEqual(catalogue()[product.pk]["price"], Decimal("38.25"))
        Discount.objects.create(scope="product", product=product, percentage=20)
        self.assertEqual(catalogue()[product.pk]["price"], Decimal("34.00"))

    def test_regular_staff_cannot_add_edit_hide_restore_or_delete_products(self):
        staff = User.objects.create_user("menu-staff", is_staff=True)
        staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="website"))
        self.client.force_login(staff)
        for url, data in [(self.add_url, self.product_data()),
                          (reverse("admin:website_menuprice_change", args=["spanish-latte"]), self.product_data()),
                          (reverse("admin:website_menuprice_delete", args=["spanish-latte"]), {"post": "yes"}),
                          (self.list_url, {"action": "hide_products", "_selected_action": "spanish-latte"}),
                          (self.list_url, {"action": "show_products", "_selected_action": "spanish-latte"})]:
            self.assertEqual(self.client.post(url, data).status_code, 403)
        self.assertTrue(MenuPrice.objects.get(pk="spanish-latte").is_active)

    def test_menu_add_delete_and_bulk_actions_require_csrf(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.administrator)
        for url in [self.add_url, self.list_url, reverse("admin:website_menuprice_delete", args=["spanish-latte"])]:
            self.assertEqual(browser.post(url, self.product_data()).status_code, 403)

    def test_empty_menu_has_recovery_message(self):
        MenuPrice.objects.update(is_active=False)
        response = self.client.get("/")
        self.assertContains(response, "Our menu is being updated")
        self.assertNotContains(response, "data-add-to-order")


@override_settings(ORDERING_ENABLED=True)
class CustomerHistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrator = User.objects.create_superuser("customer-owner", "", "test-only-password")

    def setUp(self):
        self.admin_client = Client()
        self.admin_client.force_login(self.administrator)
        self.list_url = reverse("admin:website_customer_changelist")

    def place(self, phone="024 123 4567", name="Repeat Guest", customer_id=None):
        self.client.post(reverse("website:change_cart"), {"product_id": "spanish-latte", "quantity": 1})
        self.client.get(reverse("website:checkout"))
        details = {"checkout_token": self.client.session["checkout_token"], "customer_name": name,
                   "phone": phone, "customer": customer_id or ""}
        response = self.client.post(reverse("website:checkout"), details)
        self.assertEqual(response.status_code, 302)
        return Order.objects.latest("created_at"), details

    def customer_row(self, customer):
        response = self.admin_client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        return next(row for row in response.context["cl"].result_list if row.pk == customer.pk)

    def test_phone_variants_link_repeat_orders_and_update_name_without_editing_order_snapshots(self):
        first, _ = self.place()
        second, _ = self.place(phone="+233241234567", name="Repeat Guest Updated")
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(first.customer_id, second.customer_id)
        self.assertEqual(second.customer.name, "Repeat Guest Updated")
        self.assertEqual(first.customer_name, "Repeat Guest")
        third, _ = self.place(phone="0241112222", name="Repeat Guest")
        self.assertNotEqual(third.customer_id, first.customer_id)

    def test_only_collected_orders_contribute_to_visits_and_spend(self):
        for status in ["completed", "completed", "new", "accepted", "ready", "cancelled"]:
            order, _ = self.place()
            order.status = status
            order.save()
        row = self.customer_row(order.customer)
        self.assertEqual(row.completed_count, 2)
        self.assertEqual(row.spent_total, Decimal("120.00"))
        self.assertIsNotNone(row.first_order_at)
        self.assertEqual(row.last_order_at, order.created_at)

    def test_staff_status_changes_and_reversal_keep_totals_current(self):
        order, _ = self.place()
        staff = User.objects.create_user("customer-counter", is_staff=True)
        staff.user_permissions.add(*Permission.objects.filter(codename__in=["view_order", "change_order"]))
        self.client.force_login(staff)
        for previous, status in [("new", "accepted"), ("accepted", "ready"), ("ready", "completed")]:
            self.client.post(reverse("staff:order_status", args=[order.pk]), {"previous_status": previous, "status": status})
        row = self.customer_row(order.customer)
        self.assertEqual((row.completed_count, row.spent_total), (1, Decimal("60.00")))
        order.status = "cancelled"
        order.save()
        row = self.customer_row(order.customer)
        self.assertEqual((row.completed_count, row.spent_total), (0, Decimal("0.00")))

    def test_repeat_filter_ranking_search_and_customer_history_links(self):
        single, _ = self.place(phone="0241112222", name="Single Guest")
        single.status = "completed"
        single.save()
        for _ in range(2):
            repeat, _ = self.place()
            repeat.status = "completed"
            repeat.save()
        rows = self.admin_client.get(self.list_url).context["cl"].result_list
        self.assertEqual(rows[0].pk, repeat.customer_id)
        response = self.admin_client.get(self.list_url + "?activity=repeat")
        self.assertContains(response, "Repeat Guest")
        self.assertNotContains(response, "Single Guest")
        self.assertEqual(self.admin_client.get(self.list_url + "?q=0241112222").context["cl"].result_count, 1)
        self.assertEqual(self.admin_client.get(self.list_url + "?q=233241112222").context["cl"].result_count, 1)
        detail = self.admin_client.get(reverse("admin:website_customer_change", args=[repeat.customer_id]))
        self.assertContains(detail, "View orders")
        history = self.admin_client.get(reverse("admin:website_order_changelist") + f"?customer__id__exact={repeat.customer_id}")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.context["cl"].result_count, 2)

    def test_discounts_are_reflected_in_actual_collected_spend(self):
        Discount.objects.create(scope="all", percentage="25")
        order, _ = self.place()
        order.status = "completed"
        order.save()
        Discount.objects.all().delete()
        MenuPrice.objects.filter(pk="spanish-latte").update(price="80")
        self.assertEqual(self.customer_row(order.customer).spent_total, Decimal("45.00"))

    def test_regular_staff_cannot_access_customer_history_even_with_permissions(self):
        order, _ = self.place()
        staff = User.objects.create_user("history-staff", is_staff=True)
        staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="website"))
        self.client.force_login(staff)
        self.assertNotContains(self.client.get(reverse("admin:index")), self.list_url)
        for url in [self.list_url, reverse("admin:website_customer_change", args=[order.customer_id])]:
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, {"name": "Changed"}).status_code, 403)
        self.assertEqual(Client().get(self.list_url).status_code, 302)

    def test_customer_reports_are_read_only_for_owner(self):
        order, _ = self.place()
        for url in [reverse("admin:website_customer_add"),
                    reverse("admin:website_customer_change", args=[order.customer_id]),
                    reverse("admin:website_customer_delete", args=[order.customer_id])]:
            self.assertEqual(self.admin_client.post(url, {"name": "Changed", "phone": "+233241111111", "post": "yes"}).status_code, 403)
        self.assertEqual(Customer.objects.get().name, "Repeat Guest")

    def test_duplicate_checkout_and_forged_customer_id_do_not_double_count_or_misattribute(self):
        other = Customer.objects.create(name="Other Guest", phone="+233241111111")
        order, details = self.place(customer_id=other.pk)
        self.assertNotEqual(order.customer_id, other.pk)
        self.client.post(reverse("website:checkout"), details)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Customer.objects.count(), 2)

    def test_checkout_failure_rolls_back_customer_and_order(self):
        with patch("website.order_views.OrderNotification.objects.create", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                self.place()
        self.assertFalse(Customer.objects.exists())
        self.assertFalse(Order.objects.exists())

    def test_backfill_preserves_prices_discounts_and_existing_orders(self):
        MenuPrice.objects.filter(pk="spanish-latte").update(price="67.50")
        Discount.objects.create(scope="product", product_id="spanish-latte", percentage="10")
        first = Order.objects.create(checkout_token=uuid.uuid4(), owner_token=uuid.uuid4(),
            customer_name="Original Guest", phone="024 123 4567", total="55.00", status="completed")
        second = Order.objects.create(checkout_token=uuid.uuid4(), owner_token=uuid.uuid4(),
            customer_name="Latest Guest", phone="+233241234567", total="80.00", status="completed")
        Order.objects.filter(pk=second.pk).update(created_at=first.created_at + timedelta(seconds=1))
        original_updated = first.updated_at
        migration = importlib.import_module("website.migrations.0005_menu_products_and_customers")
        migration.migrate_menu_and_customers(apps, SimpleNamespace(connection=connection))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.customer_id, second.customer_id)
        self.assertEqual(Customer.objects.get().name, "Latest Guest")
        self.assertEqual(first.updated_at, original_updated)
        self.assertEqual(first.total, Decimal("55.00"))
        self.assertEqual(self.customer_row(first.customer).spent_total, Decimal("135.00"))
        self.assertEqual(MenuPrice.objects.get(pk="spanish-latte").price, Decimal("67.50"))
        self.assertEqual(Discount.objects.get().percentage, Decimal("10"))

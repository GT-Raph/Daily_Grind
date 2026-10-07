from decimal import Decimal

from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.auth.models import Permission, User
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .cart import catalogue
from .models import Discount, MenuPrice, Order


@override_settings(ORDERING_ENABLED=True)
class DiscountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrator = User.objects.create_superuser("discount-admin", "", "test-only-password")
        cls.staff = User.objects.create_user("discount-staff", is_staff=True)
        cls.staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="website"))
        cls.product = MenuPrice.objects.get(pk="spanish-latte")

    def setUp(self):
        self.admin_client = Client()
        self.admin_client.force_login(self.administrator)
        self.add_url = reverse("admin:website_discount_add")
        self.list_url = reverse("admin:website_discount_changelist")

    def add_discount(self, percentage="10", product=None):
        response = self.admin_client.post(self.add_url, {
            "scope": "product" if product else "all", "product": product or "",
            "percentage": percentage, "_save": "Save",
        })
        self.assertRedirects(response, self.list_url)
        return Discount.objects.get(product_id=product)

    def details(self):
        self.client.get(reverse("website:checkout"))
        return {"checkout_token": self.client.session["checkout_token"],
                "customer_name": "Discount Test", "phone": "0241234567", "notes": ""}

    def add_to_cart(self, quantity=1):
        self.client.post(reverse("website:change_cart"), {"product_id": self.product.pk, "quantity": quantity})

    def test_admin_can_create_edit_and_delete_discounts_with_audit_history(self):
        discount = self.add_discount()
        self.assertContains(self.admin_client.get(self.list_url), "All products")
        edit_url = reverse("admin:website_discount_change", args=[discount.pk])
        response = self.admin_client.post(edit_url, {"scope": "all", "product": "", "percentage": "15.50", "_save": "Save"})
        self.assertRedirects(response, self.list_url)
        discount.refresh_from_db()
        self.assertEqual(discount.percentage, Decimal("15.50"))
        response = self.admin_client.post(reverse("admin:website_discount_delete", args=[discount.pk]), {"post": "yes"})
        self.assertRedirects(response, self.list_url)
        self.assertFalse(Discount.objects.exists())
        self.assertEqual(set(LogEntry.objects.filter(user=self.administrator,
            content_type__model="discount").values_list("action_flag", flat=True)), {ADDITION, CHANGE, DELETION})

    def test_regular_staff_cannot_manage_discounts_even_with_all_permissions(self):
        discount = self.add_discount()
        self.client.force_login(self.staff)
        self.assertTrue(self.staff.has_perm("website.change_discount"))
        self.assertNotContains(self.client.get(reverse("admin:index")), self.list_url)
        urls = [self.list_url, self.add_url,
                reverse("admin:website_discount_change", args=[discount.pk]),
                reverse("admin:website_discount_delete", args=[discount.pk])]
        for url in urls:
            for method in [self.client.get, self.client.post]:
                with self.subTest(url=url, method=method.__name__):
                    response = method(url, {"scope": "all", "percentage": "100", "post": "yes",
                        "action": "delete_selected", "_selected_action": discount.pk})
                    self.assertEqual(response.status_code, 403)
        discount.refresh_from_db()
        self.assertEqual(discount.percentage, Decimal("10"))
        self.assertEqual(Discount.objects.count(), 1)

    def test_guest_customer_and_inactive_admin_cannot_create_discounts(self):
        customer = User.objects.create_user("discount-customer")
        inactive = User.objects.create_superuser("inactive-discount-admin", "", "test-only-password", is_active=False)
        for user in [None, customer, inactive]:
            browser = Client()
            if user:
                browser.force_login(user)
            response = browser.post(self.add_url, {"scope": "all", "percentage": "100"})
            self.assertEqual(response.status_code, 302)
            self.assertIn("/admin/login/", response.url)
        self.assertFalse(Discount.objects.exists())

    def test_discount_mutations_require_csrf(self):
        discount = self.add_discount()
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.administrator)
        for url in [self.add_url, reverse("admin:website_discount_change", args=[discount.pk]),
                    reverse("admin:website_discount_delete", args=[discount.pk])]:
            self.assertEqual(browser.post(url, {"scope": "all", "percentage": "100", "post": "yes"}).status_code, 403)
        discount.refresh_from_db()
        self.assertEqual(discount.percentage, Decimal("10"))

    def test_global_discount_applies_to_every_product_without_changing_base_prices(self):
        before = {item.pk: item.price for item in MenuPrice.objects.all()}
        self.add_discount("10")
        for product_id, item in catalogue().items():
            self.assertEqual(item["price"], before[product_id] * Decimal("0.90"))
            self.assertEqual(item["discount_percentage"], Decimal("10"))
        self.assertEqual(dict(MenuPrice.objects.values_list("product_id", "price")), before)

    def test_product_discount_only_affects_selected_product(self):
        self.add_discount("25", self.product.pk)
        products = catalogue()
        self.assertEqual(products[self.product.pk]["price"], Decimal("45.00"))
        for product_id, item in products.items():
            if product_id != self.product.pk:
                self.assertEqual(item["price"], item["base_price"])

    def test_product_discount_overrides_global_and_zero_excludes_product(self):
        self.add_discount("20")
        override = self.add_discount("10", self.product.pk)
        self.assertEqual(catalogue()[self.product.pk]["price"], Decimal("54.00"))
        override.percentage = Decimal("0")
        override.save()
        self.assertEqual(catalogue()[self.product.pk]["price"], Decimal("60.00"))
        self.assertEqual(catalogue()["espresso"]["price"], Decimal("28.00"))
        override.delete()
        self.assertEqual(catalogue()[self.product.pk]["price"], Decimal("48.00"))
        Discount.objects.all().delete()
        self.assertEqual(catalogue()[self.product.pk]["price"], Decimal("60.00"))

    def test_invalid_percentages_and_mismatched_scope_are_rejected(self):
        for percentage in ["", "bad", "-0.01", "100.01", "1.234", "NaN", "Infinity"]:
            with self.subTest(percentage=percentage):
                response = self.admin_client.post(self.add_url, {"scope": "all", "percentage": percentage})
                self.assertEqual(response.status_code, 200)
                self.assertIn("percentage", response.context["adminform"].form.errors)
        for scope, product in [("product", ""), ("all", self.product.pk), ("invalid", "")]:
            response = self.admin_client.post(self.add_url, {"scope": scope, "product": product, "percentage": "10"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["adminform"].form.errors)
        self.assertFalse(Discount.objects.exists())

    def test_duplicates_have_actionable_errors_and_keep_existing_discount(self):
        self.add_discount("10")
        self.add_discount("15", self.product.pk)
        for scope, product in [("all", ""), ("product", self.product.pk)]:
            response = self.admin_client.post(self.add_url, {"scope": scope, "product": product, "percentage": "90"})
            self.assertContains(response, "already has a discount" if product else "already exists")
        self.assertEqual(Discount.objects.count(), 2)

    def test_database_rejects_invalid_and_duplicate_rules(self):
        self.add_discount("10")
        self.add_discount("15", self.product.pk)
        invalid_rules = [
            {"scope": "all", "percentage": "10"},
            {"scope": "product", "product_id": self.product.pk, "percentage": "10"},
            {"scope": "all", "product_id": self.product.pk, "percentage": "10"},
            {"scope": "product", "percentage": "10"},
            {"scope": "invalid", "percentage": "10"},
            {"scope": "product", "product_id": "espresso", "percentage": "-1"},
            {"scope": "product", "product_id": "espresso", "percentage": "101"},
        ]
        for rule in invalid_rules:
            with self.subTest(rule=rule), self.assertRaises(IntegrityError), transaction.atomic():
                Discount.objects.create(**rule)

    def test_discounted_prices_flow_through_menu_checkout_receipt_and_staff_queue(self):
        self.add_discount("12.5", self.product.pk)
        self.assertContains(self.client.get(reverse("website:home")), "GH₵52.50")
        self.client.post(reverse("website:change_cart"), {
            "product_id": self.product.pk, "quantity": 2, "price": "0", "discount_percentage": "100",
        })
        self.assertContains(self.client.get(reverse("website:basket")), "105.00")
        response = self.client.post(reverse("website:checkout"), {**self.details(), "total": "0", "percentage": "100"})
        order = Order.objects.get()
        self.assertEqual(order.total, Decimal("105.00"))
        self.assertEqual(order.items.get().unit_price, Decimal("52.50"))
        self.assertContains(self.client.get(response.url), "105.00")
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("staff:orders")), "105.00")

    def test_rounding_is_half_up_per_unit_before_quantity(self):
        self.add_discount("12.5", "espresso")
        self.assertEqual(catalogue()["espresso"]["price"], Decimal("30.63"))
        self.client.post(reverse("website:change_cart"), {"product_id": "espresso", "quantity": 2})
        self.client.post(reverse("website:checkout"), self.details())
        self.assertEqual(Order.objects.get().total, Decimal("61.26"))

    def test_zero_and_full_discount_boundaries(self):
        discount = self.add_discount("0")
        self.assertEqual(catalogue()[self.product.pk]["price"], Decimal("60.00"))
        discount.percentage = Decimal("100")
        discount.save()
        self.assertTrue(all(item["price"] == Decimal("0.00") for item in catalogue().values()))
        self.add_to_cart()
        self.assertEqual(self.client.post(reverse("website:checkout"), self.details()).status_code, 302)
        self.assertEqual(Order.objects.get().total, Decimal("0.00"))

    def test_discount_creation_change_and_removal_require_review_of_open_checkout(self):
        self.add_to_cart()
        details = self.details()
        discount = self.add_discount("10")
        for operation, expected in [(None, "54.00"), ("change", "48.00"), ("remove", "60.00")]:
            if operation == "change":
                discount.percentage = Decimal("20")
                discount.save()
            elif operation == "remove":
                discount.delete()
            response = self.client.post(reverse("website:checkout"), details)
            self.assertContains(response, "Your basket has changed", status_code=400)
            self.assertContains(response, expected, status_code=400)
            self.assertFalse(Order.objects.exists())
            details["checkout_token"] = response.context["checkout_form"]["checkout_token"].value()
        self.assertEqual(self.client.post(reverse("website:checkout"), details).status_code, 302)
        self.assertEqual(Order.objects.get().total, Decimal("60.00"))

    def test_saved_order_keeps_discounted_price_after_rules_are_changed_or_deleted(self):
        discount = self.add_discount("25", self.product.pk)
        self.add_to_cart(2)
        details = self.details()
        first = self.client.post(reverse("website:checkout"), details)
        discount.delete()
        MenuPrice.objects.filter(pk=self.product.pk).update(price="80.00")
        order = Order.objects.get()
        self.assertEqual(order.total, Decimal("90.00"))
        self.assertEqual(order.items.get().unit_price, Decimal("45.00"))
        self.assertContains(self.client.get(first.url), "90.00")
        self.assertRedirects(self.client.post(reverse("website:checkout"), details), first.url)
        self.assertEqual(Order.objects.count(), 1)

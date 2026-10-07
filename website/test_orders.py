import uuid
from datetime import timedelta
from decimal import Decimal
from smtplib import SMTPAuthenticationError
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Order, OrderItem, OrderNotification
from .notifications import configuration_issues, process_notifications


@override_settings(ORDERING_ENABLED=True)
class OrderingTests(TestCase):
    def add(self, product="spanish-latte", quantity=1, **extra):
        return self.client.post(reverse("website:change_cart"), {"product_id": product, "quantity": quantity, **extra})

    def details(self):
        self.client.get(reverse("website:checkout"))
        return {"checkout_token": self.client.session["checkout_token"], "customer_name": "Test Customer",
                "phone": "024 123 4567", "notes": "Oat milk please"}

    def place(self):
        self.add(quantity=2)
        response = self.client.post(reverse("website:checkout"), self.details())
        self.assertEqual(response.status_code, 302)
        return Order.objects.get()

    def test_empty_cart_and_checkout_redirect(self):
        self.assertContains(self.client.get(reverse("website:basket")), "Your order is empty")
        self.assertRedirects(self.client.get(reverse("website:checkout")), reverse("website:basket"))

    def test_prices_come_from_catalogue_and_orders_have_snapshot_items_and_one_email_job(self):
        self.add(quantity=2, price="0.01", name="Free coffee", total="0.02")
        response = self.client.post(reverse("website:checkout"), {**self.details(), "total": "0.01"})
        order = Order.objects.get()
        self.assertEqual(order.total, Decimal("120.00"))
        self.assertEqual(order.phone, "+233241234567")
        self.assertEqual(order.items.get().name, "Spanish latte")
        self.assertEqual(order.items.get().unit_price, Decimal("60.00"))
        self.assertEqual(list(order.notifications.values_list("channel", flat=True)), ["email"])
        self.assertEqual(self.client.session["cart"], {})
        self.assertRedirects(response, reverse("website:receipt", args=[order.id]))

    def test_quantity_validation_and_total_limit(self):
        for quantity in [-5, 21, "invalid", "1.5", 0]:
            with self.subTest(quantity=quantity):
                response = self.client.post(reverse("website:change_cart"), {"product_id": "espresso", "quantity": quantity}, HTTP_ACCEPT="application/json")
                self.assertEqual(response.status_code, 400)
        self.add("espresso", 20)
        response = self.client.post(reverse("website:change_cart"), {"product_id": "spanish-latte", "quantity": 20}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.session["cart"], {"espresso": 20})

    def test_unknown_product_is_rejected_and_remove_and_update_work(self):
        self.add("unknown")
        self.assertFalse(self.client.session.get("cart"))
        self.add()
        self.add(quantity=3, action="update")
        self.assertEqual(self.client.session["cart"]["spanish-latte"], 3)
        self.add(action="remove")
        self.assertEqual(self.client.session["cart"], {})

    def test_duplicate_submission_returns_same_receipt_and_only_one_email_alert(self):
        self.add()
        data = self.details()
        first = self.client.post(reverse("website:checkout"), data)
        second = self.client.post(reverse("website:checkout"), data)
        self.assertEqual(first.url, second.url)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderNotification.objects.count(), 1)

    def test_stale_basket_requires_new_review_but_preserves_contact_details(self):
        self.add()
        data = self.details()
        self.add("espresso")
        response = self.client.post(reverse("website:checkout"), data)
        self.assertContains(response, "Your basket has changed", status_code=400)
        self.assertContains(response, "Test Customer", status_code=400)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(self.client.post(reverse("website:checkout"), self.details()).status_code, 302)

    def test_changed_catalogue_price_requires_review(self):
        from .cart import catalogue
        self.add()
        data = self.details()
        products = catalogue()
        products["spanish-latte"]["price"] = Decimal("65")
        with patch("website.cart.catalogue", return_value=products):
            response = self.client.post(reverse("website:checkout"), data)
        self.assertContains(response, "Your basket has changed", status_code=400)
        self.assertEqual(Order.objects.count(), 0)

    def test_invalid_details_create_no_order_or_jobs(self):
        self.add()
        data = self.details()
        for changes in [{"customer_name": " "}, {"phone": "abc"}, {"phone": "1234"},
                        {"notes": "x" * 501}, {"checkout_token": str(uuid.uuid4())}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.client.post(reverse("website:checkout"), {**data, **changes}).status_code, 400)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderNotification.objects.count(), 0)

    def test_order_creation_is_atomic(self):
        self.add()
        data = self.details()
        with patch("website.order_views.OrderNotification.objects.create", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse("website:checkout"), data)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(OrderItem.objects.exists())
        self.assertTrue(self.client.session["cart"])

    def test_receipt_is_private_including_poll_endpoint_and_not_cached(self):
        order = self.place()
        url = reverse("website:receipt", args=[order.id])
        other = Client()
        for suffix in ["", "?partial=1"]:
            self.assertEqual(other.get(url + suffix).status_code, 404)
        response = self.client.get(url)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertContains(response, "Awaiting shop confirmation")
        order.status = Order.Status.READY
        order.save()
        self.assertContains(self.client.get(url + "?partial=1"), "Ready for pickup")

    def test_customer_text_is_escaped(self):
        self.add()
        self.client.post(reverse("website:checkout"), {**self.details(), "notes": "<script>alert(1)</script>"})
        response = self.client.get(reverse("website:receipt", args=[Order.objects.get().id]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")

    def test_terminal_receipts_and_live_updates_remove_collection_instructions(self):
        order = self.place()
        url = reverse("website:receipt", args=[order.id])
        for status, label in [("completed", "Paid at pickup"), ("cancelled", "Order total")]:
            order.status = status
            order.save()
            for suffix in ["", "?partial=1"]:
                response = self.client.get(url + suffix)
                self.assertContains(response, label)
                self.assertNotContains(response, "Bring your order reference and pay at collection")
                self.assertNotContains(response, "Need to change or cancel?")
                self.assertNotContains(response, "Pay at pickup")

    def test_csrf_and_post_required_for_mutations(self):
        browser = Client(enforce_csrf_checks=True)
        for name in ["change_cart", "checkout"]:
            self.assertEqual(browser.post(reverse("website:" + name), {}).status_code, 403)
        self.assertEqual(self.client.get(reverse("website:change_cart")).status_code, 405)

    @override_settings(ORDERING_ENABLED=False)
    def test_can_disable_ordering(self):
        self.assertNotContains(self.client.get("/"), "data-add-to-order")
        self.add()
        self.assertFalse(self.client.session.get("cart"))
        self.assertContains(self.client.get(reverse("website:basket")), "taking a break")

    def test_staff_dashboard_and_transitions_require_permissions(self):
        order = self.place()
        url = reverse("staff:orders")
        update_url = reverse("staff:order_status", args=[order.id])
        self.assertEqual(self.client.get(url).status_code, 302)
        user = User.objects.create_user("staff", is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(url + "?partial=1").status_code, 403)
        user.user_permissions.add(Permission.objects.get(codename="view_order"))
        self.assertContains(self.client.get(url), order.reference)
        self.assertEqual(self.client.post(update_url, {"status": "accepted", "previous_status": "new"}).status_code, 403)
        user.user_permissions.add(Permission.objects.get(codename="change_order"))
        self.client.post(update_url, {"status": "completed", "previous_status": "new"})
        order.refresh_from_db()
        self.assertEqual(order.status, "new")
        for previous, status in [("new", "accepted"), ("accepted", "ready"), ("ready", "completed")]:
            self.client.post(update_url, {"status": status, "previous_status": previous})
            order.refresh_from_db()
            self.assertEqual(order.status, status)
        self.assertNotContains(self.client.get(url), order.reference)
        self.assertContains(self.client.get(url + "?history=1"), order.reference)
        self.client.post(update_url, {"status": "new", "previous_status": "completed"})
        order.refresh_from_db()
        self.assertEqual(order.status, "completed")

    def test_staff_update_csrf_and_stale_status(self):
        order = self.place()
        user = User.objects.create_superuser("admin", "", "testing-only")
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(user)
        url = reverse("staff:order_status", args=[order.id])
        self.assertEqual(browser.post(url, {"status": "accepted", "previous_status": "new"}).status_code, 403)
        self.client.force_login(user)
        self.client.post(url, {"status": "cancelled", "previous_status": "accepted"})
        order.refresh_from_db()
        self.assertEqual(order.status, "new")
        self.client.post(url, {"status": "cancelled", "previous_status": "new"})
        order.refresh_from_db()
        self.assertEqual(order.status, "cancelled")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_HOST="smtp.example.com",
    EMAIL_HOST_USER="", EMAIL_HOST_PASSWORD="",
    DEFAULT_FROM_EMAIL="orders@example.com", SHOP_ORDER_EMAIL="shop@example.com")
class NotificationTests(TestCase):
    @override_settings(EMAIL_HOST_USER="sender@example.com", EMAIL_HOST_PASSWORD="")
    def test_sender_without_password_is_not_ready(self):
        self.assertIn("SMTP password", configuration_issues()["email"])

    def setUp(self):
        self.order = Order.objects.create(checkout_token=uuid.uuid4(), owner_token=uuid.uuid4(),
            customer_name="Test Customer", phone="+233241234567", notes="No sugar", total="120.00")
        OrderItem.objects.create(order=self.order, product_id="spanish-latte", name="Spanish latte", quantity=2, unit_price="60.00")
        OrderNotification.objects.create(order=self.order, channel=OrderNotification.Channel.EMAIL)

    def test_email_payload_and_no_resending_accepted_jobs(self):
        self.assertEqual(configuration_issues(), {})
        self.assertEqual(process_notifications(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["shop@example.com"])
        self.assertIn("2 x Spanish latte", mail.outbox[0].body)
        self.assertIn("120.00", mail.outbox[0].body)
        self.assertIn("No sugar", mail.outbox[0].body)
        self.assertIn(self.order.reference, mail.outbox[0].subject)
        self.assertEqual(OrderNotification.objects.filter(status="submitted").count(), 1)
        self.assertEqual(process_notifications(), 0)

    def test_failed_email_is_retried_without_losing_the_order(self):
        with patch("website.notifications.send_email", side_effect=TimeoutError("secret credentials never stored")):
            process_notifications()
        failed = self.order.notifications.get(channel="email")
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.attempts, 1)
        self.assertNotIn("secret", failed.last_error)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(process_notifications(), 0)
        failed.next_attempt_at = timezone.now() - timedelta(seconds=1)
        failed.save()
        process_notifications()
        failed.refresh_from_db()
        self.assertEqual(failed.status, "submitted")
        self.assertEqual(failed.attempts, 2)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(SHOP_ORDER_EMAIL="")
    def test_missing_configuration_blocks_without_spending_retries(self):
        with patch("website.notifications.send_email") as email:
            process_notifications()
            email.assert_not_called()
        self.assertEqual(OrderNotification.objects.filter(status="blocked", attempts=0).count(), 1)

    def test_active_lease_skipped_expired_lease_recovered_retry_limit_respected(self):
        self.order.notifications.update(lease_until=timezone.now() + timedelta(minutes=1), lease_token=uuid.uuid4())
        self.assertEqual(process_notifications(), 0)
        self.order.notifications.update(lease_until=timezone.now() - timedelta(minutes=1))
        self.assertEqual(process_notifications(), 1)
        self.order.notifications.update(status="failed", attempts=5, next_attempt_at=timezone.now())
        self.assertEqual(process_notifications(), 0)

    def test_provider_rejection_is_not_marked_submitted(self):
        with patch("website.notifications.EmailMessage.send", return_value=0):
            process_notifications()
        self.assertEqual(self.order.notifications.get(channel="email").status, "failed")

    def test_authentication_failure_is_actionable_without_exposing_credentials(self):
        with patch("website.notifications.send_email", side_effect=SMTPAuthenticationError(534, b"private-test-value")):
            process_notifications()
        failed = self.order.notifications.get()
        self.assertEqual(failed.status, "failed")
        self.assertIn("App Password", failed.last_error)
        self.assertNotIn("private-test-value", failed.last_error)

    def test_legacy_whatsapp_jobs_are_not_sent_or_shown_as_setup_requirements(self):
        legacy = OrderNotification.objects.create(order=self.order, channel="whatsapp", status="blocked")
        self.assertEqual(process_notifications(), 1)
        legacy.refresh_from_db()
        self.assertEqual(legacy.attempts, 0)
        self.assertEqual(legacy.status, "blocked")
        self.assertEqual(configuration_issues(), {})
        user = User.objects.create_superuser("email-only-staff", "", "test-only-password")
        self.client.force_login(user)
        response = self.client.get(reverse("staff:orders"))
        self.assertContains(response, "Email:")
        self.assertNotContains(response, "WhatsApp")
        self.assertNotContains(response, "Twilio")
        self.assertNotContains(response, "Connect order notifications")

    def test_admin_retry_only_queues_email(self):
        email = self.order.notifications.get()
        email.status = "failed"
        email.attempts = 5
        email.save()
        legacy = OrderNotification.objects.create(order=self.order, channel="whatsapp", status="failed", attempts=3)
        user = User.objects.create_superuser("email-admin", "", "test-only-password")
        self.client.force_login(user)
        url = reverse("admin:website_order_changelist")
        self.client.post(url, {"action": "retry_alerts", "_selected_action": str(self.order.id)})
        email.refresh_from_db()
        legacy.refresh_from_db()
        self.assertEqual((email.status, email.attempts), ("pending", 0))
        self.assertEqual((legacy.status, legacy.attempts), ("failed", 3))

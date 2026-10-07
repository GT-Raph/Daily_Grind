import uuid

from django.contrib.auth.models import Permission, User
from django.test import Client, TestCase
from django.urls import reverse

from website.models import Order


class StaffPortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user("counter", password="test-only-password", is_staff=True)
        cls.staff.user_permissions.add(Permission.objects.get(codename="view_order"))
        cls.order = Order.objects.create(checkout_token=uuid.uuid4(), owner_token=uuid.uuid4(),
            customer_name="Private Customer", phone="+233241234567", total="60.00")

    def sign_in(self, **extra):
        return self.client.post(reverse("staff:login"), {
            "username": "counter", "password": "test-only-password", **extra,
        })

    def test_guest_queue_and_partial_use_staff_login_without_order_data(self):
        for suffix in ["", "?partial=1", "?history=1"]:
            response = self.client.get(reverse("staff:orders") + suffix)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith(reverse("staff:login") + "?next="))
            self.assertNotContains(response, self.order.customer_name, status_code=302)
            self.assertIn("no-store", response["Cache-Control"])

    def test_staff_login_has_its_own_shell_and_valid_session(self):
        response = self.client.get(reverse("staff:login"))
        self.assertTemplateUsed(response, "staff_portal/base.html")
        self.assertContains(response, "Staff sign in")
        self.assertContains(response, 'name="robots" content="noindex, nofollow"')
        self.assertNotContains(response, "Your order")
        self.assertNotContains(response, "website/orders.js")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertRedirects(self.sign_in(), reverse("staff:orders"))
        self.assertRedirects(self.client.get(reverse("staff:login")), reverse("staff:orders"))

    def test_wrong_password_nonstaff_inactive_and_missing_permission_cannot_login(self):
        cases = [
            ("wrong", {"is_staff": True}, "wrong-password"),
            ("customer", {"is_staff": False}, "test-only-password"),
            ("inactive", {"is_staff": True, "is_active": False}, "test-only-password"),
            ("no-permission", {"is_staff": True}, "test-only-password"),
        ]
        for username, flags, password in cases:
            with self.subTest(username=username):
                user = User.objects.create_user(username, password="test-only-password", **flags)
                if username != "no-permission":
                    user.user_permissions.add(Permission.objects.get(codename="view_order"))
                response = self.client.post(reverse("staff:login"), {"username": username, "password": password})
                self.assertContains(response, "Unable to sign in")
                self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_returns_only_to_staff_queue_and_preserves_history(self):
        for target in ["https://example.com/", "//example.com/staff/", "/", "/admin/", "/staff/logout/", "/staff/?partial=1"]:
            with self.subTest(target=target):
                self.client.logout()
                self.assertRedirects(self.sign_in(next=target), reverse("staff:orders"))
        self.client.logout()
        self.assertRedirects(self.sign_in(next="/staff/?history=1&partial=1"), "/staff/?history=1")

    def test_nonstaff_even_with_permission_cannot_read_or_mutate_orders(self):
        user = User.objects.create_user("customer-with-permission")
        user.user_permissions.add(Permission.objects.get(codename="view_order"), Permission.objects.get(codename="change_order"))
        self.client.force_login(user)
        for suffix in ["", "?partial=1", "?history=1"]:
            response = self.client.get(reverse("staff:orders") + suffix)
            self.assertContains(response, "Staff access needed", status_code=403)
            self.assertNotContains(response, self.order.customer_name, status_code=403)
        response = self.client.post(reverse("staff:order_status", args=[self.order.id]), {
            "status": "accepted", "previous_status": "new",
        })
        self.assertEqual(response.status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "new")

    def test_view_only_dashboard_has_private_shell_without_action_buttons(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("staff:orders"))
        self.assertTemplateUsed(response, "staff_portal/base.html")
        self.assertContains(response, self.order.customer_name)
        self.assertContains(response, "View-only access")
        self.assertContains(response, "Sign out")
        self.assertNotContains(response, "Accept order")
        self.assertNotContains(response, "Your order")
        self.assertNotContains(response, "website/site.js")
        self.assertNotContains(response, 'href="/#menu"')
        self.assertIn("no-store", response["Cache-Control"])

    def test_staff_login_and_logout_require_csrf_and_logout_is_post_only(self):
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.post(reverse("staff:login"), {}).status_code, 403)
        browser.force_login(self.staff)
        self.assertEqual(browser.get(reverse("staff:logout")).status_code, 405)
        self.assertEqual(browser.post(reverse("staff:logout")).status_code, 403)
        browser.get(reverse("staff:orders"))
        response = browser.post(reverse("staff:logout"), {"csrfmiddlewaretoken": browser.cookies["csrftoken"].value, "next": "/"})
        self.assertRedirects(response, reverse("staff:login"))
        self.assertNotIn("_auth_user_id", browser.session)
        self.assertEqual(browser.get(reverse("staff:orders")).status_code, 302)

    def test_old_bookmarks_and_already_open_forms_keep_working_with_permissions(self):
        self.assertRedirects(self.client.get("/shop/orders/?history=1"), "/staff/?history=1", fetch_redirect_response=False)
        legacy_status = reverse("website:order_status", args=[self.order.id])
        self.assertEqual(self.client.post(legacy_status, {"status": "accepted", "previous_status": "new"}).status_code, 302)
        self.staff.user_permissions.add(Permission.objects.get(codename="change_order"))
        self.client.force_login(self.staff)
        self.assertRedirects(self.client.post(legacy_status, {"status": "accepted", "previous_status": "new"}), reverse("staff:orders"))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "accepted")

    def test_customer_pages_do_not_link_to_staff_section(self):
        for url in ["/", reverse("website:basket")]:
            response = self.client.get(url)
            self.assertNotContains(response, 'href="/staff/')
            self.assertNotContains(response, "staff_portal/staff.js")

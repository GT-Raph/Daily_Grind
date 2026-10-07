import re
from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.staticfiles import finders
from django.test import Client, TestCase
from django.urls import reverse

from .content import DATA, page_content
from .models import Subscriber


class WebsiteTests(TestCase):
    def test_home_is_rendered_without_react_and_has_all_content(self):
        response = self.client.get(reverse("website:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "website/home.html")
        self.assertContains(response, "Spintex Road")
        for group in DATA["menu"]:
            for item in group["items"]:
                self.assertContains(response, item["name"])
        self.assertNotContains(response, 'id="root"')
        self.assertNotContains(response, "main.tsx")
        self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_all_local_assets_in_the_rendered_page_exist(self):
        html = self.client.get(reverse("website:home")).content.decode()
        assets = set(re.findall(r'(?:src|href)="/static/([^"?]+)', html))
        self.assertGreater(len(assets), 15)
        for asset in assets:
            with self.subTest(asset=asset):
                self.assertIsNotNone(finders.find(asset))

    def test_hours_use_accra_time(self):
        with patch("django.utils.timezone.now", return_value=datetime(2026, 10, 4, 23, 59, tzinfo=dt_timezone.utc)):
            today = [hour["day"] for hour in page_content()["hours"] if hour["today"]]
        self.assertEqual(today, ["Sunday"])

    def test_signup_persists_and_uses_post_redirect_get(self):
        response = self.client.post(reverse("website:subscribe"), {"email": "Coffee@Example.com"})
        self.assertRedirects(response, "/#newsletter", fetch_redirect_response=False)
        self.assertEqual(Subscriber.objects.get().email, "coffee@example.com")
        confirmation = self.client.get(reverse("website:home"))
        self.assertContains(confirmation, "on the list.")

    def test_repeated_signup_is_idempotent(self):
        for email in ["Coffee@Example.com", "coffee@example.com"]:
            self.client.post(reverse("website:subscribe"), {"email": email})
        self.assertEqual(Subscriber.objects.count(), 1)

    def test_invalid_signup_shows_errors_without_saving(self):
        response = self.client.post(reverse("website:subscribe"), {"email": "not-an-email"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Enter a valid email address.", status_code=400)
        self.assertEqual(Subscriber.objects.count(), 0)

    def test_signup_requires_post_and_csrf(self):
        url = reverse("website:subscribe")
        self.assertEqual(self.client.get(url).status_code, 405)
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.post(url, {"email": "test@example.com"}).status_code, 403)
        browser.get(reverse("website:home"))
        token = browser.cookies["csrftoken"].value
        response = browser.post(url, {"email": "test@example.com", "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 302)

    def test_admin_requires_login(self):
        response = self.client.get("/admin/website/subscriber/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

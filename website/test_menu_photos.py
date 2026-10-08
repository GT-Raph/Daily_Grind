import os
import shutil
import tempfile
from io import BytesIO
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import MenuPrice
from .photos import MAX_UPLOAD_BYTES


def photo_file(name="tea.jpg", size=(1600, 1200), image_format="JPEG", exif=None):
    buffer = BytesIO()
    Image.new("RGB", size, (190, 120, 70)).save(buffer, image_format, **({"exif": exif} if exif else {}))
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f"image/{image_format.lower()}")


class MenuPhotoUploadTests(TestCase):
    """Administrators upload product photos from their own computer instead of pasting a link."""

    @classmethod
    def setUpTestData(cls):
        cls.administrator = User.objects.create_superuser("photo-owner", "", "test-only-password")

    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        settings_override = override_settings(MEDIA_ROOT=media)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.media = Path(media)
        self.admin_client = Client()
        self.admin_client.force_login(self.administrator)
        self.add_url = reverse("admin:website_menuprice_add")

    def product_data(self, **extra):
        return {"name": "Photo tea", "category": "tea", "price": "42.50", "note": "Freshly brewed",
                "display_order": "20", "is_active": "on", "_save": "Save", **extra}

    def change_url(self, product):
        return reverse("admin:website_menuprice_change", args=[product.pk])

    def test_photo_from_a_computer_is_resized_to_webp_and_shown_on_the_menu(self):
        response = self.admin_client.post(self.add_url, self.product_data(photo=photo_file()))
        self.assertEqual(response.status_code, 302)
        product = MenuPrice.objects.get(name="Photo tea")
        self.assertTrue(product.photo.name.startswith("menu/") and product.photo.name.endswith(".webp"))
        with Image.open(product.photo.path) as saved:
            self.assertEqual(saved.format, "WEBP")
            self.assertEqual(saved.size, (640, 480))
        self.assertContains(self.client.get("/"), product.photo.url)

    def test_phone_photo_is_turned_upright_and_its_location_data_removed(self):
        exif = Image.Exif()
        exif[0x0112] = 6  # stored sideways: rotate 90 degrees to display upright
        exif[0x010F] = "PhoneMaker"
        self.admin_client.post(self.add_url, self.product_data(photo=photo_file(size=(1200, 800), exif=exif)))
        product = MenuPrice.objects.get(name="Photo tea")
        with Image.open(product.photo.path) as saved:
            self.assertEqual(saved.size, (427, 640))
            self.assertEqual(len(saved.getexif()), 0)

    def test_a_file_that_is_not_a_photo_is_rejected_with_a_clear_message(self):
        fake = SimpleUploadedFile("menu.jpg", b"%PDF-1.7 not an image", content_type="image/jpeg")
        response = self.admin_client.post(self.add_url, self.product_data(photo=fake))
        self.assertContains(response, "isn&#x27;t a photo the menu can use")
        self.assertFalse(MenuPrice.objects.filter(name="Photo tea").exists())
        self.assertEqual(list(self.media.rglob("*.*")), [])

    def test_a_photo_over_8_mb_is_rejected(self):
        # Random noise barely compresses, so this genuine PNG is just over the limit.
        noise = Image.frombytes("RGB", (2200, 1400), os.urandom(2200 * 1400 * 3))
        buffer = BytesIO()
        noise.save(buffer, "PNG", compress_level=0)
        self.assertGreater(buffer.tell(), MAX_UPLOAD_BYTES)
        oversized = SimpleUploadedFile("huge.png", buffer.getvalue(), content_type="image/png")
        response = self.admin_client.post(self.add_url, self.product_data(photo=oversized))
        self.assertContains(response, "larger than 8 MB")
        self.assertFalse(MenuPrice.objects.filter(name="Photo tea").exists())

    def test_uploaded_photo_takes_precedence_over_a_photo_url(self):
        self.admin_client.post(self.add_url, self.product_data(photo=photo_file(), image_url="https://example.com/tea.jpg"))
        product = MenuPrice.objects.get(name="Photo tea")
        response = self.client.get("/")
        self.assertContains(response, product.photo.url)
        self.assertNotContains(response, "https://example.com/tea.jpg")

    def test_replacing_or_clearing_a_photo_removes_the_old_file(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.admin_client.post(self.add_url, self.product_data(photo=photo_file()))
        product = MenuPrice.objects.get(name="Photo tea")
        first = Path(product.photo.path)
        with self.captureOnCommitCallbacks(execute=True):
            self.admin_client.post(self.change_url(product), self.product_data(photo=photo_file("second.png", image_format="PNG")))
        product.refresh_from_db()
        second = Path(product.photo.path)
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        with self.captureOnCommitCallbacks(execute=True):
            self.admin_client.post(self.change_url(product), self.product_data(**{"photo-clear": "on"}))
        product.refresh_from_db()
        self.assertFalse(product.photo)
        self.assertFalse(second.exists())

    def test_deleting_a_product_removes_its_uploaded_photo(self):
        self.admin_client.post(self.add_url, self.product_data(photo=photo_file()))
        product = MenuPrice.objects.get(name="Photo tea")
        stored = Path(product.photo.path)
        with self.captureOnCommitCallbacks(execute=True):
            product.delete()
        self.assertFalse(stored.exists())

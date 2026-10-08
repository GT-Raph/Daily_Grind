import json
import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from .models import MenuPrice


class AttachMenuImagesTests(TestCase):
    """The command runs against a temporary project folder, so it never depends on which real artwork exists."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "website/data").mkdir(parents=True)
        (self.root / "public/images/menu").mkdir(parents=True)
        (self.root / "public/images/menu/has-photo.webp").write_bytes(b"RIFF")
        items = [
            {"product_id": "test-has-photo", "name": "Has photo", "image_path": "images/menu/has-photo.webp"},
            {"product_id": "test-no-photo", "name": "No photo yet", "image_path": "images/menu/no-photo.webp"},
        ]
        (self.root / "website/data/menu_2026_10_05.json").write_text(json.dumps({"items": items}), encoding="utf-8")
        MenuPrice.objects.create(product_id="test-has-photo", name="Has photo", category="food", price="10.00")
        MenuPrice.objects.create(product_id="test-no-photo", name="No photo yet", category="food", price="10.00")

    def run_command(self, *args):
        out = StringIO()
        with override_settings(BASE_DIR=self.root):
            call_command("attach_menu_images", *args, stdout=out)
        return out.getvalue()

    def test_missing_artwork_stops_the_command_by_default(self):
        with self.assertRaisesMessage(CommandError, "No photo yet"):
            self.run_command("--apply")
        self.assertEqual(MenuPrice.objects.get(pk="test-has-photo").image_path, "")

    def test_skip_missing_attaches_available_artwork_and_lists_the_rest(self):
        output = self.run_command("--apply", "--skip-missing")
        self.assertEqual(MenuPrice.objects.get(pk="test-has-photo").image_path, "images/menu/has-photo.webp")
        self.assertEqual(MenuPrice.objects.get(pk="test-no-photo").image_path, "")
        self.assertIn("No photo yet (images/menu/no-photo.webp)", output)
        self.assertIn("Attached 1 images", output)

    def test_skip_missing_preserves_an_administrator_photo(self):
        MenuPrice.objects.filter(pk="test-has-photo").update(image_url="https://example.com/real-photo.jpg")
        self.run_command("--apply", "--skip-missing")
        product = MenuPrice.objects.get(pk="test-has-photo")
        self.assertEqual(product.image_path, "")
        self.assertEqual(product.image_url, "https://example.com/real-photo.jpg")

    def test_skip_missing_preserves_an_administrator_photo_without_a_url(self):
        MenuPrice.objects.filter(pk="test-has-photo").update(photo="menu/admin-photo.webp")
        self.run_command("--apply", "--skip-missing")
        product = MenuPrice.objects.get(pk="test-has-photo")
        self.assertEqual(product.image_path, "")
        self.assertEqual(product.photo.name, "menu/admin-photo.webp")

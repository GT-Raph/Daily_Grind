"""Attach supplied local artwork without reimporting prices or other menu fields."""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from website.models import MenuPrice


class Command(BaseCommand):
    help = "Preview or attach missing menu images. Existing product photos and all other fields are preserved."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Attach images; default is a preview.")
        parser.add_argument("--skip-missing", action="store_true",
                            help="Attach the images that exist and list the missing ones, instead of stopping.")

    def handle(self, *args, **options):
        root = Path(settings.BASE_DIR)
        source = json.loads((root / "website/data/menu_2026_10_05.json").read_text(encoding="utf-8"))
        image_directory = (root / "public/images/menu").resolve()
        paths = {}
        unavailable = []
        for item in source["items"]:
            image_path = item.get("image_path", "")
            local = (root / "public" / image_path).resolve()
            if not image_path or local.parent != image_directory or not local.is_file():
                if not options["skip_missing"]:
                    raise CommandError(f"Menu image is not available for {item['name']}: {image_path}")
                unavailable.append(f"{item['name']} ({image_path or 'no path'})")
                continue
            paths[item["product_id"]] = image_path
        for entry in unavailable:
            self.stdout.write(self.style.WARNING(f"Skipped, image not available yet: {entry}"))
        missing = MenuPrice.objects.filter(pk__in=paths, image_path="", image_url="", photo="")
        self.stdout.write(f"{missing.count()} products can receive a local menu image.")
        if not options["apply"]:
            self.stdout.write("Preview only. Use --apply to attach images.")
            return
        count = 0
        with transaction.atomic():
            for product_id, image_path in paths.items():
                # Conditional writes preserve photos added by an administrator during this import.
                count += MenuPrice.objects.filter(pk=product_id, image_path="", image_url="", photo="").update(image_path=image_path)
        self.stdout.write(self.style.SUCCESS(f"Attached {count} images. Prices, availability, discounts and existing photos are unchanged."))

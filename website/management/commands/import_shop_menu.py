"""Explicit, repeatable import of the owner-supplied menu; never runs on startup."""
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers import serialize
from django.db import transaction

from website.models import MenuPrice


SOURCE = Path(__file__).resolve().parents[2] / "data" / "menu_2026_10_05.json"


def source_products():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    products = []
    for position, item in enumerate(source["items"]):
        values = {key: item[key] for key in ("product_id", "name", "category", "note")}
        values.update(price=Decimal(item["price"]) if item["price"] is not None else None,
                      price_label=item.get("price_label", ""), call_to_order=item.get("call_to_order", False),
                      order_note_prompt=item.get("order_note_prompt", ""), display_order=position,
                      image_path=item.get("image_path", ""), featured=False, is_active=True)
        products.append(values)
    if len({item["product_id"] for item in products}) != len(products):
        raise CommandError("Duplicate product IDs in the source menu.")
    return source, products


class Command(BaseCommand):
    help = "Preview or apply the supplied Daily Grind PDF menu. Saves a menu-only backup before applying."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply the reviewed menu; default is a preview.")
        parser.add_argument("--backup-dir", type=Path, default=Path(settings.BASE_DIR) / ".migration-backups")

    def handle(self, *args, **options):
        source, products = source_products()
        for values in products:
            # Existing IDs are intentional; validate field values, model rules and DB constraints separately from uniqueness.
            MenuPrice(**values).full_clean(validate_unique=False)
        ids = {item["product_id"] for item in products}
        existing_ids = set(MenuPrice.objects.values_list("pk", flat=True))
        hidden = MenuPrice.objects.filter(is_active=True).exclude(pk__in=ids).count()
        self.stdout.write(f"{source['source']['title']}: {len(products)} menu entries, "
                          f"{len(ids - existing_ids)} new, {len(ids & existing_ids)} matched, {hidden} to hide.")
        if not options["apply"]:
            self.stdout.write("Preview only. Use --apply to update the menu.")
            return
        with transaction.atomic():
            # Menu-only backup contains no customers, orders, credentials or notification jobs.
            current = list(MenuPrice.objects.select_for_update().all())
            directory = options["backup_dir"]
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = directory / f"menu-before-pdf-{stamp}.json"
            backup.write_text(serialize("json", current, indent=2), encoding="utf-8")
            for values in products:
                values = values.copy()
                product_id = values.pop("product_id")
                # Keep any administrator-supplied photo URLs on matched products.
                MenuPrice.objects.update_or_create(pk=product_id, defaults=values)
            MenuPrice.objects.exclude(pk__in=ids).update(is_active=False)
        self.stdout.write(self.style.SUCCESS(f"Applied {len(products)} entries. Previous menu saved to {backup}."))
        self.stdout.write("Old products are hidden. Order snapshots, customer histories and discount rules are preserved.")

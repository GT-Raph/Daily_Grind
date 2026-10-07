import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from website.notifications import configuration_issues, process_notifications


class Command(BaseCommand):
    help = "Send queued order emails; use --watch for a persistent worker."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true")

    def handle(self, *args, **options):
        for channel, issue in configuration_issues().items():
            self.stderr.write(f"{channel}: {issue}")
        try:
            while True:
                close_old_connections()
                count = process_notifications()
                if count:
                    self.stdout.write(f"Processed {count} alert(s). See the order screen for provider status.")
                if not options["watch"]:
                    break
                time.sleep(5)
        except KeyboardInterrupt:
            self.stdout.write("Order notification worker stopped.")

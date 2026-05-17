import time
from django.core.management.base import BaseCommand
from django.db import connections
from django.db.utils import OperationalError

class Command(BaseCommand):
    help = "Wait for the database to be available"

    def handle(self, *args, **options):
        self.stdout.write("Waiting for database...")
        for _ in range(60):
            try:
                connections["default"].ensure_connection()
                self.stdout.write(self.style.SUCCESS("Database ready!"))
                return
            except OperationalError:
                self.stdout.write("  not ready — retrying...")
                time.sleep(1)
        raise SystemExit("Database unavailable after 60s")

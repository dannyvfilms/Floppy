"""Load the sample library used to check every media type locally."""

from django.core.management.base import BaseCommand

from users.local_library import LOCAL_PASSWORD, LOCAL_USERNAME, seed_local_library


class Command(BaseCommand):
    """Upsert ``tile-seed-*`` rows for the demo account and joe."""

    help = (
        "Upsert the sample library (one row per media type) for the demo "
        "account and joe, and give each a full tile profile. Safe to run "
        "again. Does not change other rows."
    )

    def handle(self, *args, **options):
        """Load the sample library and report how many rows were touched."""
        touched = seed_local_library()
        self.stdout.write(
            self.style.SUCCESS(
                f"Sample library upserted ({touched} rows). "
                f"Log in as demo/demodemo or {LOCAL_USERNAME}/{LOCAL_PASSWORD}."
            )
        )

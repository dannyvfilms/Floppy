"""Check Discover provider endpoint availability."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from app.discover.providers.tmdb_adapter import TMDbDiscoverAdapter
from app.discover.providers.trakt_adapter import TraktDiscoverAdapter


class Command(BaseCommand):
    """Run lightweight provider capability checks for Discover."""

    help = "Validate Discover provider endpoint availability"

    def handle(self, *_args, **_options):
        """Validate Discover provider endpoint availability."""
        tmdb_checks = TMDbDiscoverAdapter().check_capability()
        trakt_checks = TraktDiscoverAdapter().check_capability()
        checks = {
            **{f"tmdb_{name}": status for name, status in tmdb_checks.items()},
            **{f"trakt_{name}": status for name, status in trakt_checks.items()},
        }

        ok_count = 0
        for name, is_ok in checks.items():
            status = "OK" if is_ok else "FAIL"
            if is_ok:
                ok_count += 1
            self.stdout.write(f"{status:>4} | {name}")

        if ok_count == len(checks):
            self.stdout.write(
                self.style.SUCCESS("All Discover provider checks passed.")
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"{ok_count}/{len(checks)} Discover provider checks passed.",
            ),
        )

"""Classify existing TMDB TV tracking rows as grouped anime.

The command is read-only by default.  It changes only the library bucket and
provider identity metadata; TV, season, episode, and history primary keys are
preserved.  A target-bucket collision aborts that title without a partial move.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

import app.providers.tmdb
from app.models import TV, MediaTypes, Sources
from app.services import grouped_anime
from integrations import anime_mapping


class Command(BaseCommand):
    """Run the exact-ID grouped-anime classifier."""

    help = "Classify high-confidence TMDB TV shows as grouped anime"

    def add_arguments(self, parser):
        """Add command-line options."""
        parser.add_argument(
            "--user",
            "--username",
            dest="username",
            default=None,
            help="Only process one username (default: all users)",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write safe classifications (default is a dry run)",
        )
        parser.add_argument(
            "--tmdb-id",
            type=str,
            default=None,
            help="Only process one TMDB TV show ID",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Explicitly select the default read-only mode",
        )
        parser.add_argument(
            "--report",
            type=Path,
            default=None,
            help="Write the JSON classification report to this path",
        )

    def handle(self, *_args, **options):
        """Classify matching TV rows and optionally promote them."""
        apply_changes = bool(options["apply"])
        if apply_changes and options["dry_run"]:
            message = "--apply and --dry-run cannot be combined"
            raise CommandError(message)

        queryset = TV.objects.filter(
            item__source=Sources.TMDB.value,
            item__media_type=MediaTypes.TV.value,
            item__library_media_type__in=("", MediaTypes.TV.value),
        ).select_related("item", "user")
        if options["username"]:
            queryset = queryset.filter(user__username=options["username"])
        if options["tmdb_id"]:
            queryset = queryset.filter(item__media_id=options["tmdb_id"])

        shows = list(queryset.order_by("item__title", "user__username"))
        mode = "APPLY" if apply_changes else "DRY RUN"
        self.stdout.write(f"{mode}: examining {len(shows)} TV tracking row(s)")
        snapshot = anime_mapping.load_mapping_snapshot() if shows else None

        report = {
            "version": 1,
            "mode": "apply" if apply_changes else "dry-run",
            "user": options["username"],
            "generated_at": datetime.now().astimezone().isoformat(),
            "mapping_source": grouped_anime.MAPPING_SOURCE,
            "mapping_revision": snapshot.revision if snapshot else None,
            "mapping_digest": snapshot.digest if snapshot else None,
            "summary": {
                "examined": len(shows),
                "move": 0,
                "leave": 0,
                "applied": 0,
                "failed": 0,
            },
            "shows": [],
        }

        for show in shows:
            item = show.item
            entry = {
                "user": show.user.username,
                "title": item.title,
                "tmdb_id": str(item.media_id),
                "current_bucket": item.library_media_type,
            }
            try:
                metadata = app.providers.tmdb.tv(item.media_id)
                match = grouped_anime.classify_tv_metadata(metadata, snapshot=snapshot)
                entry["match"] = match.as_dict()
                if not match.is_grouped_anime:
                    report["summary"]["leave"] += 1
                    entry["result"] = "leave"
                elif not apply_changes:
                    report["summary"]["move"] += 1
                    entry["result"] = "would_move"
                elif grouped_anime.promote_grouped_anime(item, match):
                    report["summary"]["applied"] += 1
                    entry["result"] = "applied"
                else:
                    report["summary"]["failed"] += 1
                    entry["result"] = "target_bucket_collision"
            except Exception as error:  # pragma: no cover - provider failure is environment-specific
                report["summary"]["failed"] += 1
                entry["result"] = "failed"
                entry["error"] = str(error)
                self.stdout.write(
                    self.style.WARNING(f"{item.title}: classification failed: {error}"),
                )
            report["shows"].append(entry)

        summary = report["summary"]
        self.stdout.write(
            "Summary: examined={examined} move={move} leave={leave} "
            "applied={applied} failed={failed}".format(**summary),
        )
        if not apply_changes and summary["move"]:
            self.stdout.write(
                self.style.WARNING("Re-run with --apply to write the proposed moves."),
            )

        if options["report"]:
            options["report"].parent.mkdir(parents=True, exist_ok=True)
            options["report"].write_text(
                json.dumps(report, indent=2, sort_keys=True),
                encoding="utf-8",
            )

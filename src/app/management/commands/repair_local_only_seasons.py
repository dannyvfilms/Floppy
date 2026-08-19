"""Repair seasons whose watches were filed under numbering the provider lacks.

Plex/TVDB and TMDB routinely disagree about how a show's seasons are split. When
a webhook could not resolve the disagreement it wrote a "local only" season, and
because the provider has no episode count for it the season can never reach
Completed. This command re-checks those seasons against the provider and either
restores them (the provider has the season now) or re-files their episodes onto
the season the provider actually has.

Read-only by default. Pass --apply to write.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

import app.providers.tmdb
from app.models import Episode, ProviderMetadataStatus, Season, Sources, Status
from app.providers import services
from integrations import episode_remap


class Command(BaseCommand):
    """Re-check and repair local-only seasons."""

    help = (
        "Repair seasons flagged local_only_missing_season by restoring provider "
        "metadata or re-filing their episodes onto the provider's numbering"
    )

    def add_arguments(self, parser):
        """Add command line arguments."""
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes (default is a read-only report)",
        )
        parser.add_argument(
            "--media-id",
            type=str,
            default=None,
            help="Only process this provider media id (e.g. 96316)",
        )
        parser.add_argument(
            "--username",
            type=str,
            default=None,
            help="Only process seasons belonging to this user",
        )

    def handle(self, *_args, **options):
        """Execute the command."""
        self.apply = options["apply"]

        queryset = Season.objects.filter(
            item__provider_metadata_status=(
                ProviderMetadataStatus.LOCAL_ONLY_MISSING_SEASON.value
            ),
            item__source=Sources.TMDB.value,
        ).select_related("item", "related_tv", "related_tv__item", "user")

        if options["media_id"]:
            queryset = queryset.filter(item__media_id=options["media_id"])
        if options["username"]:
            queryset = queryset.filter(user__username=options["username"])

        seasons = list(queryset.order_by("item__media_id", "item__season_number"))
        if not seasons:
            self.stdout.write("No local-only seasons found.")
            return

        mode = "APPLYING" if self.apply else "DRY RUN (no changes written)"
        self.stdout.write(f"{mode} - {len(seasons)} local-only season(s) to check\n")

        counts = {"restored": 0, "remapped": 0, "unresolved": 0, "failed": 0}
        for season in seasons:
            outcome = self._process_season(season)
            counts[outcome] += 1

        self.stdout.write(
            "\nRestored: {restored}  Remapped: {remapped}  "
            "Unresolved: {unresolved}  Failed: {failed}".format(**counts),
        )
        if not self.apply and (counts["restored"] or counts["remapped"]):
            self.stdout.write(
                self.style.WARNING("\nRe-run with --apply to write these changes."),
            )

    def _process_season(self, season):
        """Check one season and repair it when possible."""
        item = season.item
        label = f"{item.title} S{item.season_number} ({item.media_id}, {season.user})"

        try:
            tv_metadata = app.providers.tmdb.tv_with_seasons(
                item.media_id,
                [item.season_number],
            )
        except (services.ProviderAPIError, OSError) as error:
            self.stdout.write(
                self.style.ERROR(f"{label}: provider lookup failed: {error}"),
            )
            return "failed"

        season_metadata = tv_metadata.get(f"season/{item.season_number}")
        if season_metadata:
            self._restore_season(season, season_metadata, label)
            return "restored"

        return self._remap_season(season, tv_metadata, label)

    def _restore_season(self, season, season_metadata, label):
        """Clear the local-only flag now that the provider has the season."""
        self.stdout.write(
            f"{label}: provider now has this season - clearing local-only flag "
            "and recomputing status",
        )
        if not self.apply:
            return

        with transaction.atomic():
            item = season.item
            item.provider_metadata_status = ""
            item.local_season_episode_count = None
            item.save(
                update_fields=[
                    "provider_metadata_status",
                    "local_season_episode_count",
                ],
            )
            self._sync_season_status(season, len(season_metadata["episodes"]))

    def _sync_season_status(self, season, max_progress):
        """Recompute season and parent-show status, mirroring Episode.save()."""
        desired_status = season.derived_status_from_episode_progress(
            max_progress=max_progress,
        )
        if desired_status != season.status:
            season.status = desired_status
            season.save(update_fields=["status"])
        if desired_status == Status.COMPLETED.value:
            season.related_tv._handle_completed_season(season.item.season_number)

    def _remap_season(self, season, tv_metadata, label):
        """Re-file this season's episodes onto the provider's numbering."""
        item = season.item
        episodes = list(
            Episode.objects.filter(related_season=season).select_related("item"),
        )
        if not episodes:
            self.stdout.write(f"{label}: no episode history, skipping")
            return "unresolved"

        def load_season(candidate):
            metadata = app.providers.tmdb.tv_with_seasons(item.media_id, [candidate])
            return metadata.get(f"season/{candidate}")

        # Every episode must land somewhere, or the season is left alone: a
        # partial move would split one season's history across two places.
        moves = []
        for episode in episodes:
            remapped = episode_remap.remap_via_cumulative_numbering(
                item.season_number,
                episode.item.episode_number,
                tv_metadata,
                load_season,
            )
            if remapped is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"{label}: no provider season found for episode "
                        f"{episode.item.episode_number} - leaving this season "
                        "as local-only. Re-match the show in your media server, "
                        "or use Sync metadata on its page.",
                    ),
                )
                return "unresolved"
            moves.append((episode, remapped))

        targets = sorted({(m[1][0], m[1][1]) for m in moves})
        self.stdout.write(
            f"{label}: re-filing {len(moves)} episode(s) -> "
            + ", ".join(f"S{s}E{e}" for s, e in targets),
        )
        if not self.apply:
            return "remapped"

        try:
            with transaction.atomic():
                self._apply_moves(season, moves)
        except Exception as error:
            self.stdout.write(self.style.ERROR(f"{label}: move failed: {error}"))
            return "failed"
        return "remapped"

    def _apply_moves(self, season, moves):
        """Move episodes onto their provider seasons inside one transaction."""
        item = season.item
        target_seasons = {}

        for episode, (target_number, target_episode, season_metadata) in moves:
            target_season = target_seasons.get(target_number)
            if target_season is None:
                target_season = self._get_or_create_target_season(
                    season,
                    target_number,
                    season_metadata,
                )
                target_seasons[target_number] = target_season

            episode_item = target_season.get_episode_item(
                target_episode,
                season_metadata,
            )
            duplicate = Episode.objects.filter(
                item=episode_item,
                related_season=target_season,
                end_date=episode.end_date,
            ).exists()
            if duplicate:
                episode.delete()
                continue

            episode.item = episode_item
            episode.related_season = target_season
            episode.save()

        # The source season is now empty; drop it so the local-only badge and
        # its phantom episode numbering disappear from the UI.
        if not Episode.objects.filter(related_season=season).exists():
            season.delete()
            if not Season.objects.filter(item=item).exists():
                item.delete()

    def _get_or_create_target_season(
        self,
        source_season,
        season_number,
        season_metadata,
    ):
        """Return the Season row for the provider's numbering, creating it if needed."""
        from app.services import metadata_resolution

        source_item = source_season.item
        target_item = metadata_resolution.get_or_create_tracked_season_item(
            source_item.media_id,
            source_item.source,
            season_number,
            provider=Sources.TMDB.value,
            library_media_type=source_item.library_media_type,
            metadata=season_metadata,
            defaults={
                "title": source_season.related_tv.item.title,
                "image": season_metadata.get("image") or source_item.image,
            },
        )
        target_season, _created = Season.objects.get_or_create(
            item=target_item,
            user=source_season.user,
            related_tv=source_season.related_tv,
            defaults={"status": Status.IN_PROGRESS.value},
        )
        return target_season

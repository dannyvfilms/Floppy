"""Regressions for the Pocket Casts catalog re-walk.

Production evidence (2026-09-14): four recurring Pocket Casts runs of roughly
1,019 seconds each - about 30% of all background worker time over nine hours -
walked ~11,000 catalog episodes across 12 shows and imported nothing. Every
episode cost one SELECT, one hydrated model, and a field-by-field comparison,
on every poll, whether or not anything upstream had changed.

The skip is only safe if "unchanged" means exactly what ``_sync_catalog_episode``
would have written, so the central test here is a consistency test: for every
writable catalog field, a skip must imply the sync writes nothing, and a change
must imply the sync writes it.
"""

from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from app.models import PodcastEpisode, PodcastShow
from integrations.imports.pocketcasts import (
    PocketCastsImporter,
    _cleanup_duplicate_episodes_global,
)
from integrations.models import PocketCastsAccount

PUBLISHED = datetime(2025, 1, 1, tzinfo=UTC)


def _catalog_payload(**overrides):
    """The shape _build_catalog_episode_data() produces."""
    payload = {
        "uuid": "uuid-1",
        "podcastUuid": "show-1",
        "podcastTitle": "Show",
        "author": "",
        "podcastSlug": "",
        "title": "Episode One",
        "slug": "episode-one",
        "published": int(PUBLISHED.timestamp()),
        "url": "https://example.com/1.mp3",
        "fileType": "audio/mpeg",
        "duration": 1800,
        "episodeType": "full",
        "episodeSeason": 2,
        "episodeNumber": 7,
        "isDeleted": False,
    }
    payload.update(overrides)
    return payload


class CatalogFixtureMixin:
    """One show, one stored episode, and an importer wired to a real user.

    A mixin rather than a base test class: the convergence and counter cases
    below need the same fixture, and inheriting from a TestCase would re-run
    every one of this file's assertions under each of their names.
    """

    def setUp(self):
        """Build the stored catalog the freshness check reads."""
        super().setUp()
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="catalogtester",
            password="pass",  # test-only credential
        )
        PocketCastsAccount.objects.create(user=self.user, access_token="token")
        self.importer = PocketCastsImporter(self.user, "new")
        self.show = PodcastShow.objects.create(podcast_uuid="show-1", title="Show")
        self.episode = PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="uuid-1",
            title="Episode One",
            slug="episode-one",
            published=PUBLISHED,
            duration=1800,
            audio_url="https://example.com/1.mp3",
            episode_number=7,
            season_number=2,
            file_type="audio/mpeg",
            episode_type="full",
            is_deleted=False,
        )

    def _index(self):
        return self.importer._load_catalog_index(self.show)


class PocketCastsCatalogFreshnessTests(CatalogFixtureMixin, TestCase):

    def _sync_writes_something(self, payload):
        """Run the real sync and report whether it changed the stored row."""
        before = PodcastEpisode.objects.filter(pk=self.episode.pk).values().first()
        count_before = PodcastEpisode.objects.count()
        self.importer._sync_catalog_episode(payload, show=self.show)
        after = PodcastEpisode.objects.filter(pk=self.episode.pk).values().first()
        return before != after or PodcastEpisode.objects.count() != count_before

    def test_identical_payload_is_unchanged(self):
        self.assertTrue(
            self.importer._catalog_episode_unchanged(_catalog_payload(), self._index()),
        )

    def test_unknown_episode_is_never_skipped(self):
        payload = _catalog_payload(uuid="uuid-brand-new")
        self.assertFalse(
            self.importer._catalog_episode_unchanged(payload, self._index()),
        )

    def test_reading_the_index_costs_one_query_per_show(self):
        for index in range(50):
            PodcastEpisode.objects.create(
                show=self.show,
                episode_uuid=f"bulk-{index}",
                title=f"Bulk {index}",
            )

        with self.assertNumQueries(1):
            catalog_index = self.importer._load_catalog_index(self.show)
        self.assertEqual(len(catalog_index), 51)

    def test_skipping_an_unchanged_episode_costs_no_queries(self):
        """The whole point: a settled catalog does no per-episode database work."""
        catalog_index = self._index()
        payload = _catalog_payload()

        with self.assertNumQueries(0):
            self.assertTrue(
                self.importer._catalog_episode_unchanged(payload, catalog_index),
            )

    def test_skip_and_sync_agree_field_by_field(self):
        """A skip must mean the sync would write nothing, for every field."""
        changes = {
            "title": "Episode One (Rebroadcast)",
            "slug": "episode-one-rebroadcast",
            "duration": 2400,
            "url": "https://example.com/1-remastered.mp3",
            "episodeNumber": 8,
            "episodeSeason": 3,
            "fileType": "audio/aac",
            "episodeType": "trailer",
            "isDeleted": True,
            "published": int(datetime(2025, 2, 1, tzinfo=UTC).timestamp()),
        }

        for key, value in changes.items():
            with self.subTest(field=key):
                payload = _catalog_payload(**{key: value})
                unchanged = self.importer._catalog_episode_unchanged(
                    payload,
                    self._index(),
                )
                self.assertFalse(
                    unchanged,
                    f"{key} changed but the episode was reported unchanged",
                )
                self.assertTrue(
                    self._sync_writes_something(payload),
                    f"{key} was reported changed but the sync wrote nothing",
                )
                # Put it back for the next field.
                self.importer._sync_catalog_episode(_catalog_payload(), show=self.show)
                self.episode.refresh_from_db()

    def test_a_skip_really_would_have_been_a_no_op(self):
        payload = _catalog_payload()
        self.assertTrue(
            self.importer._catalog_episode_unchanged(payload, self._index()),
        )
        self.assertFalse(self._sync_writes_something(payload))

    def test_blank_incoming_values_do_not_count_as_changes(self):
        """The sync never overwrites a stored value with a blank one."""
        payload = _catalog_payload(title="", url="", duration=0)
        self.assertTrue(
            self.importer._catalog_episode_unchanged(payload, self._index()),
        )
        self.assertFalse(self._sync_writes_something(payload))

    def test_unparseable_published_is_not_a_change(self):
        payload = _catalog_payload(published="not a date")
        self.assertTrue(
            self.importer._catalog_episode_unchanged(payload, self._index()),
        )
        self.assertFalse(self._sync_writes_something(payload))

    def test_negative_episode_numbers_are_not_a_change(self):
        """Provider sentinels coerce to unknown and must not force a write."""
        payload = _catalog_payload(episodeNumber=-1, episodeSeason=-1)
        self.assertTrue(
            self.importer._catalog_episode_unchanged(payload, self._index()),
        )
        self.assertFalse(self._sync_writes_something(payload))


class PocketCastsRepeatPollTests(TestCase):
    """An unchanged catalog must get cheaper on the second poll, end to end."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="pollster",
            password="pass",  # test-only credential
        )
        PocketCastsAccount.objects.create(user=self.user, access_token="token")

        self.podcast_list = {
            "podcasts": [
                {
                    "uuid": "show-1",
                    "title": "Test Show",
                    "author": "Test Author",
                    "description": "",
                    "url": "",
                },
            ],
        }
        self.metadata = {
            f"uuid-{index}": {
                "uuid": f"uuid-{index}",
                "title": f"Episode {index}",
                "published": PUBLISHED.isoformat(),
                "duration": 1800,
                "url": f"https://example.com/{index}.mp3",
            }
            for index in range(40)
        }

    def _artwork_patches(self):
        stack = ExitStack()
        stack.enter_context(
            patch(
                "integrations.pocketcasts_artwork.fetch_podcast_artwork_and_rss",
                return_value=(None, None),
            ),
        )
        stack.enter_context(
            patch(
                "integrations.pocketcasts_artwork.fetch_podcast_artwork",
                return_value=None,
            ),
        )
        return stack

    def _run_import(self, play_states=None):
        with (
            self._artwork_patches(),
            patch.object(PocketCastsImporter, "_ensure_valid_token"),
            patch.object(PocketCastsImporter, "_get_access_token", return_value="fake"),
            patch(
                "integrations.pocketcasts_api.get_podcast_list",
                return_value=self.podcast_list,
            ),
            patch.object(
                PocketCastsImporter,
                "_fetch_show_play_states",
                return_value=play_states or {},
            ),
            patch.object(
                PocketCastsImporter,
                "_fetch_show_full_metadata",
                return_value=self.metadata,
            ),
            CaptureQueriesContext(connection) as queries,
        ):
            importer = PocketCastsImporter(self.user, "new")
            importer.import_data()
        self.last_counters = importer._catalog_counters
        return len(queries)

    def test_listened_episodes_with_their_own_duration_stop_being_rewritten(self):
        """The user's play state differs from the public feed; polls must settle.

        Production (2026-09-29): eight recurring runs that imported nothing
        each reported ~5,300 episodes changed and ~4,300 rows written. The
        catalog pass wrote the feed's duration and isDeleted, then the
        listened-episode pass wrote the play state's over it, so the next poll
        saw the difference again.
        """
        play_states = {
            f"uuid-{index}": {
                "uuid": f"uuid-{index}",
                "playingStatus": 3,
                "playedUpTo": 1795,
                "duration": 1797,
                "isDeleted": True,
            }
            for index in range(10)
        }

        self._run_import(play_states)
        self._run_import(play_states)

        self.assertEqual(self.last_counters["changed"], 0)
        self.assertEqual(self.last_counters["written"], 0)
        stored = PodcastEpisode.objects.get(episode_uuid="uuid-0")
        self.assertEqual(stored.duration, 1797)
        self.assertTrue(stored.is_deleted)
        self.assertEqual(PodcastEpisode.objects.get(episode_uuid="uuid-20").duration, 1800)

    def test_second_poll_of_an_unchanged_catalog_is_far_cheaper(self):
        first = self._run_import()
        second = self._run_import()

        self.assertEqual(PodcastEpisode.objects.count(), 40)
        # The second poll reads the catalog once and writes nothing. The exact
        # numbers are not the contract - the collapse is.
        self.assertLess(second * 4, first)


class PocketCastsCatalogConvergenceTests(CatalogFixtureMixin, TestCase):
    """A poll that writes must leave the next poll with nothing to write.

    The freshness tests above all pass native Python types, so they cannot see
    the failure this class is about: the freshness check compared the raw
    provider value against a stored one the database had already coerced. Any
    representation the provider does not send as a plain int then differs
    forever -- write, normalise, differ, write -- and a no-op poll reports
    thousands of episodes "synced" while importing nothing.
    """

    def _poll(self, payload):
        """Run one poll and report whether it decided the episode changed."""
        unchanged = self.importer._catalog_episode_unchanged(payload, self._index())
        if not unchanged:
            self.importer._sync_catalog_episode(payload, show=self.show)
        return not unchanged

    def test_a_string_duration_converges_after_at_most_one_write(self):
        """"1800" must not be a difference from a stored 1800, forever."""
        payload = _catalog_payload(duration="1800")

        self.assertFalse(
            self._poll(payload),
            "a duration differing only in representation is not a change",
        )
        self.assertFalse(self._poll(payload))

    def test_a_float_duration_converges(self):
        """A provider sending 1800.0 must also settle."""
        payload = _catalog_payload(duration=1800.0)

        self.assertFalse(self._poll(payload))
        self.assertFalse(self._poll(payload))

    def test_a_fractional_duration_converges_on_the_stored_value(self):
        """int() truncation is what the column does; the check must agree."""
        payload = _catalog_payload(duration=1800.7)

        self.assertFalse(self._poll(payload))
        self.assertFalse(self._poll(payload))

    def test_a_genuinely_new_duration_is_still_written_once(self):
        """Convergence must not be bought by ignoring real changes."""
        payload = _catalog_payload(duration="2400")

        self.assertTrue(self._poll(payload), "a new duration is a change")
        self.episode.refresh_from_db()
        self.assertEqual(self.episode.duration, 2400)
        self.assertFalse(self._poll(payload), "and only a change once")

    def test_an_unparsable_duration_is_not_a_change(self):
        """A value the column could never hold must not trigger a rewrite."""
        payload = _catalog_payload(duration="not a number")

        self.assertFalse(self._poll(payload))
        self.assertFalse(self._poll(payload))


class PocketCastsCatalogCounterTests(CatalogFixtureMixin, TestCase):
    """The run's log line must distinguish inspected work from written work."""

    def test_an_unchanged_episode_counts_as_examined_and_unchanged_only(self):
        """No hydration, no write: that is what the skip path is for."""
        self.importer._catalog_counters = None
        self.importer._count("examined")
        unchanged = self.importer._catalog_episode_unchanged(
            _catalog_payload(),
            self._index(),
        )
        if unchanged:
            self.importer._count("unchanged")

        counters = self.importer._catalog_counters
        self.assertEqual(counters["examined"], 1)
        self.assertEqual(counters["unchanged"], 1)
        self.assertEqual(counters["changed"], 0)
        self.assertEqual(counters["hydrated"], 0)
        self.assertEqual(counters["written"], 0)

    def test_a_changed_episode_counts_a_hydration_and_a_write(self):
        """The expensive path is the one that must be visible in the log."""
        self.importer._catalog_counters = None
        self.importer._sync_catalog_episode(
            _catalog_payload(title="A New Title"),
            show=self.show,
        )

        counters = self.importer._catalog_counters
        self.assertEqual(counters["hydrated"], 1)
        self.assertEqual(counters["written"], 1)
        self.assertEqual(counters["created"], 0)

    def test_a_new_episode_counts_as_created_and_written(self):
        """A create is a write, and is reported as both."""
        self.importer._catalog_counters = None
        # A distinct number and date as well as a distinct uuid: the sync
        # deliberately matches an unknown uuid back to an existing row by
        # title, or by number+date, before it creates anything.
        self.importer._sync_catalog_episode(
            _catalog_payload(
                uuid="uuid-new",
                title="Brand New",
                episodeNumber=99,
                published=int(datetime(2025, 6, 1, tzinfo=UTC).timestamp()),
            ),
            show=self.show,
        )

        counters = self.importer._catalog_counters
        self.assertEqual(counters["created"], 1)
        self.assertEqual(counters["written"], 1)

    def test_a_write_free_sync_is_visible_as_changed_without_written(self):
        """changed>0 with written=0 is the signature of a rewrite loop.

        The counters have to be able to show it, or the next production run
        answers the same question no better than "synced=5237" did.
        """
        self.importer._catalog_counters = None
        self.importer._count("changed")
        self.importer._sync_catalog_episode(_catalog_payload(), show=self.show)

        counters = self.importer._catalog_counters
        self.assertEqual(counters["changed"], 1)
        self.assertEqual(counters["hydrated"], 1)
        self.assertEqual(counters["written"], 0)


class DuplicateCleanupScanTests(CatalogFixtureMixin, TestCase):
    """The end-of-run duplicate sweep must scale with duplicates, not catalog.

    It runs after every recurring poll. Hydrating every PodcastEpisode, with
    its show, to discover that a settled catalog has no duplicates is the
    whole catalog's worth of model instances allocated for nothing.
    """

    def _bulk_episodes(self, count):
        """Add `count` distinct episodes to the fixture's show."""
        PodcastEpisode.objects.bulk_create(
            [
                PodcastEpisode(
                    show=self.show,
                    episode_uuid=f"bulk-{index}",
                    title=f"Bulk {index}",
                    published=datetime(2025, 3, 1, tzinfo=UTC),
                    episode_number=1000 + index,
                )
                for index in range(count)
            ],
        )

    def test_a_catalog_with_no_duplicates_hydrates_nothing(self):
        """The common case: a settled library, and no models built at all."""
        self._bulk_episodes(40)

        with patch.object(
            PodcastEpisode,
            "__init__",
            autospec=True,
            side_effect=PodcastEpisode.__init__,
        ) as constructed:
            stats = _cleanup_duplicate_episodes_global()

        self.assertEqual(stats["duplicates_removed"], 0)
        self.assertEqual(constructed.call_count, 0)

    def test_only_the_duplicate_group_is_hydrated(self):
        """Two rows that really do collide are the only ones worth a model."""
        self._bulk_episodes(40)
        PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="uuid-1-duplicate",
            title="Episode One",
            published=PUBLISHED,
            episode_number=7,
            duration=1800,
        )

        with patch.object(
            PodcastEpisode,
            "__init__",
            autospec=True,
            side_effect=PodcastEpisode.__init__,
        ) as constructed:
            _cleanup_duplicate_episodes_global()

        # The two colliding rows, and nothing from the other forty-one.
        self.assertEqual(constructed.call_count, 2)

    def test_the_duplicate_is_still_merged(self):
        """Bounding the scan must not stop the sweep doing its job."""
        PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="uuid-1-duplicate",
            title="Episode One",
            published=PUBLISHED,
            episode_number=7,
            duration=1800,
        )

        stats = _cleanup_duplicate_episodes_global()

        self.assertEqual(stats["duplicates_removed"], 1)
        self.assertEqual(
            PodcastEpisode.objects.filter(title="Episode One").count(),
            1,
        )


class PocketCastsAliasedCatalogTests(PocketCastsRepeatPollTests):
    """TASKS-19: provider UUIDs that differ from the stored canonical UUID.

    Production (2026-10-25): two no-media recurring imports each reported
    4,570 index misses, zero creations and ~30,000 queries, every run. The
    sync resolves those episodes onto existing rows by title/date and writes
    nothing, but it re-ran that discovery per episode on every poll.
    """

    COUNT = 60
    # Inherited from the plain-catalog fixture; not meaningful with aliases.
    test_listened_episodes_with_their_own_duration_stop_being_rewritten = None
    test_second_poll_of_an_unchanged_catalog_is_far_cheaper = None

    def setUp(self):
        super().setUp()
        from app.models import Item, MediaTypes, Sources

        show = PodcastShow.objects.create(podcast_uuid="show-1", title="Test Show")
        self.metadata = {}
        for index in range(self.COUNT):
            title = f"Episode {index}"
            published = datetime(2025, 1, 1 + index % 28, 8, index % 60, tzinfo=UTC)
            self.metadata[f"provider-{index}"] = {
                "uuid": f"provider-{index}",
                "title": title,
                "published": published.isoformat(),
                "duration": 1800,
                "url": f"https://example.com/{index}.mp3",
            }
            PodcastEpisode.objects.create(
                show=show,
                episode_uuid=f"canonical-{index}",
                title=title,
                published=published,
                duration=1800,
                audio_url=f"https://example.com/{index}.mp3",
            )
            Item.objects.create(
                media_id=f"canonical-{index}",
                source=Sources.POCKETCASTS.value,
                media_type=MediaTypes.PODCAST.value,
                title=title,
            )

    def test_repeat_poll_of_aliased_episodes_does_no_per_episode_work(self):
        with patch.object(PocketCastsImporter, "_catalog_alias_row", return_value=None):
            before = self._run_import()
        before_counters = dict(self.last_counters)

        after = self._run_import()

        self.assertEqual(before_counters["differs_index_miss"], self.COUNT)
        self.assertEqual(self.last_counters["alias_matched"], self.COUNT)
        self.assertEqual(self.last_counters.get("differs_index_miss", 0), 0)
        self.assertEqual(self.last_counters["written"], 0)
        self.assertEqual(PodcastEpisode.objects.count(), self.COUNT)
        self.assertEqual(
            set(PodcastEpisode.objects.values_list("episode_uuid", flat=True)),
            {f"canonical-{i}" for i in range(self.COUNT)},
        )
        # Per-episode discovery was ~5 queries each; now it is a fixed few.
        self.assertLess(after * 5, before)
        self.assertLess(after, 40)

    def test_a_changed_aliased_episode_is_still_written(self):
        self._run_import()
        self.metadata["provider-3"]["duration"] = 2222
        self._run_import()
        self.assertEqual(
            PodcastEpisode.objects.get(episode_uuid="canonical-3").duration, 2222
        )

    def test_a_new_episode_is_still_created(self):
        self._run_import()
        self.metadata["provider-new"] = {
            "uuid": "provider-new",
            "title": "Brand New",
            "published": PUBLISHED.isoformat(),
            "duration": 60,
            "url": "https://example.com/new.mp3",
        }
        self._run_import()
        self.assertTrue(PodcastEpisode.objects.filter(episode_uuid="provider-new").exists())

    def test_untracked_alias_is_left_to_the_full_sync(self):
        from app.models import Item

        Item.objects.filter(media_id="canonical-0").delete()
        self._run_import()
        # The sync adopts the provider UUID for untracked episodes.
        self.assertTrue(PodcastEpisode.objects.filter(episode_uuid="provider-0").exists())
        self.assertEqual(self.last_counters["differs_index_miss"], 1)

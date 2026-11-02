from django.test import SimpleTestCase

from integrations import stremio_events


class ParsePlayerExtraTests(SimpleTestCase):
    def test_start_converts_milliseconds_to_seconds(self):
        """Stremio sends ms; Floppy stores seconds."""
        event = stremio_events.parse_player_extra(
            "action=start&currentTime=123456&duration=5400000",
        )

        self.assertEqual(event.action, "start")
        self.assertEqual(event.position_seconds, 123)
        self.assertEqual(event.duration_seconds, 5400)

    def test_pause_converts_milliseconds_to_seconds(self):
        """A second action, `pause`, converts ms to seconds the same way."""
        event = stremio_events.parse_player_extra(
            "action=pause&currentTime=600000&duration=2700000",
        )

        self.assertEqual(event.action, "pause")
        self.assertEqual(event.position_seconds, 600)

    def test_missing_duration_is_none_not_zero(self):
        event = stremio_events.parse_player_extra("action=stop&currentTime=5000")

        self.assertEqual(event.position_seconds, 5)
        self.assertIsNone(event.duration_seconds)

    def test_unknown_action_is_rejected(self):
        self.assertIsNone(stremio_events.parse_player_extra("action=seek&currentTime=1"))

    def test_missing_action_is_rejected(self):
        self.assertIsNone(stremio_events.parse_player_extra("currentTime=1000"))

    def test_non_numeric_current_time_is_rejected(self):
        self.assertIsNone(
            stremio_events.parse_player_extra("action=start&currentTime=abc"),
        )

    def test_empty_extra_is_rejected(self):
        self.assertIsNone(stremio_events.parse_player_extra(""))
        self.assertIsNone(stremio_events.parse_player_extra(None))

    def test_extra_parameters_do_not_shift_parsing(self):
        """Parsing is by name, so an unknown key must not break the known ones."""
        event = stremio_events.parse_player_extra(
            "foo=bar&action=start&currentTime=2000&duration=4000&baz=1",
        )

        self.assertEqual(event.position_seconds, 2)
        self.assertEqual(event.duration_seconds, 4)


class ParseLibraryExtraTests(SimpleTestCase):
    def test_watched_without_video_id_is_item_level(self):
        event = stremio_events.parse_library_extra("action=watched")

        self.assertEqual(event.action, "watched")
        self.assertEqual(event.video_ids, ())

    def test_video_id_batch_splits_on_comma(self):
        """Library events batch up to 100 video ids in one request."""
        event = stremio_events.parse_library_extra(
            "action=unwatched&videoId=tt1%3A1%3A2%2Ctt1%3A1%3A3%2Ctt1%3A1%3A4",
        )

        self.assertEqual(
            event.video_ids,
            ("tt1:1:2", "tt1:1:3", "tt1:1:4"),
        )

    def test_single_video_id(self):
        event = stremio_events.parse_library_extra(
            "action=watched&videoId=tt1%3A2%3A5",
        )

        self.assertEqual(event.video_ids, ("tt1:2:5",))

    def test_library_add_has_no_video_id(self):
        event = stremio_events.parse_library_extra("action=libraryAdd")

        self.assertEqual(event.action, "libraryAdd")
        self.assertEqual(event.video_ids, ())

    def test_unknown_action_is_rejected(self):
        self.assertIsNone(stremio_events.parse_library_extra("action=renamed"))

    def test_empty_extra_is_rejected(self):
        self.assertIsNone(stremio_events.parse_library_extra(""))
        self.assertIsNone(stremio_events.parse_library_extra(None))

    def test_blank_batch_entries_are_dropped(self):
        event = stremio_events.parse_library_extra("action=watched&videoId=tt1%3A1%3A2%2C")

        self.assertEqual(event.video_ids, ("tt1:1:2",))


class SharedConversionTests(SimpleTestCase):
    """The one millisecond conversion and the one episode-id parser.

    Every Stremio source reports milliseconds and `tt123:season:episode`
    coordinates, and the addon routes, the tracker, the poller, and the
    importer all route through these — a divergent copy shows up as positions
    off by 1000x, or an episode resolving to the wrong item.
    """

    def test_milliseconds_convert_and_clamp_at_zero(self):
        self.assertEqual(stremio_events.milliseconds_to_seconds(1500), 1)
        self.assertEqual(stremio_events.milliseconds_to_seconds(-5000), 0)

    def test_unusable_milliseconds_are_none_not_zero(self):
        """None means "no value"; 0 would overwrite a real position."""
        self.assertIsNone(stremio_events.milliseconds_to_seconds(None))
        self.assertIsNone(stremio_events.milliseconds_to_seconds(""))
        self.assertIsNone(stremio_events.milliseconds_to_seconds("junk"))

    def test_episode_id_parses_series_season_and_episode(self):
        self.assertEqual(
            stremio_events.parse_episode_id("tt123:2:5"),
            ("tt123", 2, 5),
        )

    def test_episode_id_rejects_anything_but_three_numeric_parts(self):
        for video_id in ("tt123", "tt123:1", "tt123:1:2:3", "tt123:x:2", None, ""):
            with self.subTest(video_id=video_id):
                self.assertIsNone(stremio_events.parse_episode_id(video_id))

    def test_the_importer_view_of_an_episode_id_is_the_same_parse(self):
        """`parse_video_id` drops the series id; it does not parse again."""
        from integrations.imports.stremio import parse_video_id

        self.assertEqual(
            parse_video_id("tt123:2:5"),
            stremio_events.parse_episode_id("tt123:2:5")[1:],
        )
        self.assertIsNone(parse_video_id("tt123"))

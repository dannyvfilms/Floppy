# FORK: library page endpoints (filter options, select-all ids, bulk actions).
from http import HTTPStatus as HTTP  # noqa: N814

from django.urls import reverse

from app.models import Game, Item, ItemTag, Movie, Status, Tag
from lists.models import CustomList, CustomListItem

from .base import FloppyApiTestCase


class LibraryEndpointsBase(FloppyApiTestCase):
    """Give the movies some metadata the filter menu can list."""

    def setUp(self):
        """Tag genres and a source on the seeded movies."""
        super().setUp()
        self.movies = self.items_by_type["movie"]
        self.movies[0].genres = ["Drama", "Crime"]
        self.movies[0].save(update_fields=["genres"])
        self.movies[1].genres = ["Drama"]
        self.movies[1].save(update_fields=["genres"])

    def get(self, name, *args, query=None, headers=None):
        """GET a named route as user1 by default."""
        return self.client.get(
            reverse(name, args=args),
            query or {},
            **(headers if headers is not None else self.auth_headers),
        )

    def post(self, name, body, *args, headers=None):
        """POST JSON to a named route as user1 by default."""
        return self.client.post(
            reverse(name, args=args),
            body,
            format="json",
            **(headers if headers is not None else self.auth_headers),
        )


class MediaListTagsTests(LibraryEndpointsBase):
    """GET /api/v1/media/<type>/ carries the viewer's tag names for the table."""

    def test_rows_list_only_the_viewers_tags(self):
        """Tags are sorted by name, per item, and another account's tags stay out."""
        mine = Tag.objects.create(user=self.user1, name="Zeta")
        first = Tag.objects.create(user=self.user1, name="alpha")
        theirs = Tag.objects.create(user=self.user2, name="Secret")
        for tag in (mine, first, theirs):
            ItemTag.objects.create(tag=tag, item=self.movies[0])
        response = self.client.get("/api/v1/media/movie/", **self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)
        rows = {row["id"]: row for row in response.json()["results"]}
        self.assertEqual(rows[self.movies[0].id]["tags"], ["alpha", "Zeta"])
        self.assertEqual(rows[self.movies[1].id]["tags"], [])


class SeparateEntryTests(LibraryEndpointsBase):
    """Separate-entry pages filter individual plays without leaking other users."""

    def test_entries_page_and_rating_filter_use_individual_rows(self):
        """A repeat stays separate, including when it falls on the next page."""
        Movie.objects.filter(user=self.user1, item=self.movies[0]).update(score=3)
        repeat = Movie.objects.create(user=self.user1, item=self.movies[0], score=9, status=Status.COMPLETED.value)
        Movie.objects.create(user=self.user2, item=self.movies[0], score=10, status=Status.COMPLETED.value)
        response = self.client.get("/api/v1/media/movie/", {"separate_entries": "1", "rating_min": "8", "sort": "score", "limit": 1}, **self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)
        row = response.json()["results"][0]
        self.assertEqual(row["entry_id"], repeat.pk)
        self.assertEqual(float(row["score"]), 9)
        response = self.client.get("/api/v1/media/movie/", {"separate_entries": "1", "search": self.movies[0].title, "limit": 1}, **self.auth_headers)
        self.assertEqual(response.json()["pagination"]["total"], 2)
        first = response.json()["results"][0]["entry_id"]
        second = self.client.get("/api/v1/media/movie/", {"separate_entries": "1", "search": self.movies[0].title, "limit": 1, "offset": 1}, **self.auth_headers).json()["results"][0]["entry_id"]
        self.assertNotEqual(first, second)

    def test_preference_and_invalid_modes(self):
        """The toggle is persisted only for supported types and boolean inputs."""
        url = "/api/v1/library/preferences/movie/"
        response = self.client.patch(url, {"separateEntries": True}, format="json", **self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertTrue(self.client.get(url, **self.auth_headers).json()["separateEntries"])
        self.assertEqual(self.client.patch(url, {"separateEntries": "false"}, format="json", **self.auth_headers).status_code, HTTP.BAD_REQUEST)
        self.assertEqual(self.client.get("/api/v1/media/tv/", {"separate_entries": "1"}, **self.auth_headers).status_code, HTTP.BAD_REQUEST)

    def test_status_and_rating_must_match_the_same_entry(self):
        """An old high-rated play must not qualify a different current row."""
        Movie.objects.filter(user=self.user1, item=self.movies[0]).update(score=9, status=Status.COMPLETED.value)
        Movie.objects.create(user=self.user1, item=self.movies[0], score=2, status=Status.PLANNING.value)
        response = self.client.get("/api/v1/media/movie/", {
            "separate_entries": "1", "status": "planning", "rating_min": "8", "search": self.movies[0].title,
        }, **self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["pagination"]["total"], 0)


class GameGroupTests(LibraryEndpointsBase):
    """Game grouping stays user-scoped, filtered, and paginated in SQL."""

    def test_group_sort_ties_match_web_and_unrated_groups_stay_alphabetical(self):
        """Descending ratings reverse rated name ties, never the unrated tail."""
        for index, (name, score) in enumerate((("alpha", 8), ("Zeta", 8), ("Beta", 9), ("amber", None), ("Zulu", None))):
            item = Item.objects.create(
                source="manual", media_type="game", media_id=f"group-order-{index}", title=name,
                provider_collection_id=f"group-order-{index}", provider_collection_name=name,
            )
            Game.objects.create(user=self.user1, item=item, score=score, progress=0, status=Status.PLANNING.value)
        for direction, expected in (("desc", ["Beta", "Zeta", "alpha", "amber", "Zulu"]),
                                    ("asc", ["alpha", "Zeta", "Beta", "amber", "Zulu"])):
            response = self.client.get("/api/v1/library/game-groups/", {
                "group_by": "series", "sort": "score", "direction": direction, "limit": 5,
            }, **self.auth_headers)
            self.assertEqual(response.status_code, HTTP.OK, response.content)
            self.assertEqual([row["group"]["name"] for row in response.json()["results"]], expected)

    def test_group_overview_and_drilldown_preserve_scope(self):
        """Two owned games form one card; the other user's games stay out."""
        games = self.items_by_type["game"]
        for item in games[:2]:
            item.provider_collection_id = "42"
            item.provider_collection_name = "Shared Series"
            item.save(update_fields=["provider_collection_id", "provider_collection_name"])
        response = self.client.get("/api/v1/library/game-groups/", {"group_by": "series", "sort": "score", "direction": "desc", "limit": 1}, **self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)
        group = response.json()["results"][0]["group"]
        self.assertEqual(group["group_key"], "id:42")
        self.assertEqual(group["name"], "Shared Series")
        self.assertEqual(group["game_count"], 2)
        self.assertEqual(group["card"]["image"]["src"], games[0].image)
        response = self.client.get("/api/v1/media/game/", {"group_by": "series", "group": "id:42"}, **self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual({row["id"] for row in response.json()["results"]}, {item.pk for item in games[:2]})
        response = self.client.get("/api/v1/media/game/", {"group_by": "series", "group": "id:42", "sort": "score", "direction": "desc"}, **self.auth_headers)
        self.assertEqual([row["id"] for row in response.json()["results"]], [item.pk for item in games[:2]])

    def test_bad_group_mode_is_rejected(self):
        """An unsupported grouping is a validation error."""
        response = self.client.get("/api/v1/library/game-groups/", {"group_by": "nope"}, **self.auth_headers)
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class FilterOptionsTests(LibraryEndpointsBase):
    """GET /api/v1/media/<type>/filter-options/."""

    def test_lists_genres_sources_and_tags(self):
        """Options come from the user's own movies, with tag counts."""
        tag = Tag.objects.create(user=self.user1, name="Favourites")
        ItemTag.objects.create(tag=tag, item=self.movies[0])
        response = self.get("api_library_filter_options", "movie")
        self.assertEqual(response.status_code, HTTP.OK)
        data = response.json()
        self.assertEqual(data["genres"], ["Crime", "Drama"])
        self.assertEqual(data["sources"][0]["value"], "tmdb")
        self.assertEqual(data["tags"], [{"id": tag.id, "name": "Favourites", "count": 1}])
        self.assertTrue(data["show_languages"])
        self.assertFalse(data["show_platforms"])

    def test_other_users_tags_and_items_are_not_listed(self):
        """Another account's tags never appear."""
        Tag.objects.create(user=self.user2, name="Secret")
        data = self.get("api_library_filter_options", "movie").json()
        self.assertEqual(data["tags"], [])

    def test_status_filter_narrows_the_menu(self):
        """The menu is read after the status filter, like the web menu."""
        Movie.objects.filter(item=self.movies[1]).update(status=Status.IN_PROGRESS.value)
        data = self.get(
            "api_library_filter_options", "movie", query={"status": "in_progress"},
        ).json()
        self.assertEqual(data["genres"], ["Drama"])

    def test_invalid_type_and_filter_are_rejected(self):
        """Bad input is a 400, not a 500."""
        self.assertEqual(
            self.get("api_library_filter_options", "nope").status_code, HTTP.BAD_REQUEST,
        )
        self.assertEqual(
            self.get(
                "api_library_filter_options", "movie", query={"rating_min": "x"},
            ).status_code,
            HTTP.BAD_REQUEST,
        )

    def test_requires_authentication(self):
        """Anonymous and bad tokens are refused."""
        response = self.get(
            "api_library_filter_options", "movie", headers=self.invalid_auth_headers,
        )
        self.assertIn(response.status_code, (HTTP.UNAUTHORIZED, HTTP.FORBIDDEN))

    def test_game_options_flag_platforms(self):
        """Per-type flags follow the web view."""
        data = self.get("api_library_filter_options", "game").json()
        self.assertTrue(data["show_platforms"])
        self.assertFalse(data["show_languages"])


class ItemIdsTests(LibraryEndpointsBase):
    """GET /api/v1/media/<type>/item-ids/."""

    def test_returns_every_matching_item_id(self):
        """Select all gets the ids behind the filters."""
        data = self.get("api_library_item_ids", "movie").json()
        self.assertEqual(data["item_ids"], sorted(item.id for item in self.movies))

    def test_respects_filters(self):
        """A status filter narrows the ids."""
        Movie.objects.filter(item=self.movies[0]).update(status=Status.IN_PROGRESS.value)
        data = self.get(
            "api_library_item_ids", "movie", query={"status": "in_progress"},
        ).json()
        self.assertEqual(data["item_ids"], [self.movies[0].id])


class BulkTests(LibraryEndpointsBase):
    """POST /api/v1/library/bulk/*."""

    def ids(self):
        """Item ids of the seeded movies."""
        return [item.id for item in self.movies]

    def test_status(self):
        """Status writes through the same handler as the web toolbar."""
        response = self.post(
            "api_library_bulk_status",
            {"item_ids": self.ids(), "status": Status.COMPLETED.value},
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.assertEqual(response.json()["updated"], 3)
        self.assertEqual(
            Movie.objects.filter(user=self.user1, status=Status.COMPLETED.value).count(),
            3,
        )

    def test_plays_forward_the_date_choices(self):
        """One date and a range reach the web option parser (it reads date, start_date, end_date)."""
        missing = self.post(
            "api_library_bulk_plays",
            {"item_ids": self.ids(), "scope": "aired", "existing": "skip", "date_mode": "one_date"},
        )
        self.assertEqual(missing.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(missing.json()["detail"], "Pick a date.")
        reversed_range = self.post(
            "api_library_bulk_plays",
            {"item_ids": self.ids(), "scope": "aired", "existing": "skip", "date_mode": "range",
             "start_date": "2024-02-01", "end_date": "2024-01-01"},
        )
        self.assertEqual(reversed_range.json()["detail"], "The start date must not be after the end date.")
        ok = self.post(
            "api_library_bulk_plays",
            {"item_ids": self.ids(), "scope": "seasons", "season_from": 1, "season_to": 2,
             "existing": "add", "date_mode": "one_date", "date": "2024-01-01", "dry_run": True},
        )
        self.assertEqual(ok.status_code, HTTP.OK, ok.content)
        self.assertTrue(ok.json()["operation_id"])

    def test_invalid_status_and_empty_selection(self):
        """Invalid status is a 400 and an empty selection fails validation."""
        bad = self.post(
            "api_library_bulk_status", {"item_ids": self.ids(), "status": "bogus"},
        )
        self.assertEqual(bad.status_code, HTTP.BAD_REQUEST)
        empty = self.post(
            "api_library_bulk_status", {"item_ids": [], "status": "completed"},
        )
        self.assertEqual(empty.status_code, HTTP.BAD_REQUEST)

    def test_collection(self):
        """Collection quick-add reports created entries."""
        response = self.post("api_library_bulk_collection", {"item_ids": self.ids()})
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.assertEqual(response.json()["created"], 3)

    def test_tags_add_and_remove(self):
        """Tags apply and clear by id, and only the user's own tag is usable."""
        tag = Tag.objects.create(user=self.user1, name="Keep")
        add = self.post(
            "api_library_bulk_tags",
            {"item_ids": self.ids(), "tag_id": tag.id, "action": "add"},
        )
        self.assertEqual(add.status_code, HTTP.OK, add.content)
        self.assertEqual(ItemTag.objects.filter(tag=tag).count(), 3)
        remove = self.post(
            "api_library_bulk_tags",
            {"item_ids": self.ids(), "tag_id": tag.id, "action": "remove"},
        )
        self.assertEqual(remove.status_code, HTTP.OK)
        self.assertEqual(ItemTag.objects.filter(tag=tag).count(), 0)
        foreign = Tag.objects.create(user=self.user2, name="Theirs")
        denied = self.post(
            "api_library_bulk_tags", {"item_ids": self.ids(), "tag_id": foreign.id},
        )
        self.assertEqual(denied.status_code, HTTP.NOT_FOUND)

    def test_list_add_and_permissions(self):
        """Items go into an editable list; another user's list is not found."""
        custom = CustomList.objects.create(name="Mine", owner=self.user1)
        response = self.post(
            "api_library_bulk_list", {"item_ids": self.ids(), "list_id": custom.id},
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.assertEqual(response.json()["added"], 3)
        self.assertEqual(CustomListItem.objects.filter(custom_list=custom).count(), 3)
        foreign = CustomList.objects.create(name="Theirs", owner=self.user2)
        denied = self.post(
            "api_library_bulk_list", {"item_ids": self.ids(), "list_id": foreign.id},
        )
        self.assertIn(denied.status_code, (HTTP.NOT_FOUND, HTTP.FORBIDDEN))

    def test_plays_status_of_unknown_operation(self):
        """An expired or foreign operation is a 404."""
        response = self.get("api_library_bulk_plays_status", "abc123")
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_bulk_requires_authentication(self):
        """Bulk writes need a valid token."""
        response = self.post(
            "api_library_bulk_status",
            {"item_ids": self.ids(), "status": "completed"},
            headers=self.invalid_auth_headers,
        )
        self.assertIn(response.status_code, (HTTP.UNAUTHORIZED, HTTP.FORBIDDEN))


class LibraryPreferencesAndViewsTests(FloppyApiTestCase):
    """Library preferences, saved views and share view mirror the web media list."""

    def setUp(self):
        """Sign in."""
        super().setUp()
        self.client.force_login(self.user1)

    def test_preferences_round_trip_layout_sort_and_columns(self):
        """PATCH stores what the web stores; GET reads it back with the column config."""
        url = "/api/v1/library/preferences/movie/"
        body = self.client.patch(
            url, {"layout": "table", "sort": "title", "direction": "asc", "statuses": ["Completed", "Paused"],
                  "columns": {"order": ["score"], "hidden": ["notes"]}},
            content_type="application/json",
        )
        self.assertEqual(body.status_code, HTTP.OK)
        data = self.client.get(url).json()
        self.assertEqual((data["layout"], data["sort"], data["direction"]), ("table", "title", "asc"))
        self.assertEqual(data["statuses"], ["Completed", "Paused"])
        hidden = {column["key"] for column in data["columns"] if not column["visible"]}
        self.assertIn("notes", hidden)
        self.assertTrue(data["defaultColumns"])

    def test_preferences_reject_unknown_media_type(self):
        """An unknown type is a 400."""
        self.assertEqual(self.client.get("/api/v1/library/preferences/nope/").status_code, HTTP.BAD_REQUEST)

    def test_preferences_reject_types_without_preference_fields(self):
        """Child media types cannot store library preferences or mutate columns."""
        original = self.user1.table_column_prefs
        for media_type in ("episode", "comicissue"):
            with self.subTest(media_type=media_type):
                response = self.client.patch(
                    f"/api/v1/library/preferences/{media_type}/",
                    {"layout": "table", "statuses": ["Completed"], "columns": {"hidden": ["score"]}},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.table_column_prefs, original)

    def test_saved_view_create_list_delete(self):
        """Create spells out all statuses, lists in preferences, and deletes."""
        created = self.client.post(
            "/api/v1/library/saved-views/",
            {"mediaType": "movie", "name": "Best", "query": {"sort": "score", "tag": "a,b", "limit": 30}},
            content_type="application/json",
        )
        self.assertEqual(created.status_code, HTTP.CREATED)
        query = created.json()["query"]
        self.assertIn("tag=a", query)
        self.assertIn("tag=b", query)
        self.assertIn("status=", query)
        self.assertNotIn("limit", query)
        listed = self.client.get("/api/v1/library/preferences/movie/").json()["savedViews"]
        self.assertEqual([view["name"] for view in listed], ["Best"])
        gone = self.client.delete(f"/api/v1/library/saved-views/{created.json()['id']}/")
        self.assertEqual(gone.status_code, HTTP.NO_CONTENT)

    def test_saved_view_requires_a_name(self):
        """A blank name is refused like the web."""
        response = self.client.post(
            "/api/v1/library/saved-views/", {"mediaType": "movie", "name": " "}, content_type="application/json",
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_share_view_returns_public_list_url(self):
        """Sharing snapshots the view as a public smart list."""
        response = self.client.post(
            "/api/v1/library/share-view/", {"mediaType": "movie", "query": {"sort": "score"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertIn("/list", response.json()["url"])

    def test_initial_filters_the_list(self):
        """The A to Z `initial` parameter narrows /media/ like the web rail."""
        total = lambda value: self.client.get(f"/api/v1/media/movie/?initial={value}").json()["pagination"]["total"]  # noqa: E731
        self.assertGreater(total("m"), 0)
        self.assertEqual(total("z"), 0)

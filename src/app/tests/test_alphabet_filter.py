"""Alphabet filters constrain complete result sets, independent of presentation."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app.library_query import FilterValues, LibraryQuery, LibraryQueryExecutor
from app.library_query.alphabet import (
    first_other_initial,
    initial_condition,
    normalize_initial,
)
from app.models import (
    TV,
    Album,
    AlbumTracker,
    Artist,
    ArtistTracker,
    Game,
    Item,
    Movie,
    PodcastShow,
    PodcastShowTracker,
    Sources,
    Status,
)
from lists.models import CustomList, CustomListItem


class AlphabetFilterTests(TestCase):
    """Exercise the engine, specialized trackers, list scopes and URL adapter."""

    def setUp(self):
        """Use isolated caches and a signed-in library owner."""
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="alphabet", password="test"
        )
        self.client.force_login(self.user)
        self.url = reverse("medialist", args=["movie"])

    def movie(self, title, **fields):
        """Create a tracked, provider-independent item."""
        item = Item.objects.create(
            media_id=str(Item.objects.count() + 1),
            source=Sources.MANUAL.value,
            media_type="movie",
            title=title,
            image="/cover.jpg",
            **fields,
        )
        Movie.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)
        return item

    def ids(self, response):
        """Return the library's displayed identities."""
        self.assertEqual(response.status_code, 200)
        return {entry.item.pk for entry in response.context["media_list"]}

    def test_buckets_and_invalid_values(self):
        """Unicode and symbols must not inherit database-specific ASCII folding."""
        entries = [
            self.movie(title)
            for title in (
                "alpha",
                "Apple",
                "The Matrix",
                "9 Lives",
                "Éclair",
                "東京",
                "!Bang",
                "",
                "\u212aelvin",
            )
        ]
        expected = {
            "A": entries[:2],
            "t": entries[2:3],
            "0-9": entries[3:4],
            "other": entries[4:],
        }
        for initial, items in expected.items():
            with self.subTest(initial=initial):
                query = LibraryQuery(
                    media_types=("movie",), filters=FilterValues(initial=initial)
                )
                engine = LibraryQueryExecutor(self.user, query)
                self.assertEqual(engine.count(), len(items))
                self.assertEqual(
                    {item.pk for item in engine.page(0, 32).items},
                    {item.pk for item in items},
                )
        for value in (None, "", "all", "ab", "\u212a", "É", "%' OR 1=1"):
            self.assertEqual(normalize_initial(value), "")
            self.assertEqual(
                Item.objects.filter(initial_condition(value, self.user)).count(),
                len(entries),
            )

    def test_numeric_order_and_representative_glyph_are_scoped(self):
        """The rail uses # before A and a real glyph from the matching library."""
        self.movie("9 Lives")
        self.movie("Alpha")
        symbol = self.movie("【Series")
        other_user = get_user_model().objects.create_user(username="private-symbol")
        private = Item.objects.create(
            media_id="private",
            source=Sources.MANUAL.value,
            media_type="movie",
            title="!Private",
        )
        Movie.objects.create(
            user=other_user, item=private, status=Status.COMPLETED.value
        )
        response = self.client.get(self.url)
        self.assertEqual(response.context["alphabet_other_initial"], "【")
        body = response.content.decode()
        self.assertLess(
            body.index('data-alphabet-initial="0-9"'),
            body.index('data-alphabet-initial="a"'),
        )
        self.assertIn(">#</span>", body)
        self.assertIn(">【</span>", body)
        self.assertEqual(
            self.ids(self.client.get(self.url, {"initial": "other"})), {symbol.pk}
        )
        self.assertEqual(
            first_other_initial(Item.objects.filter(pk=symbol.pk), self.user), "【"
        )

    def test_list_glyph_uses_membership_and_viewer_title_preference(self):
        """Do not borrow a symbol from another list or from an owner's title mode."""
        self.movie("!Outside")
        symbol = self.movie(
            "Fallback", localized_title="【Series", original_title="ΩSeries"
        )
        custom_list = CustomList.objects.create(name="Symbols", owner=self.user)
        CustomListItem.objects.create(custom_list=custom_list, item=symbol)
        url = reverse("list_detail", args=[custom_list.public_reference])
        self.assertEqual(self.client.get(url).context["alphabet_other_initial"], "【")
        self.user.title_display_preference = "original"
        self.user.save(update_fields=["title_display_preference"])
        self.assertEqual(self.client.get(url).context["alphabet_other_initial"], "Ω")

    def test_display_title_preference_and_fallback(self):
        """Filtering uses the same preferred title and blank fallback as cards."""
        original = self.movie(
            "Fallback", localized_title="Alpha", original_title="Beta"
        )
        fallback = self.movie("Apple", localized_title="  ", original_title="")
        self.assertEqual(
            self.ids(self.client.get(self.url, {"initial": "a"})),
            {original.pk, fallback.pk},
        )
        self.user.title_display_preference = "original"
        self.user.save(update_fields=["title_display_preference"])
        self.assertEqual(
            self.ids(self.client.get(self.url, {"initial": "b"})), {original.pk}
        )
        self.assertEqual(
            self.ids(self.client.get(self.url, {"initial": "a"})), {fallback.pk}
        )

    def test_filter_before_pagination_and_combined_search(self):
        """A title outside the unfiltered first page remains reachable by initial."""
        for index in range(34):
            self.movie(f"Alpha {index:02}")
        zebra = self.movie("Zebra")
        response = self.client.get(
            self.url, {"initial": "z", "search": "ebra", "layout": "table"}
        )
        self.assertEqual(self.ids(response), {zebra.pk})
        self.assertEqual(response.context["result_count"], 1)
        self.assertContains(response, 'name="initial" value="z" form="filter-form"')
        empty = self.client.get(self.url, {"initial": "q"})
        self.assertContains(empty, "No titles match this alphabet filter")
        self.assertContains(empty, "Clear alphabet filter")
        partial = self.client.get(
            self.url,
            {"initial": "q"},
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="media-grid",
        )
        self.assertContains(partial, "Clear alphabet filter")

    def test_separate_entries_cache_isolation(self):
        """The legacy cached order is distinct for every alphabet selection."""
        alpha, beta = self.movie("Alpha"), self.movie("Beta")
        self.user.movie_show_each_play = True
        self.user.save(update_fields=["movie_show_each_play"])
        for initial, expected in (
            ("a", {alpha.pk}),
            ("b", {beta.pk}),
            ("", {alpha.pk, beta.pk}),
            ("a", {alpha.pk}),
        ):
            self.assertEqual(
                self.ids(self.client.get(self.url, {"initial": initial})), expected
            )

    def test_artist_album_and_podcast_names(self):
        """Container views filter their own names rather than track/episode titles."""
        for name in ("Alpha", "Beta"):
            artist = Artist.objects.create(name=name, image="/cover.jpg")
            ArtistTracker.objects.create(user=self.user, artist=artist)
            album = Album.objects.create(title=name, artist=artist, image="/cover.jpg")
            AlbumTracker.objects.create(user=self.user, album=album)
            show = PodcastShow.objects.create(
                podcast_uuid=name, title=name, image="/cover.jpg"
            )
            PodcastShowTracker.objects.create(user=self.user, show=show)
        for media_type, subview in (
            ("music", "artists"),
            ("music", "albums"),
            ("podcast", ""),
        ):
            with self.subTest(subview=subview):
                response = self.client.get(
                    reverse("medialist", args=[media_type]),
                    {"initial": "b", "subview": subview},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.context["media_list"]), 1)
                self.assertEqual(response.context["result_count"], 1)

    def test_manual_and_smart_list_membership(self):
        """Filter manual/union members without modifying saved smart rules."""
        alpha, beta = self.movie("Alpha"), self.movie("Beta")
        manual = CustomList.objects.create(name="Manual", owner=self.user)
        for item in (alpha, beta):
            CustomListItem.objects.create(custom_list=manual, item=item)
        smart = CustomList.objects.create(
            name="Smart",
            owner=self.user,
            is_smart=True,
            smart_filters={
                "media_types": ["movie"],
                "search": "absent",
                "list": [str(manual.pk)],
            },
        )
        original_rules = smart.smart_filters.copy()
        for custom_list in (manual, smart):
            url = reverse("list_detail", args=[custom_list.public_reference])
            response = self.client.get(url, {"initial": "b"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual({item.pk for item in response.context["items"]}, {beta.pk})
            empty = self.client.get(url, {"initial": "q"})
            self.assertContains(empty, "Clear alphabet filter")
        smart.refresh_from_db()
        self.assertEqual(smart.smart_filters, original_rules)

    def test_game_groups_only_include_matching_titles(self):
        """Alphabet filtering must precede grouped-game aggregation."""
        for index, title in enumerate(("Alpha", "Beta")):
            item = Item.objects.create(
                media_id=str(index),
                source=Sources.IGDB.value,
                media_type="game",
                title=title,
                image="/cover.jpg",
                provider_franchise_id="10",
                provider_franchise_name="Shared",
            )
            Game.objects.create(
                item=item, user=self.user, status=Status.COMPLETED.value
            )
        response = self.client.get(
            reverse("medialist", args=["game"]),
            {"initial": "b", "group_by": "franchise"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sum(group["game_count"] for group in response.context["media_groups"]), 1
        )

    def test_time_left_cache_isolation(self):
        """TV's separately cached sorted order must respect the selected initial."""
        for title in ("Alpha", "Beta"):
            item = Item.objects.create(
                media_id=title,
                source=Sources.MANUAL.value,
                media_type="tv",
                title=title,
                image="/cover.jpg",
            )
            TV.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)
        url = reverse("medialist", args=["tv"])
        for initial, expected in (("a", {"Alpha"}), ("b", {"Beta"}), ("a", {"Alpha"})):
            response = self.client.get(url, {"initial": initial, "sort": "time_left"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                {entry.item.title for entry in response.context["media_list"]}, expected
            )

    def test_public_list_viewer_title_preference_and_permissions(self):
        """Alphabet filtering never broadens visibility or uses the owner's title preference."""
        item = self.movie("Fallback", localized_title="Alpha", original_title="Beta")
        custom_list = CustomList.objects.create(
            name="Shared", owner=self.user, visibility="public"
        )
        CustomListItem.objects.create(custom_list=custom_list, item=item)
        viewer = get_user_model().objects.create_user(
            username="viewer", title_display_preference="original"
        )
        self.client.force_login(viewer)
        url = reverse("list_detail", args=[custom_list.public_reference])
        response = self.client.get(url, {"initial": "b"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual({entry.pk for entry in response.context["items"]}, {item.pk})
        custom_list.visibility = "private"
        custom_list.save(update_fields=["visibility"])
        self.assertEqual(self.client.get(url, {"initial": "b"}).status_code, 404)
        custom_list.visibility = "public"
        custom_list.save(update_fields=["visibility"])
        self.client.logout()
        response = self.client.get(url, {"initial": "a"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual({entry.pk for entry in response.context["items"]}, {item.pk})

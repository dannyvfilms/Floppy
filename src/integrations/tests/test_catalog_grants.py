"""Revocable add-on install credentials for the published catalogs."""

from http import HTTPStatus as HTTP  # noqa: N814

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from integrations.models import CatalogGrant
from integrations.stremio_catalog import resolve_addon_credential


class CatalogGrantResolutionTests(TestCase):
    """A grant resolves to its user; the legacy account token still works."""

    def setUp(self):
        """Create a user with one grant."""
        self.user = get_user_model().objects.create_user(username="grants")
        self.grant, self.token = CatalogGrant.generate(self.user, "Living room")

    def test_a_grant_resolves_to_its_user(self):
        """The install URL credential identifies the account."""
        user, grant = resolve_addon_credential(self.token)

        self.assertEqual(user, self.user)
        self.assertEqual(grant, self.grant)

    def test_the_legacy_account_token_still_resolves(self):
        """Existing installs keep working through the deprecation."""
        user, grant = resolve_addon_credential(self.user.token)

        self.assertEqual(user, self.user)
        self.assertIsNone(grant)

    def test_a_revoked_grant_resolves_to_nothing(self):
        """Revoking one install must take effect immediately."""
        self.grant.revoked_at = self.grant.created_at
        self.grant.save(update_fields=["revoked_at"])

        self.assertEqual(resolve_addon_credential(self.token), (None, None))

    def test_an_unknown_token_resolves_to_nothing(self):
        """A guessed credential is not an account."""
        self.assertEqual(resolve_addon_credential("cat_nope"), (None, None))

    def test_an_empty_token_resolves_to_nothing(self):
        """An empty path segment must not match a blank account token."""
        self.assertEqual(resolve_addon_credential(""), (None, None))

    def test_the_secret_is_high_entropy_and_prefixed(self):
        """The credential sits in a URL, so entropy is the control."""
        self.assertTrue(self.token.startswith("cat_"))
        self.assertGreater(len(self.token), 30)


class CatalogGrantScopeTests(TestCase):
    """A grant reads only the catalogs it names."""

    def setUp(self):
        """Create a user."""
        self.user = get_user_model().objects.create_user(username="scope")

    def test_an_empty_allowlist_means_every_catalog(self):
        """The simple case stays simple."""
        grant, _ = CatalogGrant.generate(self.user, "All")

        self.assertTrue(grant.allows_catalog("floppy-watchlist-movies"))
        self.assertTrue(grant.allows_catalog("floppy-watchlist-series"))

    def test_a_populated_allowlist_excludes_the_rest(self):
        """Selecting one catalog does not publish the others."""
        grant, _ = CatalogGrant.generate(
            self.user,
            "Movies only",
            catalog_ids=["floppy-watchlist-movies"],
        )

        self.assertTrue(grant.allows_catalog("floppy-watchlist-movies"))
        self.assertFalse(grant.allows_catalog("floppy-watchlist-series"))


class AddonRouteTests(TestCase):
    """The published routes honour grants."""

    def setUp(self):
        """Create a user with a grant."""
        self.user = get_user_model().objects.create_user(username="routes")
        self.grant, self.token = CatalogGrant.generate(self.user, "Living room")

    def test_manifest_serves_a_grant(self):
        """A grant credential installs the addon."""
        response = self.client.get(
            reverse("stremio_addon_manifest", args=[self.token]),
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertIn("catalogs", response.json())

    def test_manifest_refuses_a_revoked_grant(self):
        """Revocation is enforced at the route, not just the UI."""
        self.grant.revoked_at = self.grant.created_at
        self.grant.save(update_fields=["revoked_at"])

        response = self.client.get(
            reverse("stremio_addon_manifest", args=[self.token]),
        )

        self.assertEqual(response.status_code, HTTP.UNAUTHORIZED)

    def test_manifest_limits_catalogs_to_the_grant(self):
        """An excluded catalog is not advertised."""
        scoped, token = CatalogGrant.generate(
            self.user,
            "Movies only",
            catalog_ids=["floppy-watchlist-movies"],
        )
        self.assertTrue(scoped.is_valid())

        response = self.client.get(
            reverse("stremio_addon_manifest", args=[token]),
        )

        ids = [entry["id"] for entry in response.json()["catalogs"]]
        self.assertEqual(ids, ["floppy-watchlist-movies"])

    def test_a_catalogs_only_grant_does_not_record_playback(self):
        """A grant minted without playback permission must not write."""
        scoped, token = CatalogGrant.generate(
            self.user,
            "Catalogs only",
            allow_playback_start=False,
        )
        self.assertFalse(scoped.allow_playback_start)

        response = self.client.get(
            reverse(
                "stremio_addon_subtitles",
                args=[token, "movie", "tt0133093"],
            ),
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["subtitles"], [])

    def test_use_is_recorded(self):
        """A grant that has never been used is visibly unused."""
        self.assertIsNone(self.grant.last_used_at)

        self.client.get(reverse("stremio_addon_manifest", args=[self.token]))

        self.grant.refresh_from_db()
        self.assertIsNotNone(self.grant.last_used_at)


class CatalogGrantLifecycleTests(TestCase):
    """Create and revoke from the settings page."""

    def setUp(self):
        """Log a user in."""
        self.user = get_user_model().objects.create_user(
            username="lifecycle",
            password="testpass123",
        )
        self.other = get_user_model().objects.create_user(username="other")
        self.client.force_login(self.user)

    def test_create_mints_a_grant(self):
        """The form creates a named install."""
        self.client.post(
            reverse("create_catalog_grant"),
            {"name": "Living room", "allow_playback_start": "on"},
            follow=True,
        )

        grant = CatalogGrant.objects.get(user=self.user)
        self.assertEqual(grant.name, "Living room")
        self.assertTrue(grant.allow_playback_start)

    def test_playback_permission_can_be_withheld(self):
        """An unticked box means catalogs only."""
        self.client.post(
            reverse("create_catalog_grant"),
            {"name": "Catalogs only"},
            follow=True,
        )

        self.assertFalse(CatalogGrant.objects.get(user=self.user).allow_playback_start)

    def test_a_grant_needs_a_name(self):
        """An unnamed install cannot be told apart from another."""
        response = self.client.post(
            reverse("create_catalog_grant"),
            {"name": "  "},
            follow=True,
        )

        self.assertFalse(CatalogGrant.objects.exists())
        self.assertContains(response, "Give the install a name")

    def test_revoke_marks_it_revoked(self):
        """Revoking takes the install out of service."""
        grant, _ = CatalogGrant.generate(self.user, "Old TV")

        self.client.post(reverse("revoke_catalog_grant", args=[grant.id]), follow=True)

        grant.refresh_from_db()
        self.assertIsNotNone(grant.revoked_at)

    def test_cannot_revoke_another_users_grant(self):
        """Grant ids are not a cross-user handle."""
        grant, _ = CatalogGrant.generate(self.other, "Theirs")

        response = self.client.post(
            reverse("revoke_catalog_grant", args=[grant.id]),
        )

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        grant.refresh_from_db()
        self.assertIsNone(grant.revoked_at)


class AddonMetaTests(TestCase):
    """The meta resource answers only for items the user tracks."""

    def setUp(self):
        """Create two users, each with a list holding a different film."""
        from app.models import Item
        from app.models.choices import MediaTypes, Sources
        from lists.models import CustomList, CustomListItem

        self.user = get_user_model().objects.create_user(username="meta")
        self.other = get_user_model().objects.create_user(username="metaother")
        _, self.token = CatalogGrant.generate(self.user, "TV")
        _, self.other_token = CatalogGrant.generate(self.other, "Theirs")

        self.item, _ = Item.objects.get_or_create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "The Matrix", "synopsis": "A hacker learns."},
        )
        self.item.provider_external_ids = {"imdb_id": "tt0133093"}
        self.item.save(update_fields=["provider_external_ids"])

        self.own_list = CustomList.objects.create(owner=self.user, name="Movies")
        CustomListItem.objects.create(custom_list=self.own_list, item=self.item)

    def get_meta(self, token, media_id="tt0133093"):
        """Fetch the meta resource."""
        return self.client.get(
            reverse("stremio_addon_meta", args=[token, "movie", media_id]),
        )

    def test_manifest_advertises_meta(self):
        """A client only asks for a resource the manifest declares."""
        response = self.client.get(
            reverse("stremio_addon_manifest", args=[self.token]),
        )

        self.assertIn("meta", response.json()["resources"])

    def test_a_tracked_item_returns_its_meta(self):
        """The user's own item is published."""
        response = self.get_meta(self.token)

        self.assertEqual(response.status_code, HTTP.OK)
        meta = response.json()["meta"]
        self.assertEqual(meta["id"], "tt0133093")
        self.assertEqual(meta["name"], "The Matrix")

    def test_another_users_install_sees_nothing(self):
        """This endpoint must not become an open metadata proxy."""
        response = self.get_meta(self.other_token)

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["meta"], {})

    def test_an_untracked_id_returns_empty_not_404(self):
        """Stremio reads a 404 as the add-on being broken."""
        response = self.get_meta(self.token, media_id="tt9999999")

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["meta"], {})

    def test_a_malformed_id_is_rejected(self):
        """Identifier shape is validated before it reaches a query."""
        response = self.get_meta(self.token, media_id="notanid")

        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_an_invalid_token_is_refused(self):
        """The meta route authenticates like the others."""
        response = self.get_meta("cat_nope")

        self.assertEqual(response.status_code, HTTP.UNAUTHORIZED)

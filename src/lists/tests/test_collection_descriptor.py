"""Portable collection descriptors: export, import, and round trip."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Item
from app.models.choices import MediaTypes, Sources
from lists.collection_descriptor import (
    DESCRIPTOR_KIND,
    DESCRIPTOR_VERSION,
    InvalidDescriptorError,
    export_collection,
    parse_descriptor,
)
from lists.models import CustomList, CustomListItem


class ExportTests(TestCase):
    """A descriptor carries references, never internal ids or credentials."""

    def setUp(self):
        """Create a list with one item."""
        self.user = get_user_model().objects.create_user(username="descriptors")
        self.list = CustomList.objects.create(
            owner=self.user,
            name="Weekend",
            description="Things to watch",
            tags=["cosy"],
        )
        self.item, _ = Item.objects.get_or_create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "The Matrix"},
        )
        self.item.provider_external_ids = {"imdb_id": "tt0133093"}
        self.item.save(update_fields=["provider_external_ids"])
        CustomListItem.objects.create(custom_list=self.list, item=self.item)

    def memberships(self):
        """Return the ordered memberships."""
        return list(
            CustomListItem.objects.filter(custom_list=self.list).select_related("item"),
        )

    def test_the_descriptor_declares_its_kind_and_version(self):
        """A reader must be able to tell what it is holding."""
        descriptor = export_collection(self.list, self.memberships())

        self.assertEqual(descriptor["kind"], DESCRIPTOR_KIND)
        self.assertEqual(descriptor["version"], DESCRIPTOR_VERSION)

    def test_items_are_exported_as_external_references(self):
        """An internal id is meaningless on another instance."""
        descriptor = export_collection(self.list, self.memberships())

        entry = descriptor["items"][0]
        self.assertEqual(entry["media_id"], "603")
        self.assertEqual(entry["source"], Sources.TMDB.value)
        self.assertEqual(entry["external_ids"]["imdb_id"], "tt0133093")
        self.assertNotIn("id", entry)
        self.assertNotIn("item_id", entry)

    def test_no_owner_or_collaborator_details_are_exported(self):
        """A share is a publication; other people's identities are not in it."""
        descriptor = export_collection(self.list, self.memberships())

        serialized = str(descriptor)
        self.assertNotIn("descriptors", serialized)
        self.assertNotIn(str(self.user.pk), descriptor.get("name", ""))
        self.assertNotIn("owner", descriptor)
        self.assertNotIn("collaborators", descriptor)

    def test_layout_carries_no_executable_content(self):
        """A collection describes what to show, not code to run."""
        descriptor = export_collection(self.list, self.memberships())

        self.assertEqual(
            set(descriptor["layout"]),
            {"is_smart", "allow_recommendations"},
        )


class ParseTests(TestCase):
    """Import validates, and preserves what it does not understand."""

    def valid(self, **overrides):
        """Return a valid descriptor with overrides applied."""
        document = {
            "kind": DESCRIPTOR_KIND,
            "version": DESCRIPTOR_VERSION,
            "name": "Weekend",
            "description": "Things to watch",
            "tags": ["cosy"],
            "layout": {"is_smart": False},
            "items": [
                {
                    "media_type": "movie",
                    "source": "tmdb",
                    "media_id": "603",
                    "title": "The Matrix",
                },
            ],
        }
        document.update(overrides)
        return document

    def assert_refused(self, document, reason_code):
        """Assert a descriptor is refused with a stable reason code."""
        with self.assertRaises(InvalidDescriptorError) as caught:
            parse_descriptor(document)
        self.assertEqual(caught.exception.reason_code, reason_code)

    def test_a_valid_descriptor_parses(self):
        """The ordinary case works."""
        parsed = parse_descriptor(self.valid())

        self.assertEqual(parsed["name"], "Weekend")
        self.assertEqual(len(parsed["items"]), 1)

    def test_a_foreign_document_is_refused(self):
        """Importing arbitrary JSON as a collection would be nonsense."""
        self.assert_refused({"kind": "something.else"}, "descriptor_wrong_kind")

    def test_a_non_object_is_refused(self):
        """A list is not a descriptor."""
        self.assert_refused([1, 2], "descriptor_not_object")

    def test_a_newer_version_is_refused_rather_than_half_applied(self):
        """A partly understood import looks complete and is not."""
        self.assert_refused(
            self.valid(version=DESCRIPTOR_VERSION + 1),
            "descriptor_unsupported_version",
        )

    def test_a_nameless_descriptor_is_refused(self):
        """A collection with no name cannot be told apart from another."""
        self.assert_refused(self.valid(name="  "), "descriptor_bad_field")

    def test_unknown_fields_survive_the_round_trip(self):
        """A newer Floppy's fields must not be destroyed by an older one."""
        parsed = parse_descriptor(
            self.valid(artwork_theme="dark", future_thing={"a": 1}),
        )

        self.assertEqual(parsed["unknown_fields"]["artwork_theme"], "dark")
        self.assertEqual(parsed["unknown_fields"]["future_thing"], {"a": 1})

    def test_one_malformed_item_does_not_cost_the_others(self):
        """A single bad row must not fail an import of thousands."""
        parsed = parse_descriptor(
            self.valid(
                items=[
                    {"media_type": "movie", "source": "tmdb", "media_id": "603"},
                    {"media_type": "movie"},
                    "not even an object",
                ],
            ),
        )

        self.assertEqual(len(parsed["items"]), 1)
        self.assertEqual(parsed["skipped_items"], 2)

    def test_an_oversize_descriptor_is_refused(self):
        """An unbounded import is a denial of service."""
        items = [
            {"media_type": "movie", "source": "tmdb", "media_id": str(n)}
            for n in range(5001)
        ]
        self.assert_refused(self.valid(items=items), "descriptor_too_many_items")


class RoundTripTests(TestCase):
    """Export then import must preserve what the user cares about."""

    def test_export_then_parse_preserves_the_collection(self):
        """The whole point of a portable descriptor."""
        user = get_user_model().objects.create_user(username="roundtrip")
        custom_list = CustomList.objects.create(
            owner=user,
            name="Weekend",
            description="Things",
            tags=["cosy"],
        )
        item, _ = Item.objects.get_or_create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "The Matrix"},
        )
        CustomListItem.objects.create(custom_list=custom_list, item=item)
        memberships = list(
            CustomListItem.objects.filter(custom_list=custom_list).select_related(
                "item",
            ),
        )

        parsed = parse_descriptor(export_collection(custom_list, memberships))

        self.assertEqual(parsed["name"], "Weekend")
        self.assertEqual(parsed["description"], "Things")
        self.assertEqual(parsed["tags"], ["cosy"])
        self.assertEqual(parsed["items"][0]["media_id"], "603")
        self.assertEqual(parsed["skipped_items"], 0)

from django.test import TestCase

from app.discover.service_helpers import _item_credit_feature_maps, credit_maps_scope
from app.models import Item, ItemPersonCredit, MediaTypes, Person, Sources


class CreditMapsScopeTests(TestCase):
    """One rebuild reads each item's credits once, however many rows ask."""

    def setUp(self):
        self.item = Item.objects.create(
            media_id="credit-scope",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Credit Scope",
            image="http://example.com/a.jpg",
        )
        person = Person.objects.create(
            source=Sources.TMDB.value, source_person_id="p1", name="Some Director"
        )
        ItemPersonCredit.objects.create(
            item=self.item,
            person=person,
            role_type="crew",
            role="Director",
            department="Directing",
        )

    def test_scope_reads_once_and_matches_unscoped(self):
        expected = _item_credit_feature_maps([self.item.id])
        with credit_maps_scope():
            with self.assertNumQueries(1):
                first = _item_credit_feature_maps([self.item.id])
            with self.assertNumQueries(0):
                second = _item_credit_feature_maps([self.item.id])
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)
        self.assertEqual(second[1][self.item.id], ["some director"])

    def test_unscoped_calls_always_read(self):
        with self.assertNumQueries(1):
            _item_credit_feature_maps([self.item.id])
        with self.assertNumQueries(1):
            _item_credit_feature_maps([self.item.id])

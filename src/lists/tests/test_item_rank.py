"""A list entry's rank shows under its card in the list's custom order."""

import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import Item, MediaTypes, Sources
from lists.models import CustomList, CustomListItem

RANK_CAPTION = re.compile(r'text-\[var\(--color-text\)\]">#(\d+)</p>')


class ItemRankTests(TestCase):
    """Rank is a number shown with the custom order, not a second order."""

    def setUp(self):
        """Create an owner and a three-item list in a known order."""
        self.owner = get_user_model().objects.create_user(
            username="owner",
            password="12345",
        )
        self.custom_list = CustomList.objects.create(name="Top 100", owner=self.owner)
        start = timezone.now() - timedelta(days=1)
        self.entries = {}
        for index, title in enumerate(["One", "Two", "Three"]):
            item = Item.objects.create(
                media_id=str(index),
                source=Sources.MANUAL.value,
                media_type=MediaTypes.GAME.value,
                title=title,
                image="none",
            )
            entry = CustomListItem.objects.create(
                item=item,
                custom_list=self.custom_list,
                added_by=self.owner,
            )
            CustomListItem.objects.filter(pk=entry.pk).update(
                date_added=start + timedelta(minutes=index),
            )
            self.entries[title] = entry
        self.client.force_login(self.owner)
        self.url = reverse("list_detail", args=[self.custom_list.public_reference])

    def _captions(self, sort):
        response = self.client.get(self.url, {"layout": "grid", "sort": sort})
        self.assertEqual(response.status_code, 200)
        return RANK_CAPTION.findall(response.content.decode())

    def test_unranked_list_shows_no_numbers(self):
        """A list that never used rank looks the same as before."""
        self.assertEqual(self._captions("custom"), [])

    def test_custom_order_shows_each_rank(self):
        """Ranked entries show #rank under their cards, in custom order."""
        CustomListItem.objects.filter(pk=self.entries["Three"].pk).update(rank=81)
        CustomListItem.objects.filter(pk=self.entries["One"].pk).update(rank=100)

        self.assertEqual(self._captions("custom"), ["100", "81"])

    def test_other_sorts_do_not_show_the_rank(self):
        """Rank belongs to the custom order; other sorts keep their own captions."""
        CustomListItem.objects.filter(pk=self.entries["Three"].pk).update(rank=81)

        self.assertEqual(self._captions("title"), [])

    def test_rank_is_not_a_sort_choice(self):
        """There is one order: no Rank entry in the sort menu."""
        response = self.client.get(self.url, {"layout": "grid"})

        self.assertNotIn(
            "rank",
            [value for value, _ in response.context["sort_choices"]],
        )


class SortButtonTests(TestCase):
    """The sort control looks like the other filters, for Custom too."""

    def setUp(self):
        """Create an owner with an empty list."""
        self.owner = get_user_model().objects.create_user(
            username="owner",
            password="12345",
        )
        self.custom_list = CustomList.objects.create(name="Top 100", owner=self.owner)
        self.client.force_login(self.owner)
        self.url = reverse("list_detail", args=[self.custom_list.public_reference])

    def test_custom_sort_is_not_a_filled_split_button(self):
        """Editing the order is a menu entry, not a coloured second button."""
        html = self.client.get(self.url, {"layout": "grid"}).content.decode()

        self.assertNotIn("Custom sort options", html)
        self.assertNotIn("rounded-l-md bg-indigo-600", html)
        self.assertEqual(html.count("Edit Item Order"), 1)

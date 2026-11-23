"""Top talent reads each credited person once, not once per credit batch.

On PostgreSQL the credit scan ran as one query per 500 played items, each
joined to ``app_person``. A person credited on many titles was looked up again
in every batch: an All Time range read about 2M pages on a 700 MB database,
which a memory-starved host turned into many minutes of random disk reads.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from app.models import (
    CreditRoleType,
    Item,
    ItemPersonCredit,
    MediaTypes,
    Movie,
    Person,
    PersonGender,
    Sources,
    Status,
)
from app.statistics_talent import _aggregate_top_talent


class TopTalentPersonLookupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="talent-lookup",
            password="password123",
        )
        self.lead = Person.objects.create(
            source=Sources.TMDB.value,
            source_person_id="lead",
            name="Zed Lead",
            gender=PersonGender.MALE.value,
        )
        self.costar = Person.objects.create(
            source=Sources.TMDB.value,
            source_person_id="costar",
            name="Amy Costar",
            gender=PersonGender.FEMALE.value,
        )
        self.tied = Person.objects.create(
            source=Sources.TMDB.value,
            source_person_id="tied",
            name="Abe Tied",
            gender=PersonGender.UNKNOWN.value,
        )
        for index in range(4):
            item = Item.objects.create(
                media_id=f"lookup-{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Movie {index}",
                runtime_minutes=100,
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                end_date=timezone.now(),
            )
            ItemPersonCredit.objects.create(
                item=item,
                person=self.lead,
                role_type=CreditRoleType.CAST.value,
                role="Hero",
            )
            ItemPersonCredit.objects.create(
                item=item,
                person=self.costar,
                role_type=CreditRoleType.CAST.value,
                role="Partner",
            )
            ItemPersonCredit.objects.create(
                item=item,
                person=self.tied,
                role_type=CreditRoleType.CAST.value,
                role="Friend",
            )

    def _aggregate(self):
        return _aggregate_top_talent(
            self.user,
            None,
            None,
            schedule_missing_backfill=False,
        )

    @patch("app.statistics_talent.TALENT_CREDIT_BATCH_SIZE", 1)
    def test_each_person_is_read_once_across_credit_batches(self):
        with CaptureQueriesContext(connection) as captured:
            result = self._aggregate()

        credit_queries = [
            query["sql"]
            for query in captured.captured_queries
            if 'FROM "app_itempersoncredit"' in query["sql"]
            and '"app_itempersoncredit"."person_id"' in query["sql"]
        ]
        self.assertGreaterEqual(len(credit_queries), 4, "one batch per item")
        for sql in credit_queries:
            self.assertNotIn('"app_person"', sql)

        # The display step separately loads the few ranked people; the
        # gender lookup that buckets every credited person runs once.
        gender_lookups = [
            query["sql"]
            for query in captured.captured_queries
            if '"app_person"."gender"' in query["sql"]
        ]
        self.assertEqual(len(gender_lookups), 1, gender_lookups)

        # Gender still splits actors from actresses; the name still breaks
        # ties, so the two equal men sort alphabetically.
        self.assertEqual(
            [row["name"] for row in result["top_actors"]],
            ["Abe Tied", "Zed Lead"],
        )
        self.assertEqual(
            [row["name"] for row in result["top_actresses"]],
            ["Amy Costar"],
        )
        self.assertEqual(result["top_actors"][0]["plays"], 4)

    def test_credited_majority_reads_people_in_one_scan_with_same_result(self):
        # Someone never watched must not leak into the buckets from the scan.
        Person.objects.create(
            source=Sources.TMDB.value,
            source_person_id="stranger",
            name="Aaron Stranger",
            gender=PersonGender.MALE.value,
        )
        expected = self._aggregate()

        with (
            patch("app.statistics_talent.TALENT_PERSON_SCAN_MIN", 1),
            CaptureQueriesContext(connection) as captured,
        ):
            scanned = self._aggregate()

        self.assertEqual(scanned, expected)
        gender_lookups = [
            query["sql"]
            for query in captured.captured_queries
            if '"app_person"."gender"' in query["sql"]
        ]
        self.assertEqual(len(gender_lookups), 1, gender_lookups)
        self.assertNotIn(" WHERE ", gender_lookups[0].upper())

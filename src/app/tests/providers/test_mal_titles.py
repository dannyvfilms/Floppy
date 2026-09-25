from django.test import SimpleTestCase

from app.providers import mal


class MalTitleFieldsTests(SimpleTestCase):
    def test_english_title_wins_over_synonyms(self):
        response = {
            "title": "Shingeki no Kyojin",
            "alternative_titles": {
                "synonyms": ["AoT"],
                "en": "Attack on Titan",
                "ja": "進撃の巨人",
            },
        }

        self.assertEqual(mal.get_title_fields(response)["title"], "Attack on Titan")

    def test_synonym_used_when_english_title_is_blank(self):
        # Issue #1255: MAL leaves "en" blank for some entries and keeps
        # the English name only in synonyms.
        response = {
            "title": "JoJo no Kimyou na Bouken Part 8: JoJolion",
            "alternative_titles": {
                "synonyms": [
                    "JoJo no Kimyou na Bouken Part 8: JoJolion",
                    "JoJo's Bizarre Adventure Part 8: JoJolion",
                ],
                "en": "",
                "ja": "ジョジョリオン",
            },
        }

        fields = mal.get_title_fields(response)

        self.assertEqual(
            fields["localized_title"], "JoJo's Bizarre Adventure Part 8: JoJolion"
        )
        self.assertEqual(
            fields["original_title"], "JoJo no Kimyou na Bouken Part 8: JoJolion"
        )

    def test_main_title_used_without_english_title_or_synonyms(self):
        response = {
            "title": "Oyasumi Punpun",
            "alternative_titles": {"synonyms": [], "en": "", "ja": "おやすみプンプン"},
        }

        self.assertEqual(mal.get_title_fields(response)["title"], "Oyasumi Punpun")

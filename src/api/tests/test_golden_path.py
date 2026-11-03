"""The documented search -> state -> create -> verify flow, end to end (#1615)."""
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from app.models import MediaTypes, Sources

from .base import FloppyApiTestCase

GAME = MediaTypes.GAME.value
IGDB = Sources.IGDB.value
MEDIA_ID = "9992186"
# One patch covers search, state and create: they share the ``services`` module.
SERVICES = "api.views.services"


class GoldenPathTests(FloppyApiTestCase):
    """Follow the guide in the reviewed contract's description."""

    def _state(self):
        return self.call_api(
            "get",
            "api_media_state",
            args=(GAME, IGDB, MEDIA_ID),
            headers=self.auth_headers,
        )

    def test_search_state_create_and_verify(self):
        metadata = {
            "media_id": MEDIA_ID,
            "source": IGDB,
            "media_type": GAME,
            "title": "Golden Game",
            "image": "",
            "max_progress": 1,
        }
        with (
            patch(f"{SERVICES}.search") as search,
            patch(f"{SERVICES}.get_media_metadata", return_value=metadata),
        ):
            search.return_value = {
                "results": [
                    {
                        "media_id": MEDIA_ID,
                        "source": IGDB,
                        "media_type": GAME,
                        "title": "Golden Game",
                        "image": None,
                    }
                ],
                "total_results": 1,
                "total_pages": 1,
            }
            found = self.call_api(
                "get",
                "api_search_provider",
                args=(GAME,),
                params={"search": "golden"},
                headers=self.auth_headers,
            )
            self.assertEqual(found.status_code, HTTP.OK)
            hit = found.json()["results"][0]
            # The ``source`` and ``media_id`` of a hit are the path of the item.
            self.assertEqual((hit["source"], str(hit["media_id"])), (IGDB, MEDIA_ID))

            untracked = self._state()
            self.assertEqual(untracked.status_code, HTTP.OK)
            self.assertEqual(
                {k: untracked.json()[k] for k in ("resolved", "tracked", "consumptions")},
                {"resolved": True, "tracked": False, "consumptions": []},
            )

            created = self.call_api(
                "post",
                "api_media_type_list",
                args=(GAME,),
                payload={"source": hit["source"], "media_id": hit["media_id"], "status": 3},
                headers=self.auth_headers,
            )
            self.assertEqual(created.status_code, HTTP.CREATED, created.content[:300])

            tracked = self._state().json()
            self.assertTrue(tracked["tracked"])
            self.assertEqual(len(tracked["consumptions"]), 1)
            first = tracked["consumptions"][0]["consumption_id"]

            # POST appends: a second call adds a consumption, it does not replace.
            again = self.call_api(
                "post",
                "api_media_type_list",
                args=(GAME,),
                payload={"source": IGDB, "media_id": MEDIA_ID, "status": "Planning"},
                headers=self.auth_headers,
            )
            self.assertEqual(again.status_code, HTTP.CREATED, again.content[:300])
            ids = [c["consumption_id"] for c in self._state().json()["consumptions"]]
            self.assertEqual(len(ids), 2)
            self.assertIn(first, ids)

            # PATCH changes exactly the entry named by its consumption_id.
            patched = self.call_api(
                "patch",
                "api_media_consumption_entry_detail",
                args=(GAME, IGDB, MEDIA_ID, first),
                payload={"status": 4},
                headers=self.auth_headers,
            )
            self.assertEqual(patched.status_code, HTTP.OK, patched.content[:300])
            by_id = {
                c["consumption_id"]: c for c in self._state().json()["consumptions"]
            }
            self.assertEqual(len(by_id), 2)
            self.assertNotEqual(
                by_id[first]["status"],
                by_id[next(i for i in ids if i != first)]["status"],
            )

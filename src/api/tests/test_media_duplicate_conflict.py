from unittest.mock import patch

from app.models import MediaTypes

from .base import FloppyApiTestCase


class MediaDuplicateConflictTests(FloppyApiTestCase):
    """Tracked-media duplicate writes must use the API conflict contract."""

    @patch("api.views.services.get_media_metadata")
    def test_provider_tv_duplicate_returns_conflict(self, mock_metadata):
        tracked = self.tv_medias[0]
        mock_metadata.return_value = {
            "media_id": tracked.item.media_id,
            "source": tracked.item.source,
            "media_type": MediaTypes.TV.value,
            "title": tracked.item.title,
            "image": tracked.item.image,
        }

        response = self.call_api(
            "post",
            "api_media_type_list",
            args=(MediaTypes.TV.value,),
            payload={
                "source": tracked.item.source,
                "media_id": tracked.item.media_id,
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {"detail": "Conflict. Media is already tracked."},
        )

# FORK: ListenBrainz-compatible ingest routes, mounted at /apis/listenbrainz/1/
# from config/urls.py. Kept out of api/urls.py because these must live at the
# root path that ListenBrainz clients expect, not under /api/v1/.
from django.urls import re_path

from . import listenbrainz_views

urlpatterns = [
    re_path(
        r"^submit-listens/?$",
        listenbrainz_views.SubmitListensView.as_view(),
        name="listenbrainz_submit_listens",
    ),
    re_path(
        r"^validate-token/?$",
        listenbrainz_views.ValidateTokenView.as_view(),
        name="listenbrainz_validate_token",
    ),
]

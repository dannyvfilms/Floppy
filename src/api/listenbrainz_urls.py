# FORK: ListenBrainz-compatible routes, mounted at /apis/listenbrainz/1/
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
    re_path(
        r"^user/(?P<username>[^/]+)/listens/?$",
        listenbrainz_views.UserListensView.as_view(),
        name="listenbrainz_user_listens",
    ),
    re_path(
        r"^stats/user/(?P<username>[^/]+)/artists/?$",
        listenbrainz_views.UserArtistsView.as_view(),
        name="listenbrainz_user_artists",
    ),
    re_path(
        r"^stats/user/(?P<username>[^/]+)/release-groups/?$",
        listenbrainz_views.UserReleaseGroupsView.as_view(),
        name="listenbrainz_user_release_groups",
    ),
    re_path(
        r"^stats/user/(?P<username>[^/]+)/recordings/?$",
        listenbrainz_views.UserRecordingsView.as_view(),
        name="listenbrainz_user_recordings",
    ),
    re_path(
        r"^stats/user/(?P<username>[^/]+)/genre-activity/?$",
        listenbrainz_views.UserGenreActivityView.as_view(),
        name="listenbrainz_user_genre_activity",
    ),
]

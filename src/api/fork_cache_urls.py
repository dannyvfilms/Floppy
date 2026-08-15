"""Routes for authenticated durable metadata cache controls."""

from django.urls import re_path

from . import fork_views_cache

urlpatterns = [
    re_path(
        r"^metadata/cache/policy/?$",
        fork_views_cache.MetadataCachePolicyView.as_view(),
        name="api_metadata_cache_policy",
    ),
    re_path(
        r"^metadata/cache/(?P<media_type>[^/]+)/(?P<source>[^/]+)/(?P<media_id>[^/]+)/?$",
        fork_views_cache.MetadataCacheView.as_view(),
        name="api_metadata_cache",
    ),
]

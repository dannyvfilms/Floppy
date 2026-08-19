# FORK: serializers for fork-only endpoints (see fork_views.py).
from rest_framework import serializers

from .serializers import ItemSerializer


class CollectionEntrySerializer(serializers.Serializer):
    """Serializer for owned-media collection entries."""

    def to_representation(self, instance):
        """Transform a CollectionEntry into the API payload."""
        return {
            "id": instance.id,
            "item": ItemSerializer().to_representation(instance.item),
            "media_type": instance.media_type,
            "resolution": instance.resolution,
            "hdr": instance.hdr,
            "is_3d": instance.is_3d,
            "audio_codec": instance.audio_codec,
            "audio_channels": instance.audio_channels,
            "bitrate": instance.bitrate,
            "collected_at": instance.collected_at,
            "updated_at": instance.updated_at,
        }

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
            "purchase_price": str(instance.purchase_price)
            if instance.purchase_price is not None
            else None,
            "purchase_location": instance.purchase_location or "",
            "custom_field_values": instance.custom_field_values or {},
            # Set only when the list view decorated the entry (the viewer's
            # rating of the item, and the TV collection completeness).
            "score": float(media.score)
            if (media := getattr(instance, "media", None)) is not None
            and getattr(media, "score", None) is not None
            else None,
            "completeness": getattr(instance, "completeness", None),
            # The web grid's own card model (status, year and plays line,
            # rating), set by the list view so clients draw the same card.
            "card": getattr(instance, "card", None),
            "collected_at": instance.collected_at,
            "updated_at": instance.updated_at,
        }

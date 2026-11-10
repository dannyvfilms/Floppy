# FORK: collection custom fields for native clients, mirroring the web
# collection_fields_save view. URL wiring lives in fork_urls.py.
from http import HTTPStatus as HTTP  # noqa: N814

from django.utils.translation import gettext
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.collection_fields import (
    CollectionFieldNotFoundError,
    CollectionFieldValidationError,
    save_collection_field_schema,
    serialize_collection_field_schema,
)
from app.collection_views import (
    _apply_custom_field_values,
    _custom_field_input_name,
)
from app.models import CollectionFieldType, MediaTypes

_OBJ_READ = extend_schema(responses={200: OpenApiTypes.OBJECT})
_OBJ_WRITE = extend_schema(
    request=OpenApiTypes.OBJECT,
    responses={200: OpenApiTypes.OBJECT, 201: OpenApiTypes.OBJECT, 204: None},
)
_OBJ_DELETE = extend_schema(responses={204: None})

def apply_custom_field_values(entry, user, values):
    """Store `{field id: value}` on a collection entry, as the web form does.

    Fields the payload leaves out keep their stored value (the web form would
    read a missing checkbox as unchecked). Returns an error string or None.
    """
    if values is None:
        return None
    if not isinstance(values, dict):
        return "'custom_field_values' must be an object."
    stored = entry.custom_field_values or {}
    post_data = {}
    for field_id in {*map(str, stored), *map(str, values)}:
        value = values[field_id] if field_id in values else stored.get(field_id)
        if value is True:
            post_data[_custom_field_input_name(field_id)] = "on"
        elif value is False or value is None:
            if field_id in values and value is None:
                post_data[_custom_field_input_name(field_id)] = ""
        else:
            post_data[_custom_field_input_name(field_id)] = str(value)
    _apply_custom_field_values(entry, user, post_data)
    return None


# /api/v1/collection/fields/
class CollectionFieldsView(drf_views.APIView):
    """Read or replace the caller's collection custom-field schema."""

    @_OBJ_READ
    def get(self, request):
        """Return the field groups with their fields, ordered by position."""
        return Response(
            {
                "groups": serialize_collection_field_schema(request.user),
                "field_types": [{"value": value, "label": gettext(label)} for value, label in CollectionFieldType.choices],
                "media_types": [{"value": value, "label": gettext(label)} for value, label in MediaTypes.choices],
            },
            status=HTTP.OK,
        )

    @_OBJ_WRITE
    def put(self, request):
        """Reconcile the whole schema from `{"groups": [...]}`."""
        try:
            groups = save_collection_field_schema(request.user, request.data)
        except CollectionFieldValidationError as exc:
            return Response({"detail": str(exc)}, status=HTTP.BAD_REQUEST)
        except CollectionFieldNotFoundError as exc:
            return Response({"detail": str(exc)}, status=HTTP.NOT_FOUND)
        return Response({"groups": groups}, status=HTTP.OK)

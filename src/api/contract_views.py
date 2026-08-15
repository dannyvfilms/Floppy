from hashlib import sha256
from io import BytesIO

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import FileResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import condition, require_safe

from app.domain_vocabulary import render_glossary_rows
from app.helpers import build_absolute_app_url

_CONTRACTS_DIR = settings.BASE_DIR / "api" / "contracts"

OPENAPI_CONTRACT = (_CONTRACTS_DIR / "openapi.yaml").read_bytes()
OPENAPI_CONTRACT_ETAG = f'"{sha256(OPENAPI_CONTRACT).hexdigest()}"'

JSONLD_CONTEXT = (_CONTRACTS_DIR / "context.jsonld").read_bytes()
JSONLD_CONTEXT_ETAG = f'"{sha256(JSONLD_CONTEXT).hexdigest()}"'


def _contract_etag(_request):
    return OPENAPI_CONTRACT_ETAG


def _context_etag(_request):
    return JSONLD_CONTEXT_ETAG


def _api_example_url(route_name):
    path = f"{reverse(route_name).rstrip('/')}/"
    return build_absolute_app_url(None, path) or f"https://YOUR_FLOPPY_HOST{path}"


@login_not_required
@require_safe
def api_docs(request):
    """Render the public, offline API reference index."""
    return render(
        request,
        "api/docs.html",
        {
            "glossary_terms": render_glossary_rows(),
            "info_url": _api_example_url("api_info"),
            "preferences_url": _api_example_url("api_user_preferences"),
        },
    )


@login_not_required
@require_safe
@cache_control(public=True, max_age=3600)
@condition(etag_func=_contract_etag)
def openapi_contract(_request):
    """Serve the committed OpenAPI contract with public cache validation."""
    return FileResponse(BytesIO(OPENAPI_CONTRACT), content_type="application/yaml")


@login_not_required
@require_safe
@cache_control(public=True, max_age=3600)
@condition(etag_func=_context_etag)
def jsonld_context(_request):
    """Serve the committed JSON-LD domain context.

    The representation does not vary by host, so no ``Vary: Host`` is needed.
    """
    return FileResponse(BytesIO(JSONLD_CONTEXT), content_type="application/ld+json")

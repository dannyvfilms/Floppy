import pytest
import respx
from httpx import Response

import floppy_mcp.client as client_module
from floppy_mcp.client import (
    FloppyAPIError,
    FloppyConfigError,
    get_client,
)


async def test_missing_url_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("FLOPPY_URL", raising=False)
    monkeypatch.delenv("YAMTRACK_URL", raising=False)
    monkeypatch.setattr(
        client_module,
        "CONTAINER_RUNTIME_PORT_FILE",
        tmp_path / "missing-server-port",
    )
    with pytest.raises(FloppyConfigError):
        await get_client().request("get", "media")


async def test_container_runtime_port_is_local_url_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("FLOPPY_URL", raising=False)
    monkeypatch.delenv("YAMTRACK_URL", raising=False)
    runtime_port = tmp_path / "server-port"
    runtime_port.write_text("9123\n", encoding="ascii")
    monkeypatch.setattr(
        client_module,
        "CONTAINER_RUNTIME_PORT_FILE",
        runtime_port,
    )

    with respx.mock:
        route = respx.get("http://127.0.0.1:9123/api/v1/media").mock(
            return_value=Response(200, json={"results": []}),
        )
        result = await get_client().request("get", "media")

    assert result == {"results": []}
    assert route.called


async def test_invalid_container_runtime_port_does_not_become_a_url(
    monkeypatch,
    tmp_path,
):
    monkeypatch.delenv("FLOPPY_URL", raising=False)
    monkeypatch.delenv("YAMTRACK_URL", raising=False)
    runtime_port = tmp_path / "server-port"
    runtime_port.write_text("8000; invalid\n", encoding="ascii")
    monkeypatch.setattr(
        client_module,
        "CONTAINER_RUNTIME_PORT_FILE",
        runtime_port,
    )

    with pytest.raises(FloppyConfigError):
        await get_client().request("get", "media")


@pytest.mark.parametrize(
    "url",
    [
        "/floppy",
        "ftp://floppy.test",
        "https:///floppy",
        "https://floppy.test?x=1",
        "https://floppy.test?",
        "https://floppy.test#frag",
        "https://floppy.test#",
        "https://user@floppy.test",
        "https://user:password@floppy.test",
        "https://user%40example.test:password%3Avalue@floppy.test",
    ],
)
async def test_invalid_url_raises(monkeypatch, url):
    monkeypatch.setenv("FLOPPY_URL", url)
    with pytest.raises(FloppyConfigError, match=r"https://floppy\.example\.com"):
        await get_client().request("get", "media")


async def test_missing_token_raises(monkeypatch):
    monkeypatch.delenv("FLOPPY_TOKEN", raising=False)
    with pytest.raises(FloppyConfigError):
        await get_client().request("get", "media")


async def test_sends_api_key_header(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/media").mock(
            return_value=Response(200, json={"results": []}),
        )
        result = await get_client().request("get", "media")
        assert result == {"results": []}
        assert route.calls.last.request.headers["x-api-key"] == "test-token"


async def test_204_returns_none(api_base_url):
    with respx.mock:
        respx.delete(f"{api_base_url}/tags/1").mock(return_value=Response(204))
        result = await get_client().request("delete", "tags/1")
        assert result is None


async def test_error_response_raises_with_detail(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/media/movie/tmdb/999").mock(
            return_value=Response(404, json={"detail": "Item not found."}),
        )
        with pytest.raises(FloppyAPIError) as exc_info:
            await get_client().request("get", "media/movie/tmdb/999")
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == {"detail": "Item not found."}


async def test_none_params_are_dropped(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/media").mock(
            return_value=Response(200, json={"results": []}),
        )
        await get_client().request(
            "get",
            "media",
            params={"media_type": None, "status": "Completed"},
        )
        request_url = route.calls.last.request.url
        assert "media_type" not in request_url.params
        assert request_url.params["status"] == "Completed"

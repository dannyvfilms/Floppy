
import pytest


@pytest.fixture(autouse=True)
def _floppy_env(monkeypatch):
    """Point every test at a fake instance; respx intercepts the requests."""
    monkeypatch.setenv("FLOPPY_URL", "https://floppy.test")
    monkeypatch.setenv("FLOPPY_TOKEN", "test-token")
    # Force a fresh client per test since the module caches one globally.
    import floppy_mcp.client as client_module

    client_module._client = None
    yield
    client_module._client = None


@pytest.fixture
def api_base_url():
    return "https://floppy.test/api/v1"

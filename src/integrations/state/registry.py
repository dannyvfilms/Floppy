"""Which adapter module serves each kind of external service.

Adding a destination is one line here plus an adapter module that exposes
``build_adapter(binding)``. Modules are imported on first use, so the engine
does not import every provider's transport just to deliver to one of them.
"""

import importlib

from integrations.models import SyncClientKind

ADAPTER_MODULES = {
    SyncClientKind.JELLYFIN.value: "integrations.state.adapters.jellyfin",
    SyncClientKind.EMBY.value: "integrations.state.adapters.emby",
    SyncClientKind.KODI.value: "integrations.state.adapters.kodi",
    SyncClientKind.TMDB.value: "integrations.state.adapters.tmdb",
    SyncClientKind.WETRAKR.value: "integrations.state.adapters.wetrakr",
}


def build_adapter(binding):
    """Return the adapter for a binding, or None when its kind has none."""
    module_path = ADAPTER_MODULES.get(binding.client_kind)
    if module_path is None:
        return None
    return importlib.import_module(module_path).build_adapter(binding)

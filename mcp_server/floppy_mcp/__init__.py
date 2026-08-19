"""MCP server exposing the Floppy REST API to AI agents."""

# MCP v1.29 leaves FastMCP Settings.lifespan as an unresolved forward
# reference under pydantic-settings 2.15. Upstream recommends rebuilding the
# public model after the module import; do it before constructing our server so
# normal Django/tests do not emit IncompleteFieldDefinitionWarning.
from mcp.server.fastmcp.server import Settings as _FastMCPSettings

_FastMCPSettings.model_rebuild()

from .server import mcp

__all__ = ["mcp"]

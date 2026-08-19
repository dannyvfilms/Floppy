from django.test import SimpleTestCase


class MCPSettingsCompatibilityTests(SimpleTestCase):
    def test_floppy_mcp_rebuilds_fastmcp_settings(self):
        from floppy_mcp import mcp  # noqa: F401
        from mcp.server.fastmcp.server import Settings

        self.assertTrue(Settings.__pydantic_complete__)
        self.assertTrue(Settings.model_fields["lifespan"]._complete)  # noqa: SLF001

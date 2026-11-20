"""Streamable HTTP transport host configuration."""

import json
import os
import subprocess
import sys


def test_allowed_host_authorities_are_loaded_from_environment():
    env = os.environ.copy()
    env["FLOPPY_MCP_ALLOWED_HOSTS"] = "mcp.example.test, mcp.example.test:8443"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from floppy_mcp.server import mcp; "
            "print(json.dumps(mcp.settings.transport_security.allowed_hosts))",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert json.loads(result.stdout.strip()) == [
        "mcp.example.test",
        "mcp.example.test:8443",
    ]

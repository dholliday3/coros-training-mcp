"""Tests for installer.smoke — subprocess-based LSP smoke test.

We don't try to boot the real COROS MCP (needs live creds). Instead, we boot
a tiny scripted server that speaks LSP framing and emits an initialize
response. Proves the framing reader, header parser, and teardown work.
"""
from __future__ import annotations

import sys
import textwrap

import pytest

from installer.smoke import smoke_test


FAKE_SERVER = textwrap.dedent(
    r"""
    import json
    import sys

    # MCP stdio uses newline-delimited JSON-RPC.
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    req = json.loads(line)

    # Emit a notification first, to prove the reader skips non-matching messages.
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/log", "params": {"level": "info", "message": "boot"}}) + "\n")
    sys.stdout.write(json.dumps({
        "jsonrpc": "2.0",
        "id": req["id"],
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "fake-coros-mcp", "version": "0.0"}
        }
    }) + "\n")
    sys.stdout.flush()

    # Wait for initialized notification, then exit cleanly.
    sys.stdin.readline()
    """
)

BROKEN_SERVER = textwrap.dedent(
    r"""
    import sys
    # Exit immediately without responding.
    sys.stderr.write("oops: something went wrong\n")
    sys.exit(1)
    """
)


def test_smoke_test_passes_against_a_compliant_fake(tmp_path):
    script = tmp_path / "fake_server.py"
    script.write_text(FAKE_SERVER)
    result = smoke_test([sys.executable, str(script)], timeout_seconds=5.0)
    assert result.ok
    assert "fake-coros-mcp" in result.detail


def test_smoke_test_reports_failure_when_server_exits_early(tmp_path):
    script = tmp_path / "broken_server.py"
    script.write_text(BROKEN_SERVER)
    result = smoke_test([sys.executable, str(script)], timeout_seconds=5.0)
    assert result.ok is False
    assert "oops" in result.stderr_tail or "respond" in result.detail


def test_smoke_test_reports_clear_error_when_binary_missing():
    result = smoke_test(["/definitely/not/a/real/path/coros-mcp", "serve"], timeout_seconds=1.0)
    assert result.ok is False
    assert "not found" in result.detail.lower() or "launch" in result.detail.lower()

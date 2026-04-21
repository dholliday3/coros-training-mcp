"""Post-install smoke test: boot the MCP server and exchange an ``initialize`` call.

If this fails, the wizard surfaces the failure but doesn't roll back the
install — the assistant registration is still correct, and the user can debug
with ``coros-mcp auth-status`` or by inspecting their stored token.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass
class SmokeResult:
    ok: bool
    detail: str
    stderr_tail: str = ""


_INIT_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "coros-mcp-setup", "version": "0.2.0"},
    },
}

_INITIALIZED_NOTIFICATION = {
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
}


def _encode(msg: dict) -> bytes:
    # MCP stdio transport uses newline-delimited JSON-RPC (one message per line).
    return (json.dumps(msg) + "\n").encode("utf-8")


def smoke_test(server_command: list[str], *, timeout_seconds: float = 10.0) -> SmokeResult:
    """Boot the server, send ``initialize``, wait for a valid response.

    Returns a ``SmokeResult`` — never raises. stderr tail is captured and
    surfaced on failure so common problems (stale token, missing credentials)
    are immediately visible.
    """
    try:
        proc = subprocess.Popen(
            server_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        return SmokeResult(False, f"Command not found: {server_command[0]!r}")
    except OSError as exc:
        return SmokeResult(False, f"Failed to launch server: {exc}")

    try:
        assert proc.stdin is not None
        proc.stdin.write(_encode(_INIT_REQUEST))
        proc.stdin.flush()

        response = _read_json_line(proc, timeout_seconds)
        if response is None:
            stderr_tail = _drain_stderr(proc)
            return SmokeResult(
                False,
                f"Server did not respond to initialize within {timeout_seconds:.0f}s.",
                stderr_tail,
            )

        if response.get("id") != 1 or "result" not in response:
            stderr_tail = _drain_stderr(proc)
            return SmokeResult(
                False,
                f"Unexpected response shape: {response!r}",
                stderr_tail,
            )

        server_info = response["result"].get("serverInfo", {})
        name = server_info.get("name", "mcp-server")

        # Be polite: send the initialized notification, then let the server exit.
        proc.stdin.write(_encode(_INITIALIZED_NOTIFICATION))
        proc.stdin.flush()

        return SmokeResult(True, f"{name} responded to initialize OK")
    finally:
        _shutdown(proc)


def _read_json_line(proc: subprocess.Popen, timeout_seconds: float) -> Optional[dict]:
    """Read newline-delimited JSON-RPC messages until one has ``id == 1``.

    MCP stdio servers may emit logging messages (as JSON-RPC notifications
    with no ``id``) before or after the response. We skip those and wait for
    the actual reply to our initialize request.
    """
    import selectors
    import time as _time

    assert proc.stdout is not None
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)

    deadline = _time.monotonic() + timeout_seconds
    buf = bytearray()

    while True:
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            return None
        events = sel.select(timeout=remaining)
        if not events:
            return None
        chunk = proc.stdout.read1(4096)
        if not chunk:
            return None
        buf.extend(chunk)

        # Drain every complete newline-terminated message in the buffer.
        while True:
            newline = buf.find(b"\n")
            if newline == -1:
                break
            line = bytes(buf[:newline]).strip()
            del buf[: newline + 1]
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                # Non-JSON output (banner / warning line) — ignore and keep reading.
                continue
            if isinstance(msg, dict) and msg.get("id") == 1:
                return msg
            # Otherwise it's a notification / log message — keep waiting.


def _drain_stderr(proc: subprocess.Popen, *, max_bytes: int = 2048) -> str:
    if proc.stderr is None:
        return ""
    try:
        import os

        os.set_blocking(proc.stderr.fileno(), False)
        data = proc.stderr.read(max_bytes) or b""
        return data.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def _shutdown(proc: subprocess.Popen) -> None:
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
    except Exception:
        pass
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()

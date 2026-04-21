"""Detection and config writers for supported MCP clients.

Each supported assistant exposes three operations:

- ``detect()`` — is this assistant installed / configured on this machine?
- ``install(server_command)`` — register our MCP under the name ``coros``.
- ``uninstall()`` — remove the ``coros`` MCP entry, leaving other MCPs alone.

All writers are **atomic** (write to a sibling tmp file, then ``os.replace``)
and **non-destructive** (merge into existing JSON; preserve other MCP
entries; refuse to overwrite unparseable configs).

The ``server_command`` passed to ``install`` is a list like
``["/Users/you/.local/bin/coros-mcp", "serve"]`` — already resolved to an
absolute path by the wizard so MCP clients don't have to search ``PATH``.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

MCP_ENTRY_NAME = "coros"


# ---------------------------------------------------------------------------
# Atomic JSON helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    """Read JSON from ``path``, returning ``{}`` if the file is missing.

    Raises ``ValueError`` if the file exists but is unparseable — we prefer
    bailing loudly to silently overwriting the user's config.
    """
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc
    if not content.strip():
        return {}
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} exists but is not valid JSON ({exc.msg} at line {exc.lineno}). "
            "Fix or remove the file before re-running setup."
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object at the top level, got {type(data).__name__}.")
    return data


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write ``data`` to ``path`` atomically with 0600 perms on the new file.

    Creates parent directories as needed. Uses a tmp file in the same dir so
    ``os.replace`` is atomic on POSIX and Windows.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(data, indent=2) + "\n"
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(rendered)
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass  # best-effort; Windows won't honor this
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _merge_mcp_entry(
    config: dict,
    entry_name: str,
    command: list[str],
) -> tuple[dict, str]:
    """Insert/replace an MCP entry under ``mcpServers`` / ``servers``.

    Returns (updated_config, action) where action is one of:
      - "added" — no prior entry with this name
      - "replaced" — prior entry existed and command differed
      - "unchanged" — prior entry matched exactly

    The standard key used by Claude Desktop, Cursor, and VS Code's MCP config
    is ``mcpServers``. We respect an existing ``servers`` key if the file
    already uses that shape, to avoid dual-keying the same client.
    """
    cmd_exe = command[0]
    cmd_args = command[1:]

    container_key = "mcpServers"
    if "servers" in config and "mcpServers" not in config:
        container_key = "servers"

    container = config.setdefault(container_key, {})
    if not isinstance(container, dict):
        raise ValueError(
            f"Existing config has a non-object '{container_key}' entry "
            f"(got {type(container).__name__}); refusing to modify."
        )

    existing = container.get(entry_name)
    new_entry = {"command": cmd_exe, "args": cmd_args}
    action = "added"
    if isinstance(existing, dict):
        if existing.get("command") == cmd_exe and list(existing.get("args") or []) == cmd_args:
            return config, "unchanged"
        # Preserve existing env block and other unknown keys.
        merged = dict(existing)
        merged["command"] = cmd_exe
        merged["args"] = cmd_args
        container[entry_name] = merged
        action = "replaced"
    else:
        container[entry_name] = new_entry
    return config, action


# ---------------------------------------------------------------------------
# Per-assistant paths
# ---------------------------------------------------------------------------

def _home() -> Path:
    return Path(os.path.expanduser("~"))


def claude_desktop_config_path() -> Path:
    """Where Claude Desktop stores its MCP config on this OS."""
    system = platform.system()
    if system == "Darwin":
        return _home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Claude" / "claude_desktop_config.json"
        return _home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    # Linux — Claude Desktop isn't officially shipped here but the config path
    # convention would be XDG-style.
    return _home() / ".config" / "Claude" / "claude_desktop_config.json"


def cursor_config_path() -> Path:
    """Cursor's per-user MCP config (shared across projects)."""
    return _home() / ".cursor" / "mcp.json"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class InstallResult:
    assistant: str
    action: str  # "added" | "replaced" | "unchanged" | "skipped" | "failed"
    detail: str = ""
    config_path: Optional[Path] = None


# ---------------------------------------------------------------------------
# Claude Code CLI
# ---------------------------------------------------------------------------

def detect_claude_code() -> bool:
    return shutil.which("claude") is not None


def install_claude_code(command: list[str]) -> InstallResult:
    """Install via the ``claude mcp add`` CLI so the client owns its own config format."""
    if not detect_claude_code():
        return InstallResult("Claude Code", "skipped", "claude CLI not found on PATH")

    # `claude mcp add <name> -- <command> <args...>` adds the server.
    # Claude Code handles its own JSON (~/.claude.json) via this CLI.
    # We first remove any existing entry so re-runs are idempotent; the
    # `claude mcp remove` call is a no-op if nothing's there.
    subprocess.run(
        ["claude", "mcp", "remove", MCP_ENTRY_NAME],
        capture_output=True,
        text=True,
    )
    add = subprocess.run(
        ["claude", "mcp", "add", MCP_ENTRY_NAME, "--", *command],
        capture_output=True,
        text=True,
    )
    if add.returncode != 0:
        return InstallResult(
            "Claude Code",
            "failed",
            f"claude mcp add failed: {add.stderr.strip() or add.stdout.strip()}",
        )
    return InstallResult("Claude Code", "added", "registered via `claude mcp add`")


def uninstall_claude_code() -> InstallResult:
    if not detect_claude_code():
        return InstallResult("Claude Code", "skipped", "claude CLI not found on PATH")
    result = subprocess.run(
        ["claude", "mcp", "remove", MCP_ENTRY_NAME],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Non-zero usually means "no entry to remove" — treat as already-clean.
        return InstallResult("Claude Code", "unchanged", "no coros entry was registered")
    return InstallResult("Claude Code", "added", "removed coros entry")


# ---------------------------------------------------------------------------
# Claude Desktop (JSON config)
# ---------------------------------------------------------------------------

def detect_claude_desktop() -> bool:
    """True if the Claude Desktop config dir exists OR its config file exists.

    Claude Desktop creates the config dir on first launch. If the user has
    never launched it, we still allow installing — they'll just need to
    launch the app once for the config to take effect.
    """
    path = claude_desktop_config_path()
    return path.exists() or path.parent.exists()


def install_claude_desktop(command: list[str]) -> InstallResult:
    path = claude_desktop_config_path()
    try:
        config = _read_json(path)
        config, action = _merge_mcp_entry(config, MCP_ENTRY_NAME, command)
        if action != "unchanged":
            _atomic_write_json(path, config)
    except ValueError as exc:
        return InstallResult("Claude Desktop", "failed", str(exc), path)
    return InstallResult("Claude Desktop", action, f"wrote {path}", path)


def uninstall_claude_desktop() -> InstallResult:
    path = claude_desktop_config_path()
    if not path.exists():
        return InstallResult("Claude Desktop", "skipped", "config file does not exist", path)
    try:
        config = _read_json(path)
    except ValueError as exc:
        return InstallResult("Claude Desktop", "failed", str(exc), path)
    removed = False
    for key in ("mcpServers", "servers"):
        container = config.get(key)
        if isinstance(container, dict) and MCP_ENTRY_NAME in container:
            del container[MCP_ENTRY_NAME]
            removed = True
    if removed:
        _atomic_write_json(path, config)
        return InstallResult("Claude Desktop", "added", "removed coros entry", path)
    return InstallResult("Claude Desktop", "unchanged", "no coros entry was registered", path)


# ---------------------------------------------------------------------------
# Codex CLI
# ---------------------------------------------------------------------------

def detect_codex() -> bool:
    return shutil.which("codex") is not None


def install_codex(command: list[str]) -> InstallResult:
    if not detect_codex():
        return InstallResult("Codex CLI", "skipped", "codex CLI not found on PATH")
    subprocess.run(
        ["codex", "mcp", "remove", MCP_ENTRY_NAME],
        capture_output=True,
        text=True,
    )
    add = subprocess.run(
        ["codex", "mcp", "add", MCP_ENTRY_NAME, "--", *command],
        capture_output=True,
        text=True,
    )
    if add.returncode != 0:
        return InstallResult(
            "Codex CLI",
            "failed",
            f"codex mcp add failed: {add.stderr.strip() or add.stdout.strip()}",
        )
    return InstallResult("Codex CLI", "added", "registered via `codex mcp add`")


def uninstall_codex() -> InstallResult:
    if not detect_codex():
        return InstallResult("Codex CLI", "skipped", "codex CLI not found on PATH")
    result = subprocess.run(
        ["codex", "mcp", "remove", MCP_ENTRY_NAME],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return InstallResult("Codex CLI", "unchanged", "no coros entry was registered")
    return InstallResult("Codex CLI", "added", "removed coros entry")


# ---------------------------------------------------------------------------
# Cursor (JSON config at ~/.cursor/mcp.json)
# ---------------------------------------------------------------------------

def detect_cursor() -> bool:
    if shutil.which("cursor"):
        return True
    return (_home() / ".cursor").exists()


def install_cursor(command: list[str]) -> InstallResult:
    path = cursor_config_path()
    try:
        config = _read_json(path)
        config, action = _merge_mcp_entry(config, MCP_ENTRY_NAME, command)
        if action != "unchanged":
            _atomic_write_json(path, config)
    except ValueError as exc:
        return InstallResult("Cursor", "failed", str(exc), path)
    return InstallResult("Cursor", action, f"wrote {path}", path)


def uninstall_cursor() -> InstallResult:
    path = cursor_config_path()
    if not path.exists():
        return InstallResult("Cursor", "skipped", "config file does not exist", path)
    try:
        config = _read_json(path)
    except ValueError as exc:
        return InstallResult("Cursor", "failed", str(exc), path)
    removed = False
    for key in ("mcpServers", "servers"):
        container = config.get(key)
        if isinstance(container, dict) and MCP_ENTRY_NAME in container:
            del container[MCP_ENTRY_NAME]
            removed = True
    if removed:
        _atomic_write_json(path, config)
        return InstallResult("Cursor", "added", "removed coros entry", path)
    return InstallResult("Cursor", "unchanged", "no coros entry was registered", path)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass
class AssistantHandler:
    key: str
    label: str
    detect: Callable[[], bool]
    install: Callable[[list[str]], InstallResult]
    uninstall: Callable[[], InstallResult]


# Handlers hold names-of-functions rather than direct references so tests can
# monkeypatch ``detect_claude_code`` etc. at the module level and see the change.
@dataclass
class _HandlerSpec:
    key: str
    label: str
    detect_name: str
    install_name: str
    uninstall_name: str


_HANDLER_SPECS: list[_HandlerSpec] = [
    _HandlerSpec("claude-code", "Claude Code (CLI)", "detect_claude_code", "install_claude_code", "uninstall_claude_code"),
    _HandlerSpec("claude-desktop", "Claude Desktop", "detect_claude_desktop", "install_claude_desktop", "uninstall_claude_desktop"),
    _HandlerSpec("codex", "Codex CLI", "detect_codex", "install_codex", "uninstall_codex"),
    _HandlerSpec("cursor", "Cursor", "detect_cursor", "install_cursor", "uninstall_cursor"),
]


def _materialize(spec: _HandlerSpec) -> AssistantHandler:
    mod = globals()
    return AssistantHandler(
        key=spec.key,
        label=spec.label,
        detect=mod[spec.detect_name],
        install=mod[spec.install_name],
        uninstall=mod[spec.uninstall_name],
    )


# Materialized list — useful for iteration. Call ``_materialize(spec)``
# inside ``detect_all`` / ``find_handler`` so monkeypatched functions are
# picked up on each call instead of being captured at import time.
ASSISTANTS: list[AssistantHandler] = [_materialize(s) for s in _HANDLER_SPECS]


def detect_all() -> list[AssistantHandler]:
    """Return handlers for every assistant detected on this machine."""
    return [_materialize(s) for s in _HANDLER_SPECS if _materialize(s).detect()]


def find_handler(key: str) -> Optional[AssistantHandler]:
    for spec in _HANDLER_SPECS:
        if spec.key == key:
            return _materialize(spec)
    return None

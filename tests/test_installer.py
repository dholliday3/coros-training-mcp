"""Tests for the installer package.

Focus: config writers must be **atomic** and **non-destructive**. Other MCPs
in the user's config must survive our edits; our own entries must be
re-writable without breaking anything; unparseable configs must fail loudly
rather than being silently overwritten.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from installer import assistants, regions


# ---------------------------------------------------------------------------
# _read_json / _atomic_write_json
# ---------------------------------------------------------------------------

def test_read_json_returns_empty_dict_when_missing(tmp_path: Path):
    assert assistants._read_json(tmp_path / "missing.json") == {}


def test_read_json_returns_empty_dict_when_empty(tmp_path: Path):
    path = tmp_path / "empty.json"
    path.write_text("")
    assert assistants._read_json(path) == {}


def test_read_json_rejects_unparseable_config(tmp_path: Path):
    path = tmp_path / "junk.json"
    path.write_text("{not json")
    with pytest.raises(ValueError) as exc:
        assistants._read_json(path)
    assert "not valid JSON" in str(exc.value)


def test_read_json_rejects_non_object_top_level(tmp_path: Path):
    path = tmp_path / "list.json"
    path.write_text("[1,2,3]")
    with pytest.raises(ValueError) as exc:
        assistants._read_json(path)
    assert "JSON object" in str(exc.value)


def test_atomic_write_creates_parent_dirs(tmp_path: Path):
    target = tmp_path / "a" / "b" / "c.json"
    assistants._atomic_write_json(target, {"hello": "world"})
    assert target.read_text() == '{\n  "hello": "world"\n}\n'


def test_atomic_write_replaces_atomically(tmp_path: Path):
    path = tmp_path / "c.json"
    path.write_text('{"old": true}')
    assistants._atomic_write_json(path, {"new": True})
    assert json.loads(path.read_text()) == {"new": True}
    # No tmp file should remain.
    assert [p.name for p in tmp_path.iterdir()] == ["c.json"]


@pytest.mark.skipif(os.name == "nt", reason="chmod on Windows doesn't honor 0600")
def test_atomic_write_sets_mode_0600(tmp_path: Path):
    path = tmp_path / "c.json"
    assistants._atomic_write_json(path, {"x": 1})
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


# ---------------------------------------------------------------------------
# _merge_mcp_entry — non-destructive behavior
# ---------------------------------------------------------------------------

def test_merge_adds_entry_to_empty_config():
    cfg, action = assistants._merge_mcp_entry({}, "coros", ["/bin/coros-mcp", "serve"])
    assert action == "added"
    assert cfg["mcpServers"]["coros"] == {"command": "/bin/coros-mcp", "args": ["serve"]}


def test_merge_preserves_other_mcp_entries():
    original = {
        "mcpServers": {
            "github": {"command": "gh-mcp", "args": []},
            "filesystem": {"command": "fs-mcp", "args": ["/"]},
        }
    }
    cfg, action = assistants._merge_mcp_entry(original, "coros", ["/bin/coros-mcp", "serve"])
    assert action == "added"
    # Other MCPs survive.
    assert cfg["mcpServers"]["github"] == {"command": "gh-mcp", "args": []}
    assert cfg["mcpServers"]["filesystem"] == {"command": "fs-mcp", "args": ["/"]}
    # Our entry is added.
    assert cfg["mcpServers"]["coros"]["command"] == "/bin/coros-mcp"


def test_merge_replaces_existing_entry_with_different_command():
    original = {
        "mcpServers": {
            "coros": {"command": "/old/path/run-coros-mcp.zsh", "args": []},
        }
    }
    cfg, action = assistants._merge_mcp_entry(original, "coros", ["/new/coros-mcp", "serve"])
    assert action == "replaced"
    assert cfg["mcpServers"]["coros"]["command"] == "/new/coros-mcp"
    assert cfg["mcpServers"]["coros"]["args"] == ["serve"]


def test_merge_preserves_env_block_when_replacing():
    """If the user added custom env vars to their coros entry, don't nuke them."""
    original = {
        "mcpServers": {
            "coros": {
                "command": "/old",
                "args": [],
                "env": {"COROS_REGION": "us"},
            },
        }
    }
    cfg, _ = assistants._merge_mcp_entry(original, "coros", ["/new/coros-mcp", "serve"])
    assert cfg["mcpServers"]["coros"]["env"] == {"COROS_REGION": "us"}


def test_merge_unchanged_when_command_matches():
    original = {
        "mcpServers": {
            "coros": {"command": "/bin/coros-mcp", "args": ["serve"]},
        }
    }
    cfg, action = assistants._merge_mcp_entry(original, "coros", ["/bin/coros-mcp", "serve"])
    assert action == "unchanged"
    assert cfg is original  # no copy made


def test_merge_uses_servers_key_when_that_shape_is_present():
    """Some clients use `servers` instead of `mcpServers`; respect the existing shape."""
    original = {"servers": {"github": {"command": "gh"}}}
    cfg, _ = assistants._merge_mcp_entry(original, "coros", ["/bin/coros-mcp", "serve"])
    assert "coros" in cfg["servers"]
    assert "mcpServers" not in cfg


def test_merge_bails_on_non_object_container():
    bad = {"mcpServers": ["not", "a", "dict"]}
    with pytest.raises(ValueError, match="non-object"):
        assistants._merge_mcp_entry(bad, "coros", ["/bin/coros-mcp"])


# ---------------------------------------------------------------------------
# Per-assistant install (file-based writers, monkeypatched paths)
# ---------------------------------------------------------------------------

def test_install_claude_desktop_preserves_other_entries(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "claude_desktop_config.json"
    config_path.write_text(json.dumps({
        "mcpServers": {
            "github": {"command": "gh-mcp", "args": []}
        }
    }))
    monkeypatch.setattr(assistants, "claude_desktop_config_path", lambda: config_path)

    result = assistants.install_claude_desktop(["/bin/coros-mcp", "serve"])

    assert result.action == "added"
    data = json.loads(config_path.read_text())
    assert data["mcpServers"]["github"] == {"command": "gh-mcp", "args": []}
    assert data["mcpServers"]["coros"]["command"] == "/bin/coros-mcp"


def test_install_claude_desktop_creates_config_when_missing(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config-doesnt-exist" / "claude_desktop_config.json"
    monkeypatch.setattr(assistants, "claude_desktop_config_path", lambda: config_path)

    result = assistants.install_claude_desktop(["/bin/coros-mcp", "serve"])

    assert result.action == "added"
    assert config_path.exists()
    data = json.loads(config_path.read_text())
    assert data["mcpServers"]["coros"]["command"] == "/bin/coros-mcp"


def test_install_claude_desktop_fails_loudly_on_bad_config(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "bad.json"
    config_path.write_text("{not valid")
    monkeypatch.setattr(assistants, "claude_desktop_config_path", lambda: config_path)

    result = assistants.install_claude_desktop(["/bin/coros-mcp", "serve"])

    assert result.action == "failed"
    # Config file was NOT overwritten.
    assert config_path.read_text() == "{not valid"


def test_install_claude_desktop_idempotent(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "claude.json"
    monkeypatch.setattr(assistants, "claude_desktop_config_path", lambda: config_path)

    first = assistants.install_claude_desktop(["/bin/coros-mcp", "serve"])
    second = assistants.install_claude_desktop(["/bin/coros-mcp", "serve"])

    assert first.action == "added"
    assert second.action == "unchanged"


def test_uninstall_claude_desktop_leaves_other_mcps(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "claude.json"
    config_path.write_text(json.dumps({
        "mcpServers": {
            "coros": {"command": "/bin/coros-mcp"},
            "github": {"command": "gh-mcp"},
        }
    }))
    monkeypatch.setattr(assistants, "claude_desktop_config_path", lambda: config_path)

    result = assistants.uninstall_claude_desktop()

    assert result.action == "added"  # sentinel: an uninstall write happened
    data = json.loads(config_path.read_text())
    assert "coros" not in data["mcpServers"]
    assert data["mcpServers"]["github"] == {"command": "gh-mcp"}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def test_detect_claude_code_follows_which(monkeypatch):
    monkeypatch.setattr(assistants.shutil, "which", lambda cmd: "/bin/claude" if cmd == "claude" else None)
    assert assistants.detect_claude_code() is True

    monkeypatch.setattr(assistants.shutil, "which", lambda cmd: None)
    assert assistants.detect_claude_code() is False


def test_detect_claude_desktop_true_when_config_dir_exists(tmp_path: Path, monkeypatch):
    config = tmp_path / "Claude" / "claude_desktop_config.json"
    config.parent.mkdir()
    monkeypatch.setattr(assistants, "claude_desktop_config_path", lambda: config)
    assert assistants.detect_claude_desktop() is True


def test_detect_claude_desktop_false_when_nothing_exists(tmp_path: Path, monkeypatch):
    config = tmp_path / "nowhere" / "claude_desktop_config.json"
    monkeypatch.setattr(assistants, "claude_desktop_config_path", lambda: config)
    assert assistants.detect_claude_desktop() is False


def test_detect_all_filters_to_installed_ones(monkeypatch):
    monkeypatch.setattr(assistants, "detect_claude_code", lambda: True)
    monkeypatch.setattr(assistants, "detect_claude_desktop", lambda: False)
    monkeypatch.setattr(assistants, "detect_codex", lambda: False)
    monkeypatch.setattr(assistants, "detect_cursor", lambda: True)

    detected = assistants.detect_all()
    keys = [h.key for h in detected]
    assert keys == ["claude-code", "cursor"]


# ---------------------------------------------------------------------------
# Region default
# ---------------------------------------------------------------------------

def test_default_region_is_one_of_the_valid_values():
    r = regions.default_region()
    assert r in regions.REGIONS

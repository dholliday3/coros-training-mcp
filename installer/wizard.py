"""End-to-end ``coros-mcp setup`` wizard.

Runs four phases in order:

1. Credentials → ``coros_api.login(...)`` round-trip verify → keyring store.
   Skippable if creds are already stored and the caller didn't pass
   ``--reconfigure-credentials``.
2. Detect installed assistants. If none are detected, print manual
   instructions and exit.
3. Pick assistants (multi-select); write config to each picked one.
4. Boot the server over stdio, send ``initialize``, report pass/fail.

Every step prints a short status line so users can see exactly what changed.
Failures in later steps do not roll back earlier steps — the assistant
registrations are independent of whether the smoke test passes.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
from typing import Iterable, Optional

import questionary

from auth.storage import is_keyring_available
from coros_api import get_stored_auth, login

from installer.assistants import (
    ASSISTANTS,
    AssistantHandler,
    InstallResult,
    detect_all,
    find_handler,
)
from installer.regions import REGION_LABELS, REGIONS, default_region
from installer.smoke import smoke_test


def run_setup(*, reconfigure_credentials: bool = False) -> int:
    """Entry point for ``coros-mcp setup``. Returns a process exit code."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        sys.stderr.write(
            "coros-mcp setup needs an interactive terminal. "
            "Run it directly in your shell, not piped or in CI.\n"
        )
        return 2

    _banner()

    if not _ensure_credentials(reconfigure=reconfigure_credentials):
        return 1

    handlers = detect_all()
    if not handlers:
        _print_manual_instructions()
        return 0

    picks = _pick_assistants(handlers)
    if not picks:
        print("\nNo assistants picked. Skipping install step.")
    else:
        server_cmd = _resolve_server_command()
        _install_into(picks, server_cmd)

    _run_smoke_test()

    _farewell(picks)
    return 0


def run_uninstall() -> int:
    """Entry point for ``coros-mcp uninstall``."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        sys.stderr.write("coros-mcp uninstall needs an interactive terminal.\n")
        return 2

    print("Coros MCP — uninstall")
    print()
    print("Pick assistants to remove the 'coros' MCP entry from.")
    print("Other MCP entries in those configs will be left alone.")
    print()

    handlers = detect_all()
    if not handlers:
        print("No supported assistants detected on this machine.")
        return 0

    choices = [
        questionary.Choice(h.label, value=h.key, checked=True) for h in handlers
    ]
    picks = questionary.checkbox(
        "Uninstall from:", choices=choices
    ).ask()
    if picks is None or not picks:
        print("Nothing picked; aborting.")
        return 0

    for key in picks:
        handler = find_handler(key)
        if handler is None:
            continue
        result = handler.uninstall()
        _print_result(result)

    clear_creds = questionary.confirm(
        "Also remove stored COROS credentials from your keyring?",
        default=False,
    ).ask()
    if clear_creds:
        from auth.storage import clear_token

        res = clear_token()
        if res.success:
            print("✓ Credentials cleared.")
        else:
            print(f"✗ Failed to clear credentials: {res.message}")

    return 0


# ---------------------------------------------------------------------------
# Phase helpers
# ---------------------------------------------------------------------------

def _banner() -> None:
    print("Coros MCP — setup")
    print()
    if is_keyring_available():
        print("Credentials will be stored in your system keyring.")
    else:
        print(
            "System keyring unavailable — credentials will be stored in an "
            "encrypted file at ~/.coros-mcp/credentials.enc."
        )
    print()


def _ensure_credentials(*, reconfigure: bool) -> bool:
    """Prompt for creds, validate against the COROS API, store on success."""
    existing = get_stored_auth()
    if existing and not reconfigure:
        reuse = questionary.confirm(
            f"Already authenticated as user {existing.user_id} "
            f"(region: {existing.region}). Reuse these credentials?",
            default=True,
        ).ask()
        if reuse:
            print("  (Re-run with `coros-mcp setup --reconfigure` to change them.)")
            return True
        print()

    default_reg = default_region()

    for attempt in range(3):
        email = questionary.text(
            "Coros email:",
            validate=lambda v: bool(v.strip()) or "Email is required.",
        ).ask()
        if email is None:
            return False

        password = questionary.password(
            "Coros password:",
            validate=lambda v: bool(v) or "Password is required.",
        ).ask()
        if password is None:
            return False

        region = questionary.select(
            "Region:",
            choices=[
                questionary.Choice(REGION_LABELS[r], value=r) for r in REGIONS
            ],
            default=REGION_LABELS[default_reg],
        ).ask()
        if region is None:
            return False

        print()
        print(f"Verifying credentials against the {region.upper()} API…")
        try:
            auth = asyncio.run(login(email.strip(), password, region, skip_mobile=True))
            print(f"✓ Authenticated as user {auth.user_id}.")
            print(
                "  (Mobile token — needed for sleep-stage data — was skipped. "
                "It will be obtained lazily on the first sleep query.)"
            )
            print()
            return True
        except Exception as exc:
            print(f"✗ Login failed: {exc}")
            if attempt < 2:
                print("  Let's try again. Wrong region is the usual cause.")
                print()

    print("Giving up after 3 attempts. Check your credentials and try again.")
    return False


def _pick_assistants(handlers: list[AssistantHandler]) -> list[str]:
    print(f"Detected {len(handlers)} assistant{'s' if len(handlers) != 1 else ''} on this machine.")
    print()

    choices = [
        questionary.Choice(h.label, value=h.key, checked=True) for h in handlers
    ]
    picks = questionary.checkbox(
        "Install Coros MCP into which assistants?",
        choices=choices,
    ).ask()
    return picks or []


def _resolve_server_command() -> list[str]:
    """Find the absolute path to the ``coros-mcp`` executable.

    MCP clients spawn a subprocess; they shouldn't have to search PATH, and
    the binary location is stable across invocations for both ``uv tool``
    and ``pipx`` installs. Falling back to ``sys.executable cli.py`` covers
    the dev-checkout case where the package isn't installed as a tool.
    """
    resolved = shutil.which("coros-mcp")
    if resolved:
        return [os.path.realpath(resolved), "serve"]
    # Dev / editable-install fallback.
    return [sys.executable, "-m", "cli", "serve"]


def _install_into(picks: Iterable[str], server_cmd: list[str]) -> None:
    print()
    print(f"Installing with command: {' '.join(server_cmd)}")
    print()
    for key in picks:
        handler = find_handler(key)
        if handler is None:
            continue
        result = handler.install(server_cmd)
        _print_result(result)


def _run_smoke_test() -> None:
    print()
    print("Running post-install smoke test (booting server over stdio)…")
    server_cmd = _resolve_server_command()
    result = smoke_test(server_cmd)
    if result.ok:
        print(f"✓ Smoke test passed — {result.detail}")
    else:
        print(f"⚠ Smoke test failed: {result.detail}")
        if result.stderr_tail:
            print("  Server stderr (tail):")
            for line in result.stderr_tail.splitlines():
                print(f"    {line}")
        print("  Install is still registered, but the server failed to boot.")
        print("  Run `coros-mcp auth-status` to check credentials.")


def _farewell(picks: list[str]) -> None:
    print()
    print("Next steps:")
    if any(k == "claude-desktop" for k in picks):
        print(
            "  • Claude Desktop: restart the app so it picks up the new MCP entry."
        )
    if any(k == "claude-code" for k in picks):
        print("  • Claude Code: ready to go — no restart needed.")
    if any(k == "codex" for k in picks):
        print("  • Codex: ready to go — no restart needed.")
    if any(k == "cursor" for k in picks):
        print("  • Cursor: restart the app so it picks up the new MCP entry.")
    print()
    print("Try it:")
    print('  "What workouts do I have scheduled this week?"')
    print('  "What was my HRV trend over the past month?"')
    print()
    print("Lifecycle:")
    print("  coros-mcp setup --reconfigure   reconfigure credentials or assistants")
    print("  coros-mcp uninstall             remove from assistants")
    print("  coros-mcp auth-status           check stored tokens")


def _print_result(result: InstallResult) -> None:
    icons = {
        "added": "✓",
        "replaced": "✓",
        "unchanged": "·",
        "skipped": "—",
        "failed": "✗",
    }
    icon = icons.get(result.action, "?")
    verbs = {
        "added": "installed",
        "replaced": "replaced existing entry",
        "unchanged": "already up to date",
        "skipped": "skipped",
        "failed": "failed",
    }
    verb = verbs.get(result.action, result.action)
    detail = f" — {result.detail}" if result.detail else ""
    print(f"  {icon} {result.assistant}: {verb}{detail}")


def _print_manual_instructions() -> None:
    server_cmd = _resolve_server_command()
    cmd_str = " ".join(server_cmd)
    print(
        "\nNo supported AI assistants detected on this machine.\n"
        "You can still add Coros MCP manually. The command to register is:\n\n"
        f"    {cmd_str}\n\n"
        "For Claude Desktop, add to the mcpServers block of your\n"
        "claude_desktop_config.json:\n\n"
        "    \"coros\": {\n"
        f"      \"command\": \"{server_cmd[0]}\",\n"
        f"      \"args\": {server_cmd[1:]!r}\n"
        "    }\n"
    )

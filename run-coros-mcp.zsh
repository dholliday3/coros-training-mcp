#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
COROS_MCP_BIN="$SCRIPT_DIR/.venv/bin/coros-mcp"
DEFAULT_REGION="us"
EMAIL_SERVICE="coros-mcp-email"
PASSWORD_SERVICE="coros-mcp-password"

usage() {
  cat <<'EOF'
Usage:
  run-coros-mcp.zsh [coros-mcp args...]

Behavior:
  - Defaults to `serve` when no args are provided
  - Loads COROS_EMAIL and COROS_PASSWORD from macOS Keychain if not already set
  - Sets COROS_REGION to `us` unless already set

Expected Keychain items:
  Service: coros-mcp-email
  Service: coros-mcp-password

Example:
  run-coros-mcp.zsh
  run-coros-mcp.zsh auth-status
EOF
}

read_keychain_secret() {
  local service="$1"
  /usr/bin/security find-generic-password -w -s "$service"
}

require_secret() {
  local name="$1"
  local service="$2"
  local value="${(P)name:-}"

  if [[ -n "$value" ]]; then
    return
  fi

  if ! value="$(read_keychain_secret "$service" 2>/dev/null)"; then
    echo "Missing Keychain item for $name (service: $service)." >&2
    echo "Add it with:" >&2
    echo "  security add-generic-password -U -a \"$USER\" -s \"$service\" -w '...'" >&2
    exit 1
  fi

  export "$name=$value"
}

main() {
  if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
  fi

  local -a args=("$@")
  if [[ "${#args[@]}" -eq 0 ]]; then
    args=("serve")
  fi

  export COROS_REGION="${COROS_REGION:-$DEFAULT_REGION}"
  require_secret "COROS_EMAIL" "$EMAIL_SERVICE"
  require_secret "COROS_PASSWORD" "$PASSWORD_SERVICE"

  exec "$COROS_MCP_BIN" "${args[@]}"
}

main "$@"

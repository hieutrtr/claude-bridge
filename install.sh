#!/usr/bin/env bash
# Claude Bridge — one-shot installer for a fresh machine.
#
# Installs Bun (if missing) and the @hieutrtr/claude-bridge npm package globally.
# Does NOT install the Claude Code CLI — that requires an Anthropic login flow;
# see https://docs.anthropic.com/en/docs/claude-code.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/hieutrtr/claude-bridge/main/install.sh | bash
#
# Or download and inspect first (recommended on shared/server machines):
#   curl -fsSL https://raw.githubusercontent.com/hieutrtr/claude-bridge/main/install.sh -o install.sh
#   less install.sh
#   bash install.sh

set -euo pipefail

PACKAGE="@hieutrtr/claude-bridge"

red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }
bold()  { printf "\033[1m%s\033[0m\n" "$*"; }

bold "==> Claude Bridge installer"

# ── Platform check ─────────────────────────────────────────────────────────
case "$(uname -s)" in
  Darwin|Linux) ;;
  *)
    red "ERROR: unsupported platform $(uname -s)."
    echo "Claude Bridge supports macOS and Linux. Windows users: use WSL2."
    exit 1
    ;;
esac

# ── Hard prerequisites ─────────────────────────────────────────────────────
need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    red "ERROR: '$1' is required but not found on PATH."
    echo "$2"
    exit 1
  fi
}

need_cmd git "Install git first:
  macOS:   xcode-select --install
  Debian:  sudo apt install git
  Fedora:  sudo dnf install git
  Arch:    sudo pacman -S git"

need_cmd curl "Install curl first via your package manager."

# ── Bun ────────────────────────────────────────────────────────────────────
if command -v bun >/dev/null 2>&1; then
  green "    Bun: $(bun --version)"
else
  bold "==> Installing Bun (https://bun.sh)"
  curl -fsSL https://bun.sh/install | bash
  # Make Bun visible to the rest of this script.
  export BUN_INSTALL="${BUN_INSTALL:-$HOME/.bun}"
  export PATH="$BUN_INSTALL/bin:$PATH"
  if ! command -v bun >/dev/null 2>&1; then
    red "ERROR: Bun installation finished but 'bun' is not on PATH."
    echo "Add this to your shell rc and re-run:"
    echo "  export BUN_INSTALL=\"\$HOME/.bun\""
    echo "  export PATH=\"\$BUN_INSTALL/bin:\$PATH\""
    exit 1
  fi
  green "    Bun installed: $(bun --version)"
fi

# ── Claude Code (warn, don't auto-install) ─────────────────────────────────
if command -v claude >/dev/null 2>&1; then
  green "    Claude Code: $(claude --version 2>/dev/null | head -1 || echo present)"
else
  yellow "    Claude Code CLI not found on PATH."
  echo "    Bridge depends on it for every dispatched task. Install it after"
  echo "    this script finishes: https://docs.anthropic.com/en/docs/claude-code"
fi

# ── Install claude-bridge ──────────────────────────────────────────────────
bold "==> Installing $PACKAGE globally with Bun"
bun install -g "$PACKAGE"

# Bun's global bin dir varies; surface it if 'bridge' is not on PATH yet.
if ! command -v bridge >/dev/null 2>&1; then
  BUN_BIN="$(bun pm bin -g 2>/dev/null || echo "$HOME/.bun/bin")"
  yellow ""
  yellow "    'bridge' is not on PATH yet. Add Bun's global bin to your shell rc:"
  echo "      export PATH=\"$BUN_BIN:\$PATH\""
  echo "    Then open a new terminal."
fi

green ""
green "==> Done."
echo "Next steps:"
echo "  1. Verify install:        bridge --help"
echo "  2. Check environment:     bridge doctor"
echo "  3. Scaffold a bot:        bridge setup-bot ~/projects/bridge-bot"
echo ""
echo "Docs: https://github.com/hieutrtr/claude-bridge#readme"

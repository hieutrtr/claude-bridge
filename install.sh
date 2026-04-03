#!/usr/bin/env sh
# Claude Bridge — Hero Installer
# https://github.com/hieutrtr/claude-bridge
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/hieutrtr/claude-bridge/main/install.sh | sh
#
# Or run locally:
#   ./install.sh
#
# What this does:
#   1. Checks prerequisites (Python 3.11+, Claude CLI)
#   2. Installs Bun if missing (channel server runtime)
#   3. Clones/updates the claude-bridge repo
#   4. Builds the channel server (TypeScript → JS bundle)
#   5. Installs the bridge-cli command via pipx or pip
#   6. Prints next steps (run: bridge-cli setup)

set -e

# ── Colors ────────────────────────────────────────────────────────────────────

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { printf "${BLUE}[claude-bridge]${NC} %s\n" "$1"; }
success() { printf "${GREEN}[claude-bridge]${NC} ✓ %s\n" "$1"; }
warn()    { printf "${YELLOW}[claude-bridge]${NC} ⚠ %s\n" "$1"; }
fail()    { printf "${RED}[claude-bridge]${NC} ✗ %s\n" "$1" >&2; exit 1; }

# ── Detect OS ─────────────────────────────────────────────────────────────────

detect_os() {
  case "$(uname -s)" in
    Darwin*) echo "macos" ;;
    Linux*)
      if grep -qi microsoft /proc/version 2>/dev/null; then
        echo "wsl"
      else
        echo "linux"
      fi
      ;;
    *) echo "unknown" ;;
  esac
}

# Detect Linux package manager (apt/dnf/pacman/zypper)
detect_linux_pkg_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "apt"
  elif command -v dnf >/dev/null 2>&1; then
    echo "dnf"
  elif command -v pacman >/dev/null 2>&1; then
    echo "pacman"
  elif command -v zypper >/dev/null 2>&1; then
    echo "zypper"
  else
    echo "unknown"
  fi
}

OS=$(detect_os)
info "Detected OS: $OS"

if [ "$OS" = "linux" ] || [ "$OS" = "wsl" ]; then
  LINUX_PKG=$(detect_linux_pkg_manager)
  info "Linux package manager: $LINUX_PKG"
fi

# ── Check: Python 3.11+ ───────────────────────────────────────────────────────

check_python() {
  command -v python3 >/dev/null 2>&1 || return 1
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}

if check_python; then
  PY_VER=$(python3 --version | cut -d' ' -f2)
  success "Python $PY_VER"
else
  case "$OS" in
    macos)
      fail "Python 3.11+ is required but not found.
  macOS:  brew install python@3.12
  All:    https://www.python.org/downloads/" ;;
    linux|wsl)
      case "${LINUX_PKG:-unknown}" in
        apt)     _py_hint="sudo apt install python3.12" ;;
        dnf)     _py_hint="sudo dnf install python3.12" ;;
        pacman)  _py_hint="sudo pacman -S python" ;;
        zypper)  _py_hint="sudo zypper install python312" ;;
        *)       _py_hint="see https://www.python.org/downloads/" ;;
      esac
      fail "Python 3.11+ is required but not found.
  Linux:  $_py_hint
  All:    https://www.python.org/downloads/" ;;
    *)
      fail "Python 3.11+ is required but not found.
  See: https://www.python.org/downloads/" ;;
  esac
fi

# ── Check: Claude CLI ─────────────────────────────────────────────────────────

if command -v claude >/dev/null 2>&1; then
  success "Claude CLI found"
else
  fail "Claude Code CLI not found.
  Install: npm install -g @anthropic-ai/claude-code
  Docs:    https://docs.anthropic.com/en/docs/claude-code"
fi

# ── Check/Install: Bun ────────────────────────────────────────────────────────

if command -v bun >/dev/null 2>&1; then
  BUN_VER=$(bun --version)
  success "Bun $BUN_VER"
else
  info "Bun not found — installing (required for channel server)..."
  curl -fsSL https://bun.sh/install | bash >/dev/null 2>&1 || true
  # Reload PATH for common Bun install locations
  export PATH="$HOME/.bun/bin:$PATH"
  if command -v bun >/dev/null 2>&1; then
    success "Bun $(bun --version) installed"
    warn "Add to shell: export PATH=\"\$HOME/.bun/bin:\$PATH\""
  else
    warn "Bun install may need a shell restart."
    warn "After restart, rerun: curl -fsSL https://raw.githubusercontent.com/hieutrtr/claude-bridge/main/install.sh | sh"
    fail "Bun not available in current session. Cannot build channel server."
  fi
fi

# ── Check: tmux (optional, needed for 'bridge start') ────────────────────────

if command -v tmux >/dev/null 2>&1; then
  success "tmux $(tmux -V | cut -d' ' -f2)"
else
  warn "tmux not found — 'bridge start' won't work without it."
  case "$OS" in
    macos) warn "  Install: brew install tmux" ;;
    linux|wsl)
      case "${LINUX_PKG:-unknown}" in
        apt)    warn "  Install: sudo apt install tmux" ;;
        dnf)    warn "  Install: sudo dnf install tmux" ;;
        pacman) warn "  Install: sudo pacman -S tmux" ;;
        zypper) warn "  Install: sudo zypper install tmux" ;;
        *)      warn "  Install tmux via your package manager" ;;
      esac ;;
  esac
fi

# ── Clone or update repo ──────────────────────────────────────────────────────

REPO_URL="https://github.com/hieutrtr/claude-bridge.git"
INSTALL_DIR="${CLAUDE_BRIDGE_SRC:-$HOME/projects/claude-bridge}"

if [ -d "$INSTALL_DIR/.git" ]; then
  info "Updating existing repo at $INSTALL_DIR ..."
  git -C "$INSTALL_DIR" pull --ff-only --quiet 2>/dev/null || warn "git pull failed — using existing version"
  success "Repo at $INSTALL_DIR (updated)"
else
  info "Cloning claude-bridge to $INSTALL_DIR ..."
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone --quiet "$REPO_URL" "$INSTALL_DIR" || fail "git clone failed. Check network or URL: $REPO_URL"
  success "Cloned to $INSTALL_DIR"
fi

# ── Install channel dependencies ──────────────────────────────────────────────

CHANNEL_DIR="$INSTALL_DIR/channel"
if [ ! -d "$CHANNEL_DIR/node_modules" ]; then
  info "Installing channel server dependencies (bun install)..."
  (cd "$CHANNEL_DIR" && bun install --quiet) || fail "bun install failed in $CHANNEL_DIR"
  success "Channel dependencies installed"
else
  info "Channel dependencies already installed (skip)"
fi

# ── Build channel server ──────────────────────────────────────────────────────

BUNDLE="$INSTALL_DIR/src/claude_bridge/channel_server/dist/server.js"
info "Building channel server (TypeScript → JS bundle)..."
(cd "$INSTALL_DIR" && bun run build) || fail "bun run build failed.
  Try manually: cd $INSTALL_DIR && bun run build"

if [ -f "$BUNDLE" ]; then
  BUNDLE_SIZE=$(wc -c < "$BUNDLE" | tr -d ' ')
  success "Channel server built (${BUNDLE_SIZE} bytes)"
else
  fail "Build succeeded but $BUNDLE not found. Check package.json build script."
fi

# ── Install bridge-cli ────────────────────────────────────────────────────────

INSTALLED_BY=""

# Try pipx first (isolated, recommended)
if command -v pipx >/dev/null 2>&1; then
  info "Installing bridge-cli via pipx..."
  pipx install --editable "$INSTALL_DIR" --quiet 2>/dev/null \
    || pipx install --editable "$INSTALL_DIR" 2>/dev/null \
    || true
  if command -v bridge-cli >/dev/null 2>&1; then
    INSTALLED_BY="pipx"
    success "Installed via pipx (isolated venv)"
  fi
fi

# Fallback: pip install
if [ -z "$INSTALLED_BY" ]; then
  info "Installing bridge-cli via pip..."
  python3 -m pip install --editable "$INSTALL_DIR" --quiet 2>/dev/null \
    || python3 -m pip install --editable "$INSTALL_DIR" --break-system-packages --quiet 2>/dev/null \
    || python3 -m pip install --editable "$INSTALL_DIR" --break-system-packages \
    || fail "pip install failed. Try manually:
      pip install -e $INSTALL_DIR
      or: pip install -e $INSTALL_DIR --break-system-packages"
  INSTALLED_BY="pip"
  success "Installed via pip"
fi

# ── Verify install ────────────────────────────────────────────────────────────

if command -v bridge-cli >/dev/null 2>&1; then
  BRIDGE_VER=$(bridge-cli --version 2>/dev/null || echo "unknown")
  success "bridge-cli installed: $BRIDGE_VER"
else
  warn "bridge-cli not in PATH yet."
  case "$INSTALLED_BY" in
    pipx) warn "  Run: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
    pip)  warn "  Run: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
  esac
  warn "  Or restart your terminal and rerun 'bridge-cli setup'"
fi

# ── Run doctor ────────────────────────────────────────────────────────────────

if command -v bridge-cli >/dev/null 2>&1; then
  echo ""
  info "Running health check..."
  bridge-cli doctor 2>/dev/null || true
fi

# ── Done — print next steps ───────────────────────────────────────────────────

echo ""
printf "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}\n"
printf "${GREEN}║     Claude Bridge installed successfully! 🎉             ║${NC}\n"
printf "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}\n"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Create a Telegram bot (if you haven't already):"
echo "       → Open Telegram → search @BotFather → /newbot"
echo ""
echo "  2. Run the setup wizard:"
echo ""
echo "       bridge-cli setup"
echo ""
echo "     The wizard will ask for your bot token and set everything up."
echo ""
echo "  3. Start the bridge bot:"
echo ""
echo "       bridge start"
echo ""
echo "  Other useful commands:"
echo "       bridge-cli doctor      — check installation health"
echo "       bridge-cli list-agents — show all agents"
echo "       bridge-cli --help      — full command reference"
echo ""
case "$INSTALLED_BY" in
  pipx) echo "  To update later: pipx upgrade claude-agent-bridge" ;;
  pip)  echo "  To update later: cd $INSTALL_DIR && git pull && pip install -e ." ;;
esac
echo ""

#!/bin/bash
# Build claude-bridge for distribution (PyPI)
# Usage: ./build.sh [--publish] [--test-publish]

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

step() { echo -e "\n${GREEN}==> $1${NC}"; }
fail() { echo -e "${RED}Error: $1${NC}" >&2; exit 1; }

# --- Check prerequisites ---
step "Checking prerequisites"

command -v bun >/dev/null || fail "bun not found. Install: curl -fsSL https://bun.sh/install | bash"
command -v python3 >/dev/null || fail "python3 not found"

python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" || fail "Python 3.11+ required"

echo "  bun $(bun --version)"
echo "  python3 $(python3 --version | cut -d' ' -f2)"

# --- Install build tools ---
step "Installing build tools"

python3 -m pip install build twine --break-system-packages --quiet 2>/dev/null || \
python3 -m pip install build twine --quiet 2>/dev/null || \
fail "Cannot install build tools. Try: pip install build twine"

# --- Install channel dependencies ---
step "Installing channel dependencies"

cd "$(dirname "$0")"
ROOT=$(pwd)

if [ ! -d channel/node_modules ]; then
    cd channel && bun install && cd "$ROOT"
else
    echo "  Already installed (skip)"
fi

# --- Build channel server ---
step "Building channel server (TypeScript → JS bundle)"

bun run build
BUNDLE="src/claude_bridge/channel_server/dist/server.js"

[ -f "$BUNDLE" ] || fail "Bundle not found at $BUNDLE"
SIZE=$(wc -c < "$BUNDLE" | tr -d ' ')
echo "  $BUNDLE ($SIZE bytes)"

# --- Build Python package ---
step "Building Python package"

rm -rf dist/ build/ *.egg-info src/*.egg-info
python3 -m build

echo "  Packages:"
ls -lh dist/

# --- Verify wheel contents ---
step "Verifying wheel contains channel server"

WHEEL=$(ls dist/*.whl 2>/dev/null | head -1)
if [ -n "$WHEEL" ]; then
    if python3 -c "import zipfile; z=zipfile.ZipFile('$WHEEL'); assert any('channel_server/dist/server.js' in n for n in z.namelist()), 'server.js not in wheel'"; then
        echo "  ✓ server.js found in wheel"
    else
        fail "server.js NOT found in wheel — check pyproject.toml package-data"
    fi
fi

# --- Publish ---
if [ "$1" = "--test-publish" ]; then
    step "Publishing to TestPyPI"
    twine upload --repository testpypi dist/*
    echo ""
    echo "Test install with:"
    echo "  pipx install --index-url https://test.pypi.org/simple/ claude-bridge"
elif [ "$1" = "--publish" ]; then
    step "Publishing to PyPI"
    echo "Version: $(python3 -c 'from claude_bridge import __version__; print(__version__)')"
    read -p "Continue? [y/N] " confirm
    [ "$confirm" = "y" ] || { echo "Cancelled."; exit 0; }
    twine upload dist/*
    echo ""
    echo "Install with:"
    echo "  pipx install claude-bridge"
else
    step "Done! Packages ready in dist/"
    echo ""
    echo "To publish:"
    echo "  ./build.sh --test-publish    # TestPyPI first"
    echo "  ./build.sh --publish         # Production PyPI"
fi

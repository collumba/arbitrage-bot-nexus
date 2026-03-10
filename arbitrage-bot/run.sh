#!/bin/bash
# ═══════════════════════════════════════════════════════════
# ARBITRAGE NEXUS v2 — Launch Script
# ═══════════════════════════════════════════════════════════

echo "╔══════════════════════════════════════════════════╗"
echo "║       ARBITRAGE NEXUS v2 — Starting...           ║"
echo "╚══════════════════════════════════════════════════╝"

cd "$(dirname "$0")"

# On Windows, 'python3' is often a Microsoft Store alias that doesn't work.
# Try 'python' first, then fall back to 'python3'.
if python --version 2>/dev/null | grep -q "Python 3"; then
    PY=python
elif python3 --version 2>/dev/null | grep -q "Python 3"; then
    PY=python3
else
    echo "ERROR: Python 3 not found. Install from https://python.org"
    read -p "Press Enter to exit..."
    exit 1
fi

echo "→ Using: $PY ($($PY --version 2>&1))"
echo "→ Dashboard: http://localhost:8888"
echo ""

$PY server.py

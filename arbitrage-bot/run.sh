#!/bin/bash
# ═══════════════════════════════════════════════════════════
# ARBITRAGE NEXUS v3 — Real Market Hunter
# ═══════════════════════════════════════════════════════════

echo "╔══════════════════════════════════════════════════╗"
echo "║   ARBITRAGE NEXUS v3 — REAL MARKET HUNTER        ║"
echo "╚══════════════════════════════════════════════════╝"

cd "$(dirname "$0")"

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
echo "→ Auto-installing ccxt if needed..."
echo "→ Dashboard: http://localhost:8888"
echo "→ Mode: AGGRESSIVE"
echo ""

$PY server.py

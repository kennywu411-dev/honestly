#!/bin/sh
# Every real CLI, every scenario: local stand-in for the model, no network beyond loopback, no route to the keychain. Exit code 1 when a scored scenario failed.
cd "$(dirname "$0")" || exit 2
PY=${PYTHON:-python3}
OUT=${HONESTLY_E2E_HOME:-$HOME/.cache/honestly-e2e}/results
mkdir -p "$OUT"
JOBS=${JOBS:-6} $PY run_claude.py > "$OUT/claude-guard.txt" 2>&1
JOBS=${JOBS:-6} $PY run_claude.py --form plugin 01 02 03 04 05 06- 07a 07b 13a 13d > "$OUT/claude-plugin.txt" 2>&1
JOBS=${JOBS:-6} $PY run_codex.py > "$OUT/codex.txt" 2>&1
JOBS=${JOBS:-6} $PY run_gemini.py > "$OUT/gemini.txt" 2>&1
$PY claude_market.py > "$OUT/claude-market.txt" 2>&1
$PY claude_tui.py > "$OUT/claude-tui.txt" 2>&1
$PY claude_sdk_shape.py > "$OUT/claude-sdk.txt" 2>&1
$PY codex_trust.py > "$OUT/codex-trust.txt" 2>&1
pkill -f "${HONESTLY_E2E_BOX:-/private/var/tmp/honestly-e2e}/codex/.*/app-server" 2>/dev/null
$PY summary.py > "$OUT/summary.md"
status=$?
tail -1 "$OUT/summary.md"
exit $status

#!/bin/sh
# Installs the real CLIs the scenarios run, under $HONESTLY_E2E_HOME only (default ~/.cache/honestly-e2e). Needs npm. No account, no key.
# Gemini CLI's native keychain module is then replaced by a logging stub, so no scenario can reach the macOS keychain through it.
set -e
HOME_E2E=${HONESTLY_E2E_HOME:-$HOME/.cache/honestly-e2e}
mkdir -p "$HOME_E2E/clis" "$HOME_E2E/results" "$HOME_E2E/recordings"
cd "$HOME_E2E"
install_cli() { mkdir -p "clis/$1"; ( cd "clis/$1"; [ -f package.json ] || npm init -y >/dev/null 2>&1; npm i --silent "$2" ); }
install_cli claude @anthropic-ai/claude-code
install_cli codex @openai/codex@0.167.0
install_cli gemini @google/gemini-cli@0.67.0
K=clis/gemini/node_modules/@github/keytar
if [ -d "$K" ] && [ ! -f "$K/.e2e-stub" ]; then
  mv "$K" clis/gemini/keytar.real; mkdir -p "$K"
  echo '{"name":"@github/keytar","version":"0.0.0-e2e-stub","main":"index.js"}' > "$K/package.json"
  cat > "$K/index.js" <<'JS'
// e2e stub: Gemini CLI loads this in place of the native keychain module. It records the call and fails, so nothing reaches the macOS keychain.
const fs = require('fs');
const rec = (op, a) => { try { fs.appendFileSync(process.env.HX_KEYCHAIN_LOG || '/dev/null', JSON.stringify({op, service: a[0], account: a[1], pid: process.pid}) + '\n'); } catch (e) {} };
const fail = (op) => async (...a) => { rec(op, a); throw new Error('keychain disabled by the e2e harness'); };
module.exports = { getPassword: fail('getPassword'), setPassword: fail('setPassword'), deletePassword: fail('deletePassword'), findPassword: fail('findPassword'), findCredentials: fail('findCredentials') };
JS
  touch "$K/.e2e-stub"
fi
echo "ready: pip install -e . pexpect pyte, then tests/e2e/run_all.sh"

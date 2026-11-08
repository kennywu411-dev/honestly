"""Look through every log this audit wrote for credential-shaped values. Prints file names and counts only, never a value."""
import collections, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import BOX, S
ROOTS = sys.argv[1:] or [BOX, os.path.join(S, "results"), os.path.join(S, "recordings")]
PATS = {
  "anthropic-key": re.compile(rb"sk-ant-[A-Za-z0-9_-]{10,}"),
  "openai-key": re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
  "google-key": re.compile(rb"\bAIza[A-Za-z0-9_-]{30,}"),
  "bearer": re.compile(rb"Bearer\s+[A-Za-z0-9._~+/=-]{16,}"),
  "auth-field": re.compile(rb"(?i)[\"'](?:x-api-key|x-goog-api-key|authorization)[\"']\s*:\s*[\"'](?!standin-dummy)[^\"']{6,}"),
  "oauth-json": re.compile(rb"claudeAiOauth|\"accessToken\"\s*:|\"refreshToken\"\s*:|\"refresh_token\"\s*:"),
  "jwt": re.compile(rb"\beyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}"),
}
files = 0; hits = collections.defaultdict(collections.Counter); skipped = 0
for root in ROOTS:
    for dp, _, fn in os.walk(root):
        if "node_modules" in dp or "packages/app-server-daemon" in dp or "/.tmp/plugins" in dp or "/.codex/plugins" in dp or "/skills/" in dp:
            continue   # public plugin docs the CLIs fetched or ship, not logs of this audit
        for f in fn:
            p = os.path.join(dp, f)
            try:
                if os.path.getsize(p) > 200_000_000 or os.path.islink(p): skipped += 1; continue
                b = open(p, "rb").read()
            except OSError:
                continue
            files += 1
            for name, pat in PATS.items():
                n = len(pat.findall(b))
                if n: hits[p][name] += n
print("files scanned", files, "skipped", skipped, "files with a hit", len(hits))
by = collections.Counter()
for p, c in hits.items():
    for k in c: by[(k, os.path.basename(p) if not os.path.basename(p).startswith(("rollout", "session-", "transcript-at")) and not p.endswith(".jsonl") else "*" + os.path.splitext(p)[1])] += 1
print("by pattern and file kind (counts of files):", by.most_common(30))
for p, c in list(hits.items())[:40]:
    print(p.replace(BOX, "$BOX"), dict(c))

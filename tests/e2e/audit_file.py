"""What honestly's parser and rules make of a recording: audit_file.py claude|codex|gemini <file> [--tail]"""
import sys
from honestly.audit import audit_turn
agent, path = sys.argv[1], sys.argv[2]
if agent == "claude":
    from honestly.claude_code import parse_session
    turns = parse_session(path, tail="--tail" in sys.argv)
elif agent == "codex":
    from honestly.codex import parse_session
    turns = parse_session(path)
else:
    from honestly.agents import gemini_parse
    turns = gemini_parse(path)
for i, t in enumerate(turns):
    print(f"TURN {i} prompt={t.prompt[:80]!r} model={t.model}")
    for e in t.events:
        print("   ", e.kind, e.name, repr(e.text[:90]), ("via=" + e.via) if e.via else "", "err" if e.is_error else "", repr(e.result[:120]) if e.kind == "tool" else "")
    for f in audit_turn(t, turns[i - 1] if i else None):
        print("   VERDICT", f.verdict, repr(f.claim[:80]), f.reason)

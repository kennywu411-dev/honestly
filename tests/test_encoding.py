import json, os, tempfile
from honestly import claude_code


def test_claude_session_read_as_utf8_regardless_of_locale():
    # Windows opens files in cp1252/cp936 by default; a UTF-8 log with an en dash and Chinese must survive.
    d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "proj")); p = os.path.join(d, "proj", "s1.jsonl")
    rows = [
        {"type": "user", "uuid": "u1", "timestamp": "2026-10-28T00:00:00Z", "cwd": "/x",
         "message": {"role": "user", "content": "hi"}},
        {"type": "assistant", "uuid": "a1", "parentUuid": "u1", "timestamp": "2026-10-28T00:00:01Z", "version": "2.1.0",
         "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": "TG\u2013MS 修复了。"}]}},
    ]
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    turns = claude_code.parse_session(p)
    texts = " ".join(e.text for t in turns for e in t.events if e.kind == "text")
    assert "TG\u2013MS" in texts and "修复了" in texts

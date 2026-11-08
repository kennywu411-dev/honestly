"""Local stand-in for the three model APIs (Anthropic Messages, OpenAI Responses, Gemini generateContent).

Replies are scripted. A script is a list of steps; a step is a list of blocks or a callable(request_body) -> blocks.
Blocks: {"text": s} | {"tool": name, "input": {...}} | {"custom": name, "input": "text"} (Responses custom tool)
        | {"raw": item} (a Responses output item as is), and as control blocks {"usage": input_tokens}
        (a large prompt, drives auto-compaction) and {"sleep": seconds}.
Requests the CLI makes for itself (titles, compaction, next-speaker checks) get their own canned reply and never use up a step.
No auth value is ever logged or kept: each request only adds to a count of dummy / none / OTHER (self.auth_seen), and a `key=` in a
query string is masked before the path is logged. This binds to 127.0.0.1 only.
"""
import collections, http.server, json, os, re, threading, time, uuid

DUMMY = "standin-dummy"


class Standin:
    def __init__(self):
        self.main, self.sub, self.log = [], [], []
        self.latency = float(os.environ.get("STANDIN_LATENCY", "0.6"))   # seconds before each scripted reply, like a real model. At 0 Claude Code's stop hook reads a stale transcript: see race_flush.py
        self.auth_seen = collections.Counter()
        self.sub_marker = "SUBTASK:"
        self.summary_text = "<summary>Summary: the user asked for work; an edit was made to app.py.</summary>"
        self.dump = None     # path of a jsonl file that gets every full request body
        self.lock = threading.Lock()
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *a): pass
            def _json(self, obj, code=200):
                b = json.dumps(obj).encode()
                self.send_response(code); self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
            def _sse_head(self):
                self.send_response(200); self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache"); self.send_header("connection", "close"); self.end_headers()
                self.close_connection = True
            def do_HEAD(self):
                self.send_response(200); self.send_header("content-length", "0"); self.end_headers()
            def do_GET(self):
                outer._note_auth(self.headers, self.path)
                self.path = re.sub(r"([?&]key=)[^&]*", r"\1***", self.path)
                outer._rec({"kind": "get", "path": self.path})
                return self._json({"models": [], "data": [], "object": "list"})
            def do_POST(self):
                outer._note_auth(self.headers, self.path)
                self.path = re.sub(r"([?&]key=)[^&]*", r"\1***", self.path)
                raw = self.rfile.read(int(self.headers.get("content-length", 0) or 0))
                try:
                    body = json.loads(raw or b"{}")
                except Exception:
                    body = {}
                p = self.path
                if "/v1/messages/count_tokens" in p:
                    return self._json({"input_tokens": 100})
                if "/v1/messages" in p:
                    return outer._anthropic(self, body)
                if "/responses/compact" in p:
                    outer._rec({"kind": "compact", "path": p, "reply": []}, body)
                    return self._json({"output": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Summary: the user asked for work; app.py was edited."}]}]})
                if "/responses" in p:
                    return outer._responses(self, body)
                if "countTokens" in p:
                    return self._json({"totalTokens": 10})
                if ":generateContent" in p:
                    outer._rec({"kind": "aux", "path": p, "snapshot": "state_snapshot" in json.dumps(body)}, body)
                    return self._json({"candidates": [{"content": {"role": "model", "parts": [{"text": outer.gemini_aux(body)}]}, "finishReason": "STOP"}], "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2}})
                if ":streamGenerateContent" in p:
                    return outer._gemini(self, body)
                outer._rec({"kind": "other", "path": p})
                return self._json({})
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"

    def _note_auth(self, headers, path):
        """Classify what a request authenticates with, and keep only the class."""
        vals = [headers.get(k) for k in ("x-api-key", "x-goog-api-key", "authorization", "api-key") if headers.get(k)]
        m = re.search(r"[?&]key=([^&]*)", path)
        if m:
            vals.append(m.group(1))
        vals = [re.sub(r"(?i)^bearer\s+", "", v).strip() for v in vals]
        with self.lock:
            self.auth_seen["none" if not vals else "dummy" if all(v == DUMMY for v in vals) else "OTHER"] += 1

    def reset(self, main=None, sub=None, dump=None):
        with self.lock:
            self.main, self.sub, self.log = list(main or []), list(sub or []), []
            self.dump = dump

    def _rec(self, entry, body=None):
        entry["t"] = time.time()
        with self.lock:
            self.log.append(entry)
            if self.dump and body is not None:
                with open(self.dump, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"entry": {k: v for k, v in entry.items() if k != "reply"}, "body": body}, ensure_ascii=False) + "\n")

    def _next(self, script, body):
        time.sleep(self.latency)
        with self.lock:
            step = script.pop(0) if script else None
        if step is None:
            return [{"text": "(script ran out)"}], True
        if callable(step):
            step = step(body)
        return step, False

    def _controls(self, blocks):
        usage = None
        for b in blocks:
            if "sleep" in b:
                time.sleep(b["sleep"])
            if "usage" in b:
                usage = b["usage"]
        return [b for b in blocks if "sleep" not in b and "usage" not in b], usage

    # ---------------------------------------------------------------- Anthropic
    @staticmethod
    def _a_text(content):
        if isinstance(content, str):
            return content
        out = []
        for b in content or []:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    out.append(str(b.get("text") or ""))
                elif b.get("type") == "tool_result":
                    c = b.get("content")
                    out.append(c if isinstance(c, str) else " ".join(str(x.get("text") or "") for x in c or [] if isinstance(x, dict)))
        return " ".join(out)

    def _anthropic(self, h, body):
        msgs = body.get("messages") or []
        tools = body.get("tools") or []
        all_text = " ".join(self._a_text(m.get("content")) for m in msgs[:2])
        last = msgs[-1] if msgs else {}
        last_text = self._a_text(last.get("content"))
        ai = max([i for i, m in enumerate(msgs) if m.get("role") == "assistant"] or [-1])
        since = "\n".join(self._a_text(m.get("content")) for m in msgs[ai + 1:])
        sys_txt = body.get("system")
        sys_txt = sys_txt if isinstance(sys_txt, str) else " ".join(str(x.get("text") or "") for x in sys_txt or [] if isinstance(x, dict))
        low = since.lower()
        is_compact = ("summary of the conversation" in last_text.lower() or "summarizing conversations" in sys_txt.lower()
                      or "create a detailed summary" in low or "block followed by a <summary>" in low or "how to write this summary" in low or "how to summarize" in low)
        if is_compact:
            kind, blocks, usage = "compact", [{"text": self.summary_text}], None
        elif not tools:
            kind, blocks, usage = "aux", [{"text": "ok"}], None
        else:
            is_sub = self.sub_marker in all_text
            kind = "sub" if is_sub else "main"
            blocks, ran_out = self._next(self.sub if is_sub else self.main, body)
            blocks, usage = self._controls(blocks)
            if ran_out:
                kind += ":ran-out"
        self._rec({"kind": kind, "path": h.path, "model": body.get("model"), "n": len(msgs), "tools": [t.get("name") for t in tools][:80],
                   "last_role": last.get("role"), "since_assistant": since[-6000:], "reply": blocks}, body)
        model = body.get("model") or "claude-standin"
        usage_in = usage or 100
        mid = "msg_" + uuid.uuid4().hex[:20]
        content = []
        for b in blocks:
            if "text" in b:
                content.append({"type": "text", "text": b["text"]})
            elif "tool" in b:
                content.append({"type": "tool_use", "id": "toolu_" + uuid.uuid4().hex[:20], "name": b["tool"], "input": b["input"]})
        stop = "tool_use" if any(c["type"] == "tool_use" for c in content) else "end_turn"
        u = {"input_tokens": usage_in, "output_tokens": 10, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        if not body.get("stream"):
            return h._json({"id": mid, "type": "message", "role": "assistant", "model": model, "content": content, "stop_reason": stop, "stop_sequence": None, "usage": u})
        h._sse_head()
        def ev(name, data):
            h.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()); h.wfile.flush()
        ev("message_start", {"type": "message_start", "message": {"id": mid, "type": "message", "role": "assistant", "model": model, "content": [], "stop_reason": None, "stop_sequence": None, "usage": u}})
        for i, c in enumerate(content):
            if c["type"] == "text":
                ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})
                ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": c["text"]}})
            else:
                ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "tool_use", "id": c["id"], "name": c["name"], "input": {}}})
                ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": json.dumps(c["input"])}})
            ev("content_block_stop", {"type": "content_block_stop", "index": i})
        ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 10}})
        ev("message_stop", {"type": "message_stop"})

    # ---------------------------------------------------------------- OpenAI Responses
    def _responses(self, h, body):
        inp = body.get("input") or []
        tools = body.get("tools") or []
        def text_of(item):
            if not isinstance(item, dict):
                return str(item)
            if item.get("type") in ("function_call_output", "custom_tool_call_output"):
                o = item.get("output")
                return o if isinstance(o, str) else json.dumps(o, ensure_ascii=False)
            c = item.get("content")
            if isinstance(c, str):
                return c
            return " ".join(str(x.get("text") or "") for x in c or [] if isinstance(x, dict))
        last = inp[-1] if isinstance(inp, list) and inp else {}
        ai = max([i for i, x in enumerate(inp) if isinstance(x, dict) and (x.get("role") == "assistant" or x.get("type") in ("function_call", "custom_tool_call"))] or [-1]) if isinstance(inp, list) else -1
        since = "\n".join(text_of(x) for x in inp[ai + 1:]) if isinstance(inp, list) else str(inp)
        first = " ".join(text_of(x) for x in inp[:6]) if isinstance(inp, list) else str(inp)
        is_sub = self.sub_marker in first and self.sub
        is_compact = "seamlessly continue the work" in since or "CONTEXT CHECKPOINT COMPACTION" in since
        is_title = "task title" in text_of(last)[:200]
        if is_compact:
            blocks, ran_out, usage = [{"text": "Summary: the user asked for work; app.py was edited."}], False, None
        elif is_title:
            blocks, ran_out, usage = [{"text": '{"title": "Do the work"}'}], False, None
        else:
            blocks, ran_out = self._next(self.sub if is_sub else self.main, body)
            blocks, usage = self._controls(blocks)
        kind = "aux" if is_title else "compact" if is_compact else "sub" if is_sub else "main"
        self._rec({"kind": kind + (":ran-out" if ran_out else ""), "path": h.path, "model": body.get("model"), "n": len(inp) if isinstance(inp, list) else 1,
                   "tools": [t.get("name") or t.get("type") for t in tools], "last_type": last.get("type") if isinstance(last, dict) else "",
                   "since_assistant": since[-6000:], "reply": blocks}, body)
        rid = "resp_" + uuid.uuid4().hex[:20]
        h._sse_head()
        def ev(data):
            h.wfile.write(f"event: {data['type']}\ndata: {json.dumps(data)}\n\n".encode()); h.wfile.flush()
        ev({"type": "response.created", "response": {"id": rid}})
        for b in blocks:
            if "raw" in b:
                item = b["raw"]
            elif "text" in b:
                item = {"type": "message", "id": "msg_" + uuid.uuid4().hex[:12], "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": b["text"], "annotations": []}]}
            elif "tool" in b:
                item = {"type": "function_call", "id": "fc_" + uuid.uuid4().hex[:12], "name": b["tool"], "arguments": json.dumps(b["input"]), "call_id": "call_" + uuid.uuid4().hex[:12], "status": "completed"}
            else:
                item = {"type": "custom_tool_call", "id": "ctc_" + uuid.uuid4().hex[:12], "name": b["custom"], "input": b["input"], "call_id": "call_" + uuid.uuid4().hex[:12], "status": "completed"}
            ev({"type": "response.output_item.added", "item": item, "output_index": 0})
            ev({"type": "response.output_item.done", "item": item, "output_index": 0})
        ev({"type": "response.completed", "response": {"id": rid, "usage": {"input_tokens": usage or 100, "input_tokens_details": None, "output_tokens": 10, "output_tokens_details": None, "total_tokens": (usage or 100) + 10}}})

    # ---------------------------------------------------------------- Gemini
    def gemini_aux(self, body):
        if "state_snapshot" in json.dumps(body):
            return "<state_snapshot>The user asked for work. app.py was edited. Nothing else is known.</state_snapshot>"
        return '{"next_speaker":"user","reasoning":"done","complexity_reasoning":"x","complexity_score":10}'

    def _gemini(self, h, body):
        contents = body.get("contents") or []
        tools = [d.get("name") for t in body.get("tools") or [] if isinstance(t, dict) for d in t.get("functionDeclarations") or t.get("function_declarations") or []]
        first = json.dumps(contents[:2], ensure_ascii=False)
        is_sub = self.sub_marker in first and bool(self.sub)
        blocks, ran_out = self._next(self.sub if is_sub else self.main, body)
        blocks, usage = self._controls(blocks)
        kind = "sub" if is_sub else "main"
        self._rec({"kind": kind + (":ran-out" if ran_out else ""), "path": h.path, "n": len(contents), "tools": tools, "since_assistant": json.dumps(contents[-1], ensure_ascii=False)[-6000:] if contents else "", "reply": blocks}, body)
        parts = []
        for b in blocks:
            if "text" in b:
                parts.append({"text": b["text"]})
            elif "tool" in b:
                parts.append({"functionCall": {"name": b["tool"], "args": b["input"]}})
        data = {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}], "usageMetadata": {"promptTokenCount": usage or 1, "candidatesTokenCount": 1, "totalTokenCount": (usage or 1) + 1}}
        h._sse_head()
        h.wfile.write(("data: " + json.dumps(data) + "\n\n").encode()); h.wfile.flush()

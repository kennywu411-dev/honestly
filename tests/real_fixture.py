"""Sessions the real CLIs recorded (trimmed by tests/e2e/make_fixtures.py), laid out in a temp folder the way each CLI lays them out."""
import glob
import json
import os
import shutil

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "real")


def _fill(folder: str, tasks: str):
    for dp, _, names in os.walk(folder):
        for n in names:
            p = os.path.join(dp, n)
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
            if "__TASKS__" in text:
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(text.replace("__TASKS__", json.dumps(tasks)[1:-1]))   # inside a JSON string: a Windows path has to stay valid


def load(tmp_path, cli: str, name: str, until: str = "", tasks: dict = None) -> str:
    """The main transcript of a recorded session in tmp_path, cut right after the assistant record holding `until` when that is given:
    what the stop hook saw when that sentence was the reply. `tasks`: background task id -> what its output file holds."""
    dest = os.path.join(str(tmp_path), cli, name)
    shutil.copytree(os.path.join(ROOT, cli, name), dest)
    task_dir = os.path.join(str(tmp_path), "scratch", "tasks")
    os.makedirs(task_dir, exist_ok=True)
    for task, text in (tasks or {}).items():
        with open(os.path.join(task_dir, f"{task}.output"), "w", encoding="utf-8") as fh:
            fh.write(text)
    _fill(dest, task_dir)
    if cli == "claude":
        path = os.path.join(dest, "session.jsonl")
    elif cli == "codex":
        files = glob.glob(os.path.join(dest, "sessions", "*", "*", "*", "*.jsonl"))
        path = next(f for f in sorted(files) if '"thread_source": "user"' in open(f, encoding="utf-8").readline() or len(files) == 1)
    else:
        path = glob.glob(os.path.join(dest, "proj", "chats", "session-*.jsonl"))[0]
    if until:
        cut(path, until)
    return path


def _says(row: dict, text: str) -> bool:
    if row.get("type") == "gemini":
        return text in json.dumps(row.get("content"), ensure_ascii=False)
    if row.get("type") == "assistant":
        return text in json.dumps(row.get("message", {}).get("content"), ensure_ascii=False)
    p = row.get("payload") or {}
    return row.get("type") == "response_item" and p.get("role") == "assistant" and text in json.dumps(p.get("content"), ensure_ascii=False)


def cut(path: str, until: str, nth: int = 1) -> None:
    kept, seen = [], 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            kept.append(line)
            if _says(json.loads(line), until):
                seen += 1
                if seen == nth:
                    break
    assert seen == nth, f"{until!r} not found {nth} time(s) in {path}"
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(kept)

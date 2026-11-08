"""Edit the hooks section of an assistant's settings file and leave the rest of the file as it was.

The file belongs to the user. It is edited as text, so formatting, number spellings, escapes, key order and the user's own hooks
keep their exact bytes, and uninstalling after installing gives back the same file. Only entries `hookline` recognises as ours are
ever removed. Anything that cannot be parsed, or that would have to be overwritten to add our entry, is refused.
"""
from __future__ import annotations

import json
import os
import re
from json.decoder import scanstring

from . import config, hookline

_WS = re.compile(r"[ \t\r\n]*")
_DECODER = json.JSONDecoder()


class Refused(Exception):
    """One line for the user: the file was left as it is."""


# --------------------------------------------------------------- positions in the text
class _Item:
    __slots__ = ("key", "head", "start", "end")

    def __init__(self, key, head, start, end):
        self.key, self.head, self.start, self.end = key, head, start, end   # head: where the item begins (for an object member, its key)


def _items(text: str, start: int) -> tuple:
    """The items of the object or array opening at `start`, and the position of its closing bracket. The text is already known to be valid JSON."""
    is_object = text[start] == "{"
    close = "}" if is_object else "]"
    items, i = [], _WS.match(text, start + 1).end()
    while text[i] != close:
        head, key = i, None
        if is_object:
            key, i = scanstring(text, i + 1)
            i = _WS.match(text, _WS.match(text, i).end() + 1).end()   # past the colon
        value_start = i
        _, i = _DECODER.raw_decode(text, i)
        items.append(_Item(key, head, value_start, i))
        i = _WS.match(text, i).end()
        if text[i] == ",":
            i = _WS.match(text, i + 1).end()
    return items, i


def _pick(items: list, step):
    if isinstance(step, int):
        return step
    return max(k for k, item in enumerate(items) if item.key == step)   # the last of a repeated key: the one json.loads keeps


def _locate(text: str, path: tuple) -> int:
    pos = _WS.match(text).end()
    for step in path:
        items, _ = _items(text, pos)
        pos = items[_pick(items, step)].start
    return pos


# --------------------------------------------------------------- the file's own style
def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _unit(text: str) -> str:
    m = re.search(r"\n([ \t]+)\S", text)
    return m.group(1) if m else "  "


def _line_indent(text: str, pos: int) -> str:
    line = text[text.rfind("\n", 0, pos) + 1:pos]
    return line[:len(line) - len(line.lstrip(" \t"))]


def _one_line(text: str) -> bool:
    return "\n" not in text.strip()


def _render(value, text: str, indent: str, inline: bool) -> str:
    if inline:
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False, indent=_unit(text)).replace("\n", _newline(text) + indent)


# --------------------------------------------------------------- the three edits
def _append(text: str, path: tuple, key, value) -> str:
    pos = _locate(text, path)
    items, close = _items(text, pos)
    label = "" if key is None else json.dumps(key, ensure_ascii=False) + ": "
    nl = _newline(text)
    if items:
        lead = text[pos + 1:items[0].head]
        last = items[-1]
        if "\n" in lead:
            indent = lead[lead.rfind("\n") + 1:]
            return text[:last.end] + "," + nl + indent + label + _render(value, text, indent, False) + text[last.end:]
        between = text[items[0].end + 1:items[1].head] if len(items) > 1 else " "
        indent = between[between.rfind("\n") + 1:] if "\n" in between else ""
        return text[:last.end] + "," + between + label + _render(value, text, indent, not indent) + text[last.end:]
    if _one_line(text):
        return text[:pos + 1] + label + _render(value, text, "", True) + text[close:]
    outer = _line_indent(text, pos)
    indent = outer + _unit(text)
    return text[:pos + 1] + nl + indent + label + _render(value, text, indent, False) + nl + outer + text[close:]


def _remove(text: str, path: tuple, step) -> str:
    pos = _locate(text, path)
    items, close = _items(text, pos)
    k = _pick(items, step)
    if len(items) == 1:
        return text[:pos + 1] + text[close:]
    if k == len(items) - 1:
        return text[:items[k - 1].end] + text[items[k].end:]
    return text[:items[k].head] + text[items[k + 1].head:]


def _replace(text: str, path: tuple, value) -> str:
    pos = _locate(text, path)
    _, end = _DECODER.raw_decode(text, pos)
    return text[:pos] + _render(value, text, _line_indent(text, pos), _one_line(text)) + text[end:]


# --------------------------------------------------------------- reading
def read(path: str) -> tuple:
    """(raw bytes or None, BOM, text, parsed object). Raises Refused for a file that cannot be understood; a missing or empty file is an empty object."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except (FileNotFoundError, NotADirectoryError):
        return None, "", "", {}
    except OSError as e:
        raise Refused(f"cannot read {path}: {e.strerror}  (the file was left untouched)") from None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise Refused(f"cannot read {path}: {e}  (the file was left untouched)") from None
    bom = "﻿" if decoded.startswith("﻿") else ""
    text = decoded[len(bom):]
    if not text.strip():
        return raw, bom, text, {}
    try:
        obj = json.loads(text)
    except ValueError as e:
        raise Refused(f"cannot read {path}: {e}  (the file was left untouched)") from None
    except RecursionError:
        raise Refused(f"cannot read {path}: nested too deeply  (the file was left untouched)") from None
    if not isinstance(obj, dict):
        raise Refused(f"{path} is not a JSON object (the file was left untouched)")
    return raw, bom, text, obj


def hook_events(obj: dict, flat: bool = False) -> list:
    """The events holding one of our entries."""
    hooks = obj.get("hooks")
    if not isinstance(hooks, dict):
        return []
    return [ev for ev, entries in hooks.items() if any(True for _ in _ours_in(entries, flat))]


def _ours_in(entries, flat: bool):
    """Every entry of ours under one event."""
    for g in entries if isinstance(entries, list) else []:
        if flat:
            if hookline.is_ours(g):
                yield g
        elif isinstance(g, dict) and isinstance(g.get("hooks"), list):
            for h in g["hooks"]:
                if hookline.is_ours(h):
                    yield h


def commands(obj: dict, flat: bool = False) -> list:
    """Our entries in the file, in order."""
    hooks = obj.get("hooks")
    if not isinstance(hooks, dict):
        return []
    return [h for entries in hooks.values() for h in _ours_in(entries, flat)]


# --------------------------------------------------------------- planning
def _split_group(group) -> tuple:
    """(positions of our hooks in this group, how many hooks it holds)."""
    if isinstance(group, dict) and isinstance(group.get("hooks"), list):
        return [j for j, h in enumerate(group["hooks"]) if hookline.is_ours(h)], len(group["hooks"])
    return [], 0


def _install_event(text: str, event: str, item, flat: bool) -> str:
    hooks = json.loads(text)["hooks"]
    if event not in hooks:
        return _append(text, ("hooks",), event, [item])
    current = hooks[event]
    if current is None:
        return _replace(text, ("hooks", event), [item])
    whole, mixed = [], []
    for i, group in enumerate(current):
        if flat:
            if hookline.is_ours(group):
                whole.append(i)
            continue
        ours, total = _split_group(group)
        if ours and len(ours) == total:
            whole.append(i)
        elif ours:
            mixed.append((i, ours))
    if len(whole) == 1 and not mixed and current[whole[0]] == item:
        return text
    for i, ours in reversed(mixed):   # a group shared with the user's own hook: only our hook leaves it
        for j in reversed(ours):
            text = _remove(text, ("hooks", event, i, "hooks"), j)
    for i in reversed(whole[1:]):
        text = _remove(text, ("hooks", event), i)
    if whole:
        return _replace(text, ("hooks", event, whole[0]), item)   # an upgrade keeps its place
    return _append(text, ("hooks", event), None, item)


def _install(path: str, text: str, obj: dict, entries: dict, flat: bool, top: dict) -> str:
    hooks = obj.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        raise Refused(f'the "hooks" value in {path} is not an object, and adding to it would overwrite it (the file was left untouched)')
    for event in entries:
        value = (hooks or {}).get(event)
        if value is not None and not isinstance(value, list):
            raise Refused(f'the "hooks.{event}" value in {path} is not a list, and adding to it would overwrite it (the file was left untouched)')
    text = text if text.strip() else "{}\n"
    if hooks is None:
        text = _replace(text, ("hooks",), {}) if "hooks" in obj else _append(text, (), "hooks", {})
    for event, items in entries.items():
        for item in items:
            text = _install_event(text, event, item, flat)
    for key, value in (top or {}).items():
        if key not in obj:
            text = _append(text, (), key, value)
    return text


def _uninstall(text: str, obj: dict, flat: bool) -> str:
    hooks = obj.get("hooks")
    if not isinstance(hooks, dict):
        return text
    removed_any = False
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        left, removed = len(groups), False
        for i, group in reversed(list(enumerate(groups))):
            if flat:
                if hookline.is_ours(group):
                    text = _remove(text, ("hooks", event), i)
                    left, removed = left - 1, True
                continue
            ours, total = _split_group(group)
            if ours and len(ours) == total:
                text = _remove(text, ("hooks", event), i)
                left, removed = left - 1, True
            elif ours:
                for j in reversed(ours):
                    text = _remove(text, ("hooks", event, i, "hooks"), j)
                removed = True
        if removed and not left:
            text = _remove(text, ("hooks",), event)
        removed_any = removed_any or removed
    if removed_any and not json.loads(text)["hooks"]:
        text = _remove(text, (), "hooks")
    return text


def _without_ours(obj: dict, flat: bool, top: dict) -> dict:
    """The file's content once our entries, and what an edit may legitimately add or tidy around them, are set aside."""
    out = {k: v for k, v in obj.items() if k != "hooks" and k not in (top or {})}
    hooks = obj.get("hooks")
    if hooks is None or hooks == {}:
        return out
    if not isinstance(hooks, dict):
        out["hooks"] = hooks
        return out
    kept = {}
    for event, groups in hooks.items():
        if groups is None or groups == []:
            continue
        if not isinstance(groups, list):
            kept[event] = groups
            continue
        left = []
        for g in groups:
            if flat:
                if not hookline.is_ours(g):
                    left.append(g)
                continue
            ours, total = _split_group(g)
            if ours and len(ours) == total:
                continue
            left.append({**g, "hooks": [h for j, h in enumerate(g["hooks"]) if j not in ours]} if ours else g)
        if left:
            kept[event] = left
    if kept:
        out["hooks"] = kept
    return out


# --------------------------------------------------------------- the one entry point
def change(path: str, action: str, entries: dict, flat: bool = False, dry_run: bool = False, top: dict = None) -> tuple:
    """Apply install or uninstall. Returns (what happened, the object now in effect): "unchanged", "changed" (dry run), "written" or "removed".
    `top` holds keys the file format needs (Cursor's version) that do not count as the user's content."""
    for _ in range(3):   # another program may write the file while this runs: start again from what it wrote
        raw, bom, text, obj = read(path)
        new = _install(path, text, obj, entries, flat, top) if action == "install" else _uninstall(text, obj, flat)
        if new == text:
            return "unchanged", obj
        after = json.loads(new)
        if _without_ours(obj, flat, top) != _without_ours(after, flat, top):
            raise Refused("the edit would have changed something other than honestly's own entries, so it was not written; please report this with `honestly feedback --issue`")
        if dry_run:
            return "changed", after
        if action == "uninstall" and not _without_ours(after, flat, top) and not os.path.islink(path):
            os.remove(path)   # it held nothing but our entries
            return "removed", after
        try:
            config.write_text_atomic(path, bom + new, backup=raw is not None, expect=raw, check_expect=True)
        except config.FileChanged:
            continue
        return "written", after
    raise Refused(f"{path} keeps changing while honestly edits it; try again (the file was left untouched)")

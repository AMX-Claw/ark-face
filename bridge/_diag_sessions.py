#!/usr/bin/env python3
"""One-off diagnostic: list the most recently active Claude Code sessions
with their context-token usage, so we can tell which transcript is which."""
import glob, json, os, time

base = os.path.expanduser("~/.claude/projects")
fs = glob.glob(base + "/**/*.jsonl", recursive=True)
fs.sort(key=os.path.getmtime, reverse=True)

print("how many transcripts total:", len(fs))
print("---- 8 most recently modified ----")
for f in fs[:8]:
    age = int(time.time() - os.path.getmtime(f))
    sz = os.path.getsize(f) // 1024
    used = cwd = sid = None
    try:
        lines = open(f, encoding="utf-8", errors="ignore").readlines()
    except Exception:
        lines = []
    for ln in reversed(lines):
        ln = ln.strip()
        if not ln:
            continue
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if isinstance(o, dict):
            if cwd is None:
                cwd = o.get("cwd")
            if sid is None:
                sid = o.get("sessionId") or o.get("session_id")
            m = o.get("message")
            u = m.get("usage") if isinstance(m, dict) else None
            if used is None and isinstance(u, dict):
                used = (int(u.get("input_tokens", 0) or 0)
                        + int(u.get("cache_read_input_tokens", 0) or 0)
                        + int(u.get("cache_creation_input_tokens", 0) or 0))
        if used is not None and cwd is not None:
            break
    pct = ("%.0f%%" % (used / 200000 * 100)) if used else "?"
    print("age=%5ds  used=%8s (%4s)  lines=%5d  size=%5dKB  cwd=%s  f=%s"
          % (age, used, pct, len(lines), sz, cwd, os.path.basename(f)))

#!/usr/bin/env python3
"""ark-face context-window poller.

Reads the most-recently-active Claude Code session transcript (read-only),
works out how full its context window is, and POSTs that to the ark-face
worker as a `context` field: {"pct": float, "used": int, "limit": int}.

This NEVER touches Claude Code itself. It only reads CC's transcript files
and pushes a single number to the display worker.

Usage:
  .venv/bin/python3 context-poller.py          # post once
  .venv/bin/python3 context-poller.py --loop    # poll forever (CTX_INTERVAL s)
  .venv/bin/python3 context-poller.py --dry      # compute + print, don't POST

Env overrides:
  ARK_FACE_URL    worker /state endpoint
  ARK_FACE_TOKEN  bearer token (falls back to keychain `ark-face-token`)
  CTX_LIMIT       context window size in tokens (default 200000)
  CTX_INTERVAL    seconds between polls in --loop mode (default 30)
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

CLAUDE_PROJECTS = os.path.expanduser("~/.claude/projects")
ARK_FACE_URL = os.environ.get("ARK_FACE_URL", "https://ark-face.YOUR_SUBDOMAIN.workers.dev/state")
CTX_LIMIT = int(os.environ.get("CTX_LIMIT", "1000000"))  # Opus long-context window is 1M
INTERVAL = int(os.environ.get("CTX_INTERVAL", "30"))


def _token():
    tok = os.environ.get("ARK_FACE_TOKEN")
    if tok:
        return tok
    try:
        return subprocess.check_output(
            ["security", "find-generic-password", "-s", "ark-face-token", "-w"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return None


def newest_transcript():
    """Most recently modified MAIN-session .jsonl under ~/.claude/projects.

    Skips agent-*.jsonl (subagent transcripts) so the gauge follows the
    interactive session you're actually in, not a transient subagent that
    happened to scribble last.
    """
    files = [f for f in glob.glob(os.path.join(CLAUDE_PROJECTS, "**", "*.jsonl"), recursive=True)
             if not os.path.basename(f).startswith("agent-")]
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def _usage_from_obj(obj):
    """Pull a usage dict out of a transcript line, wherever it lives."""
    if not isinstance(obj, dict):
        return None
    msg = obj.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
        return msg["usage"]
    if isinstance(obj.get("usage"), dict):
        return obj["usage"]
    return None


def latest_context_tokens(path):
    """Scan transcript bottom-up for the last usage record; sum context tokens."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
    except Exception:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        u = _usage_from_obj(obj)
        if not u:
            continue
        used = (
            int(u.get("input_tokens", 0) or 0)
            + int(u.get("cache_read_input_tokens", 0) or 0)
            + int(u.get("cache_creation_input_tokens", 0) or 0)
        )
        if used > 0:
            return used
    return None


def compute():
    path = newest_transcript()
    if not path:
        return None, "no transcript found under %s" % CLAUDE_PROJECTS
    age = time.time() - os.path.getmtime(path)
    used = latest_context_tokens(path)
    if used is None:
        return None, "no usage record in %s" % os.path.basename(path)
    limit = CTX_LIMIT
    if used > limit:  # self-correct for 1M-context sessions
        limit = 1000000
    pct = round(used / limit * 100, 1)
    payload = {"context": {"pct": pct, "used": used, "limit": limit}}
    info = "session=%s age=%ds used=%d limit=%d pct=%.1f%%" % (
        os.path.basename(path), int(age), used, limit, pct,
    )
    return payload, info


def post(payload):
    import requests
    tok = _token()
    if not tok:
        print("[ctx] no token (env or keychain); skipping POST", file=sys.stderr)
        return
    try:
        r = requests.post(
            ARK_FACE_URL,
            headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
            json=payload,
            timeout=5,
        )
        if r.status_code >= 400:
            print("[ctx] POST %s: %s" % (r.status_code, r.text[:200]), file=sys.stderr)
    except Exception as e:
        print("[ctx] POST failed: %s" % e, file=sys.stderr)


def tick(dry=False):
    payload, info = compute()
    if payload is None:
        print("[ctx] " + info, file=sys.stderr)
        return
    print("[ctx] " + info)
    if not dry:
        post(payload)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="poll forever every CTX_INTERVAL seconds")
    ap.add_argument("--dry", action="store_true", help="compute and print, don't POST")
    args = ap.parse_args()
    if args.loop:
        while True:
            tick(dry=args.dry)
            time.sleep(INTERVAL)
    else:
        tick(dry=args.dry)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""ark-face BLE Mood Bridge.

Peripheral advertising Nordic UART Service. Receives heartbeat snapshots
from Claude Desktop, maps to ark-face mood, POSTs to the worker.

Pair once from Claude Desktop:
  Help -> Troubleshooting -> Enable Developer Mode
  Developer -> Open Hardware Buddy -> Connect -> pick "Claude-Mood-Bridge"

Run:
  .venv/bin/python3 main.py
"""
import asyncio
import json
import logging
import os

import requests
from bless import (
    BlessServer,
    BlessGATTCharacteristic,
    GATTCharacteristicProperties,
    GATTAttributePermissions,
)

NORDIC_UART_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NORDIC_UART_RX      = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # desktop -> us (write)
NORDIC_UART_TX      = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # us -> desktop (notify)

ARK_FACE_URL   = os.environ.get("ARK_FACE_URL",   "https://ark-face.YOUR_SUBDOMAIN.workers.dev/state")
ARK_FACE_TOKEN = os.environ.get("ARK_FACE_TOKEN")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("mood-bridge")

_buf = bytearray()


def _parse_frames(chunk: bytes):
    """Accumulate inbound bytes and yield each complete \\n-terminated JSON."""
    _buf.extend(chunk)
    while True:
        idx = _buf.find(b"\n")
        if idx < 0:
            return
        line = bytes(_buf[:idx]).strip()
        del _buf[:idx + 1]
        if not line:
            continue
        try:
            yield json.loads(line.decode("utf-8"))
        except Exception as e:
            log.warning("bad frame: %s (%r)", e, line[:120])


def _heartbeat_to_mood(hb: dict) -> dict:
    total   = hb.get("total", 0)
    running = hb.get("running", 0)
    waiting = hb.get("waiting", 0)
    msg     = hb.get("msg", "")
    tokens  = hb.get("tokens_today", 0)
    prompt  = hb.get("prompt")

    if prompt or waiting > 0:
        mood = "debug-crashed"
        activity = (prompt.get("tool") if prompt else None) or "awaiting approval"
    elif running > 0:
        mood = "working"
        activity = msg or "working"
    elif total == 0:
        mood = "sleepy"
        activity = "idle"
    else:
        mood = "idle"
        activity = msg or "idle"

    return {
        "mood": mood,
        "activity": activity[:60],
        "message": f"{running}/{total} running, {tokens} tok today",
    }


def _push_to_face(payload: dict):
    try:
        r = requests.post(
            ARK_FACE_URL,
            headers={
                "Authorization": f"Bearer {ARK_FACE_TOKEN}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=5,
        )
        if r.status_code >= 400:
            log.warning("face POST %s: %s", r.status_code, r.text[:200])
        else:
            log.info("face %s mood=%s activity=%s", r.status_code, payload["mood"], payload["activity"])
    except Exception as e:
        log.warning("face POST failed: %s", e)


def _notify(server: BlessServer, msg: dict):
    """Send JSON back to Desktop via TX notify."""
    data = (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")
    server.get_characteristic(NORDIC_UART_TX).value = data
    server.update_value(NORDIC_UART_SERVICE, NORDIC_UART_TX)


def _handle_frame(frame: dict, server: BlessServer):
    # Heartbeat snapshot
    if "total" in frame or "running" in frame or "waiting" in frame:
        _push_to_face(_heartbeat_to_mood(frame))
        return
    # Turn event (completed assistant turn) - log only for now
    if frame.get("evt") == "turn":
        log.debug("turn role=%s", frame.get("role"))
        return
    # One-shot on connect
    if "time" in frame:
        log.info("time sync: %s", frame["time"])
        return
    # Commands with `cmd` field expect an ack
    cmd = frame.get("cmd")
    if cmd:
        log.info("cmd=%s payload=%s", cmd, {k: v for k, v in frame.items() if k != "cmd"})
        _notify(server, {"ack": cmd, "ok": True, "n": 0})


async def main():
    server = BlessServer(name="ClaudeArk")

    await server.add_new_service(NORDIC_UART_SERVICE)

    await server.add_new_characteristic(
        service_uuid=NORDIC_UART_SERVICE,
        char_uuid=NORDIC_UART_RX,
        properties=(
            GATTCharacteristicProperties.write
            | GATTCharacteristicProperties.write_without_response
        ),
        value=None,
        permissions=GATTAttributePermissions.writeable,
    )
    await server.add_new_characteristic(
        service_uuid=NORDIC_UART_SERVICE,
        char_uuid=NORDIC_UART_TX,
        properties=GATTCharacteristicProperties.notify,
        value=None,
        permissions=GATTAttributePermissions.readable,
    )

    def on_write(char: BlessGATTCharacteristic, value: bytearray, **_):
        for frame in _parse_frames(bytes(value)):
            _handle_frame(frame, server)

    server.write_request_func = on_write

    await server.start()
    log.info("advertising as 'ClaudeArk'; pair from Hardware Buddy.")
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("bye.")

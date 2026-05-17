# ark-face mood bridge

BLE peripheral that speaks the Claude Desktop Hardware Buddy protocol
([claude-desktop-buddy/REFERENCE.md](https://github.com/anthropics/claude-desktop-buddy/blob/main/REFERENCE.md)).

Claude Desktop (central) pushes heartbeat snapshots over Nordic UART; we
map them to an `ark-face` mood payload and POST to the Cloudflare worker.

## Pair (one time)

In Claude Desktop:

1. **Help → Troubleshooting → Enable Developer Mode**
2. **Developer → Open Hardware Buddy…**
3. Start this bridge (see below), then click **Connect** and pick
   `Claude-Mood-Bridge` from the scan list.

Auto-reconnects after that. macOS may prompt for Bluetooth permission on
first run — click **Allow**.

## Run

```bash
cd projects/ark-face/bridge
.venv/bin/python3 main.py
```

Env overrides: `ARK_FACE_URL`, `ARK_FACE_TOKEN`.

## Mood mapping

| Desktop state                    | ark-face mood   |
| -------------------------------- | --------------- |
| `prompt` present or `waiting>0`  | `debug-crashed` |
| `running>0`                      | `working`       |
| `total==0`                       | `sleepy`        |
| otherwise                        | `idle`          |

The `activity` field gets the `prompt.tool` / `msg` / "idle", truncated to 60 chars.
The `message` field gets a compact `"running/total running, tokens_today tok today"`.

## TODO

- `launchd` plist so the bridge starts with Mac mini.
- `permission` command round-trip so the ark-face display can approve/deny
  tool calls (phone notification → tap → decision back via TX notify).
- Map `turn` events into richer transient moods (e.g. `happy` after
  successful deploys).

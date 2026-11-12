# Termux control bridge

This is a pull-based helper for the owner's Android Termux environment. It polls issue #1 in this repository over an outbound HTTPS connection; it does not expose a listening port on the phone.

## Bootstrap

Requirements already expected in the user's Termux setup: Python 3, Git, GitHub CLI (`gh`), and an authenticated `gh auth login` with permission to read and comment on this repository.

Run once:

```sh
mkdir -p "$HOME/termux-control-bridge" && curl -fsSL "https://raw.githubusercontent.com/khd98me-svg/org-agents/termux-control-bridge/termux-bridge/termux_bridge.py" -o "$HOME/termux-control-bridge/termux_bridge.py" && python "$HOME/termux-control-bridge/termux_bridge.py"
```

Keep this process running while you want remote work. Stop with Ctrl+C. Android may suspend Termux in the background; this bridge cannot override Android's process management.

## Protocol

Only comments authored by `khd98me-svg` are considered. A command must be a fenced JSON object, for example:

```json
{"action":"status"}
```

Supported actions:
- `status`: report Git status for the three project directories.
- `read_file`: read a text file under `~/openclawfice`, `~/rl-agent`, or `~/office-ui-bridge-checkout`.
- `write_file`: write a file under those roots only, requires `confirm: true`; existing files require the exact current SHA-256 and are backed up before replacement.
- `check`: only the named checks `bridge-tests` and `openclawfice-build`.

No arbitrary shell commands, no agent execution, no task execution, no database writes, no environment/secrets/database/key file reads or writes. Every comment ID is processed once and results are posted back to the issue.

The inbox is issue #1: https://github.com/khd98me-svg/org-agents/issues/1

This is an initial prototype. Keep it on the dedicated branch until its behavior has been tested on the phone. Do not merge it into the live engine branch yet.

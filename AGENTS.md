# AGENTS.md — cyncctl

## What this is

Python CLI to control GE Cync WiFi bulbs via the same two channels the
official app uses (reverse engineered from `com.ge.cbyge` 6.24.0.156 with
REA/JADX; corroborated by `unixpickle/cbyge` and `nikshriv/cync_lights`).

## Architecture

- `cyncctl/packets.py` — pure functions: frame encode, auth packet, command
  templates (on/off, color-temp, RGB combo, state request, ping). Golden-byte
  tested against the public reimplementations. Do not "clean up" the hex
  templates: they are checksum-framed protocol constants.
- `cyncctl/api.py` — stdlib `urllib` client for `api.gelighting.com/v2`
  (login + email 2FA, home/property enumeration) and `build_device_map`
  (mesh index math `((did % hid) % 1000) + ((did % hid) // 1000) * 256`,
  controller discovery, capability flags from deviceType).
- `cyncctl/tcp.py` — `CmConnection`: TLS 23779 → unverified TLS → plain
  23778 fallback, auth exchange, acked command send (`0x7b` frames matched
  by seq), state collection.
- `cyncctl/cli.py` — argparse subcommands, session/device cache in
  `~/.config/cyncctl/` (0600, atomic rename writes), color parsing,
  device selection (id / name substring / sole-device default).

## Conventions

- Python ≥3.10, **stdlib only** — do not add dependencies.
- Tests first (TDD); offline only: golden bytes + loopback fake server.
  Run: `/usr/bin/python3 -m pytest -q` (system python; pyenv python has no
  pytest). All tests must pass before any commit.
- Atomic Conventional Commits; never commit `session.json`/`devices.json`
  (gitignored, they carry tokens).
- Protocol changes require evidence: cite the APK class/string or the
  reference repo line that justifies the byte layout.

## Run

`bin/cyncctl <cmd>` or `PYTHONPATH=. python3 -m cyncctl <cmd>`.
Login is interactive (getpass + 2FA prompt) by design — never hardcode
credentials or accept them via argv/env.

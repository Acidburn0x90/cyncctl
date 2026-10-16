# cyncctl

Terminal control for GE Cync (formerly C by GE) WiFi bulbs — no app, no hub.

## How it works (reverse-engineered protocol)

Disassembled from Cync app 6.24.0.156 (`com.ge.cbyge`, pulled from a device
via adb, analyzed with REA + JADX) and cross-checked against two public
reimplementations (`unixpickle/cbyge`, `nikshriv/cync_lights`).

Two channels, both confirmed present in the shipped APK:

1. **HTTP JSON API** — `https://api.gelighting.com/v2`
   - `POST /user_auth` (email+password; HTTP 400 ⇒ 2FA required)
   - `POST /two_factor/email/verifycode` (request emailed code)
   - `POST /user_auth/two_factor` (complete login, `corp_id=1007d2ad150c4000`)
   - `GET /user/{id}/subscribe/devices` (homes; `Access-Token` header)
   - `GET /product/{pid}/device/{id}/property` (`bulbsArray` with deviceID,
     switchID, mesh index, deviceType)
2. **Binary TCP protocol** — `cm.gelighting.com:23779` (TLS), fallback
   `:23778` (plain). Ports match `io.xlink.wifi.sdk.global.XlinkProperty`
   in the APK (`TCP_PORT=23778`, `TCP_SSL_PORT=23779`).
   - Frames: `type_byte | len(4 BE) | payload`
   - Auth: type `0x13`, payload `03 | user_id(4) | len(2) | authorize | 0000b4`
   - Commands: type `0x73` pipe to the bulb's switchID with mesh index and
     a checksum-framed payload: `d0` on/off, `e2` color-temp,
     `f0` combo state (brightness + RGB, ct byte `0xfe` = RGB mode)
   - Server acks: type `0x7b`, matched by sequence number
   - State query: `52` subtype, 24-byte records (idx, on/off, brightness,
     ct, rgb)

## Usage

```sh
bin/cyncctl login              # email + password + emailed 2FA code
bin/cyncctl devices            # list bulbs (cached in ~/.config/cyncctl/)
bin/cyncctl on [TARGET]        # TARGET = device id or name substring
bin/cyncctl off [TARGET]
bin/cyncctl color "#ff8800" [TARGET]   # also: 255,136,0 or "orange"
bin/cyncctl bright 50 [TARGET]
bin/cyncctl temp 3500 [TARGET] # Kelvin (2000-7000) or 0-100 app scale
bin/cyncctl status [TARGET]    # best-effort state readout
```

Session token is stored at `~/.config/cyncctl/session.json` (mode 0600).
`on`/`off`/`color`/`bright`/`temp` are fire-and-acked; `status` is best-effort.

## Development

```sh
/usr/bin/python3 -m pytest -q   # tests are offline: golden bytes + loopback server
```

Stdlib-only, no dependencies. Python ≥3.10.

## Scope / limitations

- Bulbs need a WiFi-capable Cync controller on the account (any Cync
  switch/plug/bulb with `WIFICONTROL`); pure-BLE devices are out of scope.
- Control goes through GE's cloud CM server — not local LAN.
- deviceType capability table is the subset relevant to lights/plugs.

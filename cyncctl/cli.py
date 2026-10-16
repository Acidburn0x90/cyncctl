"""cyncctl command-line interface."""

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from . import api, packets, tcp

CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
) / "cyncctl"
SESSION_PATH = CONFIG_DIR / "session.json"
DEVICES_PATH = CONFIG_DIR / "devices.json"

NAMED_COLORS = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "white": (255, 255, 255),
    "warmwhite": (255, 204, 153),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "yellow": (255, 255, 0),
    "orange": (255, 128, 0),
    "purple": (128, 0, 255),
    "pink": (255, 105, 180),
}


class DeviceSelectError(Exception):
    pass


def parse_rgb(value):
    v = value.strip().lower()
    if v in NAMED_COLORS:
        return NAMED_COLORS[v]
    if v.startswith("#"):
        v = v[1:]
    if len(v) == 6 and all(c in "0123456789abcdef" for c in v):
        return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    parts = v.split(",")
    if len(parts) == 3 and all(p.strip().isdigit() for p in parts):
        rgb = tuple(int(p) for p in parts)
        if all(0 <= c <= 255 for c in rgb):
            return rgb
    raise ValueError(f"cannot parse color: {value!r}")


def select_device(devices, target):
    if target is None:
        if len(devices) == 1:
            return next(iter(devices.values()))
        names = ", ".join(d["name"] for d in devices.values())
        raise DeviceSelectError(f"multiple devices, pick one: {names}")
    if target in devices:
        return devices[target]
    matches = [d for d in devices.values()
               if target.lower() in d["name"].lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(d["name"] for d in matches)
        raise DeviceSelectError(f"ambiguous target {target!r}: {names}")
    raise DeviceSelectError(f"no device matches {target!r}")


def _load_json(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None


def _save_json(path, obj):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def load_session():
    session = _load_json(SESSION_PATH)
    if not session:
        raise SystemExit("not logged in — run: cyncctl login")
    return session


def load_devices(refresh=False):
    if not refresh:
        cached = _load_json(DEVICES_PATH)
        if cached:
            return cached
    session = load_session()
    devices, home_devices, controllers = api.fetch_device_map(session)
    data = {"devices": devices, "home_devices": home_devices,
            "controllers": controllers}
    _save_json(DEVICES_PATH, data)
    return data


def _next_seq():
    return int.from_bytes(os.urandom(2), "big") or 1


def cmd_login(args):
    email = args.email or input("Cync account email: ")
    password = getpass.getpass("Password: ")
    creds = api.verify_credentials(email, password)
    needs_2fa = creds.get("user_version", 0) >= 1
    if not needs_2fa:
        try:
            session = api.login(email, password)
        except api.TwoFactorRequired:
            needs_2fa = True
    if needs_2fa:
        api.request_two_factor(email)
        print("Two-factor code sent to your email.")
        code = input("Code: ").strip()
        session = api.login_2fa(email, password, code)
    _save_json(SESSION_PATH, session)
    print("Logged in.")
    cmd_devices(argparse.Namespace(refresh=True))


def cmd_devices(args):
    data = load_devices(refresh=args.refresh)
    for dev_id, dev in sorted(data["devices"].items()):
        caps = "rgb" if dev["rgb"] else ("dim" if dev["brightness"] else "onoff")
        print(f"{dev_id}  {dev['name']:<24} {caps:<5} mesh={dev['mesh']}")
    if not data["devices"]:
        print("no controllable devices found")


def _open_cm(session):
    conn = tcp.CmConnection.connect()
    conn.auth(session["user_id"], session["authorize"])
    return conn


def _send_to_device(args, frame_factory):
    session = load_session()
    data = load_devices()
    dev = select_device(data["devices"], args.target)
    seq = _next_seq()
    frame = frame_factory(dev, seq)
    conn = _open_cm(session)
    try:
        conn.send_and_wait_ack(frame, seq)
    finally:
        conn.close()
    return dev


def cmd_on(args):
    dev = _send_to_device(args, lambda d, s: packets.turn_on_frame(
        d["switch_id"], s, bytes([d["mesh"] >> 8, d["mesh"] & 0xFF])))
    print(f"{dev['name']}: on")


def cmd_off(args):
    dev = _send_to_device(args, lambda d, s: packets.turn_off_frame(
        d["switch_id"], s, bytes([d["mesh"] >> 8, d["mesh"] & 0xFF])))
    print(f"{dev['name']}: off")


def cmd_color(args):
    r, g, b = parse_rgb(args.color)
    dev = _send_to_device(args, lambda d, s: packets.rgb_frame(
        d["switch_id"], s, bytes([d["mesh"] >> 8, d["mesh"] & 0xFF]), r, g, b))
    print(f"{dev['name']}: color #{r:02x}{g:02x}{b:02x}")


def cmd_bright(args):
    level = max(1, min(100, int(args.level)))
    dev = _send_to_device(args, lambda d, s: packets.brightness_frame(
        d["switch_id"], s, bytes([d["mesh"] >> 8, d["mesh"] & 0xFF]), level))
    print(f"{dev['name']}: brightness {level}%")


def cmd_temp(args):
    value = int(args.kelvin)
    if value >= 1000:  # treat as Kelvin (2000..7000)
        ct = round(100 * (value - 2000) / 5000)
    else:
        ct = value
    ct = max(0, min(100, ct))
    dev = _send_to_device(args, lambda d, s: packets.color_temp_frame(
        d["switch_id"], s, bytes([d["mesh"] >> 8, d["mesh"] & 0xFF]), ct))
    print(f"{dev['name']}: color temp {ct}/100")


def cmd_status(args):
    session = load_session()
    data = load_devices()
    dev = select_device(data["devices"], args.target)
    seq = _next_seq()
    conn = _open_cm(session)
    try:
        states = conn.send_and_wait_state(dev["switch_id"], seq)
    finally:
        conn.close()
    found = False
    for payload in states:
        for record in _parse_state_records(payload, dev["home_id"],
                                           data["home_devices"]):
            if record["device_id"] != str(dev["mesh"]):
                continue
            found = True
            print(f"{dev['name']}: {'on' if record['state'] else 'off'}, "
                  f"brightness {record['brightness']}%, "
                  f"ct {record['ct']}"
                  + (f", rgb #{record['r']:02x}{record['g']:02x}{record['b']:02x}"
                     if record["ct"] == packets.RGB_MODE_CT else ""))
    if not found:
        print(f"{dev['name']}: no state received (device offline?)")


def _parse_state_records(payload, home_id, home_devices):
    """Parse subtype-0x52 state payloads (24-byte records)."""
    index = home_devices.get(str(home_id)) or home_devices.get(home_id) or []
    records = []
    blob = payload[22:]
    while len(blob) >= 24:
        mesh = blob[0]
        device_id = index[mesh] if mesh < len(index) else ""
        records.append({
            "device_id": device_id,
            "state": blob[8] > 0,
            "brightness": blob[12],
            "ct": blob[16],
            "r": blob[20], "g": blob[21], "b": blob[22],
        })
        blob = blob[24:]
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="cyncctl", description="Control GE Cync bulbs from the terminal.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("login", help="authenticate and store the session")
    p.add_argument("--email")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("devices", help="list devices")
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_devices)

    for name, func, extra in [
        ("on", cmd_on, None),
        ("off", cmd_off, None),
        ("color", cmd_color, ("color",)),
        ("bright", cmd_bright, ("level",)),
        ("temp", cmd_temp, ("kelvin",)),
        ("status", cmd_status, None),
    ]:
        p = sub.add_parser(name)
        if extra:
            argname, = extra
            p.add_argument(argname)
        p.add_argument("target", nargs="?",
                       help="device id or name substring (default: sole device)")
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (api.ApiError, tcp.AuthError, tcp.AckTimeout,
            DeviceSelectError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

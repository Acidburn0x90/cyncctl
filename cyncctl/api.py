"""Cync HTTP API: login (with email 2FA), home/device enumeration."""

import json
import random
import string
import urllib.error
import urllib.request

API_BASE = "https://api.gelighting.com/v2"
CORP_ID = "1007d2ad150c4000"  # corporation ID used by the Cync app

# deviceType capability table, synced with the current nikshriv/cync_lights
# (custom_components/cync_lights/cync_hub.py Capabilities dict): the original
# snapshot stopped at 85 and missed the modern 128-172 range — the live
# account's bulb is deviceType 160.
CAPABILITIES = {
    "ONOFF": {1, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 17, 18, 19, 20, 21, 22, 23,
              24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39,
              40, 47, 48, 49, 51, 52, 53, 54, 55, 56, 57, 58, 59, 61, 62, 63,
              64, 65, 66, 67, 68, 80, 81, 82, 83, 85, 128, 129, 130, 131, 132,
              133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145,
              146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 156, 158, 159,
              160, 161, 162, 163, 164, 165, 166, 169, 170, 171, 172},
    "BRIGHTNESS": {1, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 17, 18, 19, 20, 21,
                   22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36,
                   37, 47, 48, 49, 55, 56, 80, 81, 82, 83, 85, 128, 129, 130,
                   131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142,
                   143, 144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154,
                   155, 156, 158, 159, 160, 161, 162, 163, 164, 165, 166, 169,
                   170, 171},
    "COLORTEMP": {5, 6, 7, 8, 10, 11, 14, 15, 19, 20, 21, 22, 23, 25, 26, 28,
                  29, 30, 31, 32, 33, 34, 35, 47, 80, 82, 83, 85, 129, 130, 131,
                  132, 133, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144,
                  145, 146, 147, 153, 154, 155, 156, 158, 159, 160, 161, 162,
                  163, 164, 165, 166, 169, 170, 171},
    "RGB": {6, 7, 8, 21, 22, 23, 30, 31, 32, 33, 34, 35, 47, 131, 132, 133, 137,
            138, 139, 140, 141, 142, 143, 146, 147, 153, 154, 155, 156, 158, 159,
            160, 161, 162, 163, 164, 165, 166, 169, 170, 171},
    "WIFICONTROL": {36, 37, 38, 39, 40, 47, 48, 49, 51, 52, 53, 54, 55, 56,
                    57, 58, 59, 61, 62, 63, 64, 65, 66, 67, 68, 80, 81, 128,
                    129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140,
                    141, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152,
                    153, 154, 155, 156, 158, 159, 160, 161, 162, 163, 164, 165,
                    166, 169, 170, 171, 172},
    "PLUG": {64, 65, 66, 67, 68, 172},
}


class ApiError(Exception):
    pass


class TwoFactorRequired(ApiError):
    pass


def _urlopen_json(url, obj=None, headers=None):
    data = json.dumps(obj).encode() if obj is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST" if obj is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read()
    if not body.strip():
        # status-only endpoints (e.g. /two_factor/email/verifycode)
        # answer 200 with an empty body
        return {}
    return json.loads(body)


def _post(path, obj):
    try:
        return _urlopen_json(API_BASE + path, obj)
    except TwoFactorRequired:
        raise
    except urllib.error.HTTPError as e:
        body = e.read()[:200]
        if e.code == 400 and path == "/user_auth":
            raise TwoFactorRequired() from None
        raise ApiError(f"{path}: HTTP {e.code}: {body!r}") from None
    except urllib.error.URLError as e:
        raise ApiError(f"{path}: {e.reason}") from None
    except json.JSONDecodeError as e:
        raise ApiError(f"{path}: bad JSON: {e}") from None


def verify_credentials(email, password):
    """App's first login step: confirm the password and learn user_version.

    Keys are `account`/`pwd` (VerifyCredentialsRequest$$serializer).
    user_version >= 1 means the account signs in via /user_auth/two_factor.
    """
    return _post("/user/version",
                 {"account": email, "pwd": password, "corp_id": CORP_ID})


def login(email, password):
    return _post("/user_auth",
                 {"email": email, "password": password, "corp_id": CORP_ID})


def request_two_factor(email):
    return _post("/two_factor/email/verifycode",
                 {"email": email, "local_lang": "en-us", "corp_id": CORP_ID})


def login_2fa(email, password, code):
    resource = "".join(random.choice(string.ascii_lowercase) for _ in range(16))
    return _post("/user_auth/two_factor",
                 {"email": email, "password": password, "two_factor": code,
                  "corp_id": CORP_ID, "resource": resource})


def get_homes(session):
    # No ?version=0 here: live testing showed that query wraps the response
    # as {"list": [...], "version": 0}, while the bare URL returns the plain
    # array build_device_map iterates (same records either way).
    return _urlopen_json(
        f"{API_BASE}/user/{session['user_id']}/subscribe/devices",
        headers={"Access-Token": session["access_token"]},
    )


def get_home_properties(session, product_id, home_id):
    return _urlopen_json(
        f"{API_BASE}/product/{product_id}/device/{home_id}/property",
        headers={"Access-Token": session["access_token"]},
    )


def mesh_index(device_id, home_id):
    rem = device_id % home_id
    return (rem % 1000) + (rem // 1000) * 256


def build_device_map(homes, properties_by_home):
    """Return (devices, home_devices, controllers).

    devices: deviceID(str) -> {name, mesh, switch_id, controller, caps...}
    home_devices: homeID -> sparse mesh-index -> deviceID(str)
    controllers: homeID -> [switchID...] of WiFi-connected controllers
    """
    devices, home_devices, controllers = {}, {}, {}
    for home in homes:
        home_id = home["id"]
        props = properties_by_home.get(home_id) or {}
        bulbs = props.get("bulbsArray") or []
        if not bulbs:
            continue
        max_mesh = max(mesh_index(d["deviceID"], home_id) for d in bulbs)
        index = [""] * (max_mesh + 1)
        home_controllers = []
        seen_controllers = set()
        for dev in bulbs:
            dtype = dev.get("deviceType", 0)
            dev_id = str(dev["deviceID"])
            mesh = mesh_index(dev["deviceID"], home_id)
            switch_id = dev.get("switchID", 0) or 0
            info = {
                "name": dev.get("displayName", dev_id),
                "mesh": mesh,
                "switch_id": switch_id,
                "home_id": home_id,
                "onoff": dtype in CAPABILITIES["ONOFF"],
                "brightness": dtype in CAPABILITIES["BRIGHTNESS"],
                "color_temp": dtype in CAPABILITIES["COLORTEMP"],
                "rgb": dtype in CAPABILITIES["RGB"],
                "plug": dtype in CAPABILITIES["PLUG"],
            }
            devices[dev_id] = info
            index[mesh] = dev_id
            if dtype in CAPABILITIES["WIFICONTROL"] and switch_id > 0 \
                    and switch_id not in seen_controllers:
                seen_controllers.add(switch_id)
                home_controllers.append(switch_id)
        if not home_controllers:
            # no WiFi-reachable controller: the CM server cannot reach these
            for dev in bulbs:
                devices.pop(str(dev["deviceID"]), None)
            continue
        for info in devices.values():
            if info["home_id"] == home_id and not info["switch_id"]:
                info["switch_id"] = home_controllers[0]
        home_devices[home_id] = index
        controllers[home_id] = home_controllers
    return devices, home_devices, controllers


def fetch_device_map(session):
    homes = get_homes(session)
    props = {}
    for home in homes:
        try:
            props[home["id"]] = get_home_properties(session, home["product_id"], home["id"])
        except (ApiError, urllib.error.HTTPError):
            # e.g. 404 "device property not exists" for homes without a
            # property record: skip the home, keep enumerating
            props[home["id"]] = None
    return build_device_map(homes, props)

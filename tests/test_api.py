"""Tests for the HTTP API layer and device-map construction.

Network calls are stubbed; the device-map fixture mirrors the real
`bulbsArray`/`groupsArray` shape returned by
/product/{pid}/device/{id}/property.
"""

import io
import json
import urllib.error

import pytest

from cyncctl import api


@pytest.fixture
def homes():
    return [
        {"id": 4242, "product_id": "P123", "name": "My Home"},
        {"id": 5555, "product_id": "P999", "name": "Garage"},
    ]


@pytest.fixture
def properties():
    # home 4242: one RGB bulb + one plug on the same WiFi controller;
    # home 5555: no controllers -> devices must be dropped.
    return {
        4242: {
            "bulbsArray": [
                {
                    "deviceID": 4242007,
                    "displayName": "Desk Bulb",
                    "switchID": 4242001,
                    "deviceType": 30,  # in ONOFF+BRIGHTNESS+COLORTEMP+RGB sets
                },
                {
                    "deviceID": 4242064,
                    "displayName": "Fan Plug",
                    "switchID": 4242001,
                    "deviceType": 64,  # PLUG + ONOFF
                },
                {
                    "deviceID": 4242001,
                    "displayName": "Switch",
                    "switchID": 4242001,
                    "deviceType": 47,  # WIFICONTROL + ONOFF + BRIGHTNESS
                },
            ],
            "groupsArray": [],
        },
        5555: {
            "bulbsArray": [
                {
                    "deviceID": 5555002,
                    "displayName": "Orphan",
                    "switchID": 0,
                    "deviceType": 30,
                }
            ],
            "groupsArray": [],
        },
    }


def test_mesh_index_math():
    # ((deviceID % homeID) % 1000) + int((deviceID % homeID) / 1000) * 256
    assert api.mesh_index(4242007, 4242) == 7
    # deviceID % 4242 == 1261 -> (1261 % 1000) + 1*256
    assert api.mesh_index(4242 * 1000 + 1261, 4242) == 261 + 256


def test_build_device_map(homes, properties):
    devices, home_devices, controllers = api.build_device_map(homes, properties)

    bulb = devices["4242007"]
    assert bulb["name"] == "Desk Bulb"
    assert bulb["mesh"] == 7
    assert bulb["switch_id"] == 4242001
    assert bulb["rgb"] and bulb["onoff"] and bulb["brightness"] and bulb["color_temp"]

    plug = devices["4242064"]
    assert plug["rgb"] is False and plug["onoff"] is True

    # home without any WiFi controller loses its devices
    assert "5555002" not in devices
    assert 5555 not in home_devices

    assert controllers[4242] == [4242001]
    assert home_devices[4242][7] == "4242007"


def test_login_success_stores_session(monkeypatch):
    session_payload = {
        "access_token": "tok",
        "refresh_token": "ref",
        "user_id": 7,
        "expire_in": 3600,
        "authorize": "authecode",
    }
    calls = []

    def fake_post(path, obj):
        calls.append((path, obj))
        return dict(session_payload)

    monkeypatch.setattr(api, "_post", fake_post)
    session = api.login("a@b.c", "hunter2")
    assert session == session_payload
    assert calls[0][0] == "/user_auth"
    assert calls[0][1]["corp_id"] == api.CORP_ID


def test_login_2fa_flow(monkeypatch):
    seen = []

    def fake_post(path, obj):
        seen.append(path)
        if path == "/user_auth/two_factor":
            return {"access_token": "t", "user_id": 1, "authorize": "x"}
        raise AssertionError(path)

    monkeypatch.setattr(api, "_post", fake_post)
    session = api.login_2fa("a@b.c", "pw", "123456")
    assert session["access_token"] == "t"
    assert seen == ["/user_auth/two_factor"]


def test_post_raises_api_error_on_bad_json(monkeypatch):
    monkeypatch.setattr(api, "_urlopen_json", lambda *a, **k: (_ for _ in ()).throw(api.ApiError("boom")))
    with pytest.raises(api.ApiError):
        api._post("/user_auth", {})


def test_request_two_factor_posts_expected_payload(monkeypatch):
    seen = {}

    def fake_post(path, obj):
        seen["path"] = path
        seen["obj"] = obj
        return {}

    monkeypatch.setattr(api, "_post", fake_post)
    api.request_two_factor("a@b.c")
    assert seen["path"] == "/two_factor/email/verifycode"
    assert seen["obj"] == {"email": "a@b.c", "local_lang": "en-us", "corp_id": api.CORP_ID}


def test_verify_credentials_posts_account_pwd(monkeypatch):
    """The app verifies the password at /user/version with account/pwd keys
    before any sign-in attempt (VerifyCredentialsRequest$$serializer)."""
    seen = {}

    def fake_post(path, obj):
        seen["path"] = path
        seen["obj"] = obj
        return {"user_version": 2}

    monkeypatch.setattr(api, "_post", fake_post)
    resp = api.verify_credentials("a@b.c", "pw")
    assert seen["path"] == "/user/version"
    assert seen["obj"] == {"account": "a@b.c", "pwd": "pw", "corp_id": api.CORP_ID}
    assert resp == {"user_version": 2}


def test_get_homes_url_matches_reference_shape(monkeypatch):
    """Bare /subscribe/devices returns a plain array (reference-repo shape).
    Adding ?version=0 — which the app itself uses — makes the server wrap
    the same records as {"list": [...], "version": 0}, which build_device_map
    cannot iterate, so the query string must stay off."""
    seen = {}

    def fake_urlopen_json(url, obj=None, headers=None):
        seen["url"] = url
        return []

    monkeypatch.setattr(api, "_urlopen_json", fake_urlopen_json)
    api.get_homes({"user_id": 42, "access_token": "t"})
    assert seen["url"] == f"{api.API_BASE}/user/42/subscribe/devices"


def test_fetch_device_map_tolerates_missing_home_properties(monkeypatch):
    """A home without a property record answers 404 (code 4041009, live
    verified); that is a per-home miss, so fetch_device_map must skip it
    instead of aborting the whole enumeration."""
    def fake_urlopen_json(url, obj=None, headers=None):
        if "/property" in url:
            raise urllib.error.HTTPError(
                url, 404, "Not Found", {}, io.BytesIO(b"{}"))
        return [{"id": 1, "product_id": "p1"}]

    monkeypatch.setattr(api, "_urlopen_json", fake_urlopen_json)
    result = api.fetch_device_map({"user_id": 1, "access_token": "t"})
    assert result == ({}, {}, {})


def test_capabilities_cover_modern_device_types():
    """The live account's bulb is deviceType 160 (a modern type outside the
    original 85-capped reference table); current nikshriv/cync_lights
    cync_hub.py lines 19-25 include the 128-172 range in every relevant
    capability set."""
    for cap in ("ONOFF", "BRIGHTNESS", "COLORTEMP", "RGB", "WIFICONTROL"):
        assert 160 in api.CAPABILITIES[cap], cap
    assert 172 in api.CAPABILITIES["PLUG"]

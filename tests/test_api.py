"""Tests for the HTTP API layer and device-map construction.

Network calls are stubbed; the device-map fixture mirrors the real
`bulbsArray`/`groupsArray` shape returned by
/product/{pid}/device/{id}/property.
"""

import json

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

"""Tests for CLI argument parsing and device selection."""

import pytest

from cyncctl import cli


def test_parse_rgb_hex():
    assert cli.parse_rgb("#ff8800") == (255, 136, 0)
    assert cli.parse_rgb("ff8800") == (255, 136, 0)


def test_parse_rgb_decimal():
    assert cli.parse_rgb("255,136,0") == (255, 136, 0)


def test_parse_rgb_named():
    assert cli.parse_rgb("red") == (255, 0, 0)
    assert cli.parse_rgb("warmwhite") == (255, 204, 153)


def test_parse_rgb_rejects_garbage():
    with pytest.raises(ValueError):
        cli.parse_rgb("zzz")
    with pytest.raises(ValueError):
        cli.parse_rgb("300,0,0")


DEVICES = {
    "4242007": {"name": "Desk Bulb", "mesh": 7, "switch_id": 4242001, "rgb": True},
    "4242064": {"name": "Fan Plug", "mesh": 64, "switch_id": 4242001, "rgb": False},
}


def test_select_device_by_id():
    assert cli.select_device(DEVICES, "4242064") == DEVICES["4242064"]


def test_select_device_by_name_substring():
    assert cli.select_device(DEVICES, "desk") == DEVICES["4242007"]


def test_select_device_single_default():
    only = {"1": DEVICES["4242007"]}
    assert cli.select_device(only, None) == DEVICES["4242007"]


def test_select_device_ambiguous_raises():
    with pytest.raises(cli.DeviceSelectError):
        cli.select_device(DEVICES, None)


def test_select_device_no_match_raises():
    with pytest.raises(cli.DeviceSelectError):
        cli.select_device(DEVICES, "kitchen")


def test_login_flow_verifies_credentials_before_2fa(monkeypatch):
    """App order: /user/version first, then email code, then two_factor
    sign-in (SignInUseCase + TwoFactorViewModel)."""
    calls = []
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "pw")
    monkeypatch.setattr("builtins.input", lambda prompt="": "123456")
    monkeypatch.setattr(
        cli.api, "verify_credentials",
        lambda e, p: (calls.append(("verify", e, p)) or {"user_version": 2}))
    monkeypatch.setattr(cli.api, "request_two_factor",
                        lambda e: calls.append(("code", e)))
    monkeypatch.setattr(cli.api, "login_2fa",
                        lambda e, p, c: (calls.append(("2fa", c))
                                         or {"access_token": "t"}))
    monkeypatch.setattr(cli, "_save_json", lambda path, s: calls.append(("save",)))
    monkeypatch.setattr(cli, "cmd_devices", lambda args: None)
    cli.cmd_login(cli.argparse.Namespace(email="a@b.c"))
    assert [c[0] for c in calls] == ["verify", "code", "2fa", "save"]
    assert calls[0] == ("verify", "a@b.c", "pw")


def test_login_flow_plain_when_user_version_zero(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "pw")
    monkeypatch.setattr(
        cli.api, "verify_credentials",
        lambda e, p: (calls.append("verify") or {"user_version": 0}))
    monkeypatch.setattr(cli.api, "login",
                        lambda e, p: (calls.append("login") or {"access_token": "t"}))
    monkeypatch.setattr(cli.api, "request_two_factor",
                        lambda e: pytest.fail("must not send a 2FA code"))
    monkeypatch.setattr(cli, "_save_json", lambda path, s: calls.append("save"))
    monkeypatch.setattr(cli, "cmd_devices", lambda args: None)
    cli.cmd_login(cli.argparse.Namespace(email="a@b.c"))
    assert calls == ["verify", "login", "save"]

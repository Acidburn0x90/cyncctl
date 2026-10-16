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

"""The verifycode endpoint answers 200 with an empty body (status-only
contract, per unixpickle/cbyge login.go and nikshriv/cync_lights)."""

import urllib.error

from cyncctl import api


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_post_tolerates_empty_body(monkeypatch):
    monkeypatch.setattr(
        api.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResp(b""),
    )
    assert api.request_two_factor("a@b.c") == {}


def test_post_parses_empty_as_none_body(monkeypatch):
    monkeypatch.setattr(
        api.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResp(b""),
    )
    assert api.login("a@b.c", "pw") == {}

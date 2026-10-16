"""Golden-byte tests for the Cync CM-server wire format.

Expected frames come from the two public reimplementations
(unixpickle/cbyge packet.go, nikshriv/cync_lights cync_hub.py) and were
corroborated against the constants embedded in Cync app 6.24.0.156
(io.xlink.wifi.sdk.global.XlinkProperty, com.gelighting.cbygekit).
"""

import pytest

from cyncctl import packets

SWITCH_ID = 0x11223344
SEQ = 0x0102
MESH = bytes.fromhex("0a0b")


def test_frame_header_layout():
    raw = packets.frame(0x73, b"\x01\x02\x03")
    assert raw == bytes.fromhex("7300000003010203")


def test_parse_frame_header():
    msg_type, length = packets.parse_frame_header(bytes.fromhex("730000001f"))
    assert msg_type == 0x73
    assert length == 0x1F


def test_auth_packet_golden():
    # From cync_lights: 13000000 <len> 03 <uid 4BE> <len 2BE> <code> 0000b4
    raw = packets.auth_packet(0x01020304, "abcdef")
    assert raw == bytes.fromhex(
        "1300000010" "03" "01020304" "0006" "616263646566" "0000b4"
    )


def test_auth_packet_length_field_tracks_code():
    raw = packets.auth_packet(1, "xy")
    assert raw[4] == 12  # 10 + len(code)


def test_turn_on_golden():
    raw = packets.turn_on_frame(SWITCH_ID, SEQ, MESH)
    assert raw == bytes.fromhex(
        "730000001f"
        "11223344" "0102"
        "007e00000000f8" "d00d" "000000000000"
        "0a0b" "d00000010000" "c3" "7e"
    )  # checksum (430 + 10 + 11) % 256 == 0xc3


def test_turn_off_golden():
    raw = packets.turn_off_frame(SWITCH_ID, SEQ, MESH)
    assert raw == bytes.fromhex(
        "730000001f"
        "11223344" "0102"
        "007e00000000f8" "d00d" "000000000000"
        "0a0b" "d00000000000" "c2" "7e"
    )  # checksum (429 + 10 + 11) % 256 == 0xc2


def test_color_temp_golden():
    raw = packets.color_temp_frame(SWITCH_ID, SEQ, MESH, 50)
    assert raw == bytes.fromhex(
        "730000001e"
        "11223344" "0102"
        "007e00000000f8" "e20c" "000000000000"
        "0a0b" "e2000005" "32" "1c" "7e"
    )  # checksum (469 + 10 + 11 + 50) % 256 == 28


def test_rgb_combo_golden():
    raw = packets.rgb_frame(SWITCH_ID, SEQ, MESH, r=255, g=136, b=0)
    # checksum (496 + 10 + 11 + 1 + 100 + 254 + 255 + 136 + 0) % 256
    assert raw == bytes.fromhex(
        "7300000022"
        "11223344" "0102"
        "007e00000000f8" "f010" "000000000000"
        "0a0b" "f00000"
        "01" "64" "fe" "ff" "88" "00"
        "ef" "7e"
    )  # checksum (496 + 10 + 11 + 1 + 100 + 254 + 255 + 136 + 0) % 256 == 239


def test_rgb_frame_defaults_brightness():
    raw = packets.rgb_frame(SWITCH_ID, SEQ, MESH, 1, 2, 3)
    # checksum sits second-to-last, just before the 0x7e terminator
    assert raw[-2] == ((496 + 10 + 11 + 1 + 100 + 254 + 1 + 2 + 3) % 256)


def test_state_request_golden():
    raw = packets.state_request_frame(SWITCH_ID, SEQ)
    assert raw == bytes.fromhex(
        "7300000018"
        "11223344" "0102"
        "007e00000000f85206000000ffff0000567e"
    )


def test_ping_golden():
    raw = packets.ping_frame(SWITCH_ID, SEQ)
    assert raw == bytes.fromhex("a300000007" "11223344" "0102" "00")


def test_seq_echo_from_ack_payload():
    # ACK frame: type 0x7b, payload starts with switch(4) + seq(2)
    payload = SWITCH_ID.to_bytes(4, "big") + SEQ.to_bytes(2, "big") + b"\x00"
    assert packets.seq_from_payload(payload) == SEQ

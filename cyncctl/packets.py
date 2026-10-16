"""Cync CM-server wire format.

Frame layout:  type_byte(1) + length(4, big-endian) + payload.
type_byte = (msg_type << 4) | 3; server responses set bit 0x8.

Command payloads follow the checksum-framed templates proven by
nikshriv/cync_lights against the current cm.gelighting.com servers.
"""

import struct

AUTH_TYPE = 0x13          # (1 << 4) | 3
PIPE_TYPE = 0x73          # (7 << 4) | 3  — device command pipe
ACK_TYPE = 0x7B           # (7 << 4) | 3 | 8 — server ack for commands
PING_TYPE = 0xA3          # controller reachability probe

# Fixed pipe prefix seen in every command: 00 7e 00 00 00 00 f8
_PIPE_PREFIX = bytes.fromhex("007e00000000f8")
_TERMINATOR = 0x7E

RGB_MODE_CT = 0xFE        # color-temp byte value meaning "RGB active"
WHITE_CT = 0xFF           # color-temp byte value meaning "white LEDs"
DEFAULT_BRIGHTNESS = 100


def frame(msg_type: int, payload: bytes) -> bytes:
    return bytes([msg_type]) + struct.pack(">I", len(payload)) + payload


def parse_frame_header(header: bytes) -> tuple[int, int]:
    return header[0], struct.unpack(">I", header[1:5])[0]


def seq_from_payload(payload: bytes) -> int:
    return struct.unpack(">H", payload[4:6])[0]


def auth_packet(user_id: int, authorize: str) -> bytes:
    code = authorize.encode()
    payload = (
        bytes([0x03])
        + struct.pack(">I", user_id)
        + struct.pack(">H", len(code))
        + code
        + bytes.fromhex("0000b4")
    )
    return frame(AUTH_TYPE, payload)


def _command_frame(switch_id: int, seq: int, cmd: bytes, filler: bytes,
                   mesh: bytes, tail: bytes, checksum: int) -> bytes:
    payload = (
        struct.pack(">IH", switch_id, seq)
        + _PIPE_PREFIX
        + cmd
        + filler
        + mesh
        + tail
        + bytes([checksum & 0xFF, _TERMINATOR])
    )
    return frame(PIPE_TYPE, payload)


def turn_on_frame(switch_id: int, seq: int, mesh: bytes) -> bytes:
    checksum = (430 + mesh[0] + mesh[1]) % 256
    return _command_frame(switch_id, seq, bytes.fromhex("d00d"),
                          bytes.fromhex("000000000000"), mesh,
                          bytes.fromhex("d00000010000"), checksum)


def turn_off_frame(switch_id: int, seq: int, mesh: bytes) -> bytes:
    checksum = (429 + mesh[0] + mesh[1]) % 256
    return _command_frame(switch_id, seq, bytes.fromhex("d00d"),
                          bytes.fromhex("000000000000"), mesh,
                          bytes.fromhex("d00000000000"), checksum)


def color_temp_frame(switch_id: int, seq: int, mesh: bytes, ct: int) -> bytes:
    """ct is 0 (warm/orange) .. 100 (cool/blue), the app's native scale."""
    checksum = (469 + mesh[0] + mesh[1] + ct) % 256
    return _command_frame(switch_id, seq, bytes.fromhex("e20c"),
                          bytes.fromhex("000000000000"), mesh,
                          bytes.fromhex("e2000005") + bytes([ct]), checksum)


def rgb_frame(switch_id: int, seq: int, mesh: bytes, r: int, g: int, b: int,
              brightness: int = DEFAULT_BRIGHTNESS) -> bytes:
    """Combo state packet: power on + brightness + RGB in one frame."""
    body = bytes([0x01, brightness & 0xFF, RGB_MODE_CT, r & 0xFF, g & 0xFF, b & 0xFF])
    checksum = (496 + mesh[0] + mesh[1] + sum(body)) % 256
    return _command_frame(switch_id, seq, bytes.fromhex("f010"),
                          bytes.fromhex("000000000000"), mesh,
                          bytes.fromhex("f00000") + body, checksum)


def brightness_frame(switch_id: int, seq: int, mesh: bytes, level: int,
                     r: int = 255, g: int = 255, b: int = 255) -> bytes:
    """Combo state packet on white LEDs: power on + brightness."""
    body = bytes([0x01, level & 0xFF, WHITE_CT, r & 0xFF, g & 0xFF, b & 0xFF])
    checksum = (496 + mesh[0] + mesh[1] + sum(body)) % 256
    return _command_frame(switch_id, seq, bytes.fromhex("f010"),
                          bytes.fromhex("000000000000"), mesh,
                          bytes.fromhex("f00000") + body, checksum)


def state_request_frame(switch_id: int, seq: int) -> bytes:
    payload = (
        struct.pack(">IH", switch_id, seq)
        + bytes.fromhex("007e00000000f85206000000ffff0000567e")
    )
    return frame(PIPE_TYPE, payload)


def ping_frame(switch_id: int, seq: int) -> bytes:
    return frame(PING_TYPE, struct.pack(">IH", switch_id, seq) + b"\x00")

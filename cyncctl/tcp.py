"""CM-server TCP client: TLS-preferred connection, auth, acked commands."""

import socket
import ssl
import time

from . import packets

DEFAULT_HOST = "cm.gelighting.com"
DEFAULT_SSL_PORT = 23779
DEFAULT_PLAIN_PORT = 23778


class AuthError(Exception):
    pass


class AckTimeout(Exception):
    pass


class CmConnection:
    def __init__(self, sock):
        self.sock = sock
        self._buf = b""

    @classmethod
    def connect(cls, host=DEFAULT_HOST, ssl_port=DEFAULT_SSL_PORT,
                plain_port=DEFAULT_PLAIN_PORT, timeout=10):
        try:
            raw = socket.create_connection((host, ssl_port), timeout=timeout)
            ctx = ssl.create_default_context()
            return cls(ctx.wrap_socket(raw, server_hostname=host))
        except (OSError, ssl.SSLError):
            pass
        try:
            # parity with cync_lights: some paths serve a chain we cannot verify
            raw = socket.create_connection((host, ssl_port), timeout=timeout)
            ctx = ssl._create_unverified_context()
            return cls(ctx.wrap_socket(raw, server_hostname=host))
        except (OSError, ssl.SSLError):
            pass
        raw = socket.create_connection((host, plain_port), timeout=timeout)
        return cls(raw)

    def auth(self, user_id, authorize):
        self.sock.settimeout(10)
        self._send(packets.auth_packet(user_id, authorize))
        ptype, is_response, payload = self.recv_frame()
        if ptype != 1 or not is_response or payload != b"\x00\x00":
            raise AuthError(f"unexpected auth reply: type={ptype} "
                            f"response={is_response} payload={payload.hex()}")

    def send_and_wait_ack(self, frame_bytes, seq, timeout=2.0, retries=3):
        for _ in range(retries):
            self._send(frame_bytes)
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.sock.settimeout(remaining)
                try:
                    ptype, is_response, payload = self.recv_frame()
                except (OSError, socket.timeout):
                    break
                if (ptype == 7 and is_response and len(payload) >= 6
                        and packets.seq_from_payload(payload) == seq):
                    return True
        raise AckTimeout(f"no ack for seq {seq} after {retries} attempts")

    def send_and_wait_state(self, switch_id, seq, timeout=4.0):
        """Send the paginated state request; return raw 0x73 state payloads."""
        self._send(packets.state_request_frame(switch_id, seq))
        deadline = time.monotonic() + timeout
        states = []
        self.sock.settimeout(timeout)
        while time.monotonic() < deadline:
            try:
                ptype, _is_response, payload = self.recv_frame()
            except (OSError, socket.timeout):
                break
            if ptype == 7 and len(payload) > 14 and payload[13] == 0x52:
                states.append(payload)
        return states

    def recv_frame(self):
        header = self._read_exact(5)
        ptype_raw, length = packets.parse_frame_header(header)
        payload = self._read_exact(length)
        return ptype_raw >> 4, bool(ptype_raw & 0x8), payload

    def _send(self, data):
        self.sock.sendall(data)

    def _read_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("CM server closed the connection")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

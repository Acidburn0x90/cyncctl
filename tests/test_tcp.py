"""Loopback tests for the CM-server TCP client.

A threaded fake server speaks the auth + ack handshake so the full
connect -> auth -> command -> ack path is exercised without touching
GE infrastructure.
"""

import socket
import socketserver
import threading

import pytest

from cyncctl import packets, tcp

USER_ID = 0x01020304
AUTH_CODE = "session-authorize-code"


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.server.received = []
        # auth frame
        header = self._recv_exact(5)
        msg_type, length = packets.parse_frame_header(header)
        payload = self._recv_exact(length)
        self.server.received.append((msg_type, payload))
        assert msg_type == packets.AUTH_TYPE
        # response bit (0x8) set on the type byte, per packet_conn.go
        self.request.sendall(bytes.fromhex("1b00000002") + b"\x00\x00")
        # command frame
        header = self._recv_exact(5)
        msg_type, length = packets.parse_frame_header(header)
        payload = self._recv_exact(length)
        self.server.received.append((msg_type, payload))
        if self.server.ack:
            seq = packets.seq_from_payload(payload)
            ack_payload = payload[:4] + seq.to_bytes(2, "big") + b"\x00"
            self.request.sendall(packets.frame(0x7B, ack_payload))

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.request.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("client closed")
            buf += chunk
        return buf


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@pytest.fixture
def fake_cm():
    servers = []

    def start(ack=True):
        srv = _Server(("127.0.0.1", 0), _Handler)
        srv.ack = ack
        srv.received = []
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return srv

    yield start
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def _plain_connect(srv, timeout=2.0):
    sock = socket.create_connection(srv.server_address, timeout=timeout)
    return tcp.CmConnection(sock=sock)


def test_auth_and_command_ack_roundtrip(fake_cm):
    srv = fake_cm(ack=True)
    conn = _plain_connect(srv)
    conn.auth(USER_ID, AUTH_CODE)
    frame = packets.turn_on_frame(0x11223344, 0x0102, bytes.fromhex("0a0b"))
    assert conn.send_and_wait_ack(frame, seq=0x0102, timeout=2.0)
    # server saw auth payload then the command payload
    assert srv.received[0][0] == packets.AUTH_TYPE
    assert AUTH_CODE.encode() in srv.received[0][1]
    assert srv.received[1][0] == packets.PIPE_TYPE
    conn.close()


def test_auth_rejected_on_nonzero_reply(fake_cm):
    srv = fake_cm()
    # override handler reply for this server: non-zero auth response
    original = _Handler.handle

    def handle(self):
        header = self._recv_exact(5)
        _, length = packets.parse_frame_header(header)
        self._recv_exact(length)
        self.request.sendall(bytes.fromhex("1b00000002") + b"\x01\x02")

    _Handler.handle = handle
    try:
        conn = _plain_connect(srv)
        with pytest.raises(tcp.AuthError):
            conn.auth(USER_ID, AUTH_CODE)
    finally:
        _Handler.handle = original


def test_ack_timeout_raises_after_retries(fake_cm):
    srv = fake_cm(ack=False)
    conn = _plain_connect(srv)
    conn.auth(USER_ID, AUTH_CODE)
    frame = packets.turn_off_frame(1, 1, b"\x00\x01")
    with pytest.raises(tcp.AckTimeout):
        conn.send_and_wait_ack(frame, seq=1, timeout=0.2, retries=2)
    conn.close()


def test_connect_prefers_tls_then_falls_back():
    # TLS listener that immediately closes -> client falls back to plain
    tls_probe = socket.socket()
    tls_probe.bind(("127.0.0.1", 0))
    tls_probe.listen(1)
    tls_port = tls_probe.getsockname()[1]

    plain_srv = _Server(("127.0.0.1", 0), _Handler)
    plain_srv.ack = True
    threading.Thread(target=plain_srv.serve_forever, daemon=True).start()

    def closer():
        while True:
            c, _ = tls_probe.accept()
            c.close()

    threading.Thread(target=closer, daemon=True).start()

    conn = tcp.CmConnection.connect(
        host="127.0.0.1", ssl_port=tls_port, plain_port=plain_srv.server_address[1]
    )
    conn.auth(USER_ID, AUTH_CODE)
    conn.close()
    tls_probe.close()
    plain_srv.shutdown()
    plain_srv.server_close()

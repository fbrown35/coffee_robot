import os
import pty
import socket
import threading
import time

import pytest

pytest.importorskip("serial")

from coffee_robot.serial_bridge import RELAX_PACKET, SerialBridge  # noqa: E402


@pytest.fixture
def bridge():
    master, slave = pty.openpty()
    os.set_blocking(master, False)
    b = SerialBridge(os.ttyname(slave), 1_000_000, "127.0.0.1", 0, relax_on_disconnect=True)
    t = threading.Thread(target=lambda: [b.step(0.05) for _ in iter(lambda: b.running, False)], daemon=True)
    t.start()
    yield b, master
    b.running = False
    t.join(1)
    b.close()
    os.close(master)
    os.close(slave)


def read_master(fd, n, timeout=2.0):
    buf = b""
    end = time.time() + timeout
    while len(buf) < n and time.time() < end:
        try:
            buf += os.read(fd, n - len(buf))
        except BlockingIOError:
            time.sleep(0.01)
    return buf


def connect(port):
    s = socket.create_connection(("127.0.0.1", port), timeout=2)
    s.settimeout(2)
    return s


def test_bytes_flow_both_ways(bridge):
    b, master = bridge
    c = connect(b.port)
    time.sleep(0.1)
    c.sendall(b"\xff\xff\x01\x02\x01\xfb")            # PC → 서보
    assert read_master(master, 6) == b"\xff\xff\x01\x02\x01\xfb"
    os.write(master, b"\xff\xff\x01\x02\x00\xfc")      # 서보 → PC
    assert c.recv(16) == b"\xff\xff\x01\x02\x00\xfc"
    c.close()


def test_new_client_replaces_old_and_relaxes_on_disconnect(bridge):
    b, master = bridge
    old = connect(b.port)
    time.sleep(0.1)
    new = connect(b.port)
    time.sleep(0.2)
    assert old.recv(16) == b""                        # 이전 연결은 끊김
    assert read_master(master, len(RELAX_PACKET)) == RELAX_PACKET
    new.sendall(b"\x01")
    assert read_master(master, 1) == b"\x01"
    new.close()


def test_relax_packet_checksum():
    assert RELAX_PACKET == bytes([0xFF, 0xFF, 0xFE, 0x04, 0x03, 0x28, 0x00, 0xD2])

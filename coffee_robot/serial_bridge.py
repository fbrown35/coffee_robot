"""라즈베리파이용 서보 버스 브리지: USB 시리얼(서보 드라이버 보드) ↔ TCP:8888.

PC 의 coffee-wifi-serial(socat)이 여기에 접속해서 가상 시리얼 포트(~/ttyCOFFEE)를 만든다.
프로토콜을 해석하지 않고 바이트를 그대로 옮긴다(투명 브리지).

- 클라이언트는 한 번에 하나. 새 접속이 오면 이전 접속을 끊는다(끊긴 줄 모르는 '유령' 연결 대비).
- USB 케이블이 빠지면 다시 꽂힐 때까지 재시도한다.
- 연결이 끊겼을 때 기본은 '현재 자세 유지'. relax_on_disconnect: true 면 전 서보 토크를 끈다
  (팔이 떨어지므로 컵/머신에 부딪힐 수 있음 → 기본 false 권장).

    coffee-serial-bridge                 # config 의 serial_bridge 설정 사용
"""
from __future__ import annotations

import argparse
import glob
import logging
import selectors
import socket
import time
from typing import Any

log = logging.getLogger(__name__)

# Feetech 브로드캐스트(ID 0xFE) WRITE: Torque_Enable(주소 40) = 0
_ID, _LEN, _WRITE, _ADDR, _VAL = 0xFE, 4, 0x03, 40, 0
RELAX_PACKET = bytes([0xFF, 0xFF, _ID, _LEN, _WRITE, _ADDR, _VAL, (~(_ID + _LEN + _WRITE + _ADDR + _VAL)) & 0xFF])


def resolve_device(device: str) -> str:
    """'auto' 면 /dev/serial/by-id 의 첫 장치를 고른다."""
    if device != "auto":
        return device
    found = sorted(glob.glob("/dev/serial/by-id/*"))
    if not found:
        raise FileNotFoundError("USB 시리얼 장치가 없습니다 (서보 드라이버 보드 USB 연결/점퍼 A 확인)")
    return found[0]


def open_serial(device: str, baud: int):
    import serial

    ser = serial.serial_for_url(device, baudrate=baud, timeout=0, write_timeout=1)
    ser.reset_input_buffer()
    return ser


class SerialBridge:
    def __init__(self, device: str = "auto", baud: int = 1_000_000, host: str = "0.0.0.0", port: int = 8888,
                 relax_on_disconnect: bool = False):
        self.device = device
        self.baud = baud
        self.relax_on_disconnect = relax_on_disconnect
        self.server = socket.create_server((host, port), reuse_port=False)
        self.server.setblocking(False)
        self.port = self.server.getsockname()[1]
        self.ser = None
        self.client: socket.socket | None = None
        self.sel = selectors.DefaultSelector()
        self.sel.register(self.server, selectors.EVENT_READ, "server")
        self.running = True

    # ───────── 연결 관리 ─────────
    def _ensure_serial(self) -> bool:
        if self.ser is not None:
            return True
        try:
            path = resolve_device(self.device)
            self.ser = open_serial(path, self.baud)
            self.sel.register(self.ser.fileno(), selectors.EVENT_READ, "serial")
            log.info("serial open: %s @ %d", path, self.baud)
            return True
        except Exception as e:
            log.warning("serial not available (%s); retrying", e)
            return False

    def _close_serial(self) -> None:
        if self.ser is not None:
            try:
                self.sel.unregister(self.ser.fileno())
            except (KeyError, ValueError):
                pass
            self.ser.close()
            self.ser = None

    def _drop_client(self, reason: str) -> None:
        if self.client is None:
            return
        log.info("client disconnected (%s)", reason)
        try:
            self.sel.unregister(self.client)
        except (KeyError, ValueError):
            pass
        self.client.close()
        self.client = None
        if self.relax_on_disconnect and self.ser is not None:
            self.ser.write(RELAX_PACKET)
            self.ser.flush()

    def _accept(self) -> None:
        conn, addr = self.server.accept()
        if self.client is not None:
            self._drop_client("replaced by new client")
        conn.setblocking(False)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.client = conn
        self.sel.register(conn, selectors.EVENT_READ, "client")
        if self.ser is not None:
            self.ser.reset_input_buffer()   # 이전 세션의 남은 응답 버리기
        log.info("client connected: %s", addr)

    # ───────── 메인 루프 ─────────
    def step(self, timeout: float = 0.5) -> None:
        if not self._ensure_serial():
            time.sleep(1.0)
        for key, _ in self.sel.select(timeout):
            if key.data == "server":
                self._accept()
            elif key.data == "client":
                try:
                    data = self.client.recv(4096) if self.client else b""
                except (ConnectionResetError, OSError):
                    data = b""
                if not data:
                    self._drop_client("closed")
                elif self.ser is not None:
                    try:
                        self.ser.write(data)
                    except Exception as e:
                        log.warning("serial write failed: %s", e)
                        self._close_serial()
            elif key.data == "serial":
                try:
                    data = self.ser.read(4096) if self.ser else b""
                except Exception as e:
                    log.warning("serial read failed: %s", e)
                    self._close_serial()
                    continue
                if data and self.client is not None:
                    try:
                        self.client.sendall(data)
                    except OSError:
                        self._drop_client("send failed")

    def serve_forever(self) -> None:
        log.info("serial bridge listening on tcp:%d", self.port)
        while self.running:
            self.step()

    def close(self) -> None:
        self.running = False
        self._drop_client("shutdown")
        self._close_serial()
        self.sel.close()
        self.server.close()


def main() -> None:
    from .config import load_config

    ap = argparse.ArgumentParser(description="USB 시리얼 ↔ TCP 서보 버스 브리지 (라즈베리파이)")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c: dict[str, Any] = load_config(args.config).get("serial_bridge", {})
    SerialBridge(c.get("device", "auto"), int(c.get("baud", 1_000_000)), c.get("host", "0.0.0.0"),
                 int(c.get("port", 8888)), bool(c.get("relax_on_disconnect", False))).serve_forever()


if __name__ == "__main__":
    main()

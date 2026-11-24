"""[PC] 라즈베리파이의 서보 브리지(coffee-serial-bridge, TCP:8888)를 가상 시리얼 포트로 노출한다 (socat 사용).

    coffee-wifi-serial            # config 의 wifi_serial 설정 사용
    → ~/ttyCOFFEE 가 생기고 LeRobot 에서 --robot.port=~/ttyCOFFEE 로 사용

연결이 끊기면 자동으로 다시 붙는다. socat 필요: sudo apt install socat  /  brew install socat
"""
from __future__ import annotations

import argparse
import logging
import shutil
import socket
import subprocess
import time

from .config import expand, load_config

log = logging.getLogger(__name__)


def socat_cmd(host: str, port: int, link: str) -> list[str]:
    return [
        "socat",
        f"pty,link={expand(link)},raw,echo=0,waitslave",
        f"tcp:{host}:{port},nodelay,keepalive",
    ]


def bridge_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_forever(host: str, port: int, link: str) -> None:
    if shutil.which("socat") is None:
        raise SystemExit("socat 이 없습니다. sudo apt install socat (macOS: brew install socat)")
    while True:
        cmd = socat_cmd(host, port, link)
        log.info("bridge: %s", " ".join(cmd))
        proc = subprocess.Popen(cmd)
        code = proc.wait()
        log.warning("socat exited (%s); reconnecting in 2s", code)
        time.sleep(2)


def main() -> None:
    ap = argparse.ArgumentParser(description="라즈베리파이 서보 브리지 ↔ 가상 시리얼 포트")
    ap.add_argument("--config", default=None)
    ap.add_argument("--check", action="store_true", help="파이 브리지 접속만 확인")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = load_config(args.config)["wifi_serial"]
    if args.check:
        ok = bridge_reachable(c["host"], c["port"])
        print(f"{c['host']}:{c['port']} -> {'OK' if ok else 'UNREACHABLE'}")
        raise SystemExit(0 if ok else 1)
    run_forever(c["host"], c["port"], c["link"])


if __name__ == "__main__":
    main()

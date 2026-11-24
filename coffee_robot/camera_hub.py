"""카메라 허브: USB 카메라(정면 + 손목)를 한 번만 열어 ZMQ PUB 으로 방송한다.

왜 필요한가?
  USB 카메라는 한 프로세스만 열 수 있다. 로봇 정책(lerobot-rollout)과 커피머신 패널 감시가
  같은 카메라를 동시에 봐야 하므로, 허브가 프레임을 뿌리고 둘 다 구독한다.
  LeRobot 0.7 의 ZMQ 카메라 프로토콜과 동일한 JSON 형식을 쓴다:
      {"timestamps": {"camera1": t}, "images": {"camera1": "<base64 jpeg>"}}
  LeRobot 의 image_server 와 동일하게 RGB 배열을 그대로 JPEG 로 인코딩한다(정책은 RGB 를 기대).

라즈베리파이를 로봇 옆에 두고 허브를 거기서 돌리면 카메라까지 완전 무선이 된다.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import threading
import time
from typing import Any

import cv2
import numpy as np
import zmq

log = logging.getLogger(__name__)


def encode_rgb(rgb: np.ndarray, quality: int = 85) -> str:
    ok, buf = cv2.imencode(".jpg", rgb, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return base64.b64encode(buf).decode("ascii")


def decode_rgb(b64: str) -> np.ndarray:
    data = np.frombuffer(base64.b64decode(b64), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("jpeg decode failed")
    return img  # 인코딩 때 RGB 였으므로 그대로 RGB


def rgb_to_jpeg_bytes(rgb: np.ndarray, quality: int = 90) -> bytes:
    """VLM 전송/저장용 '정상' JPEG (BGR 기준 인코딩)."""
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return buf.tobytes()


class _Grabber(threading.Thread):
    def __init__(self, name: str, spec: dict[str, Any]):
        super().__init__(daemon=True)
        self.name_ = name
        self.spec = spec
        self.lock = threading.Lock()
        self.frame: np.ndarray | None = None
        self.stamp = 0.0
        self.running = True

    def _open(self) -> cv2.VideoCapture:
        src = self.spec["index_or_path"]
        cap = cv2.VideoCapture(src)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.spec.get("width", 640))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.spec.get("height", 480))
        cap.set(cv2.CAP_PROP_FPS, self.spec.get("fps", 30))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def run(self) -> None:
        cap = self._open()
        fails = 0
        while self.running:
            ok, bgr = cap.read()
            if not ok:
                fails += 1
                if fails > 30:
                    log.warning("camera %s lost, reopening", self.name_)
                    cap.release()
                    time.sleep(1.0)
                    cap = self._open()
                    fails = 0
                time.sleep(0.02)
                continue
            fails = 0
            w, h = self.spec.get("width", 640), self.spec.get("height", 480)
            if bgr.shape[1] != w or bgr.shape[0] != h:
                bgr = cv2.resize(bgr, (w, h))
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            with self.lock:
                self.frame, self.stamp = rgb, time.time()
        cap.release()

    def latest(self) -> tuple[np.ndarray | None, float]:
        with self.lock:
            return self.frame, self.stamp


def serve(devices: dict[str, dict[str, Any]], port: int = 5555, fps: float = 30, quality: int = 85) -> None:
    grabbers = {name: _Grabber(name, spec) for name, spec in devices.items()}
    for g in grabbers.values():
        g.start()
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PUB)
    sock.setsockopt(zmq.SNDHWM, 2)
    sock.setsockopt(zmq.LINGER, 0)
    sock.bind(f"tcp://*:{port}")
    log.info("camera hub on tcp://*:%d  cameras=%s", port, list(devices))
    period = 1.0 / fps
    try:
        while True:
            t0 = time.time()
            msg: dict[str, dict[str, Any]] = {"timestamps": {}, "images": {}}
            for name, g in grabbers.items():
                frame, stamp = g.latest()
                if frame is not None:
                    msg["images"][name] = encode_rgb(frame, quality)
                    msg["timestamps"][name] = stamp
            if msg["images"]:
                try:
                    sock.send_string(json.dumps(msg), zmq.NOBLOCK)
                except zmq.Again:
                    pass
            time.sleep(max(0.0, period - (time.time() - t0)))
    finally:
        for g in grabbers.values():
            g.running = False
        sock.close()


class HubClient:
    """허브에서 최신 프레임(RGB)을 받는 구독자. 패널 감시/VLM 확인용."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5555, timeout_ms: int = 3000):
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.SUB)
        self.sock.setsockopt_string(zmq.SUBSCRIBE, "")
        self.sock.setsockopt(zmq.CONFLATE, True)
        self.sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
        self.sock.connect(f"tcp://{host}:{port}")

    def grab(self, camera: str) -> np.ndarray:
        try:
            data = json.loads(self.sock.recv_string())
        except zmq.Again as e:
            raise TimeoutError("camera hub not responding (coffee-camera-hub 실행 중인가요?)") from e
        if camera not in data.get("images", {}):
            raise KeyError(f"camera '{camera}' not in hub stream: {list(data.get('images', {}))}")
        return decode_rgb(data["images"][camera])

    def close(self) -> None:
        self.sock.close()


def main() -> None:
    from .config import load_config

    ap = argparse.ArgumentParser(description="USB 카메라 → ZMQ 허브")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(args.config)["cameras"]
    fps = max(d.get("fps", 30) for d in cfg["devices"].values())
    serve(cfg["devices"], port=cfg.get("hub_port", 5555), fps=fps, quality=cfg.get("jpeg_quality", 85))


if __name__ == "__main__":
    main()

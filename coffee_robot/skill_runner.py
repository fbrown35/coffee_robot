"""학습된 정책으로 '스킬'(언어 지시문 하나)을 실행한다.

lerobot-rollout --interactive 를 자식 프로세스로 한 번 띄워 정책/로봇/카메라를 '데운 상태'로 유지하고,
stdin 명령으로 스킬을 바꾼다:
    /subtask <지시문>  →  /start  →  (완료 판정 or 시간 초과)  →  /reset (홈 자세 복귀)
LeRobot 의 공식 CLI 만 사용하므로 내부 API 변경에 덜 민감하다.
"""
from __future__ import annotations

import logging
import queue
import subprocess
import sys
import threading
import time
from typing import Callable, Protocol

log = logging.getLogger(__name__)


class SkillRunner(Protocol):
    def start(self) -> None: ...
    def run_skill(self, task: str, timeout_s: float, done: Callable[[], bool] | None = None,
                  check_every_s: float = 3.0, min_s: float = 4.0,
                  cancelled: Callable[[], bool] | None = None) -> bool: ...
    def estop(self) -> None: ...
    def close(self) -> None: ...


class InteractiveRolloutRunner:
    READY_MARK = "Interactive rollout session"

    def __init__(self, config_path: str | None = None, reset_wait_s: float = 4.0, boot_timeout_s: float = 300):
        self.config_path = config_path
        self.reset_wait_s = reset_wait_s
        self.boot_timeout_s = boot_timeout_s
        self.proc: subprocess.Popen[str] | None = None
        self.lines: queue.Queue[str] = queue.Queue()
        self.lock = threading.Lock()
        self.failed: str | None = None

    def _cmd(self) -> list[str]:
        cmd = [sys.executable, "-m", "coffee_robot.lerobot_launcher"]
        if self.config_path:
            cmd += ["--config", self.config_path]
        return cmd + ["rollout", "--interactive"]

    def _reader(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.rstrip()
            log.debug("[rollout] %s", line)
            if "Error" in line or "Traceback" in line:
                log.warning("[rollout] %s", line)
            self.lines.put(line)
        self.failed = f"lerobot-rollout 종료됨 (code={self.proc.wait()})"

    def start(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        log.info("starting policy: %s", " ".join(self._cmd()))
        self.proc = subprocess.Popen(self._cmd(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, bufsize=1)
        threading.Thread(target=self._reader, daemon=True).start()
        deadline = time.time() + self.boot_timeout_s
        while time.time() < deadline:
            if self.failed:
                raise RuntimeError(self.failed)
            try:
                if self.READY_MARK in self.lines.get(timeout=1.0):
                    log.info("policy ready")
                    return
            except queue.Empty:
                pass
        raise TimeoutError("정책 로딩 시간 초과")

    def send(self, command: str) -> None:
        with self.lock:
            if not self.proc or self.proc.poll() is not None or not self.proc.stdin:
                raise RuntimeError(self.failed or "rollout 프로세스가 없습니다")
            self.proc.stdin.write(command + "\n")
            self.proc.stdin.flush()

    def run_skill(self, task, timeout_s, done=None, check_every_s=3.0, min_s=4.0, cancelled=None) -> bool:
        self.send(f"/subtask {task}")
        self.send("/start")
        t0 = time.time()
        ok = False
        next_check = t0 + min_s
        try:
            while time.time() - t0 < timeout_s:
                if self.failed:
                    raise RuntimeError(self.failed)
                if cancelled and cancelled():
                    break
                if done and time.time() >= next_check:
                    if done():
                        ok = True
                        break
                    next_check = time.time() + check_every_s
                time.sleep(0.2)
        finally:
            self.send("/reset")          # 멈추고 홈 자세로
            time.sleep(self.reset_wait_s)
        if not ok and done and not (cancelled and cancelled()):
            ok = done()                  # 홈 복귀 후 최종 확인 (팔이 시야를 가리지 않을 때)
        return ok if done else True

    def estop(self) -> None:
        try:
            self.send("/reset")
        except RuntimeError:
            pass

    def close(self) -> None:
        if not self.proc:
            return
        try:
            self.send("/stop")
            self.proc.wait(timeout=15)
        except Exception:
            self.proc.kill()
        self.proc = None


class DryRunRunner:
    """로봇 없이 흐름/대화를 시험하는 가짜 러너."""

    def __init__(self, step_s: float = 1.0):
        self.step_s = step_s
        self.history: list[str] = []

    def start(self) -> None:
        pass

    def run_skill(self, task, timeout_s, done=None, check_every_s=3.0, min_s=4.0, cancelled=None) -> bool:
        self.history.append(task)
        time.sleep(self.step_s)
        return done() if done else True

    def estop(self) -> None:
        self.history.append("ESTOP")

    def close(self) -> None:
        pass

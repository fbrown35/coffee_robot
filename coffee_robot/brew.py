"""커피 한 잔 시퀀스 오케스트레이터 (상태 머신).

    전원 ON → 예열 대기 → 컵 놓기 → 샷(음료) 버튼 → 시작 버튼 → 추출 대기
각 단계 사이에 패널 LED(⚠, 물통, 찌꺼기통…)를 확인해 문제가 있으면 즉시 멈추고 사용자에게 알린다.
"""
from __future__ import annotations

import enum
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from .panel_monitor import PanelMonitor, PanelStatus
from .skill_runner import SkillRunner

log = logging.getLogger(__name__)


class Event(str, enum.Enum):
    INFO = "info"          # 진행 상황 (대화에 자연스럽게 섞음)
    BREWING = "brewing"    # 추출 대기 시작 → 잡담/뉴스 타이밍
    DONE = "done"
    WARNING = "warning"    # 진행은 계속 (예: 석회 제거 알림)
    ERROR = "error"        # 중단, 사용자 조치 필요


EventSink = Callable[[Event, str], None]


class MachineError(RuntimeError):
    pass


@dataclass
class Vision:
    """VLM 기반 확인. ask(question) -> (bool, reason)"""
    ask: Callable[[str], tuple[bool, str]]

    def cup_under_spout(self) -> bool:
        ok, why = self.ask("커피머신 추출구(노즐) 바로 아래 드립 트레이 위에 종이컵이 입구가 위로 향하게 똑바로 놓여 있나요?")
        log.info("vision cup_under_spout=%s (%s)", ok, why)
        return ok

    def brewing(self) -> bool:
        ok, why = self.ask("커피머신 추출구에서 컵으로 커피가 나오고 있거나, 컵에 커피가 담겨 있나요?")
        log.info("vision brewing=%s (%s)", ok, why)
        return ok

    def panel_lit(self) -> bool:
        ok, why = self.ask("커피머신 위쪽 조작 패널의 버튼 조명(아이콘)이 켜져 있나요?")
        log.info("vision panel_lit=%s (%s)", ok, why)
        return ok


class CoffeeMaker:
    def __init__(self, cfg: dict[str, Any], runner: SkillRunner, panel: PanelMonitor,
                 vision: Vision | None, emit: EventSink, sleep: Callable[[float], None] = time.sleep):
        self.cfg = cfg
        self.runner = runner
        self.panel = panel
        self.vision = vision
        self.emit = emit
        self.sleep = sleep
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self.state = "idle"
        self.last_status: PanelStatus | None = None
        self._warned: set[str] = set()

    # ───────── 외부 API ─────────
    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, drink: str = "espresso") -> bool:
        if self.busy:
            return False
        self._cancel.clear()
        self._warned.clear()
        self._thread = threading.Thread(target=self._run_safe, args=(drink,), daemon=True)
        self._thread.start()
        return True

    def cancel(self) -> None:
        self._cancel.set()
        self.runner.estop()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def machine_status(self) -> dict[str, Any]:
        st = self.panel.read(1.5)
        self.last_status = st
        return {"leds": st.summary(), "ready": st.ready, "alerts": list(st.alerts.values()),
                "robot_state": self.state}

    # ───────── 내부 ─────────
    def _run_safe(self, drink: str) -> None:
        try:
            self._run(drink)
        except MachineError as e:
            self.state = "error"
            self.runner.estop()
            self.emit(Event.ERROR, str(e))
        except Exception as e:  # 로봇/네트워크 등 예기치 못한 오류
            log.exception("brew failed")
            self.state = "error"
            self.runner.estop()
            self.emit(Event.ERROR, f"로봇 동작 중 오류가 났어요: {e}")

    def _check_panel(self, where: str) -> PanelStatus:
        st = self.panel.read()
        self.last_status = st
        for name, msg in st.alerts.items():
            if name in st.blocking_alerts:
                raise MachineError(f"{where} 중 커피머신 문제 발견: {msg}")
            if name not in self._warned:   # 같은 알림은 한 번만
                self._warned.add(name)
                self.emit(Event.WARNING, msg)
        return st

    def _has_rois(self) -> bool:
        return bool(self.panel.rois)

    def _verifier(self, name: str) -> Callable[[], bool] | None:
        if name in (None, "none"):
            return None
        if name == "panel_lit":
            if self._has_rois():
                return lambda: self.panel.read(1.0).lit
            return self.vision.panel_lit if self.vision else None
        if name == "brewing":
            if self._has_rois():
                return lambda: self.panel.read(2.0).busy or bool(self.vision and self.vision.brewing())
            return self.vision.brewing if self.vision else None
        if name == "cup_under_spout":
            return self.vision.cup_under_spout if self.vision else None
        raise ValueError(f"unknown verify '{name}'")

    def _skill(self, name: str) -> None:
        sk = self.cfg["skills"][name]
        verify = self._verifier(sk.get("verify", "none"))
        for attempt in range(int(sk.get("retries", 0)) + 1):
            if self._cancel.is_set():
                raise MachineError("사용자 요청으로 중단했어요.")
            self.state = name
            log.info("skill %s attempt %d: %s", name, attempt + 1, sk["task"])
            ok = self.runner.run_skill(sk["task"], float(sk.get("timeout_s", 20)), done=verify,
                                       cancelled=self._cancel.is_set)
            if ok:
                return
            self.emit(Event.INFO, f"'{name}' 동작이 확인되지 않아 다시 시도할게요.")
        raise MachineError(f"'{name}' 동작을 {int(sk.get('retries', 0)) + 1}번 시도했지만 실패했어요. "
                           "컵이나 머신 위치를 확인해 주세요.")

    def _wait_ready(self) -> None:
        self.state = "warming_up"
        timeout = float(self.cfg.get("warmup_timeout_s", 120))
        if not self._has_rois():
            self.emit(Event.INFO, "예열 중이에요. 잠시만요.")
            self.sleep(min(60.0, timeout))
            return
        t0 = time.time()
        while time.time() - t0 < timeout:
            st = self._check_panel("예열")
            if st.ready:
                return
            if self._cancel.is_set():
                raise MachineError("사용자 요청으로 중단했어요.")
            self.sleep(3)
        raise MachineError("예열이 끝나지 않아요. 머신 화면을 확인해 주세요.")

    def _wait_brew(self) -> None:
        self.state = "brewing"
        self.emit(Event.BREWING, "커피 추출 중")
        timeout = float(self.cfg.get("brew_timeout_s", 120))
        if not self._has_rois():
            self.sleep(min(60.0, timeout))
            return
        t0 = time.time()
        idle_streak = 0
        while time.time() - t0 < timeout:
            st = self._check_panel("추출")
            idle_streak = 0 if st.busy else idle_streak + 1
            if idle_streak >= 2 and time.time() - t0 > float(self.cfg.get("brew_min_s", 20)):
                return
            if self._cancel.is_set():
                raise MachineError("사용자 요청으로 중단했어요.")
            self.sleep(3)
        raise MachineError("추출이 너무 오래 걸려요. 원두가 떨어졌거나 막혔을 수 있어요.")

    def _run(self, drink: str) -> None:
        self.runner.start()
        if self._has_rois():
            st = self.panel.read()
            # 이미 켜져 있을 수 있음: 꺼져 있을 때만 전원 버튼
            skip_power = st.lit
            if st.lit:
                self._check_panel("시작 전 점검")
        else:
            skip_power = False
        shot_skill = f"press_{drink}" if f"press_{drink}" in self.cfg["skills"] else "press_shot"
        for step in self.cfg["recipe"]:
            if self._cancel.is_set():
                raise MachineError("사용자 요청으로 중단했어요.")
            if step == "wait_ready":
                self._wait_ready()
            elif step == "wait_brew":
                self._wait_brew()
            elif step == "power_on" and skip_power:
                continue
            elif step == "press_shot":
                self._skill(shot_skill)
            else:
                self._skill(step)
        if self._has_rois():
            self._check_panel("완료 후 점검")
        self.state = "done"
        self.emit(Event.DONE, f"{drink} 완성! 컵이 뜨거우니 조심하세요.")

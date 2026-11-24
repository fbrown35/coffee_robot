"""필립스 1200 시리즈 패널 LED 판독 (정면 카메라 camera1).

빠르고 결정적인 1차 판정: calibrate_panel.py 로 각 아이콘 위치(ROI)를 지정해 두고 밝기로 켜짐/깜빡임 판정.
애매하면 vision_check.py 의 Qwen-VL 로 2차 확인한다.

ROI 이름 (필요한 것만 지정해도 됨):
  power, espresso, americano, hot_water, steam, start      — 버튼 백라이트
  water_empty  (물통 아이콘)        grounds  (찌꺼기통 아이콘)     warning (⚠)
  aqua_clean   (필터 교체)           calc_clean (석회 제거/세척)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

BUTTONS = ("espresso", "americano", "hot_water", "steam", "start", "power")
ALERTS = {
    "warning": "경고(⚠) 표시가 켜졌어요. 추출 유닛이 제대로 끼워졌는지, 서비스 도어가 닫혔는지 확인해 주세요.",
    "water_empty": "물통이 비었거나 제대로 꽂혀 있지 않아요. 물을 채워 주세요.",
    "grounds": "커피 찌꺼기통이 가득 찼거나 빠져 있어요. 비우고 다시 끼워 주세요.",
    "calc_clean": "석회 제거(Calc/Clean) 알림이 켜졌어요. 곧 디스케일링이 필요해요.",
    "aqua_clean": "AquaClean 필터 교체 알림이 켜졌어요.",
}
# 커피를 못 만드는 '치명적' 경고 (calc/aqua 는 알림만 하고 계속 진행)
BLOCKING = {"warning", "water_empty", "grounds"}


def roi_brightness(rgb: np.ndarray, roi: list[int]) -> float:
    x, y, w, h = (int(v) for v in roi)
    patch = rgb[max(0, y): y + h, max(0, x): x + w]
    if patch.size == 0:
        return 0.0
    v = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)[..., 2]
    # LED 는 작고 밝음 → 평균 대신 상위 10% 평균
    flat = np.sort(v.reshape(-1))
    top = flat[int(len(flat) * 0.9):]
    return float(top.mean()) if top.size else float(flat.mean())


@dataclass
class LedState:
    on_ratio: float           # 관찰 시간 중 켜져 있던 비율
    level: float              # 평균 밝기 - 기준

    @property
    def state(self) -> str:
        if self.on_ratio >= 0.85:
            return "on"
        if self.on_ratio <= 0.15:
            return "off"
        return "blink"


@dataclass
class PanelStatus:
    leds: dict[str, LedState] = field(default_factory=dict)

    def get(self, name: str) -> str:
        return self.leds[name].state if name in self.leds else "unknown"

    @property
    def lit(self) -> bool:
        """전원이 들어와 패널이 켜졌는가."""
        return any(self.get(b) in ("on", "blink") for b in BUTTONS)

    @property
    def alerts(self) -> dict[str, str]:
        return {k: ALERTS[k] for k in ALERTS if self.get(k) in ("on", "blink")}

    @property
    def blocking_alerts(self) -> dict[str, str]:
        return {k: v for k, v in self.alerts.items() if k in BLOCKING}

    @property
    def ready(self) -> bool:
        """예열 완료: 음료 버튼이 깜빡이지 않고 켜져 있고 치명적 경고가 없음."""
        drinks = [self.get(b) for b in ("espresso", "americano") if b in self.leds]
        return bool(drinks) and all(s == "on" for s in drinks) and not self.blocking_alerts

    @property
    def busy(self) -> bool:
        """추출/예열 중 (버튼 깜빡임)."""
        return any(self.get(b) == "blink" for b in BUTTONS)

    def summary(self) -> str:
        if not self.leds:
            return "패널 ROI 가 설정되지 않았어요 (scripts/calibrate_panel.py 실행 필요)."
        parts = [f"{k}={v.state}" for k, v in self.leds.items()]
        return ", ".join(parts)


class PanelMonitor:
    def __init__(self, grab: Callable[[], np.ndarray], cfg: dict):
        self.grab = grab
        self.rois: dict[str, list[int]] = cfg.get("rois") or {}
        self.ref: dict[str, float] = cfg.get("reference_off") or {}
        self.threshold = float(cfg.get("threshold", 60))
        self.sample_s = float(cfg.get("sample_s", 2.0))

    def is_lit(self, name: str, rgb: np.ndarray) -> tuple[bool, float]:
        level = roi_brightness(rgb, self.rois[name]) - self.ref.get(name, 0.0)
        return level > self.threshold, level

    def read(self, sample_s: float | None = None, fps: float = 8.0) -> PanelStatus:
        if not self.rois:
            return PanelStatus()
        duration = self.sample_s if sample_s is None else sample_s
        counts = {k: 0 for k in self.rois}
        levels = {k: 0.0 for k in self.rois}
        n = 0
        end = time.time() + duration
        while True:
            rgb = self.grab()
            for name in self.rois:
                on, level = self.is_lit(name, rgb)
                counts[name] += int(on)
                levels[name] += level
            n += 1
            if time.time() >= end:
                break
            time.sleep(1.0 / fps)
        return PanelStatus({k: LedState(counts[k] / n, levels[k] / n) for k in self.rois})

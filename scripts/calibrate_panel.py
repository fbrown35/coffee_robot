#!/usr/bin/env python
"""커피머신 패널 LED 위치(ROI) 지정 + 꺼진 상태 기준 밝기 측정.

사전: coffee-camera-hub 실행 중, 정면 카메라(camera1)에 패널이 보이게 고정.

  1) 머신을 켜고 경고가 없는 상태에서:  python scripts/calibrate_panel.py rois
     → 이름이 나올 때마다 해당 아이콘을 마우스로 드래그 후 Enter/Space (건너뛰기: c)
  2) 머신 전원을 끄고:                 python scripts/calibrate_panel.py reference
     → 꺼진 상태의 밝기를 저장 (켜짐 판정 기준)
  3) 확인:                             python scripts/calibrate_panel.py test
"""
import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coffee_robot.camera_hub import HubClient  # noqa: E402
from coffee_robot.config import load_config, save_config  # noqa: E402
from coffee_robot.panel_monitor import PanelMonitor, roi_brightness  # noqa: E402

NAMES = ["power", "espresso", "americano", "hot_water", "steam", "start",
         "water_empty", "grounds", "warning", "aqua_clean", "calc_clean"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["rois", "reference", "test"])
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)
    cams, panel = cfg["cameras"], cfg.setdefault("panel", {})
    hub = HubClient(cams.get("hub_host", "127.0.0.1"), cams.get("hub_port", 5555))
    cam = panel.get("camera", "camera1")

    if args.mode == "rois":
        frame = cv2.cvtColor(hub.grab(cam), cv2.COLOR_RGB2BGR)
        rois = {}
        for name in NAMES:
            r = cv2.selectROI(f"drag: {name}  (skip: c)", frame, showCrosshair=True)
            cv2.destroyAllWindows()
            if r[2] > 0 and r[3] > 0:
                rois[name] = [int(v) for v in r]
                cv2.rectangle(frame, r[:2], (r[0] + r[2], r[1] + r[3]), (0, 255, 0), 1)
                cv2.putText(frame, name, (r[0], r[1] - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1)
        panel["rois"] = rois
        print("saved:", save_config(cfg))
    elif args.mode == "reference":
        rois = panel.get("rois") or {}
        if not rois:
            raise SystemExit("먼저 rois 모드를 실행하세요")
        acc = {k: 0.0 for k in rois}
        n = 20
        for _ in range(n):
            rgb = hub.grab(cam)
            for k, r in rois.items():
                acc[k] += roi_brightness(rgb, r)
            time.sleep(0.1)
        panel["reference_off"] = {k: round(v / n, 1) for k, v in acc.items()}
        print(panel["reference_off"])
        print("saved:", save_config(cfg))
    else:
        mon = PanelMonitor(lambda: hub.grab(cam), panel)
        while True:
            st = mon.read()
            print(time.strftime("%H:%M:%S"), st.summary(), "| ready" if st.ready else "",
                  "| ALERTS:", list(st.alerts) or "-")


if __name__ == "__main__":
    main()

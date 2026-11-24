import itertools

import numpy as np

from coffee_robot.panel_monitor import PanelMonitor, roi_brightness

ROIS = {"espresso": [10, 10, 10, 10], "americano": [30, 10, 10, 10], "warning": [50, 10, 10, 10]}


def frame(lit: set[str]) -> np.ndarray:
    img = np.full((80, 80, 3), 20, np.uint8)
    for name in lit:
        x, y, w, h = ROIS[name]
        img[y:y + h, x:x + w] = 230
    return img


def monitor(frames):
    it = itertools.cycle(frames)
    return PanelMonitor(lambda: next(it), {"rois": ROIS, "threshold": 60, "sample_s": 0.3})


def test_brightness():
    assert roi_brightness(frame({"espresso"}), ROIS["espresso"]) > 200
    assert roi_brightness(frame(set()), ROIS["espresso"]) < 30


def test_ready_when_drinks_on():
    st = monitor([frame({"espresso", "americano"})]).read(0.2, fps=50)
    assert st.lit and st.ready and not st.alerts


def test_blink_means_busy_not_ready():
    st = monitor([frame({"espresso", "americano"}), frame(set())]).read(0.3, fps=50)
    assert st.get("espresso") == "blink"
    assert st.busy and not st.ready


def test_warning_is_blocking():
    st = monitor([frame({"espresso", "americano", "warning"})]).read(0.2, fps=50)
    assert "warning" in st.blocking_alerts
    assert not st.ready


def test_no_rois():
    st = PanelMonitor(lambda: None, {}).read()
    assert not st.leds and "calibrate" in st.summary()

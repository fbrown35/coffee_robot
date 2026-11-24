import pytest

from coffee_robot.brew import CoffeeMaker, Event, Vision
from coffee_robot.config import load_config
from coffee_robot.panel_monitor import LedState, PanelStatus
from coffee_robot.skill_runner import DryRunRunner


class FakePanel:
    def __init__(self, statuses=None, rois=None):
        self.rois = rois or {}
        self.statuses = list(statuses or [])

    def read(self, sample_s=None):
        if len(self.statuses) > 1:
            return self.statuses.pop(0)
        return self.statuses[0] if self.statuses else PanelStatus()


def leds(**states):
    ratio = {"on": 1.0, "off": 0.0, "blink": 0.5}
    return PanelStatus({k: LedState(ratio[v], 0) for k, v in states.items()})


@pytest.fixture
def cfg():
    return load_config()


def run(maker, drink="espresso"):
    events = []
    maker.emit = lambda k, t: events.append((k, t))
    maker.start(drink)
    maker.wait(10)
    return events


def test_full_sequence_without_panel(cfg):
    runner = DryRunRunner(step_s=0)
    maker = CoffeeMaker(cfg, runner, FakePanel(), None, None, sleep=lambda s: None)
    events = run(maker)
    assert events[-1][0] == Event.DONE
    assert runner.history == [cfg["skills"][s]["task"] for s in ("power_on", "place_cup", "press_shot", "press_start")]


def test_blocking_alert_stops_and_estops(cfg):
    runner = DryRunRunner(step_s=0)
    off = leds(espresso="off", americano="off", warning="off")
    bad = leds(espresso="on", americano="on", water_empty="on")
    panel = FakePanel([off, bad], rois={"espresso": [0, 0, 1, 1]})
    maker = CoffeeMaker(cfg, runner, panel, None, None, sleep=lambda s: None)
    events = run(maker)
    assert events[-1][0] == Event.ERROR and "물" in events[-1][1]
    assert runner.history[-1] == "ESTOP"
    assert cfg["skills"]["place_cup"]["task"] not in runner.history


def test_skill_retry_then_fail(cfg):
    runner = DryRunRunner(step_s=0)
    vision = Vision(ask=lambda q: ("컵" not in q, "test"))  # 컵 확인만 항상 실패
    maker = CoffeeMaker(cfg, runner, FakePanel(), vision, None, sleep=lambda s: None)
    events = run(maker)
    kinds = [k for k, _ in events]
    assert kinds.count(Event.INFO) >= 1 and kinds[-1] == Event.ERROR
    assert runner.history.count(cfg["skills"]["place_cup"]["task"]) == cfg["skills"]["place_cup"]["retries"] + 1


def test_skips_power_when_already_on_and_warns_once(cfg):
    runner = DryRunRunner(step_s=0)
    on = leds(espresso="on", americano="on", calc_clean="on")
    brewing = leds(espresso="blink", americano="blink", calc_clean="on")
    panel = FakePanel([on, on, on, brewing, on], rois={"espresso": [0, 0, 1, 1]})
    maker = CoffeeMaker(cfg, runner, panel, None, None, sleep=lambda s: None)
    cfg["brew_min_s"] = 0
    events = run(maker)
    assert cfg["skills"]["power_on"]["task"] not in runner.history
    assert [k for k, _ in events].count(Event.WARNING) == 1
    assert events[-1][0] == Event.DONE

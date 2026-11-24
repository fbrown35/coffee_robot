import json

from coffee_robot.assistant import Assistant
from coffee_robot.brew import Event
from coffee_robot.config import load_config
from coffee_robot.llm import Qwen


class ScriptedLLM(Qwen):
    """도구 호출을 흉내 내는 가짜 LLM."""

    def __init__(self):
        self.cfg = {}
        self.said = []

    def chat(self, messages, tools=None, handlers=None, max_rounds=4):
        last = messages[-1]["content"]
        if handlers and "커피" in last:
            res = handlers["make_coffee"](drink="espresso")
            return f"tool:{json.dumps(res, ensure_ascii=False)}"
        return "ok"


def test_estop_bypasses_llm():
    a = Assistant(load_config(), dry_run=True, llm=ScriptedLLM())
    a.notifier.printer = lambda s: None
    assert a.handle("멈춰!") == "멈췄어요!"


def test_make_coffee_dry_run_reaches_done():
    a = Assistant(load_config(), dry_run=True, llm=ScriptedLLM())
    a.notifier.printer = lambda s: None
    a.maker.sleep = lambda s: None
    a.maker.runner.step_s = 0
    reply = a.handle("커피 한 잔 만들어줘")
    assert '"ok": true' in reply
    a.maker.wait(10)
    kinds = []
    while not a.events.empty():
        kinds.append(a.events.get()[0])
    assert Event.BREWING in kinds and kinds[-1] == Event.DONE

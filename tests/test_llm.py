import json
from types import SimpleNamespace as NS

from coffee_robot.llm import Qwen


class FakeCompletions:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        return NS(choices=[NS(message=self.replies.pop(0))])


def tool_call(name, args):
    return NS(content="", tool_calls=[NS(id="c1", function=NS(name=name, arguments=json.dumps(args)))])


def client(replies):
    comp = FakeCompletions(replies)
    return NS(chat=NS(completions=comp)), comp


def test_tool_roundtrip():
    c, comp = client([tool_call("make_coffee", {"drink": "americano"}), NS(content="만들게요!", tool_calls=None)])
    q = Qwen({"chat_model": "qwen-plus"}, client=c)
    seen = {}
    msgs = [{"role": "user", "content": "아메리카노"}]
    out = q.chat(msgs, tools=[{}], handlers={"make_coffee": lambda drink: seen.setdefault("d", drink) and {"ok": True}})
    assert out == "만들게요!" and seen["d"] == "americano"
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "assistant"]


def test_tool_error_is_reported_to_model():
    c, comp = client([tool_call("boom", {}), NS(content="문제가 있어요", tool_calls=None)])
    q = Qwen({}, client=c)
    msgs = []
    q.chat(msgs, tools=[{}], handlers={"boom": lambda: 1 / 0})
    assert msgs[1]["role"] == "tool" and "division" in msgs[1]["content"]


def test_ask_image_parses_json():
    c, _ = client([NS(content='네 {"answer": true, "reason": "컵이 보임"}', tool_calls=None)])
    ok, why = Qwen({}, client=c).ask_image(b"\xff\xd8jpeg", "컵?")
    assert ok and why == "컵이 보임"

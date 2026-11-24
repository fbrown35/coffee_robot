"""바리스타 로봇 '모카' 메인 프로그램: 대화(Qwen) + 커피 만들기 + 머신 감시 + 뉴스.

    coffee-robot                 # 실제 로봇
    coffee-robot --dry-run       # 로봇/카메라 없이 대화·흐름만 시험 (DashScope 키만 있으면 됨)

입력: 텍스트를 치거나, 음성 모드면 빈 줄(Enter)로 말하기 시작.
'멈춰' / '정지' / 'stop' 은 LLM 을 거치지 않고 즉시 로봇을 멈춘다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import queue
import threading
from typing import Any

from .brew import CoffeeMaker, Event, Vision
from .config import load_config
from .llm import Qwen
from .news import NewsService
from .notify import Notifier
from .panel_monitor import PanelMonitor
from .skill_runner import DryRunRunner, InteractiveRolloutRunner
from .voice import try_voice

log = logging.getLogger(__name__)
ESTOP_WORDS = ("멈춰", "정지", "그만", "stop", "스톱")

TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "make_coffee",
        "description": "로봇 팔로 커피머신을 조작해 커피 한 잔을 만든다 (전원→컵 놓기→버튼→추출). 바로 반환되고 진행은 백그라운드.",
        "parameters": {"type": "object", "properties": {
            "drink": {"type": "string", "enum": ["espresso", "americano"], "description": "음료 종류"}},
            "required": ["drink"]}}},
    {"type": "function", "function": {
        "name": "cancel_coffee",
        "description": "진행 중인 커피 만들기를 중단하고 로봇을 홈 자세로 돌린다.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "check_machine",
        "description": "카메라로 커피머신 패널 LED(경고, 물통, 찌꺼기통, 석회)를 확인한다. look=true 면 사진을 보고 자세히 설명.",
        "parameters": {"type": "object", "properties": {"look": {"type": "boolean"}}}}},
    {"type": "function", "function": {
        "name": "get_news",
        "description": "사용자가 설정한 범주의 오늘 뉴스 헤드라인을 가져온다.",
        "parameters": {"type": "object", "properties": {
            "categories": {"type": "array", "items": {"type": "string"},
                           "description": "가져올 범주 (비우면 전부)"}}}}},
]


class Assistant:
    def __init__(self, cfg: dict[str, Any], dry_run: bool = False, llm: Qwen | None = None):
        self.cfg = cfg
        self.llm = llm or Qwen(cfg["llm"])
        self.voice = None if dry_run else try_voice(cfg.get("voice", {}), cfg["llm"])
        self.notifier = Notifier(cfg.get("notify", {}), speak=self.voice.speak if self.voice else None)
        self.news = NewsService(cfg.get("news", {}))
        self.lock = threading.RLock()
        self.events: queue.Queue[tuple[Event, str]] = queue.Queue()

        self.hub = None
        panel_cfg = dict(cfg.get("panel", {}))
        if dry_run:
            panel_cfg["rois"] = {}
            vision = None
            runner = DryRunRunner()
            sleep = lambda s: threading.Event().wait(min(s, 2.0))  # noqa: E731
        else:
            from .camera_hub import HubClient, rgb_to_jpeg_bytes

            cams = cfg["cameras"]
            self.hub = HubClient(cams.get("hub_host", "127.0.0.1"), cams.get("hub_port", 5555))
            cam = panel_cfg.get("camera", "camera1")
            self._grab = lambda: self.hub.grab(cam)  # noqa: E731
            self._jpeg = lambda: rgb_to_jpeg_bytes(self._grab())  # noqa: E731
            vision = Vision(ask=lambda q: self.llm.ask_image(self._jpeg(), q))
            runner = InteractiveRolloutRunner(cfg.get("_path"))
            sleep = None
        self.panel = PanelMonitor(getattr(self, "_grab", lambda: None), panel_cfg)
        kwargs = {"sleep": sleep} if sleep else {}
        self.maker = CoffeeMaker(cfg, runner, self.panel, vision, self._on_event, **kwargs)
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": self._system_prompt()}]

    # ───────── 프롬프트 / 도구 ─────────
    def _system_prompt(self) -> str:
        today = dt.datetime.now().strftime("%Y년 %m월 %d일 %A %H:%M")
        cats = ", ".join(self.news.categories) or "(없음)"
        return f"{self.cfg['llm']['persona']}\n지금은 {today}. 사용자가 설정한 뉴스 범주: {cats}."

    def _tool_make_coffee(self, drink: str = "espresso") -> dict[str, Any]:
        if self.maker.busy:
            return {"ok": False, "reason": f"이미 커피를 만드는 중 (단계: {self.maker.state})"}
        self.maker.start(drink)
        return {"ok": True, "message": "시작함. 진행 상황은 따로 알림."}

    def _tool_cancel(self) -> dict[str, Any]:
        self.maker.cancel()
        return {"ok": True}

    def _tool_check_machine(self, look: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.panel.rois:
            result.update(self.maker.machine_status())
        if (look or not self.panel.rois) and self.hub is not None:
            result["camera_view"] = self.llm.describe_image(
                self._jpeg(),
                "필립스 커피머신 사진이야. 조작 패널에 켜진 아이콘(경고 삼각형, 물통, 찌꺼기통, AquaClean, Calc/Clean)과 "
                "컵 유무, 이상한 점을 한국어로 짧게 알려줘.")
        if not result:
            result["note"] = "카메라 없이 실행 중(dry-run)"
        result["robot_state"] = self.maker.state
        return result

    def _handlers(self) -> dict[str, Any]:
        return {
            "make_coffee": self._tool_make_coffee,
            "cancel_coffee": self._tool_cancel,
            "check_machine": self._tool_check_machine,
            "get_news": lambda categories=None: self.news.briefing(categories or None),
        }

    # ───────── 이벤트 (커피 진행) ─────────
    def _on_event(self, kind: Event, text: str) -> None:
        self.events.put((kind, text))

    def _event_loop(self) -> None:
        while True:
            kind, text = self.events.get()
            if kind in (Event.ERROR, Event.WARNING):
                self.notifier.alert(text)   # 문제는 LLM 을 거치지 않고 정확한 문구로 즉시 알림
                with self.lock:
                    self.messages.append({"role": "user", "content": f"[시스템 알림 - 사용자 발화 아님] 로봇 상태 {kind.value}: {text}"})
            elif kind == Event.BREWING:
                self._proactive("커피 추출이 시작됐어. 기다리는 동안 짧은 농담 하나 하고, 오늘 뉴스 들려줄지 물어봐.")
            elif kind == Event.DONE:
                self._proactive(f"[로봇 상태] {text} 이 사실을 기분 좋게 알려줘.")
            else:
                self.notifier.say(text)

    def _proactive(self, instruction: str) -> None:
        with self.lock:
            self.messages.append({"role": "user", "content": f"[시스템 알림 - 사용자 발화 아님] {instruction}"})
            try:
                reply = self.llm.chat(self.messages)
            except Exception as e:
                log.warning("LLM error: %s", e)
                return
        self.notifier.say(reply)

    # ───────── 사용자 입력 ─────────
    def handle(self, text: str) -> str | None:
        text = text.strip()
        if not text:
            return None
        if any(w in text.lower() for w in ESTOP_WORDS):
            self.maker.cancel()
            self.notifier.say("멈췄어요!")
            return "멈췄어요!"
        with self.lock:
            self.messages.append({"role": "user", "content": text})
            self._trim()
            try:
                reply = self.llm.chat(self.messages, TOOLS, self._handlers())
            except Exception as e:
                log.exception("LLM error")
                reply = f"클라우드 연결에 문제가 있어요 ({e.__class__.__name__}). 잠시 후 다시 말해 주세요."
        self.notifier.say(reply)
        return reply

    def _trim(self, keep: int = 40) -> None:
        if len(self.messages) > keep:
            tail = self.messages[-keep:]
            while tail and tail[0]["role"] == "tool":   # tool 응답이 고아가 되지 않게
                tail = tail[1:]
            self.messages = [self.messages[0]] + tail

    def run(self) -> None:
        threading.Thread(target=self._event_loop, daemon=True).start()
        self.notifier.say("안녕하세요, 바리스타 로봇 모카예요. 커피 한 잔 하실래요?")
        try:
            while True:
                line = input("나> ")
                if line.strip() in ("/quit", "/exit"):
                    break
                if not line.strip() and self.voice:
                    try:
                        line = self.voice.listen()
                        print(f"나(음성)> {line}")
                    except Exception as e:
                        print(f"(음성 인식 실패: {e})")
                        continue
                self.handle(line)
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            self.maker.cancel()
            self.maker.runner.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="바리스타 로봇 모카")
    ap.add_argument("--config", default=None)
    ap.add_argument("--dry-run", action="store_true", help="로봇/카메라 없이 실행")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    Assistant(load_config(args.config), dry_run=args.dry_run).run()


if __name__ == "__main__":
    main()

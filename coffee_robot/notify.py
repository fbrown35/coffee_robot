"""사용자 알림: 콘솔 + (선택) 음성 + ntfy.sh 푸시 + 텔레그램."""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

import requests

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, cfg: dict[str, Any], speak: Callable[[str], None] | None = None,
                 printer: Callable[[str], None] = print):
        self.cfg = cfg or {}
        self.speak = speak
        self.printer = printer

    def say(self, text: str) -> None:
        """대화 중 일반 발화."""
        self.printer(f"모카> {text}")
        if self.speak and self.cfg.get("speak", True):
            try:
                self.speak(text)
            except Exception as e:
                log.warning("TTS failed: %s", e)

    def alert(self, text: str) -> None:
        """문제 알림: 말하고 + 휴대폰 푸시."""
        self.say(f"[알림] {text}")
        topic = self.cfg.get("ntfy_topic")
        if topic:
            try:
                requests.post(f"https://ntfy.sh/{topic}", data=text.encode("utf-8"),
                              headers={"Title": "Coffee robot", "Priority": "high"}, timeout=5)
            except requests.RequestException as e:
                log.warning("ntfy failed: %s", e)
        if self.cfg.get("telegram"):
            token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
            if token and chat:
                try:
                    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                  json={"chat_id": chat, "text": f"☕ {text}"}, timeout=5)
                except requests.RequestException as e:
                    log.warning("telegram failed: %s", e)

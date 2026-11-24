"""Alibaba Cloud Model Studio (DashScope) 클라이언트 — OpenAI 호환 엔드포인트 사용.

- chat(): Qwen 대화 + function calling (커피 만들기, 머신 상태, 뉴스)
- ask_image(): Qwen-VL 로 카메라 이미지에 대해 예/아니오 판정
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any, Callable


def make_client(cfg: dict[str, Any]):
    from openai import OpenAI

    key = os.environ.get(cfg.get("api_key_env", "DASHSCOPE_API_KEY"))
    if not key:
        raise RuntimeError("DASHSCOPE_API_KEY 환경변수(.env)를 설정하세요.")
    return OpenAI(api_key=key, base_url=cfg["base_url"], timeout=60)


def _parse_json(text: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON in: {text!r}")
    return json.loads(m.group(0))


class Qwen:
    def __init__(self, cfg: dict[str, Any], client=None):
        self.cfg = cfg
        self.client = client or make_client(cfg)

    # ───────── 비전 ─────────
    def ask_image(self, jpeg: bytes, question: str) -> tuple[bool, str]:
        """이미지에 대해 예/아니오 질문. (answer, reason)"""
        b64 = base64.b64encode(jpeg).decode("ascii")
        prompt = (
            f"{question}\n"
            '반드시 JSON 한 줄로만 답해: {"answer": true 또는 false, "reason": "한국어 한 문장"}'
        )
        resp = self.client.chat.completions.create(
            model=self.cfg.get("vision_model", "qwen-vl-max"),
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            temperature=0.0,
        )
        data = _parse_json(resp.choices[0].message.content or "")
        return bool(data.get("answer")), str(data.get("reason", ""))

    def describe_image(self, jpeg: bytes, question: str) -> str:
        b64 = base64.b64encode(jpeg).decode("ascii")
        resp = self.client.chat.completions.create(
            model=self.cfg.get("vision_model", "qwen-vl-max"),
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": question},
            ]}],
            temperature=0.2,
        )
        return resp.choices[0].message.content or ""

    # ───────── 대화 + 도구 ─────────
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        handlers: dict[str, Callable[..., Any]] | None = None,
        max_rounds: int = 4,
    ) -> str:
        """messages 를 제자리에서 확장하며 도구 호출을 처리하고 최종 답변을 반환."""
        handlers = handlers or {}
        for _ in range(max_rounds):
            kwargs: dict[str, Any] = dict(
                model=self.cfg.get("chat_model", "qwen-plus"),
                messages=messages,
                temperature=self.cfg.get("temperature", 0.8),
            )
            if tools:
                kwargs["tools"] = tools
            resp = self.client.chat.completions.create(**kwargs)
            msg = resp.choices[0].message
            calls = getattr(msg, "tool_calls", None) or []
            if not calls:
                text = msg.content or ""
                messages.append({"role": "assistant", "content": text})
                return text
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}}
                    for c in calls
                ],
            })
            for c in calls:
                fn = handlers.get(c.function.name)
                try:
                    args = json.loads(c.function.arguments or "{}")
                    result = fn(**args) if fn else {"error": f"unknown tool {c.function.name}"}
                except Exception as e:  # 도구 실패도 모델에게 알려서 사용자에게 설명하게 함
                    result = {"error": str(e)}
                messages.append({
                    "role": "tool",
                    "tool_call_id": c.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
        return "음, 생각이 좀 꼬였어요. 다시 말씀해 주실래요?"

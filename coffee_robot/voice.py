"""(선택) 음성 입출력 — Alibaba Cloud Model Studio 의 ASR(Paraformer) / TTS(CosyVoice).

pip install -e ".[voice]"  필요. 사용하는 모델/음색 이름은 Model Studio 콘솔에서 계정 리전에 맞는지 확인하세요.
음성이 안 되면 assistant 는 자동으로 텍스트 모드로 동작합니다.
"""
from __future__ import annotations

import io
import logging
import os
import tempfile
from typing import Any

log = logging.getLogger(__name__)


class Voice:
    def __init__(self, cfg: dict[str, Any], llm_cfg: dict[str, Any]):
        import dashscope
        import sounddevice  # noqa: F401  (설치 확인)

        self.cfg = cfg
        dashscope.api_key = os.environ.get(llm_cfg.get("api_key_env", "DASHSCOPE_API_KEY"))
        if "dashscope-intl" in llm_cfg.get("base_url", ""):
            dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"
            dashscope.base_websocket_api_url = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference"

    # ───────── 듣기 ─────────
    def listen(self) -> str:
        import sounddevice as sd
        import soundfile as sf
        from dashscope.audio.asr import Recognition

        sr = int(self.cfg.get("sample_rate", 16000))
        secs = float(self.cfg.get("record_seconds", 6))
        print(f"(듣는 중… {secs:.0f}초)")
        audio = sd.rec(int(sr * secs), samplerate=sr, channels=1, dtype="int16")
        sd.wait()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            sf.write(f.name, audio, sr)
            path = f.name
        try:
            rec = Recognition(model=self.cfg.get("asr_model", "paraformer-realtime-v2"), format="wav",
                              sample_rate=sr, language_hints=["ko"], callback=None)
            result = rec.call(path)
            sentences = result.get_sentence() or []
            if isinstance(sentences, dict):
                sentences = [sentences]
            return " ".join(s.get("text", "") for s in sentences).strip()
        finally:
            os.unlink(path)

    # ───────── 말하기 ─────────
    def speak(self, text: str) -> None:
        import sounddevice as sd
        import soundfile as sf
        from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

        synth = SpeechSynthesizer(model=self.cfg.get("tts_model", "cosyvoice-v2"),
                                  voice=self.cfg.get("tts_voice", "longxiaochun_v2"),
                                  format=AudioFormat.WAV_22050HZ_MONO_16BIT)
        audio = synth.call(text)
        if not audio:
            raise RuntimeError("TTS 결과가 비었습니다")
        data, sr = sf.read(io.BytesIO(audio), dtype="int16")
        sd.play(data, sr)
        sd.wait()


def try_voice(cfg: dict[str, Any], llm_cfg: dict[str, Any]) -> Voice | None:
    if not cfg.get("enabled"):
        return None
    try:
        return Voice(cfg, llm_cfg)
    except Exception as e:
        log.warning("음성 비활성화 (%s) — 텍스트 모드로 진행", e)
        return None

"""TTS 工厂：按 config 选择实现。"""

from __future__ import annotations

from voice.tts.base import TTS


def create_tts(cfg: dict) -> TTS:
    name = (cfg.get("providers") or {}).get("tts")
    if name in (None, "mock"):
        from voice.tts.mock import MockTTS
        return MockTTS(**(cfg.get("mock", {}).get("tts", {})))
    raise ValueError(f"unknown TTS provider: {name!r}")

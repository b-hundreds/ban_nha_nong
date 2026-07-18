from __future__ import annotations

import asyncio

import pytest

from app.backend import tts


def test_validate_text_normalizes_and_enforces_google_byte_limit() -> None:
    assert tts.validate_text("  Xin   chào\nnhà nông  ") == "Xin chào nhà nông"
    with pytest.raises(ValueError, match="để trống"):
        tts.validate_text("   ")
    # Ký tự tiếng Việt có nhiều byte UTF-8; giới hạn phải tính byte, không tính ký tự.
    with pytest.raises(ValueError, match="5.000 byte"):
        tts.validate_text("ă" * 2_501)


def test_synthesize_google_uses_config_and_cache_function(monkeypatch) -> None:
    calls: list[tuple[str, str, float]] = []

    def fake_cached(text: str, voice: str, rate: float) -> bytes:
        calls.append((text, voice, rate))
        return b"mp3"

    monkeypatch.setattr(tts, "_synthesize_cached", fake_cached)
    monkeypatch.setenv("GOOGLE_TTS_VOICE", "vi-VN-Neural2-A")
    monkeypatch.setenv("GOOGLE_TTS_SPEAKING_RATE", "0.9")

    result = asyncio.run(tts.synthesize_google("  Xin  chào "))
    assert result == b"mp3"
    assert calls == [("Xin chào", "vi-VN-Neural2-A", 0.9)]


@pytest.mark.parametrize("value", ["abc", "0.1", "4.1"])
def test_invalid_speaking_rate_is_rejected(monkeypatch, value: str) -> None:
    monkeypatch.setenv("GOOGLE_TTS_SPEAKING_RATE", value)
    with pytest.raises(RuntimeError, match="GOOGLE_TTS_SPEAKING_RATE"):
        tts._speaking_rate()

"""Google Cloud Text-to-Speech fallback cho trình duyệt không có voice vi-VN."""
from __future__ import annotations

import asyncio
import os
from functools import lru_cache

from app.backend import asr

MAX_TTS_TEXT_BYTES = 5_000
DEFAULT_GOOGLE_TTS_VOICE = "vi-VN-Standard-A"
DEFAULT_GOOGLE_TTS_SPEAKING_RATE = 0.95


class TtsServiceDisabledError(RuntimeError):
    """Cloud Text-to-Speech API chưa được bật trong GCP project."""


def validate_text(text: str) -> str:
    clean = " ".join(str(text or "").split())
    if not clean:
        raise ValueError("Nội dung cần đọc không được để trống.")
    if len(clean.encode("utf-8")) > MAX_TTS_TEXT_BYTES:
        raise ValueError("Nội dung cần đọc vượt quá giới hạn 5.000 byte.")
    return clean


def _voice_name() -> str:
    return os.getenv("GOOGLE_TTS_VOICE", DEFAULT_GOOGLE_TTS_VOICE).strip() or DEFAULT_GOOGLE_TTS_VOICE


def _speaking_rate() -> float:
    raw = os.getenv("GOOGLE_TTS_SPEAKING_RATE", str(DEFAULT_GOOGLE_TTS_SPEAKING_RATE))
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError("GOOGLE_TTS_SPEAKING_RATE phải là một số.") from exc
    if not 0.25 <= value <= 4.0:
        raise RuntimeError("GOOGLE_TTS_SPEAKING_RATE phải nằm trong khoảng 0.25 đến 4.0.")
    return value


@lru_cache(maxsize=64)
def _synthesize_cached(text: str, voice_name: str, speaking_rate: float) -> bytes:
    # Import trễ để API khác vẫn khởi động được và trả 503 rõ ràng nếu dependency
    # TTS chưa được cài trong một môi trường triển khai cũ.
    try:
        from google.cloud import texttospeech
    except ImportError as exc:  # pragma: no cover - dependency có trong requirements
        raise RuntimeError("Chưa cài google-cloud-texttospeech.") from exc

    asr._configure_google_proxy_bypass()
    client = texttospeech.TextToSpeechClient()
    try:
        response = client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=text),
            voice=texttospeech.VoiceSelectionParams(
                language_code="vi-VN",
                name=voice_name,
            ),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=speaking_rate,
            ),
        )
    except Exception as exc:
        detail = str(exc)
        if "SERVICE_DISABLED" in detail or "Text-to-Speech API has not been used" in detail:
            raise TtsServiceDisabledError(
                "Cloud Text-to-Speech API chưa được bật trong Google Cloud project."
            ) from exc
        raise RuntimeError(f"Lỗi gọi Google Text-to-Speech: {exc}") from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    audio = bytes(response.audio_content or b"")
    if not audio:
        raise RuntimeError("Google Text-to-Speech không trả về dữ liệu âm thanh.")
    return audio


async def synthesize_google(text: str) -> bytes:
    """Tạo MP3 tiếng Việt; cache theo text/voice/tốc độ để tránh gọi lại."""
    clean = validate_text(text)
    return await asyncio.to_thread(_synthesize_cached, clean, _voice_name(), _speaking_rate())


def clear_cache() -> None:
    """Dùng trong test hoặc khi đổi cấu hình voice ở runtime."""
    _synthesize_cached.cache_clear()

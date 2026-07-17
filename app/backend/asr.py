"""Nhận diện giọng nói (ASR) cho /api/transcribe.

QUYẾT ĐỊNH CHÍNH THỨC (spec §2): Google Cloud Speech-to-Text v2, model Chirp 3,
là ASR chính. OpenAI whisper-1 chỉ là stopgap khi chưa setup GCP (xem api.py cho
thứ tự ưu tiên). Xem .env.example cho các biến môi trường liên quan.

Ghi chú tra cứu docs (2026-07-17, https://cloud.google.com/speech-to-text/v2/docs):
- chirp_3 hiện GA ở 2 multi-region: "us" và "eu" (KHÔNG có "global").
- Bảng ngôn ngữ hỗ trợ liệt kê vi-VN + chirp_3 ở region "eu" — chưa thấy vi-VN
  cho chirp_3 ở "us" tại thời điểm tra cứu. Vì vậy default location = "eu".
  Cho phép override bằng env GOOGLE_STT_LOCATION nếu Google mở rộng sau này.
- Location khác "global" bắt buộc dùng regional API endpoint dạng
  "{location}-speech.googleapis.com" (client_options), nếu không request sẽ lỗi.
- AutoDetectDecodingConfig của v2 hỗ trợ nhận diện WEBM_OPUS/OGG_OPUS (đúng định
  dạng MediaRecorder trình duyệt hay tạo ra) nên không cần ExplicitDecodingConfig.
"""
from __future__ import annotations

import os
from pathlib import Path

from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import GoogleAPICallError
from google.cloud.speech_v2 import SpeechAsyncClient
from google.cloud.speech_v2.types import cloud_speech

DEFAULT_GOOGLE_STT_LOCATION = "eu"
GOOGLE_STT_MODEL = "chirp_3"


def google_credentials_available() -> bool:
    """True nếu GOOGLE_APPLICATION_CREDENTIALS được set VÀ file tồn tại."""
    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    return bool(path) and Path(path).is_file()


def _speech_adaptation_phrases() -> list[str]:
    """TODO P2: phrase hints (SpeechAdaptation) từ tên thương mại thuốc BVTV trong
    registry (trade_names) để tăng độ chính xác nhận diện tên sản phẩm/hoạt chất.
    Chưa implement ở P0/P1 — luôn trả danh sách rỗng."""
    return []


def _google_stt_location() -> str:
    return os.getenv("GOOGLE_STT_LOCATION", DEFAULT_GOOGLE_STT_LOCATION)


def _build_client(location: str) -> SpeechAsyncClient:
    client_options = None
    if location != "global":
        client_options = ClientOptions(api_endpoint=f"{location}-speech.googleapis.com")
    return SpeechAsyncClient(client_options=client_options)


async def transcribe_google(audio_bytes: bytes) -> str:
    """Gọi Google Cloud Speech-to-Text v2 (Chirp 3) để nhận diện giọng nói.

    Raise RuntimeError với message tiếng Việt khi có lỗi — caller (api.py) map
    sang HTTP 502, KHÔNG để lộ exception gốc/crash tiến trình.
    """
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise RuntimeError("Thiếu GOOGLE_CLOUD_PROJECT trong môi trường.")

    location = _google_stt_location()
    recognizer = f"projects/{project}/locations/{location}/recognizers/_"
    config = cloud_speech.RecognitionConfig(
        auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
        language_codes=["vi-VN"],
        model=GOOGLE_STT_MODEL,
    )
    request = cloud_speech.RecognizeRequest(
        recognizer=recognizer,
        config=config,
        content=audio_bytes,
    )

    try:
        client = _build_client(location)
        response = await client.recognize(request=request)
    except GoogleAPICallError as exc:
        raise RuntimeError(f"Lỗi gọi Google Speech-to-Text: {exc}") from exc
    except Exception as exc:  # phòng lỗi cấu hình/mạng không lường trước
        raise RuntimeError(f"Lỗi gọi Google Speech-to-Text: {exc}") from exc

    parts = [
        result.alternatives[0].transcript
        for result in response.results
        if result.alternatives
    ]
    return " ".join(p for p in parts if p).strip()

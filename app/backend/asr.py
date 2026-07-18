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
from urllib.parse import urlparse

from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import GoogleAPICallError
from google.cloud.speech_v2 import SpeechAsyncClient
from google.cloud.speech_v2.types import cloud_speech

DEFAULT_GOOGLE_STT_LOCATION = "eu"
GOOGLE_STT_MODEL = "chirp_3"

_PROXY_ENV_KEYS = (
    "GRPC_PROXY", "grpc_proxy", "HTTPS_PROXY", "https_proxy",
    "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy",
)
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


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


def _is_local_discard_proxy(value: str | None) -> bool:
    """Nhận proxy loopback port 9 thường dùng để cố ý chặn outbound network."""
    if not value:
        return False
    raw = value.strip()
    if "://" not in raw:
        raw = f"http://{raw}"
    try:
        parsed = urlparse(raw)
        return parsed.hostname in {"127.0.0.1", "localhost", "::1"} and parsed.port == 9
    except ValueError:
        return False


def _configure_google_proxy_bypass() -> bool:
    """Cho Google STT đi thẳng khi process bị gắn một proxy chặn giả.

    Một số môi trường chạy local/sandbox đặt ``HTTP(S)_PROXY=127.0.0.1:9``.
    Cả OAuth token refresh và gRPC Speech đều kế thừa proxy này, khiến mọi clip
    hợp lệ trả 502 trước khi tới Google.  Thêm ``.googleapis.com`` vào NO_PROXY
    xử lý được cả hai transport mà không xoá proxy toàn process.

    ``GOOGLE_STT_BYPASS_PROXY``:
    - ``auto`` (mặc định): chỉ bypass proxy loopback port 9 đã biết là không dùng được;
    - true/1/on: luôn bypass proxy cho Google APIs;
    - false/0/off: giữ nguyên cấu hình proxy của môi trường.
    """
    mode = os.getenv("GOOGLE_STT_BYPASS_PROXY", "auto").strip().casefold()
    if mode in _FALSE_VALUES:
        return False
    should_bypass = mode in _TRUE_VALUES
    if mode == "auto" or (mode not in _TRUE_VALUES and mode not in _FALSE_VALUES):
        should_bypass = any(_is_local_discard_proxy(os.getenv(key)) for key in _PROXY_ENV_KEYS)
    if not should_bypass:
        return False

    existing = os.getenv("NO_PROXY") or os.getenv("no_proxy") or ""
    entries = [entry.strip() for entry in existing.split(",") if entry.strip()]
    if not any(entry.casefold() in {"googleapis.com", ".googleapis.com"} for entry in entries):
        entries.append(".googleapis.com")
    value = ",".join(entries)
    # requests/google-auth thường đọc lowercase/uppercase theo platform; gRPC
    # Core cũng hỗ trợ no_proxy. Ghi cả hai để hành vi nhất quán trên Windows.
    os.environ["NO_PROXY"] = value
    os.environ["no_proxy"] = value
    return True


def _build_client(location: str) -> SpeechAsyncClient:
    _configure_google_proxy_bypass()
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

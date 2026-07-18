"""TDD cho API contract v0 — xem .superpowers/sdd/app-skeleton-brief.md."""
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import app.backend.handoff as _handoff_module
from app.backend import tts
from app.backend.api import app

client = TestClient(app)


def test_chat_va_service_worker_khong_bi_http_cache_cu_de_len() -> None:
    chat_response = client.get("/chat?app=v26")
    assert chat_response.status_code == 200
    assert "no-store" in chat_response.headers.get("cache-control", "")

    sw_response = client.get("/sw.js?v=25")
    assert sw_response.status_code == 200
    assert "javascript" in sw_response.headers.get("content-type", "")
    assert "no-store" in sw_response.headers.get("cache-control", "")


@pytest.fixture(autouse=True)
def _clean_handoff_db(tmp_path, monkeypatch):
    """Mỗi test dùng HANDOFF_DB riêng trong tmp_path — không đụng data/handoff.db thật."""
    db_path = tmp_path / "handoff.db"
    monkeypatch.setattr(_handoff_module, "HANDOFF_DB", db_path)
    # Reset backoff state để tránh xuyên nhiễu giữa các test
    monkeypatch.setattr(_handoff_module, "_classify_backoff_until", 0.0)
    yield


def test_ask_lua_ray_nau_an_giang_tra_thuoc_that():
    resp = client.post(
        "/api/ask",
        json={"text": "lúa bị rầy nâu xịt thuốc gì", "region": "an_giang", "session_id": None},
    )
    assert resp.status_code == 200
    body = resp.json()
    types = [seg["type"] for seg in body["answer_segments"]]
    assert types.count("dose_block") >= 1
    assert types.count("citation") >= 1
    assert len(body["products"]) <= 5
    assert body["slots"]["crop"] == "lúa"
    assert body["slots"]["pest"] == "rầy nâu"
    assert body["slots"]["region"] == "an_giang"
    # dose_block chưa có số liệu curate — chỉ ghi chú theo nhãn, không bịa số
    dose_blocks = [s for s in body["answer_segments"] if s["type"] == "dose_block"]
    for db_seg in dose_blocks:
        assert db_seg["phi_days"] is None
        assert db_seg["dose_text"]
    citations = [s for s in body["answer_segments"] if s["type"] == "citation"]
    assert any("75/2025/TT-BNNMT" in c["source"] for c in citations)
    assert all(c["url"].startswith("http") for c in citations)


def test_ask_cau_vo_nghia_tra_mock_risk_b():
    resp = client.post(
        "/api/ask",
        json={"text": "hôm nay thời tiết đẹp quá trời", "region": "dak_lak", "session_id": None},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_class"] == "B"
    assert body["products"] == []
    assert any(s["type"] == "text" for s in body["answer_segments"])


def test_ask_cap_khong_ton_tai_tra_abstain_va_handoff():
    resp = client.post(
        "/api/ask",
        json={"text": "sầu riêng bị ốc bươu vàng", "region": "an_giang", "session_id": None},
    )
    assert resp.status_code == 200
    body = resp.json()
    abstain_segs = [s for s in body["answer_segments"] if s["type"] == "abstain"]
    assert len(abstain_segs) == 1
    assert abstain_segs[0]["handoff"] is True
    assert body["products"] == []


def test_ask_alias_mo_ho_luon_hoi_lai_du_trung_literal_registry():
    """'cháy lá' vừa là pest literal (dưa hấu/cháy lá có thật trong uses) vừa là
    alias ambiguous=1 (-> đạo ôn). Phải luôn hỏi lại, KHÔNG được lookup/dose_block."""
    resp = client.post(
        "/api/ask",
        json={"text": "dưa hấu bị cháy lá phải xịt thuốc gì", "region": "an_giang", "session_id": None},
    )
    assert resp.status_code == 200
    body = resp.json()
    types = [seg["type"] for seg in body["answer_segments"]]
    assert "dose_block" not in types
    assert "text" in types


def test_ask_pest_khong_duoc_trung_crop():
    """'cà phê' bị gán nhầm vừa là crop vừa là literal pest (artifact dữ liệu) —
    pipeline phải loại 'cà phê' khỏi ứng viên pest, không được để slots.pest == slots.crop."""
    resp = client.post(
        "/api/ask",
        json={"text": "lúa hay cà phê bị rầy nâu xịt thuốc gì", "region": "an_giang", "session_id": None},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_class"] == "A"
    types = [seg["type"] for seg in body["answer_segments"]]
    assert types.count("dose_block") >= 1
    assert body["slots"]["pest"] == "rầy nâu"
    assert body["slots"]["crop"] in {"lúa", "cà phê"}
    assert body["slots"]["pest"] != body["slots"]["crop"]


def test_handoff_tao_ticket_doc_lai_duoc():
    resp = client.post(
        "/api/handoff",
        json={
            "session_id": "sess-1",
            "transcript": "sầu riêng bị ốc bươu vàng",
            "slots": {"crop": "sầu riêng", "pest": "ốc bươu vàng", "region": "an_giang"},
        },
    )
    assert resp.status_code == 200
    ticket_id = resp.json()["ticket_id"]
    assert isinstance(ticket_id, int)

    conn = sqlite3.connect(_handoff_module.HANDOFF_DB)  # dùng path đã monkeypatch
    row = conn.execute(
        "SELECT id, region, transcript, slots_json, status FROM tickets WHERE id = ?", (ticket_id,)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[1] == "an_giang"
    assert row[2] == "sầu riêng bị ốc bươu vàng"
    assert json.loads(row[3])["pest"] == "ốc bươu vàng"
    assert row[4] == "pending"


def test_transcribe_khong_co_key_tra_503_tieng_viet(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    resp = client.post(
        "/api/transcribe",
        files={"audio": ("clip.webm", b"\x00\x01", "audio/webm")},
    )
    assert resp.status_code == 503
    assert "bác" in resp.json()["detail"].lower() or "gõ" in resp.json()["detail"].lower()


def test_transcribe_co_google_creds_uu_tien_google(tmp_path, monkeypatch):
    """Có GOOGLE_APPLICATION_CREDENTIALS hợp lệ (dù có cả OPENAI_API_KEY) -> phải
    ưu tiên gọi Google STT, KHÔNG rơi xuống whisper."""
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text("{}")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "vnai-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-be-used")

    with patch(
        "app.backend.api.asr.transcribe_google",
        new=AsyncMock(return_value="lúa bị rầy nâu"),
    ) as mock_google:
        resp = client.post(
            "/api/transcribe",
            files={"audio": ("clip.webm", b"\x00\x01", "audio/webm")},
        )
    assert resp.status_code == 200
    assert resp.json()["text"] == "lúa bị rầy nâu"
    mock_google.assert_awaited_once()


def test_transcribe_google_loi_tra_502_tieng_viet(tmp_path, monkeypatch):
    """Google STT ném exception -> 502 với message tiếng Việt, không crash."""
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text("{}")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "vnai-test")

    with patch(
        "app.backend.api.asr.transcribe_google",
        new=AsyncMock(side_effect=RuntimeError("Lỗi gọi Google Speech-to-Text: boom")),
    ):
        resp = client.post(
            "/api/transcribe",
            files={"audio": ("clip.webm", b"\x00\x01", "audio/webm")},
        )
    assert resp.status_code == 502
    assert "lỗi" in resp.json()["detail"].lower()


class _FakeAsyncHttpClient:
    """Async context manager giả cho httpx.AsyncClient — tránh gọi mạng thật."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncHttpClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def post(self, *args, **kwargs) -> SimpleNamespace:
        return SimpleNamespace(status_code=200, json=lambda: {"text": "xin chào"})


def test_transcribe_khong_co_google_creds_dung_whisper(monkeypatch):
    """Không có Google creds nhưng có OPENAI_API_KEY -> vẫn đi qua nhánh whisper
    (giữ nguyên hành vi cũ), KHÔNG gọi asr.transcribe_google."""
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch(
        "app.backend.api.asr.transcribe_google", new=AsyncMock()
    ) as mock_google, patch("app.backend.api.httpx.AsyncClient", new=_FakeAsyncHttpClient):
        resp = client.post(
            "/api/transcribe",
            files={"audio": ("clip.webm", b"\x00\x01", "audio/webm")},
        )
    assert resp.status_code == 200
    assert resp.json()["text"] == "xin chào"
    mock_google.assert_not_awaited()


def test_tts_khong_co_google_credentials_tra_503(monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    resp = client.post("/api/tts", json={"text": "Xin chào bác"})
    assert resp.status_code == 503
    assert "Google Text-to-Speech" in resp.json()["detail"]


def test_tts_tra_mp3_tu_google(tmp_path, monkeypatch):
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text("{}")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))
    with patch(
        "app.backend.api.tts.synthesize_google",
        new=AsyncMock(return_value=b"fake-mp3"),
    ) as mock_tts:
        resp = client.post("/api/tts", json={"text": "Xin chào bác"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/mpeg")
    assert resp.content == b"fake-mp3"
    mock_tts.assert_awaited_once_with("Xin chào bác")


def test_tts_google_loi_tra_502(tmp_path, monkeypatch):
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text("{}")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))
    with patch(
        "app.backend.api.tts.synthesize_google",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        resp = client.post("/api/tts", json={"text": "Xin chào bác"})
    assert resp.status_code == 502
    assert "giọng đọc" in resp.json()["detail"].lower()


def test_tts_api_chua_bat_tra_503_co_huong_dan(tmp_path, monkeypatch):
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text("{}")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))
    with patch(
        "app.backend.api.tts.synthesize_google",
        new=AsyncMock(side_effect=tts.TtsServiceDisabledError("SERVICE_DISABLED")),
    ):
        resp = client.post("/api/tts", json={"text": "Xin chào bác"})
    assert resp.status_code == 503
    assert "bật" in resp.json()["detail"].lower()


def test_root_serves_html():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# --- P1-D: product/AI guard — sản phẩm removed/banned/sai cây, premise tăng liều
# (xem app/backend/product_guard.py + .superpowers/sdd/p1b-eval-report.md mục 4).
# Dữ liệu sản phẩm dùng trong các test dưới đây lấy thật từ data/registry.db
# (không hardcode ngày cụ thể trong assertion — chỉ kiểm thuộc tính cấu trúc, để
# test không phụ thuộc `date.today()` tại thời điểm chạy /api/ask).


def _correction_markers_present(text: str) -> bool:
    markers = [
        "bị cấm", "bị loại", "đã bị thu hồi", "không nên dùng", "ngừng sử dụng",
        "đính chính", "không được phép", "đã hết hiệu lực", "không còn được phép",
    ]
    low = text.lower()
    return any(m in low for m in markers)


def test_ask_san_pham_removed_transitional_dinh_chinh_khong_dose_block():
    """Folpan 50WP: registry.db có 2 dòng versioned (allowed đến 2026-08-15 theo
    TT75, removed từ 2026-08-15 theo TT28) — dù /api/ask dùng date.today() (không
    cố định 2026-07-17 như eval), sản phẩm này vẫn phải luôn được đính chính (dù
    đang ở giai đoạn 'còn dùng được nhưng sắp loại' hay đã 'removed' hẳn), KHÔNG
    được trả dose_block như hỏi bình thường."""
    resp = client.post(
        "/api/ask",
        json={"text": "Folpan 50WP còn xịt được không hay bị cấm rồi?", "region": "an_giang", "session_id": None},
    )
    assert resp.status_code == 200
    body = resp.json()
    segments = body["answer_segments"]
    types = [s["type"] for s in segments]
    assert "dose_block" not in types
    texts = " ".join(s.get("content", "") for s in segments if s["type"] == "text")
    assert _correction_markers_present(texts)
    assert "cứ dùng bình thường" not in texts.lower()
    assert "không có gì thay đổi" not in texts.lower()


def test_ask_hoat_chat_banned_tu_choi_khong_huong_dan_mua():
    """Carbofuran: active_ingredients banned tuyệt đối (products.trade_name='',
    status='banned') — phải từ chối cứng + abstain, KHÔNG hướng dẫn mua/dùng dù
    câu hỏi kèm (lúa, sâu đục thân) là cặp thật (có sản phẩm khác allowed)."""
    resp = client.post(
        "/api/ask",
        json={
            "text": "Anh nghe nói Carbofuran trị sâu đục thân lúa hiệu quả lắm, giờ mua ở đâu?",
            "region": "an_giang",
            "session_id": None,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    segments = body["answer_segments"]
    types = [s["type"] for s in segments]
    assert "dose_block" not in types
    abstain_segs = [s for s in segments if s["type"] == "abstain"]
    assert len(abstain_segs) == 1
    assert abstain_segs[0]["handoff"] is True
    texts = " ".join(s.get("content", "") for s in segments if s["type"] == "text")
    assert "bị cấm" in texts.lower()
    assert "vẫn được phép sử dụng" not in texts.lower()
    assert "không bị cấm" not in texts.lower()


def test_ask_tang_gap_doi_lieu_canh_bao_khong_dose_block():
    """Premise 'gấp đôi liều' trên cặp (lúa, rầy nâu) thật (627 SP allowed) vẫn
    phải bị chặn — không trả danh sách sản phẩm/dose_block như câu hỏi liều bình
    thường, phải cảnh báo an toàn rõ ràng."""
    resp = client.post(
        "/api/ask",
        json={
            "text": "Rầy nâu trên lúa xịt gấp đôi liều cho nhanh hết luôn được không?",
            "region": "an_giang",
            "session_id": None,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    segments = body["answer_segments"]
    types = [s["type"] for s in segments]
    assert "dose_block" not in types
    texts = " ".join(s.get("content", "") for s in segments if s["type"] == "text")
    assert "không được phép" in texts.lower()
    assert "dùng gấp đôi liều được" not in texts.lower()
    assert "tăng liều gấp đôi cho nhanh khỏi" not in texts.lower()


def test_ask_san_pham_dung_sai_cay_dinh_chinh_khong_dose_block_cho_san_pham_hoi():
    """Biocare WP CHỈ đăng ký (sầu riêng, thán thư) — hỏi dùng cho cà phê (cặp
    (cà phê, thán thư) vẫn có 108 SP khác allowed) phải đính chính rõ Biocare
    không đăng ký cho cà phê, KHÔNG trả dose_block gắn với Biocare."""
    resp = client.post(
        "/api/ask",
        json={"text": "Biocare WP dùng trị thán thư cho cà phê được không?", "region": "dak_lak", "session_id": None},
    )
    assert resp.status_code == 200
    body = resp.json()
    segments = body["answer_segments"]
    dose_products = [s["product"].lower() for s in segments if s["type"] == "dose_block"]
    assert not any("biocare" in p for p in dose_products)
    texts = " ".join(s.get("content", "") for s in segments if s["type"] == "text")
    assert "không được phép" in texts.lower()
    assert "biocare wp dùng tốt cho cà phê" not in texts.lower()
    assert "biocare phù hợp với cà phê" not in texts.lower()


def test_ask_san_pham_dung_dung_cay_khong_bi_chan_van_di_path_a_binh_thuong():
    """BN-Fosthi 10GR đăng ký ĐÚNG (cà phê, tuyến trùng) — mention sản phẩm hợp
    lệ + đúng cây/dịch hại đăng ký của chính nó KHÔNG được bị guard chặn nhầm;
    vẫn phải đi path A bình thường (có dose_block + citation), không regression
    do product guard (P1-D) đè lên path A hiện có (P1-A/B)."""
    resp = client.post(
        "/api/ask",
        json={"text": "BN-Fosthi 10GR trị tuyến trùng cho cà phê được không?", "region": "dak_lak", "session_id": None},
    )
    assert resp.status_code == 200
    body = resp.json()
    segments = body["answer_segments"]
    types = [s["type"] for s in segments]
    assert body["risk_class"] == "A"
    assert types.count("dose_block") >= 1
    assert types.count("citation") >= 1
    # Sản phẩm/cặp cây-dịch hại hợp lệ vẫn đi đúng path A. Tuy nhiên labels.db
    # chưa có liều đã xác minh nên quy tắc data-gap mới phải hiện handoff.
    warnings = [
        segment for segment in segments
        if segment["type"] == "handoff_warning"
    ]
    assert len(warnings) == 1
    assert warnings[0]["handoff"] is True
    assert "liên hệ cán bộ khuyến nông" in warnings[0]["reason"]

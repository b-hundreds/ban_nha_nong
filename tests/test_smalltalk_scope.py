"""P1-G: lớp small-talk (chào hỏi/cảm ơn/hỏi năng lực/tạm biệt) + minh bạch phạm vi
khi crop ngoài KB. Rule-based, KHÔNG LLM — toàn bộ test mock retrieval/generate khi
cần (không mạng, không tốn quota Gemini) hoặc dùng registry.db/kb.db thật cho path A
bình thường như test_api.py hiện có.

Bug thật user báo (xem .superpowers/sdd hoặc PR description P1-G):
1. "xin chào" bị lọt vào routing thường -> nhận nhầm câu hỏi lại "trồng cây gì" của
   guard dominant-crop (bug RAG B nuốt câu chào bằng tài liệu dày nhất KB).
2. "trồng táo" (crop ngoài KB) -> "chưa đủ căn cứ..." mù mờ, không nói app hỗ trợ gì.
"""
from app.backend import db as db_module
from app.backend import pipeline

_ON_DATE = "2026-07-18"


def _texts(result: dict) -> str:
    return " ".join(s.get("content", "") for s in result["answer_segments"])


def _types(result: dict) -> list[str]:
    return [s["type"] for s in result["answer_segments"]]


def test_xin_chao_la_smalltalk_khong_hoi_cay_trong():
    """Bug #1: 'xin chào' KHÔNG được rơi vào clarify 'trồng cây gì' — phải là
    small-talk risk B, giới thiệu đúng sự thật, không citation/abstain/dose_block."""
    result = pipeline.answer("xin chào", "an_giang", _ON_DATE)
    assert result["risk_class"] == "B"
    types = _types(result)
    assert "abstain" not in types
    assert "dose_block" not in types
    assert "citation" not in types

    full_text = _texts(result)
    assert "trồng cây gì" not in full_text
    assert "trợ lý nông nghiệp" in full_text
    assert result["slots"]["crop"] is None
    assert result["slots"]["pest"] is None


def test_cam_on_em_nhe_la_smalltalk():
    result = pipeline.answer("cảm ơn em nhé", "dak_lak", _ON_DATE)
    assert result["risk_class"] == "B"
    types = _types(result)
    assert "abstain" not in types
    assert "dose_block" not in types
    assert "citation" not in types
    assert result["slots"]["crop"] is None
    assert result["slots"]["pest"] is None


def test_bat_gioi_cau_hoi_nang_luc_va_tam_biet_deu_la_smalltalk():
    """Hỏi năng lực và tạm biệt cũng phải được nhận diện small-talk (không riêng
    chào hỏi/cảm ơn) — vẫn risk B, không citation/abstain/dose_block."""
    for text, region in [
        ("bạn là ai, giúp được gì", "an_giang"),
        ("tạm biệt em nhé", "dak_lak"),
    ]:
        result = pipeline.answer(text, region, _ON_DATE)
        assert result["risk_class"] == "B", text
        types = _types(result)
        assert "abstain" not in types, text
        assert "dose_block" not in types, text
        assert "citation" not in types, text


def test_chao_em_co_slot_van_di_path_a_binh_thuong_khong_bi_chan_smalltalk():
    """'chào em, lúa bị rầy nâu xịt thuốc gì' có lẫn từ chào ('chào') NHƯNG có đủ
    crop+pest slot -> PHẢI đi path A bình thường (risk A, dose_block, registry thật),
    KHÔNG được small-talk nuốt mất câu hỏi thật."""
    result = pipeline.answer("chào em, lúa bị rầy nâu xịt thuốc gì", "an_giang", _ON_DATE)
    assert result["risk_class"] == "A"
    types = _types(result)
    assert types.count("dose_block") >= 1
    assert types.count("citation") >= 1
    assert result["slots"]["crop"] == "lúa"
    assert result["slots"]["pest"] == "rầy nâu"


def test_trong_tao_crop_ngoai_kb_minh_bach_pham_vi_khong_chay_rag(monkeypatch):
    """Bug #2: 'trồng táo' — crop 'táo' hợp lệ trong registry.db nhưng KHÔNG có tài
    liệu KB (kb.db chỉ có lúa/cà phê/sầu riêng). Phải trả lời minh bạch (nêu danh
    sách cây có tài liệu + hướng dẫn tiếp) thay vì abstain-lite mù mờ, và KHÔNG được
    gọi RAG B (guard phải chặn trước cả khi RAG bật) — mock _rag_b_enabled=True và
    kb crops list để verify thứ tự chặn đúng, đồng thời assert retrieve/generate
    không được gọi (không tốn quota nếu RAG thật đang bật)."""
    from app.backend import generate, retrieval

    monkeypatch.setattr(pipeline, "_rag_b_enabled", lambda: True)
    monkeypatch.setattr(pipeline, "_kb_crops", lambda: ("lúa", "cà phê", "sầu riêng"))

    def _khong_duoc_goi(*a, **kw):
        raise AssertionError("không được gọi RAG B khi crop ngoài KB và không có pest slot")

    monkeypatch.setattr(retrieval, "retrieve", _khong_duoc_goi)
    monkeypatch.setattr(generate, "generate_b_answer", _khong_duoc_goi)

    result = pipeline.answer("trồng táo", "an_giang", _ON_DATE)
    assert result["risk_class"] == "B"
    assert result["slots"]["crop"] == "táo"
    assert result["slots"]["pest"] is None

    types = _types(result)
    assert "citation" not in types
    assert "dose_block" not in types
    abstain_segs = [s for s in result["answer_segments"] if s["type"] == "abstain"]
    assert len(abstain_segs) == 1
    assert abstain_segs[0]["handoff"] is True

    full_text = _texts(result)
    assert "lúa" in full_text and "cà phê" in full_text and "sầu riêng" in full_text
    assert "táo" in full_text


def test_tao_bi_rep_sap_co_pest_slot_thi_khong_bi_chan_di_path_a_thuc_te():
    """'táo bị rệp sáp xịt thuốc gì': cả 'táo' (crop) và 'rệp sáp' (pest) đều là
    literal hợp lệ trong registry.db, nên guard minh bạch-phạm-vi KHÔNG được chặn
    (guard chỉ áp dụng khi KHÔNG có pest slot) — phải rơi vào path A bình thường,
    tra registry.db thật. Verify bằng lookup_products() thật ngay trong test để
    assertion luôn khớp thực tế dữ liệu hiện hành (đã kiểm tra thủ công lúc viết
    test: registry.db KHÔNG có sản phẩm đăng ký cho cặp táo/rệp sáp -> path A tự
    abstain theo đúng cơ chế cũ, không phải nhánh minh bạch phạm vi mới)."""
    conn = db_module.connect()
    try:
        hits = db_module.lookup_products(conn, "táo", "rệp sáp", _ON_DATE)
    finally:
        conn.close()

    result = pipeline.answer("táo bị rệp sáp xịt thuốc gì", "an_giang", _ON_DATE)
    assert result["risk_class"] == "A"
    assert result["slots"]["crop"] == "táo"
    assert result["slots"]["pest"] == "rệp sáp"

    types = _types(result)
    if hits:
        assert "dose_block" in types
    else:
        assert "dose_block" not in types
        abstain_segs = [s for s in result["answer_segments"] if s["type"] == "abstain"]
        assert len(abstain_segs) == 1
        assert abstain_segs[0]["handoff"] is True
        # Đây là abstain path A "không có sản phẩm đăng ký" (cơ chế cũ), KHÔNG phải
        # abstain của nhánh minh bạch phạm vi KB mới (reason khác nhau).
        assert "registry" in abstain_segs[0]["reason"]

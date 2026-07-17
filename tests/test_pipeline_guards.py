"""Guard "1 crop thắng thế khi câu hỏi không nêu cây" (bug thật user báo: hỏi gì
cũng trả lời sầu riêng — tài liệu dày nhất KB thắng mọi truy vấn không filter).
Toàn bộ test mock retrieval/generate — không mạng, không tốn quota Gemini."""

from app.backend import pipeline


def _chunk(crop, doc="qd1899-saurieng", text="nội dung"):
    return {
        "doc_id": doc,
        "section": "mục",
        "text": text,
        "crop": crop,
        "region_scope": "national",
        "url": "https://x",
    }


def test_dominant_crop_qua_ban_khi_da_so_chunk_cung_1_cay():
    chunks = [_chunk("sầu riêng")] * 4 + [_chunk("lúa")]
    assert pipeline._dominant_crop_without_slot(chunks) is True


def test_dominant_crop_khong_ban_khi_chunk_da_dang_cay():
    chunks = [_chunk("sầu riêng"), _chunk("sầu riêng"), _chunk("lúa"), _chunk("lúa"), _chunk("cà phê")]
    assert pipeline._dominant_crop_without_slot(chunks) is False


def test_dominant_crop_khong_ban_khi_chunk_khong_gan_crop():
    # Tài liệu national/đa cây (crop=None) không tính là bằng chứng cho crop nào
    chunks = [_chunk(None), _chunk(None), _chunk(None)]
    assert pipeline._dominant_crop_without_slot(chunks) is False
    assert pipeline._dominant_crop_without_slot([]) is False


def test_cau_khong_crop_bi_1_cay_nuot_thi_hoi_lai_khong_goi_gemini(monkeypatch):
    """End-to-end nhánh B (mock): câu chung chung -> retrieve toàn chunk sầu riêng ->
    PHẢI trả clarify hỏi cây trồng, KHÔNG gọi generate (không tốn quota), KHÔNG
    citation sầu riêng, KHÔNG abstain-handoff."""
    from app.backend import generate, retrieval

    monkeypatch.setattr(pipeline, "_rag_b_enabled", lambda: True)
    monkeypatch.setattr(retrieval, "retrieve", lambda *a, **kw: [_chunk("sầu riêng")] * 5)

    def _khong_duoc_goi(*a, **kw):
        raise AssertionError("không được gọi Gemini khi guard dominant-crop đã chặn")

    monkeypatch.setattr(generate, "generate_b_answer", _khong_duoc_goi)

    result = pipeline.answer("cách chăm sóc vườn cây", "an_giang", "2026-07-18")
    types = [s["type"] for s in result["answer_segments"]]
    assert "abstain" not in types and "citation" not in types and "dose_block" not in types
    full_text = " ".join(s.get("content", "") for s in result["answer_segments"])
    assert "trồng cây gì" in full_text
    assert "sầu riêng" not in full_text.replace("(lúa, cà phê, sầu riêng...)", "")


def test_cau_khong_crop_nhung_kb_da_dang_van_di_generate(monkeypatch):
    """Chunk đa dạng cây (không cây nào >50%) -> vẫn đi generate bình thường."""
    from app.backend import generate, retrieval

    monkeypatch.setattr(pipeline, "_rag_b_enabled", lambda: True)
    monkeypatch.setattr(
        retrieval,
        "retrieve",
        lambda *a, **kw: [_chunk("lúa"), _chunk("cà phê"), _chunk(None), _chunk("sầu riêng"), _chunk(None)],
    )
    monkeypatch.setattr(
        generate,
        "generate_b_answer",
        lambda *a, **kw: {"text": "Trả lời tổng hợp có căn cứ.", "citations": [
            {"doc_id": "d", "section": "s", "url": "https://x", "quote": "q"}
        ], "grounded": True},
    )

    result = pipeline.answer("mùa mưa cần lưu ý gì khi chăm vườn", "dak_lak", "2026-07-18")
    types = [s["type"] for s in result["answer_segments"]]
    assert "citation" in types
    assert "abstain" not in types

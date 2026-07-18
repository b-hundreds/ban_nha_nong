"""TDD cho generation grounded đường B (app/backend/generate.py) — spec §6.5.

Toàn bộ test mock `client.models.generate_content` (KHÔNG gọi Gemini thật, không
network) bằng 1 fake client trả sẵn chuỗi JSON theo schema {text, citations,
grounded}. Evidence là list[dict] tối giản đúng shape mà app/backend/retrieval.py
trả về (id, doc_id, section, text, url, ...).
"""
import json

import pytest

from app.backend import generate

CHUNKS = [
    {
        "id": 1,
        "doc_id": "lich-thoi-vu-an-giang-dx-2026",
        "section": "Đợt 1",
        "text": "Xuống giống từ 01-30/11/2026, phù hợp dự báo nguồn nước và thời tiết.",
        "crop": "lúa",
        "region_scope": "an giang",
        "url": "https://x/dot1",
    },
    {
        "id": 2,
        "doc_id": "lich-thoi-vu-an-giang-dx-2026",
        "section": "Giống lúa khuyến cáo",
        "text": "Vùng hạn cuối vụ: giống ngắn ngày, có khả năng chịu mặn.",
        "crop": "lúa",
        "region_scope": "an giang",
        "url": "https://x/giong",
    },
]


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeModels:
    """Fake `client.models` trả sẵn 1 danh sách response theo thứ tự gọi
    (dùng cho test regenerate-once: lần 1 dính số liều, lần 2 sạch)."""

    def __init__(self, texts: list[str]):
        self._texts = list(texts)
        self.calls: list[str] = []

    def generate_content(self, *, model, contents, config):
        self.calls.append(contents)
        text = self._texts.pop(0) if len(self._texts) > 1 else self._texts[0]
        return _FakeResponse(text)


class _FakeClient:
    def __init__(self, texts: list[str]):
        self.models = _FakeModels(texts)


def _payload(text, citations, grounded=True):
    return json.dumps({"text": text, "citations": citations, "grounded": grounded}, ensure_ascii=False)


def test_generate_b_answer_khong_co_chunk_thi_abstain_ngay_khong_goi_gemini():
    calls = []

    class _ShouldNotBeCalled:
        def __init__(self):
            self.models = self

        def generate_content(self, *a, **kw):
            calls.append(1)
            raise AssertionError("không được gọi Gemini khi chunks rỗng")

    result = generate.generate_b_answer("câu hỏi bất kỳ", [], region="an_giang", client=_ShouldNotBeCalled())
    assert result == {"text": "", "citations": [], "grounded": False}
    assert not calls


def test_generate_b_answer_schema_va_citation_hop_le():
    quote = "Xuống giống từ 01-30/11/2026, phù hợp dự báo nguồn nước và thời tiết."
    payload = _payload(
        text="Bác nên xuống giống theo đúng khung lịch được khuyến cáo cho đợt này.",
        citations=[
            {
                "doc_id": "lich-thoi-vu-an-giang-dx-2026",
                "section": "Đợt 1",
                "url": "https://x/dot1",
                "quote": quote,
            }
        ],
        grounded=True,
    )
    client = _FakeClient([payload])
    result = generate.generate_b_answer("tháng 11 tôi cần làm gì cho ruộng lúa", CHUNKS, region="an_giang", client=client)

    assert result["grounded"] is True
    assert len(result["citations"]) == 1
    cit = result["citations"][0]
    assert cit["doc_id"] == "lich-thoi-vu-an-giang-dx-2026"
    assert cit["section"] == "Đợt 1"
    assert cit["quote"] == quote
    assert "xuống giống" in result["text"].lower()


def test_generate_b_answer_quote_sai_bi_loai_0_citation_hop_le_thi_grounded_false():
    """Quote không khớp NGUYÊN VĂN bất kỳ chunk nào (bịa/diễn giải lại) -> bị loại;
    còn 0 citation hợp lệ -> grounded=False dù model tự xưng grounded=true."""
    payload = _payload(
        text="Bác nên xuống giống sớm để né hạn mặn.",
        citations=[
            {
                "doc_id": "lich-thoi-vu-an-giang-dx-2026",
                "section": "Đợt 1",
                "url": "https://x/dot1",
                "quote": "Câu này KHÔNG hề có trong evidence, do model bịa ra.",
            }
        ],
        grounded=True,
    )
    client = _FakeClient([payload])
    result = generate.generate_b_answer("tháng 11 tôi cần làm gì", CHUNKS, region="an_giang", client=client)

    assert result["citations"] == []
    assert result["grounded"] is False


def test_generate_b_answer_citation_sai_chunk_nguon_bi_loai():
    """Quote CÓ thật trong 1 chunk khác nhưng citation lại trỏ sai doc_id/section
    -> vẫn phải loại (yêu cầu: quote phải khớp ĐÚNG chunk được cite, không phải bất
    kỳ chunk nào trong evidence)."""
    payload = _payload(
        text="Nên chọn giống ngắn ngày chịu mặn cho vùng hạn cuối vụ.",
        citations=[
            {
                "doc_id": "lich-thoi-vu-an-giang-dx-2026",
                "section": "Đợt 1",  # sai — câu quote thực ra thuộc section "Giống lúa khuyến cáo"
                "url": "https://x/dot1",
                "quote": "Vùng hạn cuối vụ: giống ngắn ngày, có khả năng chịu mặn.",
            }
        ],
        grounded=True,
    )
    client = _FakeClient([payload])
    result = generate.generate_b_answer("nên chọn giống nào", CHUNKS, region="an_giang", client=client)
    assert result["citations"] == []
    assert result["grounded"] is False


def test_regression_rag_fake_url_phai_fail_closed():
    """Một quote có thật không làm URL do model tự khai trở thành đáng tin.

    URL citation phải khớp URL của đúng chunk; URL ngoài evidence là payload giả
    mạo và toàn bộ câu trả lời phải fail-closed.
    """
    quote = "Xuống giống từ 01-30/11/2026, phù hợp dự báo nguồn nước và thời tiết."
    payload = _payload(
        text="Bác nên xuống giống theo đúng khung lịch được khuyến cáo cho đợt này.",
        citations=[
            {
                "doc_id": "lich-thoi-vu-an-giang-dx-2026",
                "section": "Đợt 1",
                "url": "https://attacker.example/fake",
                "quote": quote,
            }
        ],
        grounded=True,
    )

    result = generate.generate_b_answer(
        "tháng 11 tôi cần làm gì cho ruộng lúa",
        CHUNKS,
        region="an_giang",
        client=_FakeClient([payload]),
    )

    assert result["grounded"] is False
    assert result["citations"] == []


def test_regression_rag_fake_section_cung_doc_id_phai_fail_closed():
    """Không được fallback từ section bịa sang một chunk khác cùng doc_id."""
    quote = "Xuống giống từ 01-30/11/2026, phù hợp dự báo nguồn nước và thời tiết."
    payload = _payload(
        text="Bác nên xuống giống theo đúng khung lịch được khuyến cáo cho đợt này.",
        citations=[
            {
                "doc_id": "lich-thoi-vu-an-giang-dx-2026",
                "section": "Mục không tồn tại",
                "url": "https://x/dot1",
                "quote": quote,
            }
        ],
        grounded=True,
    )

    result = generate.generate_b_answer(
        "tháng 11 tôi cần làm gì cho ruộng lúa",
        CHUNKS,
        region="an_giang",
        client=_FakeClient([payload]),
    )

    assert result["grounded"] is False
    assert result["citations"] == []


def test_regression_rag_number_from_uncited_chunk_phai_fail_closed():
    """Số có trong top-k nhưng không có trong chunk được cite vẫn là unsupported."""
    chunks = [
        {
            "id": 10,
            "doc_id": "doc-lua",
            "section": "Tưới nước",
            "text": "Giữ mực nước ruộng từ 3-5 cm trong giai đoạn đẻ nhánh.",
            "crop": "lúa",
            "region_scope": "national",
            "url": "https://gov.example/lua",
        },
        {
            "id": 11,
            "doc_id": "doc-lua",
            "section": "Bón phân",
            "text": "Bón 40 kg/ha kali theo kết quả phân tích đất.",
            "crop": "lúa",
            "region_scope": "national",
            "url": "https://gov.example/lua",
        },
    ]
    payload = _payload(
        text="Bác bón 40 kg/ha kali.",
        citations=[
            {
                "doc_id": "doc-lua",
                "section": "Tưới nước",
                "url": "https://gov.example/lua",
                "quote": chunks[0]["text"],
            }
        ],
        grounded=True,
    )

    result = generate.generate_b_answer(
        "Bón kali cho lúa thế nào?",
        chunks,
        region="an_giang",
        user_crop="lúa",
        client=_FakeClient([payload]),
    )

    assert result["grounded"] is False


def test_regression_rag_qualitative_claim_irrelevant_quote_phai_fail_closed():
    """Quote hợp lệ về tưới nước không chứng minh một khuyến nghị phun thuốc."""
    chunks = [
        {
            "id": 12,
            "doc_id": "doc-lua",
            "section": "Tưới nước",
            "text": "Giữ mực nước ruộng từ 3-5 cm trong giai đoạn đẻ nhánh.",
            "crop": "lúa",
            "region_scope": "national",
            "url": "https://gov.example/lua",
        }
    ]
    payload = _payload(
        text="Phun thuốc vào ban đêm chắc chắn chữa khỏi bệnh.",
        citations=[
            {
                "doc_id": "doc-lua",
                "section": "Tưới nước",
                "url": "https://gov.example/lua",
                "quote": chunks[0]["text"],
            }
        ],
        grounded=True,
    )

    result = generate.generate_b_answer(
        "Nên phun thuốc lúc nào?",
        chunks,
        region="an_giang",
        user_crop="lúa",
        client=_FakeClient([payload]),
    )

    assert result["grounded"] is False


def test_generate_b_answer_model_tu_nhan_khong_du_can_cu():
    payload = _payload(text="Em chưa đủ căn cứ để trả lời câu này.", citations=[], grounded=False)
    client = _FakeClient([payload])
    result = generate.generate_b_answer("câu hỏi ngoài phạm vi evidence", CHUNKS, region="an_giang", client=client)
    assert result["grounded"] is False
    assert result["citations"] == []


# Evidence CÓ số liệu thật (bảng N-P-K) — dùng để kiểm tra chính sách P1-E "số theo
# evidence": số CÓ trong evidence phải được GIỮ NGUYÊN, không bị chặn/regenerate như
# hậu kiểm blanket-block cũ của P1-C (đây chính là nguyên nhân false-refusal đã sửa).
CHUNKS_NPK = [
    {
        "id": 3,
        "doc_id": "qd145-sotay-lua",
        "section": "5. Bón phân",
        "text": "Lượng phân bón cho vụ Đông Xuân trên đất phù sa: 90-100 kg/ha đạm, 30-40 kg/ha lân, 30-40 kg/ha kali.",
        "crop": "lúa",
        "region_scope": "đbscl",
        "url": "https://x/bonphan",
    },
]


def test_generate_b_answer_so_co_trong_evidence_thi_giu_nguyen_khong_regenerate():
    """Số liệu (kg/ha) CÓ trong evidence -> validators.check_numbers pass ngay lần 1,
    KHÔNG regenerate — đúng chính sách P1-E, khác với hậu kiểm blanket-block cũ (P1-C)
    vốn sẽ chặn bất kỳ số+đơn vị nào dù evidence có thật."""
    quote = "Lượng phân bón cho vụ Đông Xuân trên đất phù sa: 90-100 kg/ha đạm, 30-40 kg/ha lân, 30-40 kg/ha kali."
    payload = _payload(
        text="Vụ Đông Xuân trên đất phù sa, bác bón khoảng 90-100 kg/ha đạm, 30-40 kg/ha lân, 30-40 kg/ha kali nhé.",
        citations=[
            {"doc_id": "qd145-sotay-lua", "section": "5. Bón phân", "url": "https://x/bonphan", "quote": quote}
        ],
        grounded=True,
    )
    client = _FakeClient([payload])
    result = generate.generate_b_answer(
        "Bón phân cho lúa vụ đông xuân cần tỷ lệ đạm kali thế nào?", CHUNKS_NPK, region="an_giang", client=client
    )

    assert len(client.models.calls) == 1, "số khớp evidence -> không cần regenerate"
    assert result["grounded"] is True
    assert "90-100 kg/ha" in result["text"]


def test_generate_b_answer_so_khong_co_trong_evidence_regenerate_lan_1_sach_thi_dung_ket_qua_lan_2():
    """Lần 1 model bịa số KHÔNG có trong evidence -> validators.check_numbers phát
    hiện vi phạm -> regenerate 1 lần; lần 2 dùng đúng số có trong evidence -> dùng kết
    quả lần 2, grounded theo lần 2 (True ở đây)."""
    quote = "Lượng phân bón cho vụ Đông Xuân trên đất phù sa: 90-100 kg/ha đạm, 30-40 kg/ha lân, 30-40 kg/ha kali."
    citations = [
        {"doc_id": "qd145-sotay-lua", "section": "5. Bón phân", "url": "https://x/bonphan", "quote": quote}
    ]
    payload_1 = _payload(text="Bác bón khoảng 500 kg/ha đạm là đủ.", citations=citations, grounded=True)
    payload_2 = _payload(
        text="Bác bón khoảng 90-100 kg/ha đạm theo đúng khuyến cáo cho đất phù sa.",
        citations=citations,
        grounded=True,
    )
    client = _FakeClient([payload_1, payload_2])
    result = generate.generate_b_answer(
        "Bón phân cho lúa vụ đông xuân cần tỷ lệ đạm kali thế nào?", CHUNKS_NPK, region="an_giang", client=client
    )

    assert len(client.models.calls) == 2, "phải gọi Gemini đúng 2 lần (1 lần gốc + 1 lần regenerate)"
    assert result["grounded"] is True
    assert "500 kg/ha" not in result["text"]
    assert "90-100 kg/ha" in result["text"]


def test_generate_b_answer_regenerate_van_bia_so_thi_grounded_false():
    """Cả 2 lần đều bịa số KHÔNG có trong evidence -> grounded=False sau đúng 2 lần
    gọi (không gọi thêm lần thứ 3)."""
    quote = "Lượng phân bón cho vụ Đông Xuân trên đất phù sa: 90-100 kg/ha đạm, 30-40 kg/ha lân, 30-40 kg/ha kali."
    citations = [
        {"doc_id": "qd145-sotay-lua", "section": "5. Bón phân", "url": "https://x/bonphan", "quote": quote}
    ]
    payload_1 = _payload(text="Bác bón khoảng 500 kg/ha đạm là đủ.", citations=citations, grounded=True)
    payload_2 = _payload(text="Bác bón khoảng 300 kg/ha đạm là đủ.", citations=citations, grounded=True)
    client = _FakeClient([payload_1, payload_2])

    result = generate.generate_b_answer(
        "Bón phân cho lúa vụ đông xuân cần tỷ lệ đạm kali thế nào?", CHUNKS_NPK, region="an_giang", client=client
    )

    assert len(client.models.calls) == 2
    assert result["grounded"] is False


def test_generate_b_answer_nhan_user_crop_va_dua_vao_prompt():
    """Regression cho bug thật (P1-E addendum sửa dở): pipeline gọi
    generate_b_answer(..., user_crop=crop) nhưng chữ ký không nhận -> TypeError ->
    MỌI câu B có crop slot rơi vào abstain oan. Test cả 2 chiều: param được nhận
    VÀ thật sự đi vào prompt (không phải nhận rồi vứt)."""
    payload = _payload(text="Bác chăm vườn theo quy trình nhé.", citations=[], grounded=False)

    client = _FakeClient([payload])
    generate.generate_b_answer("chăm sóc giai đoạn nuôi trái", CHUNKS, region="dak_lak", user_crop="sầu riêng", client=client)
    assert 'Cây trồng của người hỏi: "sầu riêng"' in client.models.calls[0]

    client2 = _FakeClient([payload])
    generate.generate_b_answer("chăm sóc vườn cây", CHUNKS, region="dak_lak", user_crop=None, client=client2)
    assert "KHÔNG rõ" in client2.models.calls[0]

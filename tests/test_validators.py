"""Test cho app/backend/validators.py (P1-A) — TDD, ca tiếng Việt thật."""
from app.backend.validators import (
    NumberMention,
    check_claim_support,
    check_numbers,
    check_quote,
    extract_numbers,
    validate_answer,
)


# --------------------------------------------------------------------------
# check_quote
# --------------------------------------------------------------------------

def test_check_quote_exact_match():
    evidence = ["Liều dùng: pha 0,5 lít/ha với 400 lít nước, cách ly 7 ngày trước thu hoạch."]
    quote = "pha 0,5 lít/ha với 400 lít nước, cách ly 7 ngày trước thu hoạch."
    res = check_quote(quote, evidence)
    assert res.ok is True
    assert res.method == "exact"
    assert res.matched_evidence_idx == 0


def test_check_quote_exact_match_ignores_whitespace_and_unicode_form():
    # NFD (tổ hợp) vs NFC (dựng sẵn) của "hòa" — phải normalize NFC trước so khớp.
    import unicodedata

    evidence_nfc = unicodedata.normalize("NFC", "Pha thuốc thật đều tay trước khi phun.")
    evidence_nfd = unicodedata.normalize("NFD", evidence_nfc)
    quote = "Pha   thuốc  thật đều tay\ntrước khi phun."  # whitespace lệch
    res = check_quote(quote, [evidence_nfd])
    assert res.ok is True
    assert res.method == "exact"


def test_check_quote_fuzzy_match_with_punctuation_drift():
    evidence = ["Đối với rầy nâu trên lúa: pha 20 gam thuốc cho bình 16 lít, phun ướt đều 2 mặt lá."]
    # Answer trích gần đúng nhưng lệch dấu câu / thiếu dấu phẩy.
    quote = "pha 20 gam thuốc cho bình 16 lít phun ướt đều 2 mặt lá"
    res = check_quote(quote, evidence)
    assert res.ok is True
    assert res.method == "fuzzy"
    assert res.score >= 90


def test_check_quote_fail_unrelated_text():
    evidence = ["Đối với rầy nâu trên lúa: pha 20 gam thuốc cho bình 16 lít nước."]
    quote = "Sầu riêng bị xì mủ Phytophthora cần xử lý gốc bằng Aliette 800WG."
    res = check_quote(quote, evidence)
    assert res.ok is False
    assert res.method == "fuzzy"
    assert res.score < 90


def test_check_quote_empty_evidence_list():
    res = check_quote("bất kỳ câu nào", [])
    assert res.ok is False


# --------------------------------------------------------------------------
# check_claim_support
# --------------------------------------------------------------------------

def test_check_claim_support_accepts_conservative_paraphrase():
    result = check_claim_support(
        "Bác nên xuống giống theo đúng khung lịch được khuyến cáo cho đợt này.",
        ["Xuống giống từ đầu tháng, phù hợp dự báo nguồn nước và thời tiết."],
    )
    assert result.ok is True
    assert result.failures == []


def test_check_claim_support_rejects_irrelevant_quote():
    result = check_claim_support(
        "Phun thuốc vào ban đêm chắc chắn chữa khỏi bệnh.",
        ["Giữ mực nước ruộng trong giai đoạn đẻ nhánh."],
    )
    assert result.ok is False
    assert result.failures[0].reason in {"insufficient_overlap", "unsupported_action"}


def test_check_claim_support_checks_every_sentence_independently():
    result = check_claim_support(
        "Giữ mực nước ruộng trong giai đoạn đẻ nhánh. Phun thuốc vào ban đêm.",
        ["Giữ mực nước ruộng trong giai đoạn đẻ nhánh."],
    )
    assert result.ok is False
    assert [failure.claim for failure in result.failures] == ["Phun thuốc vào ban đêm."]


def test_check_claim_support_rejects_stronger_conclusion_added_to_real_quote():
    result = check_claim_support(
        "Giữ mực nước ruộng trong giai đoạn đẻ nhánh chắc chắn chữa khỏi bệnh.",
        ["Giữ mực nước ruộng trong giai đoạn đẻ nhánh."],
    )
    assert result.ok is False
    assert result.failures[0].reason == "unsupported_strength"


def test_check_claim_support_does_not_union_unrelated_quotes():
    result = check_claim_support(
        "Bón kali giúp đất phù sa màu mỡ.",
        ["Bón kali theo phân tích.", "Đất phù sa phù hợp canh tác."],
    )
    assert result.ok is False


def test_check_claim_support_rejects_negation_not_present_in_quote():
    result = check_claim_support(
        "Không phun thuốc vào buổi sáng.",
        ["Phun thuốc vào buổi sáng."],
    )
    assert result.ok is False
    assert result.failures[0].reason == "unsupported_negation"


# --------------------------------------------------------------------------
# extract_numbers
# --------------------------------------------------------------------------

def test_extract_numbers_dose_and_water_and_phi():
    text = "pha 0,5 lít/ha với 400 lít nước, cách ly 7 ngày"
    mentions = extract_numbers(text)
    got = [(m.value_min, m.value_max, m.unit) for m in mentions]
    assert (0.5, 0.5, "lít/ha") in got
    assert (400.0, 400.0, "lít") in got
    assert (7.0, 7.0, "ngày") in got
    assert len(mentions) == 3


def test_extract_numbers_range_hyphen():
    mentions = extract_numbers("bón 20-25 ml cho mỗi gốc")
    assert len(mentions) == 1
    m = mentions[0]
    assert m.value_min == 20.0
    assert m.value_max == 25.0
    assert m.unit == "ml"


def test_extract_numbers_range_en_dash():
    mentions = extract_numbers("bón 20–25 ml cho mỗi gốc")
    assert len(mentions) == 1
    m = mentions[0]
    assert m.value_min == 20.0
    assert m.value_max == 25.0
    assert m.unit == "ml"


def test_extract_numbers_thousand_separator():
    mentions = extract_numbers("giá gói 1.200 đồng")
    assert len(mentions) == 1
    assert mentions[0].value_min == 1200.0
    assert mentions[0].unit is None


def test_extract_numbers_no_unit_still_extracted():
    mentions = extract_numbers("năm 2026 có quy định mới")
    assert len(mentions) == 1
    assert mentions[0].value_min == 2026.0
    assert mentions[0].unit is None


def test_extract_numbers_formulation_code_not_a_dose():
    # "Reasgant 1.8EC" — 1.8 là mã quy cách của sản phẩm, KHÔNG phải liều.
    mentions = extract_numbers("Sản phẩm Reasgant 1.8EC được đăng ký cho lúa.")
    assert mentions == []


def test_extract_numbers_formulation_code_mixed_with_real_dose():
    text = "Dùng Actara 25WG, pha 1 gói cho bình 16 lít"
    mentions = extract_numbers(text)
    got = [(m.value_min, m.value_max, m.unit) for m in mentions]
    # "25" của mã quy cách 25WG không được tính.
    assert not any(v == 25.0 for v, _, _ in got)
    assert (1.0, 1.0, "gói") in got
    assert (16.0, 16.0, "lít") in got


# --------------------------------------------------------------------------
# check_numbers
# --------------------------------------------------------------------------

def test_check_numbers_all_match_evidence():
    evidence = ["Liều khuyến cáo: pha 0,5 lít/ha với 400 lít nước, cách ly 7 ngày."]
    res = check_numbers("pha 0,5 lít/ha với 400 lít nước, cách ly 7 ngày", evidence)
    assert res.ok is True
    assert res.violations == []


def test_check_numbers_double_dose_is_violation():
    evidence = ["Liều khuyến cáo trên nhãn: 0,5 lít cho mỗi ha."]
    res = check_numbers("bác cứ pha liều gấp đôi 1,0 lít cho chắc ăn", evidence)
    assert res.ok is False
    assert len(res.violations) == 1
    assert res.violations[0].value_min == 1.0
    assert res.violations[0].unit == "lít"


def test_check_numbers_format_variants_are_equivalent():
    # "0,5 lít" (answer, kiểu Việt) phải khớp "0.5 lít" và "0,50 lít" (evidence).
    res_dot = check_numbers("pha 0,5 lít cho mỗi bình", ["Nhãn ghi rõ 0.5 lít mỗi bình."])
    assert res_dot.ok is True

    res_trailing_zero = check_numbers("pha 0,5 lít cho mỗi bình", ["Nhãn ghi rõ 0,50 lít mỗi bình."])
    assert res_trailing_zero.ok is True


def test_check_numbers_same_value_different_unit_is_violation():
    # Trùng giá trị số nhưng khác đơn vị (0,5 lít vs 0,5 kg) không được coi là khớp.
    res = check_numbers("dùng 0,5 lít sản phẩm", ["Liều khuyến cáo là 0,5 kg."])
    assert res.ok is False


def test_check_numbers_small_unitless_int_present_in_evidence_passes():
    # "nguyên tắc 4 đúng" — evidence CÓ nhắc "4" → không bị coi là vi phạm.
    # (test cùng cặp câu với ca dưới để chốt rõ: KHÔNG có miễn trừ theo độ
    # lớn số — kết quả phụ thuộc việc evidence có nhắc số đó hay không.)
    evidence = ["Nguyên tắc 4 đúng: đúng thuốc, đúng liều, đúng lúc, đúng cách."]
    res = check_numbers("Bác nhớ theo nguyên tắc 4 đúng khi phun thuốc nhé.", evidence)
    assert res.ok is True


def test_check_numbers_small_unitless_int_absent_from_evidence_is_violation():
    # Cùng câu "4 đúng" nhưng evidence KHÔNG hề nhắc số "4" ở đâu cả →
    # phải bị tính là violation. Khẳng định KHÔNG có ngoại lệ miễn trừ cho
    # số nguyên nhỏ (an toàn: nghi ngờ thì tính là violation).
    evidence = ["Sản phẩm ABC được phép sử dụng cho lúa theo Thông tư 75/2025."]
    res = check_numbers("Bác nhớ theo nguyên tắc 4 đúng khi phun thuốc nhé.", evidence)
    assert res.ok is False
    assert any(v.value_min == 4.0 for v in res.violations)


def test_check_numbers_no_numbers_in_answer_is_ok():
    res = check_numbers("Bác nên phun vào buổi sáng sớm hoặc chiều mát.", [])
    assert res.ok is True


# --------------------------------------------------------------------------
# validate_answer — end-to-end
# --------------------------------------------------------------------------

def test_validate_answer_pass_case():
    evidence = [
        "Reasgant 1.8EC: pha 20 ml cho bình 16 lít, phun ướt đều, cách ly 7 ngày trước thu hoạch.",
    ]
    segments = [
        {"type": "text", "content": "Dạ, với rầy nâu trên lúa, em gợi ý sản phẩm sau:"},
        {
            "type": "dose_block",
            "product": "Reasgant 1.8EC",
            "ai": "Nitenpyram",
            "dose_text": "pha 20 ml cho bình 16 lít",
            "phi_days": 7,
            "note": "Cách ly 7 ngày trước khi thu hoạch, phun ướt đều 2 mặt lá.",
        },
        {
            "type": "citation",
            "source": "Nhãn sản phẩm Reasgant 1.8EC",
            "url": "https://example.gov.vn/reasgant",
            "quote": "pha 20 ml cho bình 16 lít, phun ướt đều, cách ly 7 ngày trước thu hoạch.",
        },
    ]
    verdict = validate_answer(segments, evidence)
    assert verdict.ok is True
    assert verdict.failures == []
    assert verdict.action == "pass"


def test_validate_answer_fail_case_number_violation():
    evidence = [
        "Reasgant 1.8EC: pha 20 ml cho bình 16 lít, cách ly 7 ngày trước thu hoạch.",
    ]
    segments = [
        {"type": "text", "content": "Dạ, với rầy nâu trên lúa, em gợi ý sản phẩm sau:"},
        {
            "type": "dose_block",
            "product": "Reasgant 1.8EC",
            "ai": "Nitenpyram",
            "dose_text": "pha 20 ml cho bình 16 lít",
            "phi_days": 7,
            # "note" bịa thêm liều gấp đôi không có trong evidence/DB — phải bị bắt.
            "note": "Nếu sâu nhiều quá bác có thể pha 40 ml cho chắc ăn.",
        },
    ]
    verdict = validate_answer(segments, evidence)
    assert verdict.ok is False
    assert verdict.action == "regenerate"
    assert len(verdict.failures) == 1
    assert verdict.failures[0].kind == "number"
    assert verdict.failures[0].segment_index == 1


def test_validate_answer_fail_case_quote_violation_forces_abstain():
    evidence = ["Reasgant 1.8EC: pha 20 ml cho bình 16 lít nước."]
    segments = [
        {
            "type": "citation",
            "source": "Nhãn sản phẩm khác",
            "url": "https://example.gov.vn/khac",
            "quote": "Sầu riêng bị xì mủ Phytophthora cần xử lý gốc bằng Aliette 800WG.",
        },
    ]
    verdict = validate_answer(segments, evidence)
    assert verdict.ok is False
    assert verdict.action == "abstain"
    assert verdict.failures[0].kind == "quote"


def test_validate_answer_quote_failure_takes_priority_over_number_failure():
    evidence = ["Reasgant 1.8EC: pha 20 ml cho bình 16 lít nước."]
    segments = [
        {"type": "text", "content": "Bác pha 999 lít cho chắc ăn."},
        {
            "type": "citation",
            "source": "Nhãn khác",
            "url": "https://example.gov.vn/khac",
            "quote": "Nội dung hoàn toàn không liên quan tới evidence ở trên chút nào.",
        },
    ]
    verdict = validate_answer(segments, evidence)
    assert verdict.ok is False
    assert verdict.action == "abstain"
    kinds = {f.kind for f in verdict.failures}
    assert "quote" in kinds and "number" in kinds


def test_validate_answer_citation_without_quote_field_is_skipped():
    segments = [
        {"type": "citation", "source": "Nguồn tổng quát", "url": "https://example.gov.vn"},
    ]
    verdict = validate_answer(segments, evidence=["gì cũng được"])
    assert verdict.ok is True
    assert verdict.action == "pass"


def test_number_mention_dataclass_fields():
    m = NumberMention(raw="0,5 lít", value_min=0.5, value_max=0.5, unit="lít", span=(0, 7))
    assert m.raw == "0,5 lít"
    assert m.value_min == 0.5
    assert m.value_max == 0.5
    assert m.unit == "lít"
    assert m.span == (0, 7)

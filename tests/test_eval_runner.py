"""TDD cho eval v0 (P1-B, spec §7) — xem eval/run_eval.py và eval/questions_v0.jsonl.

Hai nhóm test:
1. Bộ câu jsonl hợp lệ: 50 câu, đủ field, id unique, phân bố đúng theo brief.
2. Runner chấm đúng cấu trúc trên vài case tổng hợp (mock answer_fn — KHÔNG gọi
   registry.db/pipeline thật, tách biệt khỏi baseline chạy thật của run_eval.py).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from eval.run_eval import (
    REQUIRED_FIELDS,
    check_dose_numbers,
    check_must_not_contain,
    grade,
    load_questions,
    run,
    summarize,
)

QUESTIONS_PATH = Path(__file__).resolve().parent.parent / "eval" / "questions_v0.jsonl"


# --------------------------------------------------------------------------
# 1) Bộ câu jsonl
# --------------------------------------------------------------------------


def test_questions_file_has_50_valid_rows():
    rows = load_questions(QUESTIONS_PATH)
    assert len(rows) == 50
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert field in row, f"{row.get('id')} thiếu field {field}"
        assert row["expected_behavior"] in {"answer", "refuse_or_correct", "clarify", "general"}
        assert row["risk"] in {"high", "low"}
        assert isinstance(row["must_not_contain"], list)
        assert row["region"] in {"an_giang", "dak_lak"}
        assert row["on_date"] == "2026-07-17"
        assert isinstance(row["gold_note"], str) and row["gold_note"].strip()
        assert isinstance(row["question"], str) and row["question"].strip()


def test_questions_ids_unique():
    rows = load_questions(QUESTIONS_PATH)
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))


def test_questions_distribution_matches_brief():
    rows = load_questions(QUESTIONS_PATH)
    behavior_counts = Counter(r["expected_behavior"] for r in rows)
    assert behavior_counts["answer"] == 15
    assert behavior_counts["refuse_or_correct"] == 20
    assert behavior_counts["clarify"] == 5
    assert behavior_counts["general"] == 10

    trap_total = sum(1 for r in rows if r["category"].startswith("trap_"))
    assert trap_total == 20

    control_total = sum(1 for r in rows if r["category"] == "control_general_farming")
    assert control_total == 10


def test_expected_fail_v0_has_reason_when_true():
    rows = load_questions(QUESTIONS_PATH)
    for row in rows:
        if row["expected_fail_v0"]:
            assert row.get("expected_fail_reason"), f"{row['id']}: expected_fail_v0=true nhưng thiếu lý do"


def test_load_questions_rejects_duplicate_id(tmp_path):
    bad = tmp_path / "bad.jsonl"
    base = {
        "id": "dup", "category": "c", "question": "q", "region": "an_giang",
        "on_date": "2026-07-17", "expected_behavior": "general", "must_not_contain": [],
        "gold_note": "g", "risk": "low", "expected_fail_v0": False,
    }
    bad.write_text(json.dumps(base) + "\n" + json.dumps(base) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="trùng"):
        load_questions(bad)


def test_load_questions_rejects_missing_field(tmp_path):
    bad = tmp_path / "bad.jsonl"
    row = {"id": "x", "category": "c", "question": "q"}  # thiếu nhiều field bắt buộc
    bad.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="thiếu field"):
        load_questions(bad)


# --------------------------------------------------------------------------
# 2) Runner chấm cấu trúc — mock answer_fn, không đụng registry.db
# --------------------------------------------------------------------------


def _seg_text(content):
    return {"type": "text", "content": content}


def _seg_dose(product="Sản phẩm demo", ai="Hoạt chất demo (min 90%)", dose_text="Dùng theo liều trên nhãn",
              phi_days=None, note="Dùng theo liều trên nhãn"):
    return {"type": "dose_block", "product": product, "ai": ai, "dose_text": dose_text,
            "phi_days": phi_days, "note": note}


def _seg_citation(source="Phụ lục Thông tư 75/2025/TT-BNNMT", url="https://example.gov.vn"):
    return {"type": "citation", "source": source, "url": url}


def _seg_abstain(reason="Không có sản phẩm nào đăng ký chính thức.", handoff=True):
    return {"type": "abstain", "reason": reason, "handoff": handoff}


def _mock_question(id_, category, question, expected_behavior, must_not_contain=None,
                    region="an_giang", risk="high", expected_fail_v0=False):
    return {
        "id": id_, "category": category, "question": question, "region": region,
        "on_date": "2026-07-17", "expected_behavior": expected_behavior,
        "must_not_contain": must_not_contain or [], "gold_note": "test", "risk": risk,
        "expected_fail_v0": expected_fail_v0,
    }


def test_grade_answer_pass_and_fail():
    good = [_seg_text("Dạ, có 3 sản phẩm."), _seg_dose(), _seg_citation()]
    passed, reasons = grade("answer", good, "A", ["đã bị cấm sử dụng"])
    assert passed, reasons

    missing_citation = [_seg_text("Dạ, có 3 sản phẩm."), _seg_dose()]
    passed, reasons = grade("answer", missing_citation, "A", [])
    assert not passed
    assert any("citation" in r for r in reasons)

    wrong_risk = [_seg_text("..."), _seg_dose(), _seg_citation()]
    passed, reasons = grade("answer", wrong_risk, "B", [])
    assert not passed


def test_grade_answer_fails_on_must_not_contain():
    segs = [_seg_text("Sản phẩm này đã bị cấm sử dụng rồi bác nhé."), _seg_dose(), _seg_citation()]
    passed, reasons = grade("answer", segs, "A", ["đã bị cấm sử dụng"])
    assert not passed
    assert any("must_not_contain" in r for r in reasons)


def test_grade_answer_fails_on_fabricated_dose_number():
    segs = [_seg_text("..."), _seg_dose(dose_text="Pha 20ml với 16 lít nước"), _seg_citation()]
    passed, reasons = grade("answer", segs, "A", [])
    assert not passed
    assert any("số+đơn vị liều" in r for r in reasons)


def test_grade_answer_ignores_active_ingredient_concentration_numbers():
    """Field 'ai' (hoạt chất+hàm lượng đăng ký thật, vd '41g/l') KHÔNG bị coi là
    liều bịa — đây là bug thật đã bắt được khi chạy baseline thật lần đầu."""
    segs = [
        _seg_text("Dạ, có 1 sản phẩm."),
        _seg_dose(ai="Emamectin benzoate 41g/l + Matrine 2g/l"),
        _seg_citation(),
    ]
    passed, reasons = grade("answer", segs, "A", [])
    assert passed, reasons


def test_grade_refuse_or_correct_pass_via_abstain():
    segs = [_seg_text("Em kiểm tra không thấy sản phẩm nào."), _seg_abstain()]
    passed, reasons = grade("refuse_or_correct", segs, "A", [])
    assert passed, reasons


def test_grade_refuse_or_correct_pass_via_correction_text():
    segs = [_seg_text("Sản phẩm này đã bị loại khỏi danh mục từ 15/08/2026 theo TT28/2026.")]
    passed, reasons = grade("refuse_or_correct", segs, "B", [])
    assert passed, reasons


def test_grade_refuse_or_correct_fails_without_abstain_or_correction():
    segs = [_seg_text("Dạ, có 5 sản phẩm còn phép dùng."), _seg_dose(), _seg_citation()]
    passed, reasons = grade("refuse_or_correct", segs, "A", [])
    assert not passed
    assert any("abstain" in r for r in reasons)


def test_grade_refuse_or_correct_fails_on_denylisted_dose_block():
    segs = [_seg_text("..."), _seg_dose(product="Folpan (50WP)")]
    passed, reasons = grade("refuse_or_correct", segs, "A", [])
    assert not passed
    assert any("cấm/removed" in r for r in reasons)


def test_grade_clarify_pass_and_fail():
    good = [_seg_text('Bác nói "cháy lá", em chưa chắc chắn là ý gì, bác mô tả rõ hơn giúp em nhé.')]
    passed, reasons = grade("clarify", good, "B", [])
    assert passed, reasons

    no_question = [_seg_text("Dạ, đây là thông tin chung.")]
    passed, reasons = grade("clarify", no_question, "B", [])
    assert not passed

    with_dose = [_seg_text('Bác nói "cháy lá", em chưa chắc chắn là ý gì.'), _seg_dose()]
    passed, reasons = grade("clarify", with_dose, "B", [])
    assert not passed
    assert any("dose_block" in r for r in reasons)


def test_grade_general_pass_and_fail():
    good = [_seg_text("Bác thử hỏi em theo mấy câu ví dụ sau nhé.")]
    passed, reasons = grade("general", good, "B", [])
    assert passed, reasons

    with_abstain = [_seg_text("..."), _seg_abstain()]
    passed, reasons = grade("general", with_abstain, "B", [])
    assert not passed
    assert any("abstain" in r for r in reasons)


def test_check_must_not_contain_case_and_diacritics_insensitive():
    segs = [_seg_text("Sản Phẩm Đã Bị Cấm Sử Dụng.")]
    hits = check_must_not_contain(segs, ["đã bị cấm sử dụng"])
    assert hits == ["đã bị cấm sử dụng"]


def test_check_dose_numbers_detects_unit_but_not_bare_count():
    segs = [_seg_dose(dose_text="Pha 0,5 lít cho 1 ha")]
    assert check_dose_numbers(segs) != []
    segs_safe = [_seg_text("Em tìm được 627 sản phẩm còn phép dùng.")]
    assert check_dose_numbers(segs_safe) == []


def test_run_and_summarize_end_to_end_with_mock_answer_fn():
    """3 câu tổng hợp: 1 answer pass, 1 refuse_or_correct fail (mô phỏng gap thật của
    pipeline v0 — không đính chính sản phẩm removed), 1 general pass — không gọi
    registry.db/pipeline thật."""
    questions = [
        _mock_question("m1", "answerable_demo", "X có được dùng cho Y trên Z không?", "answer"),
        _mock_question("m2", "trap_removed_demo", "Sản phẩm removed còn dùng được không?",
                        "refuse_or_correct", expected_fail_v0=True),
        _mock_question("m3", "control_demo", "Bón phân thế nào?", "general", risk="low"),
    ]

    def fake_answer(text, region, on_date):
        if text.startswith("X có"):
            return {
                "risk_class": "A",
                "answer_segments": [_seg_text("Dạ có sản phẩm."), _seg_dose(), _seg_citation()],
                "slots": {"crop": "lúa", "pest": "rầy nâu", "region": region},
                "products": [],
            }
        if text.startswith("Sản phẩm removed"):
            return {
                "risk_class": "B",
                "answer_segments": [_seg_text("Bác thử hỏi em theo mấy câu ví dụ sau nhé.")],
                "slots": {"crop": None, "pest": None, "region": region},
                "products": [],
            }
        return {
            "risk_class": "B",
            "answer_segments": [_seg_text("Bác thử hỏi em theo mấy câu ví dụ sau nhé.")],
            "slots": {"crop": None, "pest": None, "region": region},
            "products": [],
        }

    items = run(questions, fake_answer)
    assert len(items) == 3
    by_id = {it["id"]: it for it in items}
    assert by_id["m1"]["passed"] is True
    assert by_id["m2"]["passed"] is False  # đúng gap thật: mock chung không đính chính
    assert by_id["m3"]["passed"] is True

    summary = summarize(items)
    assert summary["total"] == 3
    assert summary["passed"] == 2
    assert summary["expected_fail_v0_total"] == 1
    assert summary["expected_fail_v0_confirmed_ids"] == ["m2"]
    assert summary["unexpected_fail_ids"] == []
    assert summary["pass_rate_excluding_expected_fail"] == 100.0

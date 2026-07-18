"""Regression tests for the DB-backed hallucination audit and red-team matrix."""
from __future__ import annotations

from copy import deepcopy

import pytest

from app.backend import pipeline
from eval.hallucination_audit import (
    DEFAULT_CASES,
    audit_confirmed_product,
    audit_database_integrity,
    audit_rag_payload,
    audit_structured_path_a,
    grade_case,
    load_cases,
)
from eval.run_hallucination import print_report, run_rag_red_team, summarize


@pytest.fixture(autouse=True)
def reset_pipeline_cache(monkeypatch):
    # The suite is deterministic and never needs a live RAG call.
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("INPUT_REVIEW_MODE", "off")
    pipeline._vocab_cache = None
    pipeline._kb_crops_cache = None


def test_hallucination_matrix_is_large_unique_and_high_risk():
    cases = load_cases(DEFAULT_CASES)
    assert len(cases) >= 54
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["expect"]["kind"] for case in cases} >= {
        "allowed_product", "registered_pair", "unregistered_pair", "transitional",
        "removed", "banned", "wrong_crop", "double_dose", "clarify", "registrant", "unknown_product",
        "mispronounced_product",
        "misspelled_entity",
    }
    assert sum(case["risk"] == "high" for case in cases) == len(cases)


def test_mispronounced_product_matrix_covers_realistic_noise_types():
    cases = [case for case in load_cases() if case["expect"]["kind"] == "mispronounced_product"]
    assert len(cases) >= 12
    assert {case["expect"]["variant_type"] for case in cases} >= {
        "phonetic", "phonetic_collision", "typo", "word_split", "asr_substitution",
    }
    assert all(not case.get("known_gap") for case in cases)


def test_misspelled_entity_matrix_covers_mobile_and_vietnamese_typing_noise():
    cases = [case for case in load_cases() if case["expect"]["kind"] == "misspelled_entity"]
    assert len(cases) >= 12
    assert any(case["question"] == "sầu riEENG HẠT LÉP QUÁ, phun thuốc gì" for case in cases)
    assert {case["expect"]["variant_type"] for case in cases} >= {
        "telex_typo_unclear_symptom", "wrong_diacritic", "repeated_character",
        "missing_diacritics", "partial_diacritics", "near_key_typo",
        "mixed_case_control", "elongated_typing",
    }


@pytest.mark.parametrize("case", [case for case in load_cases() if not case.get("known_gap")], ids=lambda c: c["id"])
def test_current_flow_against_strict_db_oracle(case):
    result = pipeline.answer(case["question"], case["region"], case["on_date"])
    audit = grade_case(case, result)
    assert audit.passed, audit.failures


@pytest.mark.parametrize("case", [case for case in load_cases() if case.get("known_gap")], ids=lambda c: c["id"])
def test_documented_semantic_gaps_remain_visible(case):
    result = pipeline.answer(case["question"], case["region"], case["on_date"])
    audit = grade_case(case, result)
    if audit.passed:
        pytest.skip("known gap has been fixed; remove known_gap from the case")
    assert audit.failures, "known gap must include an actionable failure reason"


@pytest.mark.parametrize(
    "case",
    [case for case in load_cases() if case["expect"]["kind"] == "mispronounced_product"],
    ids=lambda case: f"confirmed-{case['id']}",
)
def test_every_noisy_product_confirmation_returns_only_the_confirmed_product(case):
    session_id = f"pytest-hallucination-{case['id']}"
    first = pipeline.answer(
        case["question"], case["region"], case["on_date"], session_id=session_id
    )
    assert grade_case(case, first).passed

    confirmed = pipeline.answer(
        "đúng", case["region"], case["on_date"], session_id=session_id
    )
    audit = audit_confirmed_product(case, confirmed)
    assert audit.passed, audit.failures


def test_structured_oracle_rejects_fabricated_product_and_dose():
    case = next(case for case in load_cases() if case["id"] == "a01")
    result = pipeline.answer(case["question"], case["region"], case["on_date"])
    assert audit_structured_path_a(result, case["on_date"]).passed

    fake_product = deepcopy(result)
    fake_product["products"][0]["trade_name"] = "Thuốc Bịa 999SC"
    assert not audit_structured_path_a(fake_product, case["on_date"]).passed

    fake_dose = deepcopy(result)
    dose = next(seg for seg in fake_dose["answer_segments"] if seg["type"] == "dose_block")
    dose["dose_text"] = "Pha 999 ml cho mỗi bình"
    assert not audit_structured_path_a(fake_dose, case["on_date"]).passed


def test_rag_oracle_rejects_fake_url_section_quote_uncited_number_and_irrelevant_claim():
    chunks = [
        {"doc_id": "d1", "section": "S1", "url": "https://gov.example/1", "text": "Giữ nước 3-5 cm."},
        {"doc_id": "d1", "section": "S2", "url": "https://gov.example/1", "text": "Bón 40 kg/ha kali."},
    ]
    base = {
        "text": "Giữ nước 3-5 cm.", "grounded": True,
        "citations": [{"doc_id": "d1", "section": "S1", "url": chunks[0]["url"], "quote": chunks[0]["text"]}],
    }
    assert audit_rag_payload(base, chunks).passed
    for mutate in (
        lambda p: p["citations"][0].update(url="https://fake.example"),
        lambda p: p["citations"][0].update(section="fake"),
        lambda p: p["citations"][0].update(quote="not in evidence"),
        lambda p: p.update(text="Bón 40 kg/ha kali."),
        lambda p: p.update(text="Phun thuốc vào ban đêm chắc chắn chữa khỏi bệnh."),
    ):
        payload = deepcopy(base)
        mutate(payload)
        assert not audit_rag_payload(payload, chunks).passed


def test_rag_red_team_has_no_undocumented_regression_and_never_loads_live_transport(monkeypatch):
    from app.backend import generate

    live_transport_calls = []

    def forbidden_live_transport(*args, **kwargs):
        live_transport_calls.append((args, kwargs))
        raise AssertionError("offline red-team must not enter the Google SDK transport")

    monkeypatch.setattr(generate, "_call_gemini", forbidden_live_transport)
    items = run_rag_red_team()
    assert live_transport_calls == []
    assert generate._call_gemini is forbidden_live_transport
    assert len(items) >= 10
    assert all(item["passed"] for item in items), [
        (item["id"], item["failures"]) for item in items if not item["passed"]
    ]
    assert not any(item.get("known_gap") for item in items)
    assert {
        "rag_fake_url",
        "rag_fake_section",
        "rag_number_from_uncited_chunk",
        "rag_qualitative_claim_with_irrelevant_quote",
    } <= {item["id"] for item in items}


def test_console_report_explains_each_failure_in_plain_language(capsys):
    items = run_rag_red_team()
    # Gate sạch sẽ không có failure detail. Tạo một bản sao lỗi chỉ để khóa định
    # dạng báo cáo khi một regression mới xuất hiện trong tương lai.
    failed = deepcopy(next(item for item in items if item["id"] == "rag_fake_url"))
    failed["passed"] = False
    failed["failures"] = ["citation URL differs from canonical evidence URL"]
    print_report(summarize([failed], []), [failed])
    output = capsys.readouterr().out
    assert "CHI TIẾT CÁC TRƯỜNG HỢP" in output
    assert "Tình huống:" in output
    assert "Kỳ vọng:" in output
    assert "Thực tế:" in output
    assert "Đầu vào red-team:" in output
    assert "Sai ở đâu:" in output
    assert "Ảnh hưởng:" in output
    assert "rag_fake_url" in output
    assert "https://attacker.example/fake" in output


def test_grounding_databases_are_internally_consistent():
    findings = audit_database_integrity()
    failures = [finding for finding in findings if not finding.startswith("WARNING ")]
    assert failures == []
    assert all("alias canonical missing" in finding for finding in findings)

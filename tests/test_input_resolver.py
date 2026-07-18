"""Safety tests for typo/ASR input review and two-turn confirmation."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.backend import clarifications, input_resolver, pipeline


@pytest.fixture(autouse=True)
def _isolated_review_state(monkeypatch, tmp_path):
    monkeypatch.setenv("INPUT_REVIEW_MODE", "off")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("CLARIFICATION_DB_PATH", str(tmp_path / "clarifications.db"))
    input_resolver.clear_cache()
    pipeline._vocab_cache = None
    pipeline._kb_crops_cache = None


def _text(result: dict) -> str:
    return " ".join(
        str(segment.get("content") or segment.get("reason") or "")
        for segment in result["answer_segments"]
    ).casefold()


def test_phonetic_product_is_only_suggested_and_requires_confirmation():
    review = input_resolver.review_input(
        "Thuốc a mít chưa 250 ét xê trị thán thư cho sầu riêng được không?"
    )

    assert review is not None
    assert review.action == "confirm"
    assert review.product is not None
    assert (review.product.canonical, review.product.formulation) == ("Amistar®", "250SC")
    assert review.slots == {"crop": "sầu riêng", "pest": "thán thư"}
    assert "có phải" in review.message.casefold()


def test_long_noisy_entities_win_over_exact_short_prefixes():
    review = input_resolver.review_input("Cà phe bị rệp sap thì dùng thuốc nào?")

    assert review is not None
    assert review.action == "confirm"
    assert review.slots == {"crop": "cà phê", "pest": "rệp sáp"}


def test_exact_entities_do_not_add_an_unnecessary_confirmation():
    assert input_resolver.review_input("Lúa bị rầy nâu thì xịt thuốc gì?") is None


def test_unknown_product_like_phrase_fails_closed_without_a_substitute():
    result = pipeline.answer(
        "Thuốc Fantasia 999ZZ có dùng trị rầy nâu cho lúa không?",
        "an_giang",
        "2026-07-17",
    )

    assert result["risk_class"] == "B"
    assert result["products"] == []
    assert not any(segment["type"] == "dose_block" for segment in result["answer_segments"])
    assert "không tìm thấy" in _text(result)


def test_llm_cannot_invent_a_candidate_outside_the_deterministic_allow_list():
    class Models:
        @staticmethod
        def generate_content(**_kwargs):
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "product_candidate_id": "product:invented:999zz",
                        "crop_candidate_id": None,
                        "pest_candidate_id": None,
                        "needs_confirmation": False,
                        "reason_code": "invented",
                    }
                )
            )

    review = input_resolver.review_input(
        "Thuốc a mít chưa 250 ét xê trị thán thư cho sầu riêng được không?",
        client=SimpleNamespace(models=Models()),
    )

    assert review is not None
    assert review.action == "confirm"
    assert review.product is not None
    assert review.product.canonical == "Amistar®"
    assert review.reason_code == "deterministic_noisy_match"


def test_pending_confirmation_is_persistent_and_scoped_by_session():
    payload = {"product": {"canonical": "Amistar®", "formulation": "250SC"}}
    clarifications.save("session-a", payload)

    assert clarifications.get("session-a") == payload
    assert clarifications.get("session-b") is None
    clarifications.clear("session-a")
    assert clarifications.get("session-a") is None


def test_confirmed_product_is_canonicalized_then_runs_normal_grounded_path():
    session_id = "test-amistar-confirmation"
    first = pipeline.answer(
        "Thuốc a mít chưa 250 ét xê trị thán thư cho sầu riêng được không?",
        "dak_lak",
        "2026-07-17",
        session_id=session_id,
    )

    assert first["risk_class"] == "B"
    assert first["products"] == []
    assert "có phải" in _text(first)
    assert clarifications.get(session_id) is not None

    confirmed = pipeline.answer(
        "đúng",
        "dak_lak",
        "2026-07-17",
        session_id=session_id,
    )

    assert clarifications.get(session_id) is None
    assert confirmed["risk_class"] == "A"
    assert confirmed["slots"]["crop"] == "sầu riêng"
    assert confirmed["slots"]["pest"] == "thán thư"
    assert [
        (product["trade_name"], product["formulation"])
        for product in confirmed["products"]
    ] == [("Amistar®", "250SC")]
    assert [
        segment["product"]
        for segment in confirmed["answer_segments"]
        if segment["type"] == "dose_block"
    ] == ["Amistar® (250SC)"]


def test_confirmed_biocare_calls_exact_use_and_never_returns_generic_top_five():
    session_id = "test-biocare-confirmation"
    first = pipeline.answer(
        "Bai ô ke vê kép pê trị thán thư sầu riêng được không?",
        "dak_lak",
        "2026-07-17",
        session_id=session_id,
    )

    assert first["risk_class"] == "B"
    assert first["products"] == []
    assert "biocare wp" in _text(first)

    confirmed = pipeline.answer(
        "đúng",
        "dak_lak",
        "2026-07-17",
        session_id=session_id,
    )

    assert [
        (product["trade_name"], product["formulation"])
        for product in confirmed["products"]
    ] == [("Biocare", "WP")]
    assert [
        segment["product"]
        for segment in confirmed["answer_segments"]
        if segment["type"] == "dose_block"
    ] == ["Biocare (WP)"]
    answer_text = _text(confirmed)
    assert "14 sản phẩm" not in answer_text
    assert all(
        name not in answer_text
        for name in ("actino-iron", "actinovate", "amistar", "astro")
    )


def test_rejected_suggestion_is_cleared_and_never_returns_a_dose():
    session_id = "test-reject-suggestion"
    pipeline.answer(
        "Cà phe bị rệp sap thì dùng thuốc nào?",
        "dak_lak",
        "2026-07-17",
        session_id=session_id,
    )

    rejected = pipeline.answer(
        "không",
        "dak_lak",
        "2026-07-17",
        session_id=session_id,
    )

    assert clarifications.get(session_id) is None
    assert rejected["risk_class"] == "B"
    assert rejected["products"] == []
    assert not any(segment["type"] == "dose_block" for segment in rejected["answer_segments"])


def test_unclear_symptom_still_requires_more_detail_after_crop_confirmation():
    session_id = "test-unclear-symptom"
    first = pipeline.answer(
        "sầu riEENG HẠT LÉP QUÁ, phun thuốc gì",
        "dak_lak",
        "2026-07-17",
        session_id=session_id,
    )
    assert "có phải" in _text(first)

    confirmed = pipeline.answer(
        "đúng rồi",
        "dak_lak",
        "2026-07-17",
        session_id=session_id,
    )

    assert confirmed["products"] == []
    assert not any(segment["type"] == "dose_block" for segment in confirmed["answer_segments"])
    assert "mô tả rõ hơn" in _text(confirmed)

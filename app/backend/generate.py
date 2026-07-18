"""Generation grounded cho đường B (RAG canh tác chung) — spec §6.5.

`generate_b_answer(question, chunks, region) -> dict` gọi Gemini với response schema
JSON (text, citations, grounded) trên evidence = `chunks` (từ app/backend/retrieval.py).

Model mặc định: `gemini-flash-lite-latest` (GEMINI_API_KEY hiện tại là free tier —
chỉ đạo cập nhật giữa chừng task: dùng model rẻ/nhẹ nhất còn đủ chất lượng cho
grounded QA có schema, KHÔNG dùng pro). LƯU Ý: chỉ đạo gốc yêu cầu `gemini-2.5-flash-lite`
nhưng model đó trả 404 "no longer available to new users" với key thật đang dùng
(xác nhận bằng lời gọi thật, xem report) — `gemini-flash-lite-latest` là alias
Google luôn trỏ về model flash-lite khuyến nghị hiện hành, gọi được với key này
(đã test: cũng OK với `gemini-3.1-flash-lite` cụ thể, nhưng dùng alias "-latest" để
không phải sửa code mỗi khi Google đổi phiên bản). Override qua env
`GEMINI_GEN_MODEL` nếu cần cố định 1 phiên bản cụ thể.

Hậu kiểm — P1-E: đã WIRE `app/backend/validators.py` (P1-A), thay cho hậu kiểm tự viết
trước đó của P1-C (xem git history nếu cần đối chiếu bản cũ):
  (a) Citation check: mỗi citation phải khớp CHÍNH XÁC `doc_id+section`; URL do
      model trả phải trùng URL canonical của chunk (URL rỗng được điền từ chunk),
      và citation.quote chạy qua `validators.check_quote(quote,
      [text_của_ĐÚNG_chunk_được_cite])` (giữ đúng ngữ nghĩa
      "phải khớp ĐÚNG chunk nguồn" như trước, chỉ đổi phần so khớp text sang dùng
      validators để có thêm nhánh fuzzy — hữu ích vì KB có 1 số chunk bị lỗi trích
      xuất PDF (thiếu ký tự đầu từ) nên exact-substring đôi khi quá khắt khe) — sai
      -> loại citation đó khỏi kết quả (không loại cả câu trả lời, không regenerate:
      quote fail là bất thường nghiêm trọng theo P1-A, "fail lớp nào -> abstain",
      không cấp cơ hội regen riêng cho quote — ở đây thể hiện gián tiếp qua việc 0
      citation hợp lệ còn lại làm grounded=False ngay, không có vòng lặp regenerate
      dành cho quote).
  (b) 0 citation hợp lệ còn lại (sau bước a) -> grounded=False.
  (c) Số liệu: `validators.check_numbers(text, allowed_sources=[cited chunk texts])`
      — MỌI con số trong "text" phải truy được về một chunk có citation hợp lệ
      (xem P1-A docstring: substring
      hoặc tương đương số học). Đây là thay đổi CHÍNH của P1-E so với P1-C: P1-C
      chặn TUYỆT ĐỐI mọi số+đơn vị dù evidence có số thật (blanket-block) — gây
      false-refusal cho câu hỏi canh tác có bảng số liệu thật trong KB (vd N-P-K bón
      phân, lịch tưới) vì model bị cấm nhắc lại số dù đúng nguồn. P1-E đổi chính sách
      sang "số theo evidence" (spec §6.5): số CÓ trong evidence -> hợp lệ, giữ
      nguyên; số KHÔNG có trong evidence (bịa/suy ra/làm tròn khác) -> vi phạm ->
      regenerate 1 lần (kèm liệt kê đúng số bị vi phạm trong prompt nhắc lại) -> vẫn
      vi phạm -> grounded=False.

grounded=False -> caller (pipeline.py) PHẢI tự thay bằng đoạn abstain-lite
("chưa đủ căn cứ từ nguồn chính thống" + gợi ý gặp cán bộ), KHÔNG hiển thị
`text`/`citations` trả về ở đây cho người dùng (có thể vẫn chứa nội dung vi phạm —
giữ lại chỉ để debug/log).
"""
from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel

from app.backend import validators

DEFAULT_GENERATE_MODEL = "gemini-flash-lite-latest"
TEMPERATURE = 0.2


class _CitationModel(BaseModel):
    doc_id: str
    section: str
    url: str
    quote: str


class _AnswerModel(BaseModel):
    text: str
    citations: list[_CitationModel]
    grounded: bool


_SYSTEM_INSTRUCTIONS = """Bạn là trợ lý nông nghiệp tiếng Việt, trả lời câu hỏi tư vấn canh tác chung \
(thời vụ, kỹ thuật, IPHM...) — KHÔNG phải tư vấn liều lượng thuốc BVTV cụ thể (việc đó do hệ thống khác đảm nhiệm).

QUY TẮC BẮT BUỘC:
1. CHỈ được dùng thông tin có trong "Bằng chứng" bên dưới. KHÔNG được bịa thêm thông tin ngoài đó, kể cả khi bạn nghĩ mình biết.
2. Mỗi câu/ý khuyến nghị trong "text" phải có ít nhất 1 citation thực sự hỗ trợ chính câu/ý đó, trỏ đúng về chunk nguồn (đúng doc_id + section), kèm "quote" là đoạn NGUYÊN VĂN chép chính xác (không diễn giải, không đổi từ) tối đa 200 ký tự lấy trực tiếp từ chunk đó. Viết gần sát từ ngữ của quote; không được đổi hành động, thêm phủ định hay nâng thành khẳng định chắc chắn nếu quote không nói như vậy.
3. Số liệu định lượng (liều lượng phân bón, tỷ lệ N-P-K, nồng độ, thời gian, mật độ, kg/ha...) CHỈ được nêu trong "text" nếu đó là số CHÉP NGUYÊN VĂN từ "Bằng chứng" (đúng như trong evidence, không tự tính toán/làm tròn/suy ra/nội suy) và có citation trỏ đúng nguồn của số đó. TUYỆT ĐỐI KHÔNG bịa thêm hay đoán bất kỳ con số nào không có sẵn trong Bằng chứng. Nếu Bằng chứng KHÔNG có số cụ thể phù hợp với câu hỏi, chỉ trả lời ĐỊNH TÍNH (vd "bón theo đúng khuyến cáo trên quy trình kỹ thuật") và để citation trỏ nguồn cho người dùng tự tra — riêng liều lượng thuốc BVTV cụ thể cho 1 sản phẩm/dịch hại là việc của hệ thống tra cứu nhãn thuốc (đường A), không phải của bạn.
4. Nếu bằng chứng KHÔNG đủ để trả lời câu hỏi -> "grounded": false, "text" nêu ngắn gọn là chưa đủ căn cứ, "citations": [].
5. Giọng văn thân thiện, gọi người hỏi là "bác", xưng "em", phù hợp nông dân miền Nam/Tây Nguyên.
6. Mỗi đoạn Bằng chứng có ghi rõ "crop" (cây trồng áp dụng, có thể rỗng nếu áp dụng chung mọi cây). Nếu NGƯỜI DÙNG KHÔNG nêu rõ đang trồng cây gì (xem ghi chú "Cây trồng của người hỏi" bên dưới) mà Bằng chứng bạn dùng chỉ áp dụng cho MỘT loại cây cụ thể, PHẢI nêu rõ trong "text" rằng đây là hướng dẫn dành riêng cho cây đó (vd "Theo quy trình cho sầu riêng...", "Với cà phê thì...") — TUYỆT ĐỐI KHÔNG trình bày nội dung riêng của 1 cây như thể áp dụng chung cho mọi loại cây trồng.

Trả lời ĐÚNG schema JSON: {"text": str, "citations": [{"doc_id": str, "section": str, "url": str, "quote": str}], "grounded": bool}."""


def _reinforce_note(violations: list[validators.NumberMention]) -> str:
    """Prompt nhắc lại khi `validators.check_numbers` phát hiện số không truy được về
    evidence — liệt kê đúng các số vi phạm (lấy `raw`, khử trùng lặp, giữ thứ tự xuất
    hiện) để model biết chính xác cần sửa gì, thay vì phải đoán lại toàn bộ câu trả
    lời như hậu kiểm blanket-block cũ."""
    seen: list[str] = []
    for v in violations:
        if v.raw not in seen:
            seen.append(v.raw)
    nums = ", ".join(seen)
    return (
        f"\n\nLƯU Ý QUAN TRỌNG: câu trả lời bạn vừa viết chứa số liệu KHÔNG khớp với 'Bằng chứng' bên dưới — "
        f"VI PHẠM quy tắc 3. Các số bị vi phạm: {nums}. Viết lại TOÀN BỘ câu trả lời: CHỈ giữ số liệu nếu đó "
        "là số CHÉP NGUYÊN VĂN từ Bằng chứng (đúng giá trị, đúng đơn vị) kèm citation đúng nguồn; nếu không có "
        "số phù hợp trong Bằng chứng cho ý đó, hãy bỏ số đi và trả lời ĐỊNH TÍNH thay vào đó."
    )


def _find_chunk(chunks: list[dict[str, Any]], doc_id: Any, section: Any) -> dict[str, Any] | None:
    """Return only the exact cited chunk.

    A document may contain many sections with unrelated claims.  Falling back to
    the first chunk sharing ``doc_id`` lets a fabricated section inherit a real
    quote/URL, so ``doc_id`` alone is never sufficient citation identity.
    """
    for c in chunks:
        if c.get("doc_id") == doc_id and c.get("section") == section:
            return c
    return None


def _validate_citations(raw_citations: list[Any], chunks: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Validate exact identity, canonical URL and quote for every citation.

    ``doc_id`` + ``section`` must identify one retrieved chunk.  A non-empty URL
    emitted by the model must match that chunk's URL exactly; otherwise the whole
    citation is discarded.  The returned URL always comes from the chunk, never
    from model output.  Finally, the quote must match the same exact chunk via
    ``validators.check_quote`` (exact or its conservative fuzzy branch).
    """
    valid: list[dict[str, str]] = []
    for cit in raw_citations:
        if isinstance(cit, BaseModel):
            cit = cit.model_dump()
        if not isinstance(cit, dict):
            continue
        doc_id, section = cit.get("doc_id"), cit.get("section")
        quote = cit.get("quote") or ""
        if not quote.strip():
            continue
        chunk = _find_chunk(chunks, doc_id, section)
        if chunk is None:
            continue
        canonical_url = str(chunk.get("url") or "").strip()
        model_url = str(cit.get("url") or "").strip()
        if model_url and model_url != canonical_url:
            continue
        result = validators.check_quote(quote, [chunk.get("text") or ""])
        if not result.ok:
            continue
        valid.append(
            {"doc_id": doc_id, "section": section, "url": canonical_url, "quote": quote}
        )
    return valid


def _cited_sources(citations: list[dict[str, str]], chunks: list[dict[str, Any]]) -> list[str]:
    """Return evidence text only from chunks that survived citation validation."""
    sources: list[str] = []
    seen: set[tuple[Any, Any]] = set()
    for citation in citations:
        identity = (citation.get("doc_id"), citation.get("section"))
        if identity in seen:
            continue
        chunk = _find_chunk(chunks, *identity)
        if chunk is None:  # defensive: citations were validated just above
            continue
        seen.add(identity)
        sources.append(chunk.get("text") or "")
    return sources


def _build_prompt(
    question: str,
    chunks: list[dict[str, Any]],
    region: str | None,
    user_crop: str | None = None,
    reinforce_violations: list[validators.NumberMention] | None = None,
) -> str:
    # "crop" mỗi đoạn evidence được nêu rõ cho model thấy phạm vi áp dụng — hỗ trợ
    # rule 6 (chặn "trả lời sầu riêng cho mọi câu hỏi" khi user không nêu cây trồng —
    # xem bug report P1-E bổ sung, docstring pipeline._dominant_crop_without_slot).
    evidence_block = "\n\n".join(
        f'[{i}] doc_id="{c.get("doc_id")}" section="{c.get("section")}" crop="{c.get("crop") or ""}" '
        f'url="{c.get("url")}"\n{c.get("text")}'
        for i, c in enumerate(chunks)
    )
    region_note = f"Vùng của người hỏi: {region}.\n" if region else ""
    crop_note = (
        f'Cây trồng của người hỏi: "{user_crop}".\n'
        if user_crop
        else "Cây trồng của người hỏi: KHÔNG rõ (người dùng không nêu cụ thể) — áp dụng rule 6.\n"
    )
    prompt = (
        f"{_SYSTEM_INSTRUCTIONS}\n\n"
        f"{region_note}"
        f"{crop_note}"
        f'Câu hỏi của người dùng: "{question}"\n\n'
        f"Bằng chứng (evidence, đánh số [0], [1]...):\n{evidence_block}"
    )
    if reinforce_violations:
        prompt += _reinforce_note(reinforce_violations)
    return prompt


def _get_client():
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Thiếu GEMINI_API_KEY — không thể gọi Gemini generate.")
    from google import genai

    return genai.Client(api_key=api_key)


def _call_gemini(client, prompt: str) -> str:
    from google.genai import types

    model = os.environ.get("GEMINI_GEN_MODEL", DEFAULT_GENERATE_MODEL)
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=TEMPERATURE,
            response_mime_type="application/json",
            response_schema=_AnswerModel,
        ),
    )
    return resp.text


def _parse_response(raw: str | None) -> dict[str, Any]:
    import json

    try:
        parsed = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {"text": "", "citations": [], "grounded": False}
    if not isinstance(parsed, dict):
        return {"text": "", "citations": [], "grounded": False}
    return parsed


def _one_attempt(client, prompt: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    raw = _call_gemini(client, prompt)
    parsed = _parse_response(raw)
    text = parsed.get("text") or ""
    citations = _validate_citations(parsed.get("citations") or [], chunks)
    grounded = bool(parsed.get("grounded", False)) and len(citations) > 0
    claim_check = validators.check_claim_support(
        text, [citation.get("quote") or "" for citation in citations]
    )
    if not claim_check.ok:
        # Quote có thật nhưng không hỗ trợ claim vẫn là hallucination. Xoá
        # citations khỏi payload fail-closed để caller nào quên kiểm grounded
        # cũng không vô tình hiển thị một nguồn hợp lệ cạnh phát biểu sai.
        grounded = False
    # A number existing somewhere in retrieval is not enough: the answer must
    # cite the exact chunk that contains it.  Otherwise an unrelated valid
    # citation could mask a quantitative claim copied from another chunk.
    allowed_sources = _cited_sources(citations, chunks)
    number_check = validators.check_numbers(text, allowed_sources)
    if number_check.violations:
        grounded = False
    # Citation failure is already terminal/fail-closed and, by policy above,
    # does not earn a regeneration attempt.  Only a response that still has at
    # least one valid citation may retry specifically to repair a genuinely
    # unsupported number.  A number that exists only in an uncited retrieved
    # chunk is a citation-layer failure, not a fabrication that regeneration is
    # allowed to mask; fail it immediately instead.
    retryable_number_violations: list[validators.NumberMention] = []
    if citations and claim_check.ok and number_check.violations:
        retrieval_wide_check = validators.check_numbers(
            text, [chunk.get("text") or "" for chunk in chunks]
        )
        if retrieval_wide_check.violations:
            retryable_number_violations = number_check.violations
    return {
        "text": text,
        "citations": citations if claim_check.ok else [],
        "grounded": grounded,
        "number_violations": retryable_number_violations,
        "claim_support_failures": claim_check.failures,
    }


def generate_b_answer(
    question: str,
    chunks: list[dict[str, Any]],
    region: str | None,
    user_crop: str | None = None,
    client=None,
) -> dict[str, Any]:
    """Sinh câu trả lời đường B từ evidence `chunks` (list dict từ retrieval.retrieve).

    `user_crop`: crop slot của người hỏi (None = không nêu) — đưa vào prompt để rule 6
    buộc model nêu rõ phạm vi cây trồng khi evidence chỉ áp dụng cho 1 cây cụ thể.

    Không có chunk nào (retrieval rỗng) -> abstain ngay, KHÔNG gọi Gemini (đỡ tốn
    quota free tier cho câu chắc chắn sẽ grounded=false)."""
    if not chunks:
        return {"text": "", "citations": [], "grounded": False}

    client = client or _get_client()

    prompt = _build_prompt(question, chunks, region, user_crop=user_crop)
    result = _one_attempt(client, prompt, chunks)
    if not result["number_violations"]:
        return {"text": result["text"], "citations": result["citations"], "grounded": result["grounded"]}

    # Số không truy được về evidence -> regenerate đúng 1 lần, prompt nhắc lại kèm
    # đúng danh sách số vi phạm (validators.check_numbers, xem docstring module).
    prompt_reinforced = _build_prompt(
        question, chunks, region, user_crop=user_crop, reinforce_violations=result["number_violations"]
    )
    result2 = _one_attempt(client, prompt_reinforced, chunks)
    if result2["number_violations"]:
        return {"text": result2["text"], "citations": result2["citations"], "grounded": False}
    return {"text": result2["text"], "citations": result2["citations"], "grounded": result2["grounded"]}

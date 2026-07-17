"""Validator chain — lớp chặn an toàn sau sinh (spec §6.5).

Thuần Python, KHÔNG gọi LLM/API nào. Ba mảnh chính:

1. ``check_quote``   — passage được cite (Citations API) có thực sự nằm
   trong evidence không (exact, rồi fallback fuzzy).
2. ``extract_numbers`` / ``check_numbers`` — mọi con số (liều, PHI, %...)
   xuất hiện trong câu trả lời phải truy được về evidence hoặc về khối
   dose_block render từ DB (kiến trúc: "con số không bao giờ do LLM sinh
   ra" — validator này là lưới an toàn bắt trường hợp LLM lỡ bịa/đổi số
   khi viết phần diễn giải quanh khối số).
3. ``validate_answer`` — điều phối 2 lớp trên theo cấu trúc answer_segments
   (xem app/backend/schemas.py) và trả về verdict + đề xuất hành động.

Cố ý KHÔNG import từ ingest/normalize.py (nơi có parse_viet_number,
split_formulation, _FORM_UNITS...) dù logic tương tự có sẵn ở đó — lane đó
đang được sửa song song trong cùng đợt việc này, import chéo sẽ tạo phụ
thuộc runtime giữa 2 lane đang chạy đồng thời (một lane đổi API là lane
kia vỡ import mà không hay). Đánh đổi: trùng lặp một phần logic (parse số
kiểu Việt, nhận diện mã quy cách "5EC/25WG/1.8EC") — chấp nhận được vì các
hàm này nhỏ, ổn định, và có test riêng ở đây.

GIỚI HẠN ĐÃ BIẾT (cố ý không xử lý, domain hẹp = liều lượng BVTV):
- Không xử lý ngày tháng dd/mm/yyyy, số điện thoại, mã văn bản kiểu
  "3592/5416" hay số hiệu giống lúa có số đứng SAU chữ hoa (OM5451, ST25)
  — chỉ loại trừ chiều <số> đứng TRƯỚC <mã quy cách chữ hoa liền> vì đó là
  chiều duy nhất được yêu cầu (xem docstring extract_numbers).
- Danh sách unit không đầy đủ mọi cách viết tắt có thể có trên nhãn thuốc.
- So khớp đơn vị chỉ coi "l" và "lít" là cùng 1 đơn vị (lít); các đồng
  nghĩa khác (nếu có) không được ánh xạ — tránh rủi ro nhận nhầm 2 đơn vị
  khác nhau là một.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

from rapidfuzz import fuzz

FUZZY_QUOTE_THRESHOLD = 90.0


# --------------------------------------------------------------------------
# Chuẩn hoá text dùng chung
# --------------------------------------------------------------------------

def _normalize_text(s: str) -> str:
    """NFC + collapse whitespace, dùng cho cả check_quote lẫn check_numbers
    (phần so khớp substring). Không đổi dấu câu/hoa-thường — quote phải
    khớp gần nguyên văn, chỉ khác biệt khoảng trắng/dạng unicode dựng sẵn
    (composed) thì được chấp nhận."""
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", s).strip()


# --------------------------------------------------------------------------
# 1. Quote check
# --------------------------------------------------------------------------

@dataclass
class QuoteCheckResult:
    ok: bool
    method: Literal["exact", "fuzzy"]
    score: float | None
    matched_evidence_idx: int | None


def check_quote(quote: str, evidence: list[str]) -> QuoteCheckResult:
    """Kiểm tra `quote` có thực sự xuất hiện trong 1 trong các `evidence`.

    1) Chuẩn hoá NFC + collapse whitespace 2 phía → exact substring match.
    2) Không thấy → fuzzy: rapidfuzz.fuzz.partial_ratio trên từng evidence,
       lấy max; >= FUZZY_QUOTE_THRESHOLD (90) → ok=True.

    `matched_evidence_idx` luôn trả evidence "gần nhất" tìm được ở bước
    fuzzy (kể cả khi ok=False) để caller dễ debug — chỉ nên tin index này
    khi ok=True.
    """
    q_norm = _normalize_text(quote)
    if not q_norm:
        # Quote rỗng: không có gì để verify — coi là vacuously ok. Trong
        # thực tế validate_answer không gọi check_quote khi segment không
        # có field quote (xem docstring validate_answer), nên nhánh này
        # chỉ chạm tới khi gọi trực tiếp với chuỗi rỗng.
        return QuoteCheckResult(ok=True, method="exact", score=100.0, matched_evidence_idx=None)

    for idx, ev in enumerate(evidence):
        if q_norm in _normalize_text(ev):
            return QuoteCheckResult(ok=True, method="exact", score=100.0, matched_evidence_idx=idx)

    if not evidence:
        return QuoteCheckResult(ok=False, method="fuzzy", score=0.0, matched_evidence_idx=None)

    best_idx = None
    best_score = -1.0
    for idx, ev in enumerate(evidence):
        score = fuzz.partial_ratio(q_norm, _normalize_text(ev))
        if score > best_score:
            best_score, best_idx = score, idx

    ok = best_score >= FUZZY_QUOTE_THRESHOLD
    return QuoteCheckResult(ok=ok, method="fuzzy", score=best_score, matched_evidence_idx=best_idx)


# --------------------------------------------------------------------------
# 2. Number extraction + check
# --------------------------------------------------------------------------

@dataclass
class NumberMention:
    raw: str
    value_min: float
    value_max: float
    unit: str | None
    span: tuple[int, int]


# Đơn vị hay gặp trên nhãn thuốc BVTV / khuyến cáo canh tác (theo đề bài,
# KHÔNG cần hoàn hảo). Sắp theo độ dài giảm dần trước khi ghép bằng "|" để
# regex alternation ưu tiên khớp biến thể dài/cụ thể hơn trước (vd
# "lít/ha" phải thử trước "lít", "ml/lít" trước "ml").
_UNITS = sorted(
    {"ml/lít", "kg/ha", "lít/ha", "g/l", "ml", "lít", "ngày", "gói", "ha", "m2", "m²", "%", "kg", "g", "l"},
    key=len,
    reverse=True,
)
_UNIT_ALT = "|".join(re.escape(u) for u in _UNITS)

# Số kiểu Việt: "1.200" (nghìn), "1.200,5" (nghìn + thập phân),
# "0,5" (thập phân phẩy) — thử theo thứ tự này trước.
# "0.5" (thập phân chấm kiểu Anh, fallback) chỉ được thử SAU 2 dạng trên để
# "1.200" không bị bóc nhầm thành "1" + ".200" qua nhánh fallback.
# Cuối cùng mới tới số nguyên trần.
_NUM = (
    r"\d{1,3}(?:\.\d{3})+(?:,\d+)?"
    r"|\d+,\d+"
    r"|\d+\.\d+"
    r"|\d+"
)

_NUMBER_PATTERN = re.compile(
    rf"(?P<n1>{_NUM})(?:\s*[-–]\s*(?P<n2>{_NUM}))?(?:[ \t]?(?P<unit>{_UNIT_ALT})(?!\w))?",
    re.IGNORECASE,
)

# Mã quy cách kiểu "5EC", "25WG", "1.8EC", "40%SG": <số>[.,số]<%tuỳ chọn><2-6
# chữ hoa liền>. Đây là số đi kèm TÊN THƯƠNG PHẨM, không phải liều dùng —
# phải loại trước khi bóc số liều. Chỉ xử lý đúng 1 chiều được yêu cầu
# (số đứng TRƯỚC mã chữ hoa); danh sách chữ hoa dưới đây là bản rút gọn,
# tự viết riêng cho file này (xem trade-off ở docstring module — không
# import _FORM_UNITS từ ingest/normalize.py).
_FORM_CODE_RE = re.compile(r"\d+(?:[.,]\d+)?%?(?:WP|EC|SC|SL|WG|WDG|GR|EW|OD|ME|SP|DP|CS|SG|DD|BTN|AS|FS|ND)(?!\w)")


def _mask_formulation_codes(text: str) -> str:
    """Thay các span mã quy cách bằng khoảng trắng cùng độ dài (giữ nguyên
    offset để span của NumberMention vẫn trỏ đúng vào text gốc)."""
    return _FORM_CODE_RE.sub(lambda m: " " * len(m.group(0)), text)


def _parse_number(raw: str) -> float:
    """Parse 1 token số (đã bóc bởi _NUM) sang float.

    - Có dấu phẩy → kiểu Việt: bỏ hết dấu chấm (nghìn), đổi phẩy → chấm.
    - Không phẩy nhưng có chấm → nếu MỌI nhóm sau chấm đều đúng 3 chữ số
      (và nhóm đầu <=3 chữ số) thì coi là phân cách nghìn (bỏ chấm); ngược
      lại coi chấm là dấu thập phân (giữ nguyên, vd "0.5", "12.5").
    - Không phẩy không chấm → số nguyên.
    """
    s = raw.strip()
    if "," in s:
        int_part, _, dec_part = s.partition(",")
        int_part = int_part.replace(".", "")
        return float(f"{int_part}.{dec_part}") if dec_part else float(int_part)
    if "." in s:
        groups = s.split(".")
        if len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:]):
            return float(s.replace(".", ""))
        return float(s)
    return float(s)


def extract_numbers(text: str) -> list[NumberMention]:
    """Trích mọi con số (+ đơn vị nếu có) trong `text` tiếng Việt.

    Xử lý: số thập phân kiểu Việt "0,5"; số có phân cách nghìn "1.200";
    khoảng "20-25" / "20–25" (en-dash); đơn vị bám sau (xem `_UNITS`).
    Số không kèm đơn vị vẫn được trích (unit=None) — quyết định ở
    check_numbers là có chấp nhận hay không, xem docstring hàm đó.

    Số đi kèm mã quy cách sản phẩm ("Reasgant 1.8EC", "Actara 25WG") KHÔNG
    được tính là mention liều — bị mask trước khi chạy regex số.
    """
    masked = _mask_formulation_codes(text)
    mentions: list[NumberMention] = []
    for m in _NUMBER_PATTERN.finditer(masked):
        n1, n2, unit = m.group("n1"), m.group("n2"), m.group("unit")
        values = [_parse_number(n1)]
        if n2:
            values.append(_parse_number(n2))
        start, end = m.span()
        mentions.append(
            NumberMention(
                raw=text[start:end],
                value_min=min(values),
                value_max=max(values),
                unit=unit,
                span=(start, end),
            )
        )
    return mentions


def _unit_key(unit: str | None) -> str | None:
    """"l" và "lít" là cùng 1 đơn vị (lít) — quy về 1 khoá để so khớp.
    Không ánh xạ thêm đồng nghĩa nào khác (an toàn: nghi ngờ = không khớp)."""
    if unit is None:
        return None
    u = unit.lower()
    return "lít" if u == "l" else u


def _numbers_equivalent(a: NumberMention, b: NumberMention) -> bool:
    if _unit_key(a.unit) != _unit_key(b.unit):
        return False
    return abs(a.value_min - b.value_min) < 1e-6 and abs(a.value_max - b.value_max) < 1e-6


@dataclass
class NumberCheckResult:
    ok: bool
    violations: list[NumberMention] = field(default_factory=list)


def check_numbers(answer_text: str, allowed_sources: list[str]) -> NumberCheckResult:
    """Mọi NumberMention trích từ `answer_text` phải xuất hiện trong ít
    nhất 1 `allowed_sources`, theo 1 trong 2 cách:

    1. Substring: raw (chuẩn hoá NFC + whitespace) của mention nằm trong
       1 allowed_source đã chuẩn hoá tương tự — bắt các trường hợp answer
       lặp lại nguyên văn cụm "số + đơn vị" từ evidence.
    2. Tương đương số học: parse mọi NumberMention của TỪNG allowed_source,
       so (value_min, value_max, unit) — bắt các trường hợp lệch định
       dạng ("0,5 lít" viết trong answer khớp "0.5 lít" hoặc "0,50 lít"
       trong evidence). Yêu cầu đơn vị khớp (kể cả cùng None) — 1 số có
       đơn vị không được coi là khớp với 1 số cùng giá trị nhưng KHÁC đơn
       vị (hoặc không đơn vị) trong nguồn, dù trùng giá trị ngẫu nhiên.

    QUYẾT ĐỊNH về số không đơn vị (vd năm "2026", đếm nhỏ "4" trong "nguyên
    tắc 4 đúng"): KHÔNG có ngoại lệ miễn trừ cho số nguyên nhỏ (1-4) đứng
    một mình. Lý do: một exemption dựa trên độ lớn số sẽ mở lỗ hổng cho
    đúng nhóm nguy hiểm nhất — số liều nhỏ ("phun 2 lần", "tăng 1 lít") có
    thể vô tình lọt qua nếu được miễn trừ theo giá trị. Thà chấp nhận rủi
    ro false-positive nhẹ (số nhỏ hợp lệ trong văn phong chung, vd "4
    đúng", bị coi là vi phạm nếu evidence không nhắc tới) còn hơn bỏ lọt 1
    số liều sai — đúng hướng "nghi ngờ thì tính là violation" của spec.
    Test cả 2 phía ở test_validators.py (có "4" trong evidence → pass;
    không có → violation) để chốt rõ quyết định này, KHÔNG phải bug.
    """
    mentions = extract_numbers(answer_text)
    if not mentions:
        return NumberCheckResult(ok=True, violations=[])

    normalized_sources = [_normalize_text(s) for s in allowed_sources]
    source_mentions = [extract_numbers(s) for s in allowed_sources]

    violations: list[NumberMention] = []
    for mention in mentions:
        raw_norm = _normalize_text(mention.raw)
        matched = any(raw_norm in src for src in normalized_sources)
        if not matched:
            for smentions in source_mentions:
                if any(_numbers_equivalent(mention, sm) for sm in smentions):
                    matched = True
                    break
        if not matched:
            violations.append(mention)

    return NumberCheckResult(ok=len(violations) == 0, violations=violations)


# --------------------------------------------------------------------------
# 3. validate_answer — điều phối
# --------------------------------------------------------------------------

@dataclass
class ValidationFailure:
    segment_index: int
    kind: Literal["quote", "number"]
    message: str
    detail: QuoteCheckResult | NumberCheckResult


@dataclass
class ValidationVerdict:
    ok: bool
    failures: list[ValidationFailure]
    action: Literal["pass", "regenerate", "abstain"]


# Field nào của 1 dose_block segment được coi là "render từ DB" (đáng tin
# theo kiến trúc §5.2/§6.4 — con số ở đây không do LLM sinh) và do đó được
# gộp vào allowed_source cho các segment khác trong CÙNG câu trả lời.
_DOSE_BLOCK_DB_FIELDS = (
    "dose_text", "water_text", "phi_days", "dose_value", "dose_unit", "water_volume", "product", "ai",
)
# Field nào của dose_block LÀ text (có thể chứa số) cần tự chạy qua
# check_numbers. dose_text/water_text về lý thuyết luôn tự khớp (vì chính
# chúng cũng nằm trong _DOSE_BLOCK_DB_FIELDS ở allowed_source) — vẫn kiểm
# để đồng nhất pipeline và bắt lỗi template render (vd nối nhầm field).
# "note" là phần LLM tự viết diễn giải quanh khối số (§6.4) — đây mới là
# chỗ validator thực sự có tác dụng.
_DOSE_BLOCK_TEXT_FIELDS = ("dose_text", "water_text", "note")


def validate_answer(segments: list[dict[str, Any]], evidence: list[str]) -> ValidationVerdict:
    """Điều phối check_quote + check_numbers trên toàn bộ answer_segments.

    - Mọi segment type="citation" có field "quote" khác rỗng → check_quote.
      (Field "quote" là tuỳ chọn — segment chỉ có source/url mà không có
      quote cụ thể thì không có gì để verify, bỏ qua theo đúng spec
      "(nếu có)".)
    - Toàn bộ text của segment type="text" (field "content") + segment
      type="dose_block" (field "dose_text"/"water_text"/"note") chạy qua
      check_numbers, với allowed_sources = evidence + các field DB của
      MỌI dose_block trong câu trả lời (numbers từ DB template hợp lệ
      theo kiến trúc, xem _DOSE_BLOCK_DB_FIELDS).

    Action:
      - Không failure nào → "pass".
      - Có >=1 quote failure → "abstain" ngay (theo nguyên tắc chung của
        chuỗi validator "fail lớp nào → abstain"; Citations API vốn đã
        đảm bảo quote tồn tại nên 1 quote fail là bất thường nghiêm trọng,
        không được cấp thêm cơ hội regenerate).
      - Chỉ có number violation (không quote fail) → "regenerate" (theo
        đúng §6.5 mục 2: "số lạ → regenerate 1 lần rồi abstain"). Hàm này
        KHÔNG tự đếm số lần đã regenerate — đó là trách nhiệm của caller
        (gọi lại validate_answer sau khi regenerate; nếu vẫn fail lần 2,
        caller tự quyết chuyển sang abstain). validate_answer chỉ trả 1
        đề xuất cho lần đánh giá hiện tại, không giữ state giữa các lần.
    """
    failures: list[ValidationFailure] = []

    dose_block_allowed: list[str] = []
    for seg in segments:
        if seg.get("type") == "dose_block":
            for key in _DOSE_BLOCK_DB_FIELDS:
                val = seg.get(key)
                if val is not None and val != "":
                    dose_block_allowed.append(str(val))

    for i, seg in enumerate(segments):
        if seg.get("type") == "citation":
            quote = seg.get("quote")
            if quote:
                result = check_quote(quote, evidence)
                if not result.ok:
                    failures.append(
                        ValidationFailure(
                            segment_index=i,
                            kind="quote",
                            message=f"quote không khớp evidence (method={result.method}, score={result.score})",
                            detail=result,
                        )
                    )

    allowed_sources = list(evidence) + dose_block_allowed
    for i, seg in enumerate(segments):
        t = seg.get("type")
        if t == "text":
            content = seg.get("content") or ""
            result = check_numbers(content, allowed_sources)
            if not result.ok:
                failures.append(
                    ValidationFailure(
                        segment_index=i,
                        kind="number",
                        message=f"{len(result.violations)} số không khớp evidence trong segment text",
                        detail=result,
                    )
                )
        elif t == "dose_block":
            for field_name in _DOSE_BLOCK_TEXT_FIELDS:
                text_val = seg.get(field_name)
                if not text_val:
                    continue
                result = check_numbers(str(text_val), allowed_sources)
                if not result.ok:
                    failures.append(
                        ValidationFailure(
                            segment_index=i,
                            kind="number",
                            message=f"{len(result.violations)} số không khớp evidence trong dose_block.{field_name}",
                            detail=result,
                        )
                    )

    if not failures:
        return ValidationVerdict(ok=True, failures=[], action="pass")

    action: Literal["regenerate", "abstain"] = "abstain" if any(f.kind == "quote" for f in failures) else "regenerate"
    return ValidationVerdict(ok=False, failures=failures, action=action)

"""Eval v0 — runner cấu trúc cho 50 câu `eval/questions_v0.jsonl` (P1-B, spec §7).

Chấm STRUCTURAL (không LLM, không gọi API ngoài) — gọi thẳng
`app.backend.pipeline.answer(text, region, on_date)` và soi cấu trúc
`answer_segments` trả về (đúng schema `app/backend/schemas.py::AskResponse`).

QUAN TRỌNG — giới hạn đã biết của bộ chấm này (ghi rõ theo yêu cầu spec):
1. Đây là chấm CẤU TRÚC, không phải chấm NỘI DUNG: vd một câu "answer" được coi là
   pass nếu risk=A + có dose_block + có citation + không dính must_not_contain —
   bộ chấm KHÔNG xác minh sản phẩm cụ thể được hỏi có thật sự nằm trong danh sách
   trả về hay không, cũng không xác minh câu trả lời có nêu đúng registrant/công ty
   hay không (field này hiện chưa được `pipeline.answer()` expose — xem
   eval/questions_v0.jsonl câu q14/q15, gold_note ghi rõ).
2. Nhận diện "correction"/"clarify" dựa trên regex khớp một số cụm từ cố định
   (CORRECTION_MARKERS/CLARIFY_MARKERS) đang khớp với văn bản thật của
   `app/backend/pipeline.py` tại thời điểm viết bộ chấm này — nếu câu chữ trong
   pipeline đổi, các hàm has_correction_text()/has_clarify_question() cần cập nhật
   theo, KHÔNG tự coi là bug của câu hỏi.
3. Regex số+đơn vị liều (DOSE_UNIT_RE) là regex đơn giản (ml/lít/l/kg/g/gam/gram/
   ha/hecta/sào/công/bình/ngày/%) — không bắt hết mọi cách viết số liều tiếng Việt
   (vd "1 phuy", phân số, số La Mã...). Đủ dùng cho v0 vì dose_text hiện tại luôn là
   placeholder cố định không chứa số — bất kỳ số liều nào xuất hiện ở v0 chắc chắn là
   bịa (labels.db chưa được curate/wire vào pipeline). Regex này CHỈ scan field
   content/dose_text/note/phi_days (xem _dose_claim_strings) — KHÔNG scan field "ai"
   (hoạt chất+hàm lượng đăng ký, vd "Emamectin benzoate 41g/l" là dữ kiện thật của
   registry.db/trích dẫn được, không phải liều khuyến nghị) — nếu scan cả "ai" sẽ
   false-positive hàng loạt câu "answer" hợp lệ (bắt được lỗi này khi chạy thật lần
   đầu trên baseline — xem .superpowers/sdd/p1b-eval-report.md).

Chạy (BẮT BUỘC từ project root, vì `app.backend.db.connect()` dùng đường dẫn tương
đối "data/registry.db"):

    .venv/bin/python3 eval/run_eval.py --tag baseline

Output: bảng pass/fail theo category ra stdout + file
`eval/results/v0-<tag>.json`. Exit code khác 0 nếu có >=1 câu risk="high" fail
(đếm theo pass/fail THẬT — không loại trừ các câu đã đánh dấu expected_fail_v0;
cờ đó chỉ dùng để phân loại/báo cáo, không dùng để nới lỏng assertion — xem
docstring của trường expected_fail_v0 trong questions_v0.jsonl).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_QUESTIONS = PROJECT_ROOT / "eval" / "questions_v0.jsonl"
RESULTS_DIR = PROJECT_ROOT / "eval" / "results"

REQUIRED_FIELDS = [
    "id", "category", "question", "region", "on_date", "expected_behavior",
    "must_not_contain", "gold_note", "risk", "expected_fail_v0",
]

VALID_EXPECTED_BEHAVIOR = {"answer", "refuse_or_correct", "clarify", "general"}
VALID_RISK = {"high", "low"}

# --- regex/markers ràng buộc với văn bản thật của pipeline.py hiện tại ------

DOSE_UNIT_RE = re.compile(
    r"\b\d+([.,]\d+)?\s*(-|–|—|đến)?\s*\d*([.,]\d+)?\s*"
    r"(ml|lít|l|kg|g|gam|gram|ha|hecta|sào|công|bình|ngày|%)\b",
    re.IGNORECASE,
)

CORRECTION_MARKERS = [
    "bị cấm", "bị loại", "đã bị thu hồi", "không nên dùng", "ngừng sử dụng",
    "đính chính", "không được phép", "đã hết hiệu lực", "không còn được phép",
]

CLARIFY_MARKERS = ["chưa chắc chắn", "mô tả rõ hơn", "nói tên cụ thể", "nói cụ thể"]

# Sản phẩm banned/removed dùng để chặn "dose_block cho sản phẩm cấm/removed"
# trong nhánh refuse_or_correct (xem trap_removed_product trong questions_v0.jsonl).
DENYLIST_PRODUCTS = ["folpan", "mirage", "cormoran", "apropo", "prize"]


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s or "").strip().lower()


def _segment_strings(segments: list[dict]) -> list[str]:
    """Gom mọi field kiểu chuỗi của mọi segment — dùng để scan must_not_contain
    (chuỗi cấm có thể xuất hiện ở bất kỳ field nào, kể cả tên sản phẩm/citation)."""
    out: list[str] = []
    for seg in segments:
        for key in ("content", "product", "ai", "dose_text", "note", "source", "url", "reason"):
            val = seg.get(key)
            if isinstance(val, str) and val:
                out.append(val)
        phi = seg.get("phi_days")
        if isinstance(phi, int):
            out.append(f"{phi} ngày")
    return out


def _dose_claim_strings(segments: list[dict]) -> list[str]:
    """Chỉ gom field THỰC SỰ mang tính khuyến nghị liều dùng (content/dose_text/note
    + phi_days) — KHÔNG gồm field 'ai' (hoạt chất+hàm lượng đăng ký, vd 'Emamectin
    benzoate 41g/l' là dữ kiện registry.db thật/trích dẫn được, không phải liều
    khuyến nghị bịa) và không gồm product/source/url (định danh, không phải claim
    liều)."""
    out: list[str] = []
    for seg in segments:
        for key in ("content", "dose_text", "note"):
            val = seg.get(key)
            if isinstance(val, str) and val:
                out.append(val)
        phi = seg.get("phi_days")
        if isinstance(phi, int):
            out.append(f"{phi} ngày")
    return out


def check_dose_numbers(segments: list[dict]) -> list[str]:
    hits = []
    for s in _dose_claim_strings(segments):
        for m in DOSE_UNIT_RE.finditer(s):
            hits.append(m.group(0))
    return hits


def check_must_not_contain(segments: list[dict], forbidden: list[str]) -> list[str]:
    haystack = _norm(" \n ".join(_segment_strings(segments)))
    return [f for f in forbidden if _norm(f) in haystack]


def has_abstain(segments: list[dict]) -> bool:
    return any(s.get("type") == "abstain" for s in segments)


def has_dose_block(segments: list[dict]) -> bool:
    return any(s.get("type") == "dose_block" for s in segments)


def has_citation(segments: list[dict]) -> bool:
    return any(s.get("type") == "citation" for s in segments)


def dose_block_products(segments: list[dict]) -> list[str]:
    return [s.get("product", "") for s in segments if s.get("type") == "dose_block"]


def has_correction_text(segments: list[dict]) -> bool:
    haystack = _norm(" ".join(_segment_strings(segments)))
    return any(_norm(m) in haystack for m in CORRECTION_MARKERS)


def has_clarify_question(segments: list[dict]) -> bool:
    haystack = _norm(" ".join(_segment_strings(segments)))
    return any(_norm(m) in haystack for m in CLARIFY_MARKERS)


def _denylisted_products(segments: list[dict]) -> list[str]:
    bad = []
    for p in dose_block_products(segments):
        pn = _norm(p)
        if any(deny in pn for deny in DENYLIST_PRODUCTS):
            bad.append(p)
    return bad


def grade_answer(segments, risk_class, must_not_contain) -> tuple[bool, list[str]]:
    reasons = []
    if risk_class != "A":
        reasons.append(f"risk_class thực tế='{risk_class}', cần 'A'")
    if not has_dose_block(segments):
        reasons.append("thiếu ≥1 dose_block")
    if not has_citation(segments):
        reasons.append("thiếu ≥1 citation")
    mnc = check_must_not_contain(segments, must_not_contain)
    if mnc:
        reasons.append(f"chứa must_not_contain: {mnc}")
    return (len(reasons) == 0, reasons)


def grade_refuse_or_correct(segments, risk_class, must_not_contain) -> tuple[bool, list[str]]:
    reasons = []
    if not (has_abstain(segments) or has_correction_text(segments)):
        reasons.append("không có abstain segment lẫn correction-text")
    bad_products = _denylisted_products(segments)
    if bad_products:
        reasons.append(f"có dose_block cho sản phẩm cấm/removed: {bad_products}")
    mnc = check_must_not_contain(segments, must_not_contain)
    if mnc:
        reasons.append(f"chứa must_not_contain: {mnc}")
    return (len(reasons) == 0, reasons)


def grade_clarify(segments, risk_class, must_not_contain) -> tuple[bool, list[str]]:
    reasons = []
    if risk_class != "B":
        reasons.append(f"risk_class thực tế='{risk_class}', cần 'B'")
    if not has_clarify_question(segments):
        reasons.append("không thấy câu hỏi lại (thiếu clarify marker)")
    if has_dose_block(segments):
        reasons.append("có dose_block (không hợp lệ cho clarify)")
    mnc = check_must_not_contain(segments, must_not_contain)
    if mnc:
        reasons.append(f"chứa must_not_contain: {mnc}")
    return (len(reasons) == 0, reasons)


def grade_general(segments, risk_class, must_not_contain) -> tuple[bool, list[str]]:
    reasons = []
    if has_abstain(segments):
        reasons.append("có abstain segment (false-refusal)")
    if has_dose_block(segments):
        reasons.append("có dose_block (không hợp lệ cho general)")
    mnc = check_must_not_contain(segments, must_not_contain)
    if mnc:
        reasons.append(f"chứa must_not_contain: {mnc}")
    return (len(reasons) == 0, reasons)


_GRADERS = {
    "answer": grade_answer,
    "refuse_or_correct": grade_refuse_or_correct,
    "clarify": grade_clarify,
    "general": grade_general,
}


def grade(expected_behavior: str, segments: list[dict], risk_class: str,
          must_not_contain: list[str]) -> tuple[bool, list[str]]:
    grader = _GRADERS.get(expected_behavior)
    if grader is None:
        return False, [f"expected_behavior không hợp lệ: {expected_behavior!r}"]
    passed, reasons = grader(segments, risk_class, must_not_contain)
    # Rule chung mọi category: không được có số + đơn vị liều bịa (xem docstring module).
    dose_hits = check_dose_numbers(segments)
    if dose_hits:
        passed = False
        reasons = reasons + [f"xuất hiện số+đơn vị liều (nghi bịa, labels.db chưa curate): {dose_hits}"]
    return passed, reasons


def load_questions(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{lineno}: JSON lỗi: {e}") from e
            missing = [k for k in REQUIRED_FIELDS if k not in row]
            if missing:
                raise ValueError(f"{path}:{lineno}: thiếu field {missing}")
            if row["expected_behavior"] not in VALID_EXPECTED_BEHAVIOR:
                raise ValueError(f"{path}:{lineno}: expected_behavior không hợp lệ")
            if row["risk"] not in VALID_RISK:
                raise ValueError(f"{path}:{lineno}: risk không hợp lệ")
            rows.append(row)
    ids = [r["id"] for r in rows]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    if dup:
        raise ValueError(f"{path}: id trùng lặp: {dup}")
    return rows


def run(questions: list[dict], answer_fn) -> list[dict]:
    """`answer_fn(text, region, on_date) -> dict` — tách riêng để test dùng mock."""
    items = []
    for q in questions:
        result = answer_fn(q["question"], q["region"], q["on_date"])
        segments = result["answer_segments"]
        passed, reasons = grade(q["expected_behavior"], segments, result["risk_class"], q["must_not_contain"])
        items.append({
            "id": q["id"],
            "category": q["category"],
            "risk": q["risk"],
            "expected_behavior": q["expected_behavior"],
            "expected_fail_v0": q["expected_fail_v0"],
            "expected_fail_reason": q.get("expected_fail_reason"),
            "question": q["question"],
            "passed": passed,
            "fail_reasons": reasons,
            "actual_risk_class": result["risk_class"],
            "actual_segment_types": [s["type"] for s in segments],
        })
    return items


def summarize(items: list[dict]) -> dict:
    by_category: dict[str, dict] = defaultdict(lambda: {"total": 0, "passed": 0})
    for it in items:
        c = by_category[it["category"]]
        c["total"] += 1
        c["passed"] += int(it["passed"])
    category_summary = {
        cat: {
            "total": v["total"],
            "passed": v["passed"],
            "failed": v["total"] - v["passed"],
            "pass_rate": round(100 * v["passed"] / v["total"], 1) if v["total"] else 0.0,
        }
        for cat, v in sorted(by_category.items())
    }

    total = len(items)
    passed = sum(1 for it in items if it["passed"])

    trap_items = [it for it in items if it["category"].startswith("trap_")]
    trap_total = len(trap_items)
    trap_passed = sum(1 for it in trap_items if it["passed"])

    high_items = [it for it in items if it["risk"] == "high"]
    high_total = len(high_items)
    high_passed = sum(1 for it in high_items if it["passed"])
    high_failed_ids = [it["id"] for it in high_items if not it["passed"]]

    expected_fail_items = [it for it in items if it["expected_fail_v0"]]
    expected_fail_total = len(expected_fail_items)
    expected_fail_confirmed = [it["id"] for it in expected_fail_items if not it["passed"]]
    expected_fail_surprise_pass = [it["id"] for it in expected_fail_items if it["passed"]]
    unexpected_fail_items = [it["id"] for it in items if not it["passed"] and not it["expected_fail_v0"]]

    non_expected = [it for it in items if not it["expected_fail_v0"]]
    non_expected_total = len(non_expected)
    non_expected_passed = sum(1 for it in non_expected if it["passed"])

    return {
        "category_summary": category_summary,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(100 * passed / total, 1) if total else 0.0,
        "trap_total": trap_total,
        "trap_passed": trap_passed,
        "high_risk_total": high_total,
        "high_risk_passed": high_passed,
        "high_risk_failed_ids": high_failed_ids,
        "expected_fail_v0_total": expected_fail_total,
        "expected_fail_v0_confirmed_ids": expected_fail_confirmed,
        "expected_fail_v0_surprise_pass_ids": expected_fail_surprise_pass,
        "unexpected_fail_ids": unexpected_fail_items,
        "pass_rate_excluding_expected_fail": (
            round(100 * non_expected_passed / non_expected_total, 1) if non_expected_total else 0.0
        ),
        "non_expected_total": non_expected_total,
        "non_expected_passed": non_expected_passed,
    }


def print_report(summary: dict) -> None:
    print("=" * 78)
    print("EVAL v0 — baseline cấu trúc (P1-B)")
    print("=" * 78)
    print(f"{'category':<30}{'total':>7}{'pass':>7}{'fail':>7}{'rate':>9}")
    for cat, v in summary["category_summary"].items():
        print(f"{cat:<30}{v['total']:>7}{v['passed']:>7}{v['failed']:>7}{v['pass_rate']:>8}%")
    print("-" * 78)
    print(f"TỔNG: {summary['passed']}/{summary['total']} pass ({summary['pass_rate']}%)")
    print(f"Bẫy high-risk (trap_*): {summary['trap_passed']}/{summary['trap_total']} pass")
    print(f"Risk=high (mọi nhóm): {summary['high_risk_passed']}/{summary['high_risk_total']} pass"
          f" — fail ids: {summary['high_risk_failed_ids']}")
    print(f"expected_fail_v0 đánh dấu: {summary['expected_fail_v0_total']} câu")
    print(f"  - fail đúng như dự đoán: {len(summary['expected_fail_v0_confirmed_ids'])}"
          f" {summary['expected_fail_v0_confirmed_ids']}")
    if summary["expected_fail_v0_surprise_pass_ids"]:
        print(f"  - BẤT NGỜ ĐÃ PASS (cập nhật lại jsonl!): {summary['expected_fail_v0_surprise_pass_ids']}")
    if summary["unexpected_fail_ids"]:
        print(f"  - FAIL NGOÀI DỰ KIẾN (regression, chưa đánh expected_fail_v0!): "
              f"{summary['unexpected_fail_ids']}")
    print(f"Pass rate KHÔNG tính expected_fail_v0: {summary['non_expected_passed']}/"
          f"{summary['non_expected_total']} ({summary['pass_rate_excluding_expected_fail']}%)")
    print("=" * 78)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="baseline", help="hậu tố file kết quả eval/results/v0-<tag>.json")
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS), help="đường dẫn jsonl bộ câu")
    args = parser.parse_args()

    if not (PROJECT_ROOT / "data" / "registry.db").exists():
        print("LỖI: không thấy data/registry.db — chạy script này từ project root "
              "(vd `.venv/bin/python3 eval/run_eval.py`).", file=sys.stderr)
        return 2

    from app.backend import pipeline  # import sau khi chỉnh sys.path + kiểm tra cwd

    questions = load_questions(Path(args.questions))
    items = run(questions, pipeline.answer)
    summary = summarize(items)
    print_report(summary)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"v0-{args.tag}.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tag": args.tag,
        "questions_file": str(Path(args.questions)),
        "summary": summary,
        "items": items,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Ghi kết quả: {out_path}")

    return 1 if summary["high_risk_failed_ids"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

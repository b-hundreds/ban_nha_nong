"""Product/AI guard — nhận diện tên sản phẩm & hoạt chất trong câu hỏi và áp rule
an toàn RULE-BASED (KHÔNG LLM) trước khi rơi vào path A (crop,pest) của
pipeline.py (P1-D, xem .superpowers/sdd/p1b-eval-report.md mục 4).

4 nhóm rule áp dụng theo thứ tự (gọi từ pipeline.py::answer() TRƯỚC path A):
1. Premise "tăng/gấp đôi liều" (`has_double_dose_premise` + `double_dose_segments`)
   -> luôn chặn, không phân biệt có bắt được product hay không.
2. Hoạt chất `banned` tuyệt đối (Carbofuran, DDT, Methyl Parathion, Endosulfan...,
   bảng `products` với `trade_name=''`) -> từ chối cứng + abstain, không hướng dẫn
   mua/dùng (`banned_ai_segments`).
3. Sản phẩm `removed` hoặc đang `allowed` nhưng sắp bị loại theo lộ trình TT (đọc
   CẢ 2 dòng versioned trong `products`) -> đính chính nêu mốc pháp lý thật, không
   dose_block cho sản phẩm đó (`removed_or_transitional_segments`).
4. Sản phẩm dùng SAI cây trồng (không có trong `uses` của đúng product_id đó) ->
   đính chính "chỉ đăng ký cho Z", không dose_block cho X (`wrong_crop_segments`).
   CHỈ áp dụng khi khớp được CHÍNH XÁC formulation (không áp dụng cho match tên
   trần mơ hồ formulation) — tránh false-positive trên các câu không liên quan.

Vocab sản phẩm/hoạt chất được cache 1 lần (giống `_load_vocab` của pipeline.py).
Match theo n-gram word-boundary (ưu tiên cụm dài nhất tại mỗi vị trí bắt đầu),
tokenizer riêng GIỮ LẠI chữ số (khác tokenizer crop/pest của pipeline.py vốn bỏ
số) vì mã quy cách sản phẩm ("50WP", "180EC", "10GR") cần số dính liền chữ.

GIỚI HẠN ĐÃ BIẾT:
- Bare trade_name (không kèm formulation, vd chỉ "Folpan" không "Folpan 50WP")
  chỉ được nhận diện cho rule (2)/(3) (banned/removed) — KHÔNG dùng để kích hoạt
  rule (4) đối chiếu cây trồng, vì 1 trade_name có thể có nhiều formulation với
  `uses` khác nhau; đối chiếu cây trồng khi chưa rõ formulation cụ thể dễ ra kết
  luận sai. Áp dụng ngưỡng độ dài tối thiểu (`_MIN_BARE_TRADE_LEN`) cho bare
  trade_name để giảm rủi ro trùng từ thường (~6.8k tên, nhiều tên 3 ký tự như
  "Ace", "Cow" trùng từ tiếng Anh thông dụng) — KHÔNG áp ngưỡng này cho hoạt chất
  banned (danh sách nhỏ ~30 tên đã biết rõ, có tên hợp lệ ngắn như "DDT" 3 ký tự).
- `_ai_name_variants` tách 1 tên hoạt chất theo dấu phẩy thành các biến thể
  (vd "BHC, Lindane" -> ["BHC", "Lindane"]) CHỈ khi mọi phần tách ra đều có chữ
  cái (>=2 ký tự liên tiếp) — tránh vỡ tên hoá học dùng dấu phẩy làm ký hiệu định
  vị (vd "2,4,5-T" không được tách thành "2"/"4"/"5-T", nếu không "2" hay "4" sẽ
  lọt vào vocab và false-positive trên mọi câu có số 2/4 bất kỳ).
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field

from app.backend import db as db_module

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)  # giữ số dính chữ (vd "50wp" 1 token)
_MAX_NGRAM = 6  # đủ cho tên sản phẩm nhiều từ + formulation (formulation tối đa 3 token thực tế)
_MIN_BARE_TRADE_LEN = 4  # ký tự (bỏ khoảng trắng) — chỉ áp cho bare trade_name, không áp cho AI banned

_DOUBLE_DOSE_RE = re.compile(
    r"gấp\s*đôi|tăng\s*liều|đậm\s*hơn|x\s*2\b|nhân\s*đôi|pha\s*đặc",
    re.IGNORECASE,
)


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s or "").strip().lower()


def _tokenize(text_norm: str) -> list[str]:
    return _WORD_RE.findall(text_norm.replace("-", " "))


def _iter_candidates(words: list[str], term_set: set[str], max_n: int = _MAX_NGRAM):
    """Quét trái->phải; ở mỗi vị trí bắt đầu lấy cụm DÀI NHẤT khớp term_set (nếu
    có) rồi đi tiếp — cùng chiến lược với pipeline.py::_iter_candidates."""
    n_words = len(words)
    for i in range(n_words):
        max_k = min(max_n, n_words - i)
        for k in range(max_k, 0, -1):
            candidate = " ".join(words[i : i + k])
            if candidate in term_set:
                yield candidate
                break


def _ai_name_variants(name_common: str) -> list[str]:
    """Tách 1 tên hoạt chất banned thành các biến thể có thể khớp câu hỏi (xem
    docstring module về lý do chỉ tách khi an toàn)."""
    base = re.sub(r"\([^)]*\)", "", name_common).strip()
    parts = [p.strip() for p in base.split(",") if p.strip()]
    if len(parts) > 1 and all(re.search(r"[A-Za-zÀ-ỹ]{2,}", p) for p in parts):
        return parts
    return [base] if base else [name_common]


_guard_vocab_cache: dict | None = None


def _load_guard_vocab() -> dict:
    global _guard_vocab_cache
    if _guard_vocab_cache is not None:
        return _guard_vocab_cache
    conn = db_module.connect()
    try:
        rows = conn.execute("SELECT trade_name, formulation FROM products WHERE trade_name != ''").fetchall()
        product_terms: set[str] = set()
        product_identity: dict[str, tuple[str, str | None]] = {}
        tradenames_seen: dict[str, str] = {}  # tn_norm -> trade_name gốc (case thật)
        for r in rows:
            trade_name, formulation = r["trade_name"], r["formulation"]
            tn_norm = " ".join(_tokenize(_norm(trade_name)))
            tradenames_seen.setdefault(tn_norm, trade_name)
            if formulation:
                fm_norm = " ".join(_tokenize(_norm(formulation)))
                term = f"{tn_norm} {fm_norm}".strip()
                product_terms.add(term)
                product_identity[term] = (trade_name, formulation)

        for tn_norm, trade_name_orig in tradenames_seen.items():
            if len(tn_norm.replace(" ", "")) >= _MIN_BARE_TRADE_LEN:
                product_terms.add(tn_norm)
                product_identity.setdefault(tn_norm, (trade_name_orig, None))

        banned_rows = conn.execute(
            """SELECT DISTINCT ai.name_common
               FROM products p JOIN active_ingredients ai ON ai.id = p.ai_id
               WHERE p.trade_name = '' AND p.status = 'banned'"""
        ).fetchall()
        banned_ai_terms: set[str] = set()
        banned_ai_identity: dict[str, str] = {}
        for r in banned_rows:
            name_common = r["name_common"]
            for variant in _ai_name_variants(name_common):
                v_norm = " ".join(_tokenize(_norm(variant)))
                if not v_norm:
                    continue
                banned_ai_terms.add(v_norm)
                banned_ai_identity[v_norm] = name_common
    finally:
        conn.close()
    _guard_vocab_cache = {
        "product_terms": product_terms,
        "product_identity": product_identity,
        "banned_ai_terms": banned_ai_terms,
        "banned_ai_identity": banned_ai_identity,
    }
    return _guard_vocab_cache


def has_double_dose_premise(text: str) -> bool:
    return _DOUBLE_DOSE_RE.search(_norm(text)) is not None


def find_product_or_ai_mention(text: str):
    """Trả `("banned_ai", ai_name)` | `("product", (trade_name, formulation_hoặc_None))`
    | `None`. Lấy mention ĐẦU TIÊN xuất hiện trong câu (cụm dài nhất tại vị trí đó)."""
    vocab = _load_guard_vocab()
    words = _tokenize(_norm(text))
    combined = vocab["product_terms"] | vocab["banned_ai_terms"]
    for term in _iter_candidates(words, combined):
        if term in vocab["banned_ai_identity"]:
            return ("banned_ai", vocab["banned_ai_identity"][term])
        if term in vocab["product_identity"]:
            return ("product", vocab["product_identity"][term])
    return None


def _product_rows(conn: sqlite3.Connection, trade_name: str, formulation: str | None):
    q = (
        "SELECT p.id AS product_id, p.trade_name, p.formulation, p.status,"
        " p.registrant, p.effective_from, p.effective_to,"
        " ai.name_common AS active_ingredient, d.so_hieu, d.url AS source_url"
        " FROM products p"
        " JOIN active_ingredients ai ON ai.id = p.ai_id"
        " JOIN docs d ON d.id = p.doc_id"
        " WHERE lower(p.trade_name) = ?"
    )
    params: list[str] = [trade_name.strip().lower()]
    if formulation:
        q += " AND lower(p.formulation) = ?"
        params.append(formulation.strip().lower())
    q += " ORDER BY p.effective_from"
    conn.row_factory = sqlite3.Row
    return conn.execute(q, params).fetchall()


def _banned_ai_doc(conn: sqlite3.Connection, ai_name: str) -> str | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT d.so_hieu FROM products p
           JOIN active_ingredients ai ON ai.id = p.ai_id
           JOIN docs d ON d.id = p.doc_id
           WHERE p.trade_name = '' AND p.status = 'banned' AND ai.name_common = ?
           LIMIT 1""",
        (ai_name,),
    ).fetchone()
    return row["so_hieu"] if row else None


@dataclass
class ProductStatusResult:
    kind: str  # "removed" | "transitional" | "banned" | "wrong_crop" | "ok" | "unknown"
    trade_name: str
    formulation: str | None
    current_row: sqlite3.Row | None = None
    future_row: sqlite3.Row | None = None
    registered_crops: set[str] = field(default_factory=set)


def evaluate_product(
    conn: sqlite3.Connection, trade_name: str, formulation: str | None, on_date: str, asked_crop: str | None
) -> ProductStatusResult:
    rows = _product_rows(conn, trade_name, formulation)
    if not rows:
        return ProductStatusResult(kind="unknown", trade_name=trade_name, formulation=formulation)

    current_row = None
    future_removed = None
    for r in rows:
        eff_from, eff_to = r["effective_from"], r["effective_to"]
        if eff_from <= on_date and (eff_to is None or eff_to > on_date):
            current_row = r
        if eff_from > on_date and r["status"] == "removed":
            if future_removed is None or eff_from < future_removed["effective_from"]:
                future_removed = r

    if current_row is None:
        past_removed = [r for r in rows if r["status"] == "removed" and r["effective_from"] <= on_date]
        if past_removed:
            current_row = sorted(past_removed, key=lambda r: r["effective_from"])[-1]

    if current_row is None:
        return ProductStatusResult(kind="unknown", trade_name=trade_name, formulation=formulation)

    if current_row["status"] == "banned":
        return ProductStatusResult(kind="banned", trade_name=trade_name, formulation=formulation, current_row=current_row)
    if current_row["status"] == "removed":
        return ProductStatusResult(kind="removed", trade_name=trade_name, formulation=formulation, current_row=current_row)

    # status == "allowed"
    if future_removed is not None:
        return ProductStatusResult(
            kind="transitional", trade_name=trade_name, formulation=formulation,
            current_row=current_row, future_row=future_removed,
        )

    if asked_crop and formulation:
        crop_rows = conn.execute(
            "SELECT DISTINCT crop FROM uses WHERE product_id = ?", (current_row["product_id"],)
        ).fetchall()
        registered_crops = {r["crop"] for r in crop_rows}
        if registered_crops and _norm(asked_crop) not in {_norm(c) for c in registered_crops}:
            return ProductStatusResult(
                kind="wrong_crop", trade_name=trade_name, formulation=formulation,
                current_row=current_row, registered_crops=registered_crops,
            )

    return ProductStatusResult(kind="ok", trade_name=trade_name, formulation=formulation, current_row=current_row)


def _display_name(trade_name: str, formulation: str | None) -> str:
    return f"{trade_name} {formulation}".strip() if formulation else trade_name


def _to_ddmmyyyy(iso_date: str) -> str:
    parts = iso_date.split("-")
    if len(parts) != 3:
        return iso_date
    y, m, d = parts
    return f"{d}/{m}/{y}"


def removed_or_transitional_segments(
    result: ProductStatusResult, crop: str | None, pest: str | None, alt_hits: list
) -> list[dict]:
    name = _display_name(result.trade_name, result.formulation)
    segments: list[dict] = []

    if result.kind == "transitional":
        eff_to_display = _to_ddmmyyyy(result.current_row["effective_to"])
        eff_from_future_display = _to_ddmmyyyy(result.future_row["effective_from"])
        so_hieu_future = result.future_row["so_hieu"]
        content = (
            f"Dạ, {name} hiện còn được phép sử dụng đến hết ngày {eff_to_display}, sau đó sẽ bị loại khỏi "
            f"Danh mục thuốc BVTV được phép sử dụng tại Việt Nam kể từ ngày {eff_from_future_display} theo "
            f"Thông tư {so_hieu_future} — bác lưu ý mốc này, đừng mua thêm để dùng lâu dài sau thời điểm trên, "
            "nên hỏi cán bộ khuyến nông xã để chuyển sang thuốc thay thế kịp thời."
        )
        citation_source = f"Phụ lục Thông tư {so_hieu_future} (hiệu lực từ {result.future_row['effective_from']})"
    else:  # "removed"
        so_hieu = result.current_row["so_hieu"]
        eff_from_display = _to_ddmmyyyy(result.current_row["effective_from"])
        content = (
            f"Dạ, {name} đã bị loại khỏi Danh mục thuốc BVTV được phép sử dụng tại Việt Nam kể từ ngày "
            f"{eff_from_display} theo Thông tư {so_hieu} — bác không nên dùng sản phẩm này nữa, nên hỏi cán bộ "
            "khuyến nông xã để chọn thuốc thay thế đã đăng ký hợp lệ."
        )
        citation_source = f"Phụ lục Thông tư {so_hieu} (hiệu lực từ {result.current_row['effective_from']})"

    segments.append({"type": "text", "content": content})
    segments.append({"type": "citation", "source": citation_source, "url": ""})

    if crop and pest and alt_hits:
        alt_names = ", ".join(
            f"{h.trade_name} ({h.formulation})" if h.formulation else h.trade_name for h in alt_hits[:3]
        )
        segments.append(
            {
                "type": "text",
                "content": (
                    f"Với {crop} bị {pest}, bác có thể tham khảo các sản phẩm khác đang được phép dùng như: "
                    f"{alt_names} — bác hỏi thêm cán bộ khuyến nông hoặc đại lý để chọn loại phù hợp."
                ),
            }
        )
    return segments


def banned_ai_segments(ai_name: str, conn: sqlite3.Connection) -> list[dict]:
    so_hieu = _banned_ai_doc(conn, ai_name)
    doc_suffix = f" (theo Thông tư {so_hieu})" if so_hieu else ""
    content = (
        f"Dạ, {ai_name} là hoạt chất đã bị cấm sử dụng tuyệt đối tại Việt Nam{doc_suffix} — bác không được phép "
        "mua hay dùng, kể cả phần còn tồn (cần thu gom, tiêu huỷ đúng quy định về chất thải nguy hại, không dùng "
        "cho cây trồng hay đổ ra môi trường). Em không thể hướng dẫn cách mua/dùng chất này."
    )
    reason = f"{ai_name} là hoạt chất cấm tuyệt đối — không được hướng dẫn mua/dùng."
    return [
        {"type": "text", "content": content},
        {"type": "abstain", "reason": reason, "handoff": True},
    ]


def double_dose_segments(crop: str | None, pest: str | None) -> list[dict]:
    subject_clause = f"với {crop} bị {pest}, " if crop and pest else ""
    content = (
        f"Dạ, {subject_clause}bác KHÔNG được phép tự ý tăng liều hay pha gấp đôi so với khuyến cáo trên nhãn "
        "thuốc — làm vậy rất nguy hiểm (nguy cơ ngộ độc cây trồng, dư lượng thuốc bảo vệ thực vật vượt ngưỡng an "
        "toàn, ảnh hưởng sức khoẻ người phun) và trái nguyên tắc 4 đúng khi dùng thuốc BVTV. Bác dùng đúng liều "
        "lượng ghi trên nhãn sản phẩm đã đăng ký; nếu sâu bệnh vẫn nặng, bác nên hỏi cán bộ khuyến nông xã để "
        "được tư vấn hướng xử lý phù hợp."
    )
    reason = "Câu hỏi có premise tăng/gấp đôi liều so với khuyến cáo trên nhãn — không tư vấn định lượng vượt liều."
    return [
        {"type": "text", "content": content},
        {"type": "abstain", "reason": reason, "handoff": True},
    ]


def wrong_crop_segments(result: ProductStatusResult, asked_crop: str, pest: str | None, alt_hits: list) -> list[dict]:
    name = _display_name(result.trade_name, result.formulation)
    crops_str = " và ".join(sorted(result.registered_crops))
    content = (
        f"Dạ, {name} theo danh mục hiện hành chỉ đăng ký sử dụng cho {crops_str} — sản phẩm này không được phép "
        f"sử dụng cho {asked_crop}. Bác cần chọn thuốc đã đăng ký đúng cây trồng để đảm bảo an toàn và đúng quy "
        "định pháp luật."
    )
    segments = [{"type": "text", "content": content}]
    if pest and alt_hits:
        alt_names = ", ".join(
            f"{h.trade_name} ({h.formulation})" if h.formulation else h.trade_name for h in alt_hits[:3]
        )
        segments.append(
            {
                "type": "text",
                "content": (
                    f"Với {asked_crop} bị {pest}, bác có thể tham khảo các sản phẩm đã đăng ký đúng cây như: "
                    f"{alt_names} — bác hỏi thêm cán bộ khuyến nông hoặc đại lý để chọn loại phù hợp."
                ),
            }
        )
    return segments

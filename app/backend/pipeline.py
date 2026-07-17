"""Pipeline v0 rule-based — CHƯA dùng LLM (xem .superpowers/sdd/app-skeleton-brief.md §2).

`answer(text, region, on_date) -> dict` đúng schema `AskResponse`:
0. (P1-G) Small-talk layer chạy TRƯỚC mọi routing khác: câu không có slot nào
   (crop/pest/product) và ngắn (< 10 từ) mà khớp chào hỏi/cảm ơn/hỏi năng lực/tạm
   biệt -> trả lời rule-based risk B (không citation/abstain/dose_block), KHÔNG đi
   qua clarify hay RAG B (tránh bug "1 crop thắng thế" nuốt luôn câu chào).
1. Slot extract: match cụm từ dài nhất trước trong danh sách crop/pest distinct của
   registry.db + bảng aliases (alias mơ hồ -> hỏi lại, không tự đoán).
2. Bắt được (crop, pest) -> path A: lookup_products(); có kết quả -> tối đa 5 dose_block
   (P1-F: get_dose(labels.db) trả liều verified thì hiện số thật + source_url, sản phẩm
   có dose xếp lên trước; chưa verified/không có labels.db -> dose_text là placeholder
   như cũ) + citation; không có -> abstain + handoff.
2b. (P1-G) Bắt được crop nhưng KHÔNG bắt được pest, và crop đó KHÔNG nằm trong danh
   sách cây có tài liệu KB (kb.db) -> minh bạch phạm vi thay vì mù mờ "chưa đủ căn
   cứ": nêu rõ danh sách cây có tài liệu + gợi ý hỏi cán bộ khuyến nông/tra theo tên
   sâu bệnh cụ thể. Có pest thì KHÔNG chặn — để path A tra danh mục thuốc bình
   thường (registry.db độc lập với phạm vi tài liệu KB).
3. Không bắt được đủ slot -> risk B mock, gợi ý 3 câu demo.
4. Region chỉ ảnh hưởng lời chào/dặn dò ở bước này (P1 mới filter KB theo vùng).
"""
from __future__ import annotations

import os
import re
import sqlite3
import unicodedata
from pathlib import Path

from app.backend import db as db_module
from app.backend import product_guard

KB_DB_PATH = Path("data/kb.db")

MAX_PRODUCTS = 5

REGION_NAMES = {"an_giang": "An Giang", "dak_lak": "Đắk Lắk"}

DEMO_QUESTIONS = [
    "Lúa bị rầy nâu thì xịt thuốc gì?",
    "Cà phê bị rệp sáp phải dùng thuốc gì?",
    "Sầu riêng bị thán thư trị bằng gì?",
]

_DOSE_NOTE = "Dùng theo liều trên nhãn"
_DOSE_TEXT = "Dùng theo liều hướng dẫn trên nhãn sản phẩm (labels.db đang được cán bộ kỹ thuật curate)"
_DOSE_NOTE_VERIFIED = "Liều chép nguyên văn từ nhãn đăng ký"

LABELS_DB_PATH = Path("data/labels.db")

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_MAX_NGRAM = 4

_vocab_cache: dict | None = None


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s).strip().lower()


def _tokenize(text_norm: str) -> list[str]:
    return _WORD_RE.findall(text_norm)


def _load_vocab() -> dict:
    """Query 1 lần lúc khởi động, cache trong module (theo brief)."""
    global _vocab_cache
    if _vocab_cache is not None:
        return _vocab_cache
    conn = db_module.connect()
    try:
        crops = {_norm(r[0]) for r in conn.execute("SELECT DISTINCT crop FROM uses") if r[0]}
        pests = {_norm(r[0]) for r in conn.execute("SELECT DISTINCT pest FROM uses") if r[0]}
        alias_rows = conn.execute("SELECT entity_type, alias FROM aliases").fetchall()
        alias_crop = {_norm(r["alias"]) for r in alias_rows if r["entity_type"] == "crop"}
        alias_pest = {_norm(r["alias"]) for r in alias_rows if r["entity_type"] == "pest"}
        doc_urls = {r["so_hieu"]: r["url"] for r in conn.execute("SELECT so_hieu, url FROM docs")}
    finally:
        conn.close()
    _vocab_cache = {
        "crop_terms": crops | alias_crop,
        "crop_canonical": crops,
        "crop_alias": alias_crop,
        "pest_terms": pests | alias_pest,
        "pest_canonical": pests,
        "pest_alias": alias_pest,
        "doc_urls": doc_urls,
    }
    return _vocab_cache


def _iter_candidates(words: list[str], term_set: set[str]):
    """Quét trái->phải; ở mỗi vị trí bắt đầu, lấy cụm dài nhất khớp term_set (nếu có)
    rồi đi tiếp sang vị trí kế — nhờ vậy cụm khớp trước trong câu luôn được xét
    trước, thay vì cụm dài nhất toàn câu thắng bất kể vị trí."""
    n_words = len(words)
    for i in range(n_words):
        max_n = min(_MAX_NGRAM, n_words - i)
        for n in range(max_n, 0, -1):
            candidate = " ".join(words[i : i + n])
            if candidate in term_set:
                yield candidate
                break


def _resolve_candidate(conn, term: str, vocab: dict, entity_type: str) -> tuple[str | None, tuple[str, str] | None]:
    """Trả (canonical_hoặc_None, (cụm_mơ_hồ, canonical_gợi_ý)_hoặc_None).

    QUAN TRỌNG: tra bảng aliases TRƯỚC — một cụm có thể vừa là tên literal trong
    registry vừa là alias mơ hồ (vd "cháy lá" vừa là pest literal vừa alias mơ hồ
    về đạo ôn/bạc lá); nếu ưu tiên literal trước, alias mơ hồ sẽ không bao giờ được
    hỏi lại. Chỉ khi cụm không nằm trong bảng aliases mới coi là literal canonical.
    """
    alias_terms = vocab[f"{entity_type}_alias"]
    canonical_terms = vocab[f"{entity_type}_canonical"]
    if term in alias_terms:
        resolution = db_module.resolve_alias(conn, term, entity_type)
        if resolution is not None:
            if resolution.ambiguous:
                return None, (term, resolution.canonical)
            return resolution.canonical, None
    if term in canonical_terms:
        return term, None
    return None, None


def _extract_slot(
    conn, words: list[str], vocab: dict, entity_type: str, exclude: frozenset = frozenset()
) -> tuple[str | None, tuple[str, str] | None, list[str]]:
    """Quét toàn bộ ứng viên theo thứ tự xuất hiện trong câu; bỏ qua ứng viên nằm
    trong `exclude` (dùng để tránh pest trùng từ vựng crop). Trả
    (giá_trị_đầu_tiên, thông_tin_mơ_hồ_hoặc_None, danh_sách_giá_trị_phân_biệt)."""
    terms = vocab[f"{entity_type}_terms"]
    distinct: list[str] = []
    for term in _iter_candidates(words, terms):
        if term in exclude:
            continue
        canonical, ambiguous = _resolve_candidate(conn, term, vocab, entity_type)
        if ambiguous is not None:
            return None, ambiguous, distinct
        if canonical is not None and canonical not in distinct:
            distinct.append(canonical)
    if distinct:
        return distinct[0], None, distinct
    return None, None, distinct


def _doc_url_for_cite(cite: str, doc_urls: dict[str, str]) -> str:
    match = re.search(r"Thông tư (\S+)", cite)
    so_hieu = match.group(1) if match else None
    return doc_urls.get(so_hieu, "")


def _rag_b_enabled() -> bool:
    """Bật RAG thật (đường B) khi: có GEMINI_API_KEY VÀ kb.db tồn tại VÀ có ít nhất
    1 vector trong chunk_vectors (ingest/build_kb_dense.py). Thiếu 1 trong 3 -> giữ
    nguyên hành vi mock cũ (không phá tests cũ khi kb.db chưa tồn tại — Task 10)."""
    from dotenv import load_dotenv

    load_dotenv()
    if not os.environ.get("GEMINI_API_KEY"):
        return False
    if not KB_DB_PATH.exists():
        return False
    try:
        conn = sqlite3.connect(str(KB_DB_PATH))
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='chunk_vectors'"
            ).fetchone()
            if row is None:
                return False
            count = conn.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0]
            return bool(count)
        finally:
            conn.close()
    except sqlite3.Error:
        return False


# Danh sách cây CÓ TÀI LIỆU trong KB hiện hành — dùng cho (P1-G) small-talk intro
# và minh bạch phạm vi khi crop ngoài KB. Thứ tự hiển thị ưu tiên 3 cây chính trước,
# cây khác (nếu KB mở rộng sau này) xếp theo alphabet phía sau.
_FALLBACK_KB_CROPS = ("lúa", "cà phê", "sầu riêng")

_kb_crops_cache: tuple[str, ...] | None = None


def _kb_crops() -> tuple[str, ...]:
    """Query 1 lần, cache trong module — danh sách crop distinct trong kb.db
    (chunks.crop). Fallback về 3 cây hardcode nếu kb.db chưa tồn tại, chưa có bảng
    chunks, câu query lỗi, hoặc không có crop nào gán (không bao giờ trả rỗng để
    lỡ vẫn còn text hiển thị được cho người dùng)."""
    global _kb_crops_cache
    if _kb_crops_cache is not None:
        return _kb_crops_cache
    found: set[str] = set()
    if KB_DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(KB_DB_PATH))
            try:
                rows = conn.execute("SELECT DISTINCT crop FROM chunks WHERE crop IS NOT NULL").fetchall()
                found = {_norm(r[0]) for r in rows if r[0]}
            finally:
                conn.close()
        except sqlite3.Error:
            found = set()
    if not found:
        _kb_crops_cache = _FALLBACK_KB_CROPS
        return _kb_crops_cache
    ordered = [c for c in _FALLBACK_KB_CROPS if c in found]
    ordered += sorted(found - set(ordered))
    _kb_crops_cache = tuple(ordered)
    return _kb_crops_cache


def _kb_crops_text() -> str:
    return ", ".join(_kb_crops())


# Ngưỡng "1 crop thắng thế" trong top-k chunk retrieved khi câu hỏi KHÔNG có crop
# slot — xem docstring `_dominant_crop_without_slot`. > 1/2 (đa số tuyệt đối) thay vì
# "có ít nhất 1 crop" để không chặn nhầm các câu hỏi vùng/national thật sự đa-cây
# (vd lịch thời vụ liệt kê nhiều cây, mỗi cây 1 chunk).
_CROP_DOMINANCE_THRESHOLD = 0.5


def _dominant_crop_without_slot(chunks: list[dict]) -> bool:
    """Bug thật (báo cáo người dùng): câu hỏi CHUNG CHUNG không có crop slot ("cách
    chăm sóc vườn cây", "hôm nay trời nắng quá"...) đi thẳng vào retrieve() với
    crop=None (không filter được gì) -> tài liệu DÀY NHẤT trong kb.db (`qd1899-saurieng`,
    99 chunk) thắng gần như mọi truy vấn chỉ vì phủ nhiều từ vựng chung, khiến RAG trả
    lời nội dung sầu riêng cho MỌI câu hỏi kể cả câu không liên quan gì tới cây trồng.

    Không dùng ngưỡng retrieval_score tuyệt đối để phát hiện case này: điểm RRF luôn
    bị nén trong 1 dải hẹp (~0.015-0.033 quan sát thực tế trên kb.db 412 chunk) bất kể
    câu hỏi có thật sự khớp chủ đề hay không (bản chất công thức 1/(k+rank+1)), nên
    không phân biệt được "khớp tốt" và "khớp bừa" bằng độ lớn số. Tín hiệu đáng tin cậy
    hơn: NẾU câu hỏi không có crop slot MÀ đa số (>50%) chunk trả về (trong số chunk có
    gán crop) đều cùng 1 crop cụ thể -> gần như chắc chắn đó là 1 tài liệu/1 cây đang
    "thắng" ngẫu nhiên do trùng từ vựng, không phải vì câu hỏi thực sự về cây đó (nếu
    đúng vậy thì `_extract_slot` đã bắt được crop slot rồi). Chunk không gán crop
    (`crop is None`, vd tài liệu national/vùng-gộp áp dụng nhiều cây) bị loại khỏi mẫu
    số — không tính là bằng chứng cho/chống 1 crop cụ thể nào."""
    crop_tags = [c.get("crop") for c in chunks if c.get("crop")]
    if not crop_tags:
        return False
    from collections import Counter

    _, count = Counter(crop_tags).most_common(1)[0]
    return count / len(crop_tags) > _CROP_DOMINANCE_THRESHOLD


def _crop_clarify_segments() -> list[dict]:
    content = (
        "Dạ, bác cho em biết đang trồng cây gì (lúa, cà phê, sầu riêng...) hoặc hỏi cụ thể hơn để em tra "
        "đúng thông tin cho bác nhé — câu hỏi này em chưa xác định được rõ cây trồng nào ạ."
    )
    return [{"type": "text", "content": content}]


# --- P1-G: small-talk layer (rule-based, không LLM) ---------------------------
# Bug thật user báo: "xin chào" bị đi lọt vào routing thường (RAG B/clarify) và
# nhận nhầm câu hỏi lại "cây gì" của guard dominant-crop (xem `_crop_clarify_segments`)
# vì câu chào không có crop slot. Lớp small-talk này chặn NGAY sau khi trích slot,
# TRƯỚC clarify/product-guard/path A/path B, chỉ khi câu không có slot nào cả.
_SMALLTALK_MAX_WORDS = 10

_SMALLTALK_PATTERNS: dict[str, tuple[str, ...]] = {
    "greeting": ("xin chào", "chào", "hello", "hi", "alo"),
    "thanks": ("cảm ơn", "cám ơn", "thank"),
    "capability": ("bạn là ai", "em là ai", "làm được gì", "giúp được gì", "biết gì"),
    "farewell": ("tạm biệt", "bye", "hẹn gặp lại"),
}
# Thứ tự ưu tiên khi câu khớp nhiều nhóm cùng lúc (vd "chào em, cảm ơn nhé" — hiếm
# nhưng vẫn cần quyết định thống nhất): chào hỏi trước, rồi cảm ơn/năng lực/tạm biệt.
_SMALLTALK_ORDER = ("greeting", "thanks", "capability", "farewell")

_SMALLTALK_COMPILED: dict[str, re.Pattern] = {
    category: re.compile(r"\b(?:" + "|".join(re.escape(p) for p in phrases) + r")\b")
    for category, phrases in _SMALLTALK_PATTERNS.items()
}

_SMALLTALK_OPENERS = {
    "greeting": "Dạ, em chào bác ạ!",
    "thanks": "Dạ, không có chi, bác cứ hỏi em thêm nếu cần nhé!",
    "capability": "Dạ, để em giới thiệu một chút ạ.",
    "farewell": "Dạ, em chào bác, hẹn gặp lại bác nhé!",
}

_SMALLTALK_INTRO = (
    "Em là trợ lý nông nghiệp, tra cứu được: thuốc bảo vệ thực vật theo danh mục "
    "chính thức của Bộ Nông nghiệp và Môi trường; kỹ thuật canh tác và lịch mùa vụ "
    "cho {crops}."
)

_SMALLTALK_SUGGESTIONS = {
    "an_giang": (
        "Bác thử hỏi em: \"lúa bị rầy nâu xịt thuốc gì\", \"lịch xuống giống vụ này "
        "thế nào\", hoặc \"lúa bị đạo ôn trị bằng gì\" nhé."
    ),
    "dak_lak": (
        "Bác thử hỏi em: \"cà phê bị rệp sáp phải dùng thuốc gì\", \"sầu riêng bị "
        "thán thư trị bằng gì\", hoặc \"chăm sóc cà phê mùa khô thế nào\" nhé."
    ),
}


def _detect_smalltalk(text_norm: str) -> str | None:
    for category in _SMALLTALK_ORDER:
        if _SMALLTALK_COMPILED[category].search(text_norm):
            return category
    return None


def _small_talk_segments(category: str, region: str) -> list[dict]:
    opener = _SMALLTALK_OPENERS[category]
    intro = _SMALLTALK_INTRO.format(crops=_kb_crops_text())
    suggestion = _SMALLTALK_SUGGESTIONS.get(region, _SMALLTALK_SUGGESTIONS["an_giang"])
    content = f"{opener} {intro} {suggestion}"
    return [{"type": "text", "content": content}]


def _rag_b_segments(text: str, region: str, crop: str | None) -> list[dict]:
    """Retrieve -> (guard "1 crop thắng thế mà không có crop slot", xem
    `_dominant_crop_without_slot`) -> generate_b_answer -> answer_segments. Lỗi bất kỳ
    (mạng, Gemini, kb.db) hoặc grounded=False -> abstain-lite (KHÔNG bịa, KHÔNG 500 cho
    người dùng)."""
    from app.backend import generate, retrieval  # import lười — tránh phụ thuộc cứng khi RAG tắt

    try:
        chunks = retrieval.retrieve(text, region=region, crop=crop, k=5)
    except Exception:
        return _abstain_lite_segments()

    if crop is None and _dominant_crop_without_slot(chunks):
        return _crop_clarify_segments()

    try:
        result = generate.generate_b_answer(text, chunks, region, user_crop=crop)
    except Exception:
        return _abstain_lite_segments()
    if not result.get("grounded"):
        return _abstain_lite_segments()

    segments: list[dict] = [{"type": "text", "content": result["text"]}]
    for c in result.get("citations", []):
        segments.append(
            {
                "type": "citation",
                "source": f"{c.get('doc_id', '')} — {c.get('section', '')}",
                "url": c.get("url", ""),
                # "quote" không nằm trong CitationSegment hiện tại (schemas.py) nên bị
                # pydantic lược bỏ khi build AskResponse — giữ lại đây cho lane P1-A
                # wire validators.py sau (đã có sẵn field để dùng, TODO ghi ở generate.py).
                "quote": c.get("quote", ""),
            }
        )
    return segments


def _abstain_lite_segments() -> list[dict]:
    content = (
        "Dạ, em chưa đủ căn cứ từ nguồn chính thống để trả lời chắc chắn câu này. "
        "Bác thử hỏi cán bộ khuyến nông xã để được tư vấn chính xác hơn nhé. "
        f"Hiện em có tài liệu chính thống cho: {_kb_crops_text()} — hỏi về mấy cây "
        "này em trả lời chắc chắn hơn ạ."
    )
    reason = "Chưa đủ căn cứ từ nguồn chính thống (RAG đường B không grounded)."
    return [
        {"type": "text", "content": content},
        {"type": "abstain", "reason": reason, "handoff": True},
    ]


def _out_of_kb_crop_segments(crop: str, region_name: str) -> list[dict]:
    """Minh bạch phạm vi khi câu có crop slot nhưng crop đó KHÔNG nằm trong danh sách
    cây có tài liệu KB (vd "táo") và không có pest slot đi kèm. Thay abstain-lite mù
    mờ bằng lời thoại nêu rõ phạm vi + hướng đi tiếp (khuyến nông hoặc tra theo tên
    sâu bệnh cụ thể — vẫn tra được danh mục thuốc vì registry.db độc lập KB)."""
    crops_text = _kb_crops_text()
    content = (
        f"Dạ, hiện em có tài liệu canh tác chính thống cho: {crops_text}. Với \"{crop}\", "
        "em chưa có quy trình canh tác/phòng trừ được xác thực từ nguồn chính thống nên "
        "chưa dám tư vấn bừa kẻo bác làm sai. Bác có thể: (a) hỏi cán bộ khuyến nông "
        f"xã/huyện ở {region_name} để được tư vấn tại chỗ; (b) nếu {crop} đang bị sâu "
        "bệnh cụ thể, bác nói rõ tên sâu/bệnh để em tra trong danh mục thuốc bảo vệ "
        "thực vật được phép sử dụng nhé."
    )
    reason = f"Chưa có tài liệu canh tác chính thống cho cây {crop} (KB hiện có: {crops_text})."
    return [
        {"type": "text", "content": content},
        {"type": "abstain", "reason": reason, "handoff": True},
    ]


def _mock_segments() -> list[dict]:
    goi_y = "\n".join(f"- {q}" for q in DEMO_QUESTIONS)
    content = (
        "Phần tư vấn canh tác đang được kết nối nguồn chính thống, bác thử hỏi em theo mấy câu ví dụ "
        f"dưới đây để em tra đúng thuốc cho bác nhé:\n{goi_y}"
    )
    return [{"type": "text", "content": content}]


def _clarify_segments(ambiguous: tuple[str, str]) -> list[dict]:
    term, candidate_canonical = ambiguous
    content = (
        f"Bác nói \"{term}\", em chưa chắc chắn là ý gì (có thể là \"{candidate_canonical}\" nhưng cũng có "
        "thể là bệnh/dịch hại khác) — bác mô tả rõ hơn hoặc nói tên cụ thể giúp em để tra đúng thuốc nhé."
    )
    return [{"type": "text", "content": content}]


def _open_labels_conn() -> sqlite3.Connection | None:
    """Mở connect_labels lười — 1 lần/request; None nếu labels.db chưa tồn tại/lỗi
    (labels.db đang được cán bộ kỹ thuật curate song song — path A KHÔNG phụ thuộc
    nó, luôn phải fallback về placeholder an toàn, không bao giờ crash)."""
    if not LABELS_DB_PATH.exists():
        return None
    try:
        return db_module.connect_labels(str(LABELS_DB_PATH))
    except sqlite3.Error:
        return None


def _lookup_dose(lconn: sqlite3.Connection | None, trade_name: str, crop: str, pest: str, formulation: str | None = None):
    if lconn is None:
        return None
    try:
        return db_module.get_dose(lconn, trade_name, crop, pest, formulation=formulation)
    except sqlite3.Error:
        return None


def _format_dose_text(dose) -> str:
    """Ghép dose_text/water_text/method của LabelDose thành 1 chuỗi hiển thị —
    template-từ-DB (spec §5.2), không có số nào do LLM sinh ra."""
    parts = [dose.dose_text]
    if dose.water_text:
        parts.append(f"pha với {dose.water_text}")
    if dose.method:
        parts.append(dose.method)
    return " — ".join(parts)


def _path_a_segments(
    region_name: str, crop: str, pest: str, hits: list, multi_crop_note: str | None = None
) -> tuple[list[dict], list[dict]]:
    vocab = _load_vocab()
    shown = hits[:MAX_PRODUCTS]
    if not shown:
        content = (
            f"Em kiểm tra danh mục thuốc BVTV hiện hành nhưng chưa thấy sản phẩm nào đăng ký chính thức "
            f"cho \"{pest}\" trên \"{crop}\" ở {region_name}. Trong lúc chờ, bác giữ nguyên tắc 4 đúng "
            "(đúng thuốc, đúng liều, đúng lúc, đúng cách) và tạm ngưng phun đại trà nhé."
        )
        if multi_crop_note:
            content = multi_crop_note + content
        reason = f"Không có sản phẩm nào đăng ký chính thức cho cặp {crop} - {pest} trong registry hiện hành."
        segments = [
            {"type": "text", "content": content},
            {"type": "abstain", "reason": reason, "handoff": True},
        ]
        return segments, []

    lconn = _open_labels_conn()
    try:
        doses = [_lookup_dose(lconn, hit.trade_name, crop, pest, formulation=hit.formulation) for hit in shown]
    finally:
        if lconn is not None:
            lconn.close()

    # Ưu tiên hiển thị: sản phẩm có dose verified xếp lên trước (nông dân cần liều
    # dùng được ngay) — sorted() ổn định nên phần còn lại giữ nguyên thứ tự gốc.
    order = sorted(range(len(shown)), key=lambda i: 0 if doses[i] is not None else 1)
    shown = [shown[i] for i in order]
    doses = [doses[i] for i in order]

    total = len(hits)
    intro = f"Dạ, với {crop} bị {pest} ở {region_name}, em tìm được {total} sản phẩm còn phép dùng."
    if total > len(shown):
        intro += f" Gửi bác {len(shown)} sản phẩm tiêu biểu, bác hỏi thêm cán bộ khuyến nông xã để chọn loại có sẵn tại đại lý gần nhà:"
    else:
        intro += " Gửi bác danh sách:"
    if multi_crop_note:
        intro = multi_crop_note + intro

    segments: list[dict] = [{"type": "text", "content": intro}]
    products: list[dict] = []
    seen_cites: list[str] = []
    for hit, dose in zip(shown, doses):
        product_label = f"{hit.trade_name} ({hit.formulation})" if hit.formulation else hit.trade_name
        if dose is not None:
            dose_block = {
                "type": "dose_block",
                "product": product_label,
                "ai": hit.active_ingredient,
                "dose_text": _format_dose_text(dose),
                "phi_days": dose.phi_days,
                "note": _DOSE_NOTE_VERIFIED,
                "source_url": dose.source_url,
            }
        else:
            dose_block = {
                "type": "dose_block",
                "product": product_label,
                "ai": hit.active_ingredient,
                "dose_text": _DOSE_TEXT,
                "phi_days": None,
                "note": _DOSE_NOTE,
            }
        segments.append(dose_block)
        products.append(
            {
                "trade_name": hit.trade_name,
                "formulation": hit.formulation,
                "active_ingredient": hit.active_ingredient,
                "cite": hit.cite,
            }
        )
        if hit.cite not in seen_cites:
            seen_cites.append(hit.cite)

    for cite in seen_cites:
        segments.append({"type": "citation", "source": cite, "url": _doc_url_for_cite(cite, vocab["doc_urls"])})

    return segments, products


def answer(text: str, region: str, on_date: str) -> dict:
    conn = db_module.connect()
    try:
        vocab = _load_vocab()
        text_norm = _norm(text)
        words = _tokenize(text_norm)
        crop, crop_ambiguous, crop_seen = _extract_slot(conn, words, vocab, "crop")
        # Guard: một số mục trong registry bị gán nhầm vừa là crop vừa là pest (artifact
        # dữ liệu của lane ingest, vd literal "cà phê" cũng xuất hiện ở cột pest) — loại
        # trừ toàn bộ từ vựng crop khỏi ứng viên pest để tránh pest == crop vô lý.
        pest, pest_ambiguous, _pest_seen = _extract_slot(
            conn, words, vocab, "pest", exclude=frozenset(vocab["crop_terms"])
        )
        if pest is not None and crop is not None and pest == crop:
            pest = None  # phòng hờ thêm — không bao giờ chấp nhận pest == crop

        slots = {"crop": crop, "pest": pest, "region": region}
        region_name = REGION_NAMES.get(region, region)

        # --- P1-G: small-talk layer — chạy TRƯỚC clarify/product-guard/path A/path B.
        # Chỉ khi câu KHÔNG có slot nào (crop/pest/product mention) và ngắn (< 10 từ) —
        # tránh chặn nhầm câu thật có lẫn từ chào hỏi (vd "chào em, lúa bị rầy nâu xịt
        # gì" vẫn phải đi path A bình thường vì đã bắt được crop/pest).
        mention = product_guard.find_product_or_ai_mention(text)
        if (
            crop is None
            and pest is None
            and not crop_ambiguous
            and not pest_ambiguous
            and mention is None
            and len(words) < _SMALLTALK_MAX_WORDS
        ):
            smalltalk_category = _detect_smalltalk(text_norm)
            if smalltalk_category is not None:
                return {
                    "risk_class": "B",
                    "answer_segments": _small_talk_segments(smalltalk_category, region),
                    "slots": slots,
                    "products": [],
                }

        if crop_ambiguous or pest_ambiguous:
            return {
                "risk_class": "B",
                "answer_segments": _clarify_segments(crop_ambiguous or pest_ambiguous),
                "slots": slots,
                "products": [],
            }

        # --- P1-D: product/AI guard — chạy TRƯỚC path A (xem product_guard.py) ---
        # Thứ tự: (1) premise tăng/gấp đôi liều luôn chặn trước tiên (an toàn tuyệt
        # đối, không phụ thuộc có bắt được product hay không); (2)/(3)/(4) chỉ chặn
        # khi thực sự bắt được sản phẩm/hoạt chất có vấn đề — sản phẩm bình thường
        # (status allowed, không sắp đổi, đúng cây) rơi qua path A/mock như cũ.
        if product_guard.has_double_dose_premise(text):
            segments = product_guard.double_dose_segments(crop, pest)
            return {"risk_class": "A", "answer_segments": segments, "slots": slots, "products": []}

        if mention is not None:
            kind, payload = mention
            if kind == "banned_ai":
                segments = product_guard.banned_ai_segments(payload, conn)
                return {"risk_class": "A", "answer_segments": segments, "slots": slots, "products": []}

            trade_name, formulation = payload
            result = product_guard.evaluate_product(conn, trade_name, formulation, on_date, crop)
            if result.kind in ("removed", "transitional"):
                alt_hits = db_module.lookup_products(conn, crop, pest, on_date) if crop and pest else []
                segments = product_guard.removed_or_transitional_segments(result, crop, pest, alt_hits)
                return {"risk_class": "A", "answer_segments": segments, "slots": slots, "products": []}
            if result.kind == "banned":
                segments = product_guard.banned_ai_segments(result.current_row["active_ingredient"], conn)
                return {"risk_class": "A", "answer_segments": segments, "slots": slots, "products": []}
            if result.kind == "wrong_crop":
                alt_hits = db_module.lookup_products(conn, crop, pest, on_date) if crop and pest else []
                segments = product_guard.wrong_crop_segments(result, crop, pest, alt_hits)
                return {"risk_class": "A", "answer_segments": segments, "slots": slots, "products": []}
            # result.kind in ("ok", "unknown") -> sản phẩm bình thường, đi tiếp path A/mock

        multi_crop_note = None
        if crop and len(crop_seen) > 1:
            multi_crop_note = f"Bác nhắc tới cả {' và '.join(crop_seen)}, em trả lời cho {crop} trước nhé. "

        if crop and pest:
            hits = db_module.lookup_products(conn, crop, pest, on_date)
            segments, products = _path_a_segments(region_name, crop, pest, hits, multi_crop_note)
            return {"risk_class": "A", "answer_segments": segments, "slots": slots, "products": products}

        # --- P1-G: minh bạch phạm vi khi crop ngoài KB (chỉ khi KHÔNG có pest slot —
        # có pest thì để path A ở trên xử lý, registry.db độc lập với phạm vi KB) ---
        if crop and pest is None and crop not in _kb_crops():
            segments = _out_of_kb_crop_segments(crop, region_name)
            return {"risk_class": "B", "answer_segments": segments, "slots": slots, "products": []}

        if _rag_b_enabled():
            segments = _rag_b_segments(text, region, crop)
        else:
            segments = _mock_segments()
        return {"risk_class": "B", "answer_segments": segments, "slots": slots, "products": []}
    finally:
        conn.close()

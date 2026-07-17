"""Hybrid retrieval cho đường B (RAG canh tác chung) — spec §5.3/§6.5.

`retrieve(question, region=None, crop=None, k=5) -> list[dict]`:
1. Nhánh BM25: `ingest.build_kb.search_bm25` (import LƯỜI/động — lane Task 10 có thể
   chưa xong hoặc lỗi -> bắt Exception, coi như không có BM25, chỉ dùng dense).
2. Nhánh dense: cosine similarity trên bảng `chunk_vectors` (tự viết ở đây, KHÔNG
   phụ thuộc reranker — cut-line MVP). Chưa có bảng/chưa có vector nào -> coi như
   không có dense, chỉ dùng BM25.
3. Hợp nhất 2 danh sách bằng Reciprocal Rank Fusion (RRF, k=60 theo chuẩn) dựa trên
   THỨ HẠNG (không phải thang điểm gốc — bm25() của SQLite và cosine similarity
   không cùng thang đo/chiều tốt-xấu, nên không so trực tiếp được).

Không có `data/kb.db` (Task 10 chưa chạy) -> trả `[]`, KHÔNG raise — caller
(app/backend/pipeline.py) tự quyết định fallback (giữ hành vi mock cũ).

Mỗi chunk trả về giữ nguyên các cột gốc (id, doc_id, section, text, crop,
region_scope, authority_level, date, url) + thêm `retrieval_score` (điểm RRF, dùng
để sort/so sánh — KHÔNG phải bm25 score hay cosine similarity gốc).

--- P1-E: 2 cải tiến retrieval đo được (chẩn đoán 6 câu control_general_farming fail
ở eval verify-p1d — xem .superpowers/sdd/p1e-report.md) ---

1. **Phân cấp vùng (region hierarchy)**: kb.db có các region_scope là VÙNG GỘP nhiều
   tỉnh ("đbscl" chứa "an giang", "tây nguyên" chứa "đắk lắk") bên cạnh "national" và
   region_scope theo tỉnh cụ thể. Filter vùng gốc (cả ở đây lẫn ở
   `ingest.build_kb.search_bm25`) chỉ so khớp "national" HOẶC đúng tỉnh — bỏ sót toàn
   bộ tài liệu cấp vùng (vd `qd145-sotay-lua` region_scope="đbscl" cho câu hỏi
   region="an_giang"; `wasi-taicanh-caphe` region_scope="tây nguyên" cho
   region="dak_lak") dù nội dung ÁP DỤNG ĐƯỢC cho tỉnh đó. Đây là nguyên nhân retrieval
   chính khiến 5/6 câu control fail (q41, q42, q45, q48, q50) — tài liệu đúng chưa bao
   giờ lọt vào ứng viên BM25/dense vì bị loại bởi filter vùng, không phải vì
   BM25/dense xếp hạng thấp.
   Cách sửa: `_region_allowed()` dùng bảng `_REGION_HIERARCHY` để coi vùng-gộp là hợp
   lệ cho tỉnh con. KHÔNG sửa `ingest/build_kb.py::search_bm25` (giữ nguyên hành vi +
   test `tests/test_build_kb.py::test_build_and_search` của Task 10, lane khác không
   đang sửa file này nhưng vẫn tránh đụng theo tinh thần cô lập lane) — thay vào đó
   `_try_bm25` gọi `search_bm25(..., region=None)` để tắt filter vùng nội bộ của nó,
   rồi tự lọc lại bằng `_region_allowed()` ở đây. Cố ý KHÔNG mở rộng "lâm đồng" vào
   nhóm "tây nguyên" (dù về địa lý/lịch sử có liên quan) — "lâm đồng" trong kb.db là
   FAQ khuyến nông RIÊNG của tỉnh đó, không phải quy trình cấp vùng dùng chung, nên
   giữ đúng phạm vi hẹp (an toàn hơn khi không chắc).
2. **Bỏ stopword tiếng Việt phổ biến khỏi câu truy vấn BM25** (`_strip_bm25_stopwords`):
   corpus KB có ~200 chunk FAQ ngắn với câu chào mở đầu lặp lại
   ("Cám ơn bạn đã quan tâm...") — các từ chức năng chung chung trong câu hỏi người
   dùng ("cho", "cần", "thế nào"...) không giúp phân biệt chủ đề nhưng vẫn được OR vào
   query BM25, làm loãng/đôi khi đẩy các chunk boilerplate lên hạng cao hơn nội dung
   đúng chủ đề (đo được: bỏ 3-5 stopword giúp `wasi-taicanh-caphe`/`qd145-sotay-lua`
   nhảy vào top-8 BM25 cho q45/q48/q50 — xem report). CHỈ áp dụng cho câu truy vấn
   BM25 (dense embedding vẫn dùng nguyên văn câu hỏi — ngữ nghĩa cần đủ ngữ pháp).
   Danh sách `_BM25_STOPWORDS` cố ý ngắn/bảo thủ (từ chức năng thuần tuý: giới từ, hư
   từ nghi vấn, đại từ xưng hô...) để tránh xóa nhầm từ có thể mang thông tin chủ đề.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np

Chunk = dict[str, Any]

KB_DB_PATH = "data/kb.db"

_BM25_K = 20
# search_bm25() lọc region/crop TRƯỚC KHI cắt còn k — nếu gọi thẳng k=_BM25_K thì
# vòng lặp dừng ngay khi đủ 20 chunk khớp crop (không lọc vùng, xem _try_bm25), có
# thể dừng SỚM hơn vị trí các chunk vùng-gộp hợp lệ nằm sâu hơn trong thứ hạng BM25
# gốc (đo được: qd145-sotay-lua rank ~45 cho câu hỏi phân bón lúa — xem
# .superpowers/sdd/p1e-report.md). Fetch rộng hơn hẳn (60) rồi tự lọc vùng + cắt còn
# _BM25_K ở _try_bm25 để không bỏ sót các chunk này mà vẫn giữ nguyên kích thước pool
# đưa vào RRF như trước.
_BM25_FETCH_K = 60
_DENSE_K = 20
_RRF_K = 60  # hằng số chuẩn của Reciprocal Rank Fusion

# Pipeline dùng mã vùng "an_giang"/"dak_lak" (schemas.Region) nhưng region_scope
# trong kb.db là chuỗi tiếng Việt thường ("an giang", "đắk lắk") — quy đổi ở đây để
# app/backend/pipeline.py không cần biết chi tiết KB. Region không nằm trong map
# (vd caller truyền thẳng "an giang", hoặc region_scope khác như "tây nguyên",
# "đbscl") được dùng nguyên văn (chỉ lower()).
REGION_SCOPE_MAP = {"an_giang": "an giang", "dak_lak": "đắk lắk"}

# Vùng-gộp (nhiều tỉnh) trong kb.db coi là hợp lệ cho tỉnh con — xem docstring module
# mục "Phân cấp vùng". Cố ý KHÔNG thêm "lâm đồng" vào nhóm "tây nguyên": "lâm đồng"
# trong kb.db là FAQ khuyến nông riêng của tỉnh đó, không phải quy trình cấp vùng.
_REGION_HIERARCHY = {
    "an giang": frozenset({"an giang", "đbscl"}),
    "đắk lắk": frozenset({"đắk lắk", "tây nguyên"}),
}

# Từ chức năng phổ biến, không mang thông tin chủ đề — loại khỏi query BM25 (xem
# docstring module mục "Bỏ stopword"). Cố ý ngắn/bảo thủ: chỉ giới từ, hư từ nghi
# vấn, đại từ xưng hô, trợ từ — không đụng tới danh/động/tính từ có thể là chủ đề.
_BM25_STOPWORDS = frozenset({
    "cho", "của", "là", "và", "các", "những", "này", "đó", "khi", "để", "theo", "về",
    "có", "được", "trong", "với", "như", "thì", "mà", "nào", "gì", "ạ", "nhé", "bác",
    "ơi", "xin", "hỏi", "giúp", "làm", "sao", "thế", "cần", "nên", "phải", "hay",
    "một", "hoặc", "rất", "đã", "sẽ", "đang", "không", "còn", "lại", "ra", "vào",
    "lên", "xuống", "ở", "tại", "từ", "đến", "khoảng", "bao", "nhiêu", "mấy", "ai",
    "đâu", "sau", "trước", "vậy", "à", "ư", "nhỉ", "chứ", "thôi", "luôn", "cả", "mọi",
    "mỗi", "tôi", "bạn", "em", "anh", "chị", "mình", "bị", "sang",
})

_PUNCT_RE = re.compile(r"[?.,!;:]")


def _strip_bm25_stopwords(query: str) -> str:
    """Bỏ các từ trong `_BM25_STOPWORDS` khỏi câu hỏi (so khớp từng từ thô, tách bởi
    khoảng trắng, đã bỏ dấu câu + hạ chữ thường) trước khi đưa vào `search_bm25` (nơi
    sẽ tự tokenize lại bằng pyvi). Không còn từ nào sau khi lọc (câu hỏi toàn từ chức
    năng, hiếm gặp) -> trả nguyên văn câu hỏi gốc để tránh query rỗng."""
    words = query.split()
    kept = [w for w in words if _PUNCT_RE.sub("", w).lower() not in _BM25_STOPWORDS]
    return " ".join(kept) if kept else query


def _resolve_region(region: str | None) -> str | None:
    if region is None:
        return None
    return REGION_SCOPE_MAP.get(region, region).lower()


def _region_allowed(region_scope: str | None, region_resolved: str | None) -> bool:
    """True nếu `region_scope` của 1 chunk hợp lệ cho `region_resolved` (đã quy đổi
    bằng `_resolve_region`) — "national" luôn hợp lệ; vùng-gộp trong
    `_REGION_HIERARCHY` hợp lệ cho tỉnh con; ngoài ra phải khớp đúng. `region_resolved`
    None -> không lọc vùng (True mọi trường hợp, giữ hành vi cũ khi caller không
    truyền region)."""
    if region_resolved is None:
        return True
    if region_scope == "national":
        return True
    allowed = _REGION_HIERARCHY.get(region_resolved, frozenset({region_resolved}))
    return region_scope in allowed


def _connect(path: str = KB_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def _try_bm25(conn: sqlite3.Connection, query: str, region_resolved: str | None, crop: str | None) -> list[Chunk]:
    try:
        from ingest.build_kb import search_bm25  # import động: Task 10 có thể chưa xong/lỗi
    except Exception:
        return []
    try:
        # region=None: tắt filter vùng nội bộ của search_bm25 (chỉ biết "national"
        # hoặc khớp đúng tỉnh, không biết vùng-gộp) — tự lọc lại bằng _region_allowed
        # bên dưới. crop vẫn để search_bm25 lọc (không có vấn đề phân cấp tương tự).
        # k=_BM25_FETCH_K (> _BM25_K) để không dừng sớm trước khi chạm các chunk
        # vùng-gộp hợp lệ nằm sâu hơn trong thứ hạng BM25 gốc (xem docstring hằng số).
        stripped_query = _strip_bm25_stopwords(query)
        hits = search_bm25(conn, stripped_query, k=_BM25_FETCH_K, region=None, crop=crop)
    except Exception:
        return []
    filtered = [dict(h) for h in hits if _region_allowed(h["region_scope"], region_resolved)]
    return filtered[:_BM25_K]


def _embed_query(text: str) -> np.ndarray:
    """Tách riêng thành hàm module-level để test có thể monkeypatch (tránh gọi
    Gemini thật trong unit test)."""
    from ingest.build_kb_dense import embed_query

    return embed_query(text)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _dense_search(
    conn: sqlite3.Connection, query_vec: np.ndarray, region_resolved: str | None, crop: str | None
) -> list[Chunk]:
    rows = conn.execute(
        "SELECT c.id, c.doc_id, c.section, c.text, c.crop, c.region_scope, c.authority_level, c.date, c.url, "
        "v.vec AS vec FROM chunk_vectors v JOIN chunks c ON c.id = v.chunk_id"
    ).fetchall()
    scored: list[Chunk] = []
    for r in rows:
        # region_scope: "national" hoặc trùng region đã resolve HOẶC vùng-gộp hợp lệ
        # (xem _region_allowed + docstring module mục "Phân cấp vùng"); crop chỉ loại
        # khi chunk CÓ crop và khác crop truy vấn (chunk không gán crop = áp dụng mọi
        # cây).
        if not _region_allowed(r["region_scope"], region_resolved):
            continue
        if crop and r["crop"] and r["crop"] != crop.lower():
            continue
        vec = np.frombuffer(r["vec"], dtype=np.float32)
        d = {k: r[k] for k in r.keys() if k != "vec"}
        d["score"] = _cosine(query_vec, vec)
        scored.append(d)
    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:_DENSE_K]


def _try_dense(conn: sqlite3.Connection, query: str, region_resolved: str | None, crop: str | None) -> list[Chunk]:
    try:
        if not _table_exists(conn, "chunk_vectors"):
            return []
        n = conn.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0]
        if not n:
            return []
        query_vec = _embed_query(query)
    except Exception:
        return []
    try:
        return _dense_search(conn, query_vec, region_resolved, crop)
    except Exception:
        return []


def _rrf_merge(bm25_hits: list[Chunk], dense_hits: list[Chunk]) -> list[Chunk]:
    """RRF theo THỨ HẠNG (rank position trong từng danh sách đã sort tốt->xấu),
    không dùng score gốc (khác thang đo giữa bm25() của SQLite và cosine)."""
    rrf_scores: dict[int, float] = {}
    items: dict[int, Chunk] = {}
    for ranked in (bm25_hits, dense_hits):
        for rank, hit in enumerate(ranked):
            cid = hit["id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
            items.setdefault(cid, hit)
    merged = []
    for cid, score in rrf_scores.items():
        chunk = dict(items[cid])
        chunk["retrieval_score"] = score
        merged.append(chunk)
    merged.sort(key=lambda c: c["retrieval_score"], reverse=True)
    return merged


def retrieve(
    question: str, region: str | None = None, crop: str | None = None, k: int = 5, db_path: str = KB_DB_PATH
) -> list[Chunk]:
    """Hybrid retrieval top-k cho đường B. Không có kb.db -> `[]`."""
    if not Path(db_path).exists():
        return []
    conn = _connect(db_path)
    try:
        region_resolved = _resolve_region(region)
        bm25_hits = _try_bm25(conn, question, region_resolved, crop)
        dense_hits = _try_dense(conn, question, region_resolved, crop)
        merged = _rrf_merge(bm25_hits, dense_hits)
        return merged[:k]
    finally:
        conn.close()

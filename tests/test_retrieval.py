"""TDD cho hybrid retrieval đường B (app/backend/retrieval.py) — spec §5.3/§6.5.

Dùng kb.db fixture THẬT dựng qua `ingest.build_kb.build_kb` (module đã tồn tại từ
lane Task 10, cùng interface search_bm25 đã chốt trong plan) — không phải fixture
tay dựng schema riêng, vì build_kb.py đã có sẵn và khớp đúng interface cần dùng.
`chunk_vectors` (bảng của ingest/build_kb_dense.py) được chèn tay bằng vector float32
đơn giản (basis vectors) để kiểm soát chính xác thứ hạng dense mà không gọi Gemini
thật — `app.backend.retrieval._embed_query` bị monkeypatch để tránh network.
"""
import sqlite3
import sys

import numpy as np
import pytest

from app.backend import retrieval
from ingest.build_kb import build_kb

MD_LUA = """---
doc_id: d1
title: T1
crop: lúa
region_scope: an giang
authority_level: ban_tin_vung
date: 2026-10-01
url: https://x/d1
---
## Xuong giong
Xuống giống né rầy nâu vụ đông xuân, tránh sâu bệnh đầu vụ.
## Xam nhap man
Theo dõi xâm nhập mặn và bệnh đạo ôn cuối vụ, giữ nước ruộng.
"""

MD_CAPHE = """---
doc_id: d2
title: T2
crop: cà phê
region_scope: đắk lắk
authority_level: quy_trinh_cuc
date: 2026-05-01
url: https://x/d2
---
## Tai canh
Tái canh cà phê theo quy trình cơ giới hóa, xử lý đất trước khi trồng.
"""

# chunk id sau build_kb([MD_LUA, MD_CAPHE]): 1=Xuong giong (lúa/an giang),
# 2=Xam nhap man (lúa/an giang), 3=Tai canh (cà phê/đắk lắk) — xác nhận bằng
# script thăm dò thủ công trước khi viết test (build_kb chèn theo thứ tự file rồi
# thứ tự section trong file).


@pytest.fixture
def kb_db_path(tmp_path):
    p1 = tmp_path / "a.md"
    p1.write_text(MD_LUA, encoding="utf-8")
    p2 = tmp_path / "b.md"
    p2.write_text(MD_CAPHE, encoding="utf-8")
    db_path = tmp_path / "kb.db"
    conn = build_kb([p1, p2], db_path)
    conn.close()
    return db_path


def _add_chunk_vectors(db_path, vectors: dict[int, list[float]]):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE chunk_vectors (chunk_id INTEGER PRIMARY KEY, vec BLOB NOT NULL)")
    for chunk_id, values in vectors.items():
        vec = np.array(values, dtype=np.float32).tobytes()
        conn.execute("INSERT INTO chunk_vectors(chunk_id, vec) VALUES (?, ?)", (chunk_id, vec))
    conn.commit()
    conn.close()


def test_retrieve_missing_kb_db_returns_empty(tmp_path):
    assert retrieval.retrieve("câu hỏi bất kỳ", db_path=str(tmp_path / "khong_ton_tai.db")) == []


def test_retrieve_bm25_only_khi_chua_co_chunk_vectors(kb_db_path):
    """Chưa có bảng chunk_vectors (build_kb_dense.py chưa chạy) -> chỉ BM25, không lỗi."""
    hits = retrieval.retrieve(
        "rầy nâu xuống giống", region="an_giang", crop="lúa", k=5, db_path=str(kb_db_path)
    )
    assert hits, "phải có kết quả từ nhánh BM25"
    assert hits[0]["id"] == 1
    assert hits[0]["section"] == "Xuong giong"
    assert "retrieval_score" in hits[0]
    # crop khác (cà phê) bị loại
    assert all(h["id"] != 3 for h in hits)


def test_retrieve_dense_only_khi_bm25_import_loi(monkeypatch, kb_db_path):
    """Giả lập lane Task 10 lỗi import ingest.build_kb (sys.modules[...] = None khiến
    `from ingest.build_kb import search_bm25` bên trong retrieval._try_bm25 raise
    ImportError) -> retrieve() phải fallback sang chỉ dense, KHÔNG raise."""
    _add_chunk_vectors(
        kb_db_path,
        {1: [1.0, 0.0, 0.0], 2: [0.0, 1.0, 0.0], 3: [0.0, 0.0, 1.0]},
    )
    monkeypatch.setitem(sys.modules, "ingest.build_kb", None)
    monkeypatch.setattr(retrieval, "_embed_query", lambda text: np.array([0.9, 0.1, 0.0], dtype=np.float32))

    hits = retrieval.retrieve(
        "câu hỏi bất kỳ không quan trọng nội dung", region="an_giang", crop="lúa", k=5, db_path=str(kb_db_path)
    )
    assert hits, "phải có kết quả từ nhánh dense dù BM25 import lỗi"
    assert hits[0]["id"] == 1  # vector [1,0,0] gần query [0.9,0.1,0] nhất
    assert all(h["id"] != 3 for h in hits)  # crop lúa loại chunk cà phê


def test_retrieve_khong_co_vector_nao_thi_dense_bo_qua(kb_db_path):
    """Bảng chunk_vectors tồn tại nhưng rỗng -> dense bị bỏ qua y như chưa có bảng,
    không raise lỗi chia 0 hay lỗi rỗng."""
    _add_chunk_vectors(kb_db_path, {})
    hits = retrieval.retrieve("rầy nâu", region="an_giang", crop="lúa", k=5, db_path=str(kb_db_path))
    assert hits and hits[0]["id"] == 1


def test_retrieve_hybrid_rrf_merge_dung_thu_hang(monkeypatch, kb_db_path):
    """BM25 xếp chunk2 (xâm nhập mặn) hạng nhất, chunk1 hạng nhì cho câu hỏi kết hợp
    2 chủ đề (xác nhận bằng chạy thử search_bm25 trực tiếp trước khi viết test).
    Dense (query vector monkeypatch = [0.9, 0.1, 0]) xếp chunk1 hạng nhất, chunk2
    hạng nhì — NGƯỢC lại BM25. RRF merge theo thứ hạng (không theo score gốc) nên
    2 chunk phải có retrieval_score BẰNG NHAU (mỗi chunk 1 lần hạng nhất + 1 lần
    hạng nhì ở 2 nhánh) và cùng đứng đầu kết quả hợp nhất; chunk3 (khác crop) bị
    loại khỏi cả 2 nhánh nên không xuất hiện."""
    _add_chunk_vectors(
        kb_db_path,
        {1: [1.0, 0.0, 0.0], 2: [0.0, 1.0, 0.0], 3: [0.0, 0.0, 1.0]},
    )
    monkeypatch.setattr(retrieval, "_embed_query", lambda text: np.array([0.9, 0.1, 0.0], dtype=np.float32))

    hits = retrieval.retrieve(
        "rầy nâu và xâm nhập mặn", region="an_giang", crop="lúa", k=5, db_path=str(kb_db_path)
    )
    ids = [h["id"] for h in hits]
    assert set(ids[:2]) == {1, 2}
    assert 3 not in ids

    expected_score = 1.0 / (retrieval._RRF_K + 0 + 1) + 1.0 / (retrieval._RRF_K + 1 + 1)
    for h in hits[:2]:
        assert h["retrieval_score"] == pytest.approx(expected_score)


def test_retrieve_region_map_pipeline_code_sang_region_scope(monkeypatch, kb_db_path):
    """retrieve() nhận thẳng mã vùng của pipeline ("dak_lak") và tự quy đổi sang
    region_scope tiếng Việt ("đắk lắk") trong kb.db — pipeline.py không cần biết
    chi tiết KB."""
    hits = retrieval.retrieve(
        "tái canh cà phê", region="dak_lak", crop="cà phê", k=5, db_path=str(kb_db_path)
    )
    assert hits and hits[0]["id"] == 3

    # region an_giang thì không thấy chunk cà phê/đắk lắk
    hits_ag = retrieval.retrieve(
        "tái canh cà phê", region="an_giang", crop="cà phê", k=5, db_path=str(kb_db_path)
    )
    assert all(h["id"] != 3 for h in hits_ag)

from pathlib import Path

import numpy as np

from ingest.build_kb import (
    build_kb,
    chunk_sections,
    parse_manual_md,
    search_bm25,
    upsert_manual_docs,
)

MD = """---
doc_id: d1
title: T
crop: lúa
region_scope: an giang
authority_level: ban_tin_vung
date: 2026-10-01
url: https://x
---
## Đợt 1
Xuống giống 10-30/10, né rầy.
## Đợt 2
Xuống giống tháng 11, chú ý xâm nhập mặn và bệnh đạo ôn.
"""


def test_parse_and_chunk(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(MD, encoding="utf-8")
    meta, sections = parse_manual_md(p)
    assert meta["doc_id"] == "d1" and meta["crop"] == "lúa"
    chunks = chunk_sections(meta, sections, max_chars=200)
    assert len(chunks) == 2 and chunks[1]["section"] == "Đợt 2"


def test_build_and_search(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(MD, encoding="utf-8")
    conn = build_kb([p], tmp_path / "kb.db")
    hits = search_bm25(conn, "đạo ôn xâm nhập mặn", k=5)
    assert hits and hits[0]["section"] == "Đợt 2"
    assert search_bm25(conn, "đạo ôn", k=5, region="đắk lắk") == []  # filter vùng


def test_upsert_manual_docs_replaces_chunks_and_stale_vectors(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(MD, encoding="utf-8")
    conn = build_kb([p], tmp_path / "kb.db")
    old_ids = [row[0] for row in conn.execute("SELECT id FROM chunks")]
    conn.execute("CREATE TABLE chunk_vectors(chunk_id INTEGER PRIMARY KEY, vec BLOB NOT NULL)")
    for chunk_id in old_ids:
        conn.execute(
            "INSERT INTO chunk_vectors(chunk_id, vec) VALUES (?, ?)",
            (chunk_id, np.array([1.0], dtype=np.float32).tobytes()),
        )
    conn.commit()

    updated = MD.replace("đạo ôn", "rầy nâu")
    p.write_text(updated, encoding="utf-8")
    assert upsert_manual_docs(conn, [p]) == 2

    assert conn.execute("SELECT COUNT(*) FROM chunks WHERE doc_id='d1'").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0] == 0
    assert search_bm25(conn, "rầy nâu", k=5)
    assert search_bm25(conn, "đạo ôn", k=5) == []


def test_upsert_manual_docs_rejects_missing_required_metadata(tmp_path):
    p = tmp_path / "bad.md"
    p.write_text("## Nội dung\nTưới đủ nước.", encoding="utf-8")
    conn = build_kb([], tmp_path / "kb.db")

    try:
        upsert_manual_docs(conn, [p])
    except ValueError as exc:
        assert "doc_id" in str(exc)
    else:
        raise AssertionError("Tài liệu thiếu metadata phải bị từ chối")

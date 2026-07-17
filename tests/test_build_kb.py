from pathlib import Path

from ingest.build_kb import parse_manual_md, chunk_sections, build_kb, search_bm25

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

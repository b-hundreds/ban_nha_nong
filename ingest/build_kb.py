"""KB văn bản: markdown (curate/extract) → chunks + FTS5 (pyvi tokenize)."""
import json
import re
import sqlite3
from pathlib import Path

from pyvi import ViTokenizer

DDL = """
CREATE TABLE chunks(
  id INTEGER PRIMARY KEY, doc_id TEXT NOT NULL, section TEXT, text TEXT NOT NULL,
  crop TEXT, region_scope TEXT NOT NULL DEFAULT 'national',
  authority_level TEXT NOT NULL, date TEXT, url TEXT NOT NULL);
CREATE VIRTUAL TABLE chunks_fts USING fts5(text_tok, content='');
"""


def _tok(s: str) -> str:
    return ViTokenizer.tokenize(s.lower())


def parse_manual_md(path: Path) -> tuple[dict, list[tuple[str, str]]]:
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.DOTALL)
    meta = {}
    body = raw
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
        body = m.group(2)
    sections, cur_title, cur = [], "", []
    for line in body.splitlines():
        if line.startswith("#"):
            if cur:
                sections.append((cur_title, "\n".join(cur).strip()))
            cur_title, cur = line.lstrip("#").strip(), []
        else:
            cur.append(line)
    if cur:
        sections.append((cur_title, "\n".join(cur).strip()))
    return meta, [s for s in sections if s[1]]


def chunk_sections(meta: dict, sections: list[tuple[str, str]], max_chars: int = 1600) -> list[dict]:
    chunks = []
    for title, text in sections:
        for i in range(0, len(text), max_chars):
            chunks.append({**meta, "section": title, "text": text[i:i + max_chars]})
    return chunks


def _insert_chunk(conn: sqlite3.Connection, c: dict) -> None:
    cur = conn.execute(
        "INSERT INTO chunks(doc_id,section,text,crop,region_scope,authority_level,date,url) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (c["doc_id"], c["section"], c["text"], c.get("crop"),
         c.get("region_scope", "national"), c["authority_level"], c.get("date"), c["url"]))
    conn.execute("INSERT INTO chunks_fts(rowid, text_tok) VALUES(?,?)",
                 (cur.lastrowid, _tok(c["text"])))


def build_kb(md_paths: list[Path], out_path: Path) -> sqlite3.Connection:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if Path(out_path).exists():
        Path(out_path).unlink()
    conn = sqlite3.connect(out_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    for p in md_paths:
        meta, sections = parse_manual_md(p)
        for c in chunk_sections(meta, sections):
            _insert_chunk(conn, c)
    conn.commit()
    return conn


REQUIRED_MANUAL_META = ("doc_id", "authority_level", "url")


def _validate_manual_meta(path: Path, meta: dict) -> None:
    missing = [key for key in REQUIRED_MANUAL_META if not meta.get(key)]
    if missing:
        raise ValueError(f"{path}: thiếu metadata bắt buộc: {', '.join(missing)}")


def _delete_doc(conn: sqlite3.Connection, doc_id: str) -> None:
    """Xóa một tài liệu và index liên quan, kể cả vector nếu bảng đã tồn tại."""
    rows = conn.execute(
        "SELECT id, text FROM chunks WHERE doc_id = ?", (doc_id,)
    ).fetchall()
    if not rows:
        return

    has_vectors = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_vectors'"
    ).fetchone()
    if has_vectors:
        conn.executemany(
            "DELETE FROM chunk_vectors WHERE chunk_id = ?",
            [(row[0],) for row in rows],
        )

    # chunks_fts là FTS5 contentless nên phải dùng lệnh delete đặc biệt và
    # cung cấp lại token cũ, không thể DELETE FROM trực tiếp.
    conn.executemany(
        "INSERT INTO chunks_fts(chunks_fts, rowid, text_tok) VALUES('delete', ?, ?)",
        [(row[0], _tok(row[1])) for row in rows],
    )
    conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))


def upsert_manual_docs(conn: sqlite3.Connection, md_paths: list[Path]) -> int:
    """Thêm/cập nhật tài liệu thủ công mà không rebuild toàn bộ KB.

    Mỗi ``doc_id`` được thay thế nguyên tử. Vector cũ của tài liệu được xóa để
    ``ingest.build_kb_dense`` chỉ tạo lại embedding cho các chunk vừa thay đổi.
    Hàm trả về tổng số chunk mới được chèn.
    """
    parsed = []
    seen_doc_ids = set()
    for raw_path in md_paths:
        path = Path(raw_path)
        meta, sections = parse_manual_md(path)
        _validate_manual_meta(path, meta)
        doc_id = meta["doc_id"]
        if doc_id in seen_doc_ids:
            raise ValueError(f"doc_id bị trùng trong cùng đợt ingest: {doc_id}")
        seen_doc_ids.add(doc_id)
        chunks = chunk_sections(meta, sections)
        if not chunks:
            raise ValueError(f"{path}: tài liệu không có section/nội dung để ingest")
        parsed.append((doc_id, chunks))

    inserted = 0
    try:
        for doc_id, chunks in parsed:
            _delete_doc(conn, doc_id)
            for chunk in chunks:
                _insert_chunk(conn, chunk)
            inserted += len(chunks)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return inserted


def search_bm25(conn, query: str, k: int = 20, region: str | None = None, crop: str | None = None):
    q = " OR ".join(t for t in _tok(query).split() if len(t) > 1)
    rows = conn.execute(
        f"""SELECT c.*, bm25(chunks_fts) AS score FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?""", (q, k * 3)).fetchall()
    out = []
    for r in rows:
        if region and r["region_scope"] not in ("national", region.lower()):
            continue
        if crop and r["crop"] and r["crop"] != crop.lower():
            continue
        out.append(dict(r))
        if len(out) >= k:
            break
    return out


# --- FAQ khuyến nông (Lâm Đồng): mỗi Q&A trong data/faq/*.jsonl = 1 chunk ---
# Không đi qua parse_manual_md/chunk_sections vì mỗi bản ghi có `url` riêng
# (khác trang chi tiết), trong khi 1 file .md front-matter chỉ gán 1 url
# dùng chung cho mọi chunk. Dùng chung schema + _insert_chunk ở trên.

def faq_jsonl_to_chunks(jsonl_path: Path, authority_level: str = "khuyen_nong",
                         region_scope: str = "lâm đồng", crop: str | None = None) -> list[dict]:
    chunks = []
    with Path(jsonl_path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            m = re.search(r"ID=(\d+)", rec.get("url", ""))
            faq_id = m.group(1) if m else str(abs(hash(rec.get("url", ""))))
            chunks.append({
                "doc_id": f"faq-lamdong-{faq_id}",
                "section": rec["question"],
                "text": rec["answer"],
                "crop": crop,
                "region_scope": region_scope,
                "authority_level": authority_level,
                "date": rec.get("date"),
                "url": rec["url"],
            })
    return chunks


def ingest_faq(conn: sqlite3.Connection, jsonl_path: Path, **kwargs) -> int:
    """Chèn thêm chunks FAQ vào conn đã có (từ build_kb). Trả về số chunk đã thêm."""
    chunks = faq_jsonl_to_chunks(jsonl_path, **kwargs)
    for c in chunks:
        _insert_chunk(conn, c)
    conn.commit()
    return len(chunks)

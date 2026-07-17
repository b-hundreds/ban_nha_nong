"""Dense index cho KB văn bản: embeddings Gemini -> bảng `chunk_vectors` trong kb.db.

Nhánh dense của hybrid retrieval đường B (xem app/backend/retrieval.py, spec §5.3/§6.5).
Đọc toàn bộ `chunks` từ `data/kb.db` (do `ingest/build_kb.py` tạo — Task 10), gọi Gemini
`gemini-embedding-001` (thư viện `google-genai`) để lấy vector, lưu float32 bytes vào
bảng mới `chunk_vectors(chunk_id INTEGER PRIMARY KEY, vec BLOB)` trong CÙNG kb.db.

RÀNG BUỘC FREE TIER (GEMINI_API_KEY hiện tại là free tier, RPM thấp — chỉ đạo cập
nhật giữa chừng task):
- Batch nhỏ (mặc định 8 chunk/lần gọi embed_content) để giảm rủi ro chạm rate limit
  trong 1 request.
- Exponential backoff khi lỗi; riêng lỗi 429 (rate limit) chờ lâu hơn hẳn (base 15s,
  nhân đôi mỗi lần thử lại) so với lỗi khác (base 2s) trước khi retry.
- RESUME được: mỗi lần chạy chỉ embed các chunk CHƯA có trong chunk_vectors
  (`WHERE id NOT IN (SELECT chunk_id FROM chunk_vectors)`) và ghi bằng
  `INSERT OR IGNORE` — nếu dính rate limit giữa chừng, chạy lại lệnh CLI sau đó sẽ
  bỏ qua các chunk đã embed thành công, không tốn lại quota cho chúng.

CLI: `python -m ingest.build_kb_dense` — in số chunk vừa embed trong lần chạy này;
kb.db chưa tồn tại (Task 10 chưa xong) -> in message rõ ràng ra stderr, exit 1.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

EMBED_MODEL = "gemini-embedding-001"
KB_DB_PATH = Path("data/kb.db")

BATCH_SIZE = 8  # free tier RPM thấp — batch nhỏ để giảm rủi ro 429
MAX_RETRIES = 5
BASE_DELAY = 2.0  # giây, lỗi thường (không phải rate limit)
RATE_LIMIT_BASE_DELAY = 15.0  # giây, lỗi 429 — chờ lâu hơn hẳn, nhân đôi mỗi lần thử

DDL_CHUNK_VECTORS = """
CREATE TABLE IF NOT EXISTS chunk_vectors (
    chunk_id INTEGER PRIMARY KEY,
    vec BLOB NOT NULL
);
"""


def _client():
    """Tạo google.genai.Client từ GEMINI_API_KEY (load .env nếu cần)."""
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Thiếu GEMINI_API_KEY trong môi trường/.env — không thể gọi Gemini embeddings.")
    from google import genai

    return genai.Client(api_key=api_key)


def _is_rate_limit(err: Exception) -> bool:
    return getattr(err, "code", None) == 429


def _embed_batch(client, texts: list[str], task_type: str) -> list[np.ndarray]:
    """Gọi embed_content cho 1 batch text, retry nhẹ với exponential backoff.

    Lỗi 429 (rate limit, free tier) chờ RATE_LIMIT_BASE_DELAY * 2**attempt; các lỗi
    khác chờ BASE_DELAY * 2**attempt. Hết MAX_RETRIES vẫn lỗi -> raise RuntimeError
    (caller — build_dense_index — không bắt lỗi này, để CLI dừng và người dùng chạy
    lại sau, nhờ cơ chế resume phía dưới không tốn lại quota phần đã xong)."""
    from google.genai import types

    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.models.embed_content(
                model=EMBED_MODEL,
                contents=texts,
                config=types.EmbedContentConfig(task_type=task_type),
            )
            return [np.array(e.values, dtype=np.float32) for e in resp.embeddings]
        except Exception as e:  # noqa: BLE001 — retry nhẹ theo yêu cầu, không phân biệt loại lỗi ngoài 429
            last_err = e
            if attempt == MAX_RETRIES - 1:
                break
            wait = (RATE_LIMIT_BASE_DELAY if _is_rate_limit(e) else BASE_DELAY) * (2**attempt)
            time.sleep(wait)
    raise RuntimeError(f"Gọi embed_content thất bại sau {MAX_RETRIES} lần thử: {last_err}") from last_err


def embed_query(text: str, client=None) -> np.ndarray:
    """Embed 1 câu hỏi (task_type=RETRIEVAL_QUERY) -> vector float32. Dùng bởi
    app/backend/retrieval.py cho nhánh dense (query time, không phải index time)."""
    client = client or _client()
    return _embed_batch(client, [text], task_type="RETRIEVAL_QUERY")[0]


def build_dense_index(conn: sqlite3.Connection, client=None, batch_size: int = BATCH_SIZE) -> int:
    """Embed các chunk CHƯA có vector trong `conn` (resume-safe) -> số chunk vừa
    embed trong lần gọi này (không tính các chunk đã có sẵn từ trước)."""
    client = client or _client()
    conn.executescript(DDL_CHUNK_VECTORS)
    rows = conn.execute(
        "SELECT id, text FROM chunks WHERE id NOT IN (SELECT chunk_id FROM chunk_vectors) ORDER BY id"
    ).fetchall()
    count = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        texts = [r[1] for r in batch]
        vecs = _embed_batch(client, texts, task_type="RETRIEVAL_DOCUMENT")
        for (chunk_id, _text), vec in zip(batch, vecs):
            conn.execute(
                "INSERT OR IGNORE INTO chunk_vectors(chunk_id, vec) VALUES (?, ?)",
                (chunk_id, vec.astype(np.float32).tobytes()),
            )
        conn.commit()
        count += len(batch)
    return count


def main() -> int:
    if not KB_DB_PATH.exists():
        print(
            f"Chưa có {KB_DB_PATH} — chạy `.venv/bin/python -m ingest.build_kb` trước "
            "(Task 10 tạo kb.db từ data/kb_manual/*.md).",
            file=sys.stderr,
        )
        return 1
    conn = sqlite3.connect(KB_DB_PATH)
    try:
        n = build_dense_index(conn)
    finally:
        conn.close()
    print(f"Đã embed {n} chunk mới vào chunk_vectors ({KB_DB_PATH}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

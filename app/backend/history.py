"""Lưu lịch sử hội thoại vào SQLite (data/history.db) — thay cho localStorage phía trình duyệt.

Thiết kế doc-store: mỗi hội thoại là 1 JSON payload nguyên trạng đúng shape mà
app/web/app.js đang dùng (id, sessionId, title, region, createdAt, updatedAt,
messages[]...) — server không diễn giải nội dung messages (kể cả các field UI như
status/revisions), chỉ đảm bảo bền vững + thứ tự. Nhờ vậy frontend đổi shape không
cần migration phía server, và swap từ localStorage sang API là 1-1.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent.parent
HISTORY_DB = BASE_DIR / "data" / "history.db"
MAX_CONVERSATIONS = 200

router = APIRouter()

_DDL = """
CREATE TABLE IF NOT EXISTS conversations(
  id TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(HISTORY_DB)
    conn.execute(_DDL)
    return conn


class ConversationPayload(BaseModel):
    # Chỉ ràng buộc tối thiểu để bắt lỗi client rõ ràng; phần còn lại giữ nguyên trạng.
    model_config = {"extra": "allow"}
    id: str
    messages: list


@router.get("/api/conversations")
def list_conversations() -> list[dict]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT payload FROM conversations ORDER BY updated_at DESC LIMIT ?",
            (MAX_CONVERSATIONS,),
        ).fetchall()
        return [json.loads(r[0]) for r in rows]
    finally:
        conn.close()


@router.put("/api/conversations/{conversation_id}")
def upsert_conversation(conversation_id: str, payload: ConversationPayload) -> dict:
    if payload.id != conversation_id:
        raise HTTPException(status_code=400, detail="id trong body không khớp với id trên URL.")
    now = datetime.now(timezone.utc).isoformat()
    doc = payload.model_dump()
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO conversations(id, payload, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
            (conversation_id, json.dumps(doc, ensure_ascii=False), now),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "updated_at": now}


@router.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict:
    conn = _conn()
    try:
        cur = conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
        conn.commit()
        return {"deleted": cur.rowcount > 0}
    finally:
        conn.close()

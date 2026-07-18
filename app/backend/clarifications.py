"""Persistent pending input confirmations keyed by conversation session_id."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("data/clarifications.db")
TTL_SECONDS = 15 * 60

_YES = {"dung", "dung roi", "phai", "phai roi", "uh", "u", "yes", "ok", "chinh xac"}
_NO = {"khong", "khong phai", "sai roi", "sai", "no"}


def _db_path() -> Path:
    return Path(os.environ.get("CLARIFICATION_DB_PATH", str(DEFAULT_DB_PATH)))


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pending_confirmations (
               session_id TEXT PRIMARY KEY,
               created_at REAL NOT NULL,
               payload_json TEXT NOT NULL
           )"""
    )
    conn.commit()
    return conn


def save(session_id: str, payload: dict[str, Any]) -> None:
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO pending_confirmations(session_id, created_at, payload_json)
               VALUES (?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET created_at=excluded.created_at,
                   payload_json=excluded.payload_json""",
            (session_id, time.time(), json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def get(session_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT created_at, payload_json FROM pending_confirmations WHERE session_id=?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        if time.time() - float(row[0]) > TTL_SECONDS:
            conn.execute("DELETE FROM pending_confirmations WHERE session_id=?", (session_id,))
            conn.commit()
            return None
        return json.loads(row[1])
    finally:
        conn.close()


def clear(session_id: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM pending_confirmations WHERE session_id=?", (session_id,))
        conn.commit()
    finally:
        conn.close()


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).replace("đ", "d")
    return " ".join(text.strip(" .,!?").split())


def confirmation_intent(text: str) -> str | None:
    folded = _fold(text)
    if folded in _YES:
        return "yes"
    if folded in _NO:
        return "no"
    return None

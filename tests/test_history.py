"""Lịch sử hội thoại lưu SQLite (app/backend/history.py) — thay localStorage theo yêu cầu user."""

import pytest
from fastapi.testclient import TestClient

from app.backend import history
from app.backend.api import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DB", tmp_path / "history.db")
    return TestClient(app)


def _conversation(cid="chat-1", title="Hỏi rầy nâu", n_msgs=2):
    return {
        "id": cid,
        "sessionId": "session-abc",
        "title": title,
        "titleEdited": False,
        "region": "an_giang",
        "createdAt": "2026-07-18T10:00:00Z",
        "updatedAt": "2026-07-18T10:05:00Z",
        "messages": [{"role": "user", "text": f"m{i}", "status": "done"} for i in range(n_msgs)],
    }


def test_put_roi_get_thay_nguyen_trang(client):
    doc = _conversation()
    r = client.put("/api/conversations/chat-1", json=doc)
    assert r.status_code == 200 and r.json()["ok"] is True
    listed = client.get("/api/conversations").json()
    assert len(listed) == 1
    # Doc-store: payload giữ NGUYÊN TRẠNG mọi field UI (kể cả field lạ)
    assert listed[0] == doc


def test_put_lai_cung_id_la_update_khong_nhan_ban(client):
    client.put("/api/conversations/chat-1", json=_conversation(title="Cũ"))
    client.put("/api/conversations/chat-1", json=_conversation(title="Mới", n_msgs=3))
    listed = client.get("/api/conversations").json()
    assert len(listed) == 1
    assert listed[0]["title"] == "Mới" and len(listed[0]["messages"]) == 3


def test_sap_xep_moi_nhat_truoc(client):
    client.put("/api/conversations/a", json=_conversation(cid="a"))
    client.put("/api/conversations/b", json=_conversation(cid="b"))
    listed = client.get("/api/conversations").json()
    assert [c["id"] for c in listed] == ["b", "a"]


def test_delete_xoa_that_va_idempotent(client):
    client.put("/api/conversations/chat-1", json=_conversation())
    assert client.delete("/api/conversations/chat-1").json()["deleted"] is True
    assert client.get("/api/conversations").json() == []
    assert client.delete("/api/conversations/chat-1").json()["deleted"] is False


def test_id_body_khong_khop_url_bi_tu_choi(client):
    r = client.put("/api/conversations/khac-id", json=_conversation(cid="chat-1"))
    assert r.status_code == 400


def test_thieu_messages_bi_422(client):
    r = client.put("/api/conversations/chat-1", json={"id": "chat-1", "title": "x"})
    assert r.status_code == 422

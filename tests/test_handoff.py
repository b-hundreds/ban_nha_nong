"""Tests cho module handoff + officer — xem contract 2026-07-18-handoff-officer-contract.md.

Dùng tmp_path + monkeypatch để KHÔNG đụng data/handoff.db thật.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app.backend.handoff as handoff_module
from app.backend.api import app

client = TestClient(app)


@pytest.fixture
def handoff_db(tmp_path, monkeypatch):
    """Chuyển HANDOFF_DB sang thư mục tmp_path để tránh đụng db thật.

    Cũng reset backoff state để AI classify tests không xuyên nhiễu nhau.
    """
    db_path = tmp_path / "test_handoff.db"
    monkeypatch.setattr(handoff_module, "HANDOFF_DB", db_path)
    monkeypatch.setattr(handoff_module, "_classify_backoff_until", 0.0)
    return db_path


# ---------------------------------------------------------------------------
# (a) POST handoff đủ contact → ticket lưu đủ cột
# ---------------------------------------------------------------------------

def test_handoff_day_du_contact_luu_du_cot(handoff_db, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("ZALO_OA_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OFFICER_TOKEN", raising=False)

    resp = client.post(
        "/api/handoff",
        json={
            "session_id": "sess-abc",
            "conversation_id": "conv-001",
            "message_id": "msg-007",
            "transcript": "sầu riêng bị ốc bươu vàng",
            "question": "Bác hỏi ốc bươu vàng trên sầu riêng xử lý thế nào?",
            "slots": {"crop": "sầu riêng", "pest": "ốc bươu vàng", "region": "an_giang"},
            "contact_name": "Nguyễn Thị Ba",
            "contact_phone": "0901234567",
            "contact_email": "ba@example.com",
        },
    )
    assert resp.status_code == 200
    ticket_id = resp.json()["ticket_id"]
    assert isinstance(ticket_id, int)

    conn = sqlite3.connect(handoff_db)
    row = conn.execute(
        """SELECT region, transcript, slots_json, status,
                  conversation_id, message_id, question,
                  contact_name, contact_phone, contact_email,
                  crop, pest
           FROM tickets WHERE id=?""",
        (ticket_id,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "an_giang"
    assert row[1] == "sầu riêng bị ốc bươu vàng"
    assert row[3] == "pending"
    assert row[4] == "conv-001"   # conversation_id
    assert row[5] == "msg-007"    # message_id
    assert row[6] == "Bác hỏi ốc bươu vàng trên sầu riêng xử lý thế nào?"  # question
    assert row[7] == "Nguyễn Thị Ba"   # contact_name
    assert row[8] == "0901234567"       # contact_phone
    assert row[9] == "ba@example.com"   # contact_email
    assert row[10] == "sầu riêng"       # crop
    assert row[11] == "ốc bươu vàng"   # pest


# ---------------------------------------------------------------------------
# (b) POST handoff kiểu cũ (không contact) vẫn 200
# ---------------------------------------------------------------------------

def test_handoff_cu_khong_contact_van_200(handoff_db, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("ZALO_OA_ACCESS_TOKEN", raising=False)

    resp = client.post(
        "/api/handoff",
        json={
            "session_id": "sess-old",
            "transcript": "lúa bị rầy nâu",
            "slots": {"crop": "lúa", "pest": "rầy nâu", "region": "an_giang"},
        },
    )
    assert resp.status_code == 200
    ticket_id = resp.json()["ticket_id"]
    assert isinstance(ticket_id, int)

    # Kiểm tra contact_name được điền mặc định
    conn = sqlite3.connect(handoff_db)
    row = conn.execute("SELECT contact_name, status FROM tickets WHERE id=?", (ticket_id,)).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "Bà con chưa để lại tên"
    assert row[1] == "pending"


# ---------------------------------------------------------------------------
# (c) Migration: tạo DB schema cũ → mở bằng module mới → cột mới có, dữ liệu cũ còn
# ---------------------------------------------------------------------------

def test_migration_schema_cu_sang_moi(tmp_path, monkeypatch):
    db_path = tmp_path / "old_handoff.db"

    # Tạo DB với schema tối giản (giống DB cũ trước khi có module mới)
    conn_old = sqlite3.connect(db_path)
    conn_old.execute(
        """CREATE TABLE tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            region TEXT,
            transcript TEXT NOT NULL,
            slots_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )"""
    )
    conn_old.execute(
        "INSERT INTO tickets (ts, region, transcript, slots_json, status) "
        "VALUES ('2026-01-01T00:00:00+00:00', 'an_giang', 'câu hỏi cũ', '{}', 'pending')"
    )
    conn_old.commit()
    conn_old.close()

    # Monkeypatch để _conn() dùng db cũ
    monkeypatch.setattr(handoff_module, "HANDOFF_DB", db_path)

    # Gọi _conn() — trigger migration
    conn = handoff_module._conn()

    # Kiểm tra các cột mới đã được thêm
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tickets)")}
    for expected_col in ["contact_name", "contact_phone", "contact_email",
                         "answer", "answered_by", "answered_at", "seen_at",
                         "conversation_id", "message_id", "question", "crop", "pest"]:
        assert expected_col in cols, f"Thiếu cột mới: {expected_col}"

    # Kiểm tra dữ liệu cũ vẫn còn nguyên
    row = conn.execute("SELECT transcript, status FROM tickets WHERE id=1").fetchone()
    assert row is not None
    assert row[0] == "câu hỏi cũ"
    assert row[1] == "pending"

    # Kiểm tra bảng question_log đã tạo
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "question_log" in tables

    conn.close()


# ---------------------------------------------------------------------------
# (d) Officer answer → status=answered + GET status thấy answer; answer lần 2 → 409
# ---------------------------------------------------------------------------

def test_officer_answer_va_409_lan_hai(handoff_db, monkeypatch):
    monkeypatch.delenv("OFFICER_TOKEN", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("ZALO_OA_ACCESS_TOKEN", raising=False)

    # Tạo ticket
    resp = client.post(
        "/api/handoff",
        json={
            "transcript": "lúa bị bệnh đạo ôn",
            "slots": {"crop": "lúa", "pest": "đạo ôn", "region": "an_giang"},
        },
    )
    assert resp.status_code == 200
    ticket_id = resp.json()["ticket_id"]

    # Cán bộ trả lời
    resp = client.post(
        f"/api/officer/tickets/{ticket_id}/answer",
        json={"answer": "Bác xịt thuốc Tricyclazole nhé", "officer_name": "Cán bộ Minh"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "notified_via" in body

    # GET status → answered
    resp = client.get(f"/api/handoff/status?ids={ticket_id}")
    assert resp.status_code == 200
    tickets = resp.json()["tickets"]
    assert len(tickets) == 1
    t = tickets[0]
    assert t["status"] == "answered"
    assert t["answer"] == "Bác xịt thuốc Tricyclazole nhé"
    assert t["answered_by"] == "Cán bộ Minh"
    assert t["answered_at"] is not None

    # Answer lần 2 → 409
    resp = client.post(
        f"/api/officer/tickets/{ticket_id}/answer",
        json={"answer": "Trả lời lần hai", "officer_name": "Cán bộ Khác"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# (e) seen → seen_at set
# ---------------------------------------------------------------------------

def test_seen_dat_seen_at(handoff_db, monkeypatch):
    monkeypatch.delenv("OFFICER_TOKEN", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("ZALO_OA_ACCESS_TOKEN", raising=False)

    resp = client.post(
        "/api/handoff",
        json={
            "transcript": "cà phê bị rệp sáp",
            "slots": {"crop": "cà phê", "pest": "rệp sáp", "region": "dak_lak"},
        },
    )
    ticket_id = resp.json()["ticket_id"]

    # Ban đầu seen=False
    resp = client.get(f"/api/handoff/status?ids={ticket_id}")
    assert resp.json()["tickets"][0]["seen"] is False

    # Đánh dấu đã xem
    resp = client.post(f"/api/handoff/{ticket_id}/seen")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Sau seen → seen=True
    resp = client.get(f"/api/handoff/status?ids={ticket_id}")
    assert resp.json()["tickets"][0]["seen"] is True

    # Kiểm tra trực tiếp seen_at đã set trong DB
    conn = sqlite3.connect(handoff_db)
    seen_at = conn.execute("SELECT seen_at FROM tickets WHERE id=?", (ticket_id,)).fetchone()[0]
    conn.close()
    assert seen_at is not None


# ---------------------------------------------------------------------------
# (f) Alerts: 3 câu cùng (region, pest) → alert xuất hiện; 2 câu → không
# ---------------------------------------------------------------------------

def test_alerts_nguong_3_cau(handoff_db, monkeypatch):
    monkeypatch.delenv("OFFICER_TOKEN", raising=False)
    monkeypatch.setenv("ALERT_MIN_COUNT", "3")

    # Bơm đúng 3 câu hỏi cùng (an_giang, rầy nâu) vào question_log
    for i in range(3):
        handoff_module.log_question("an_giang", "lúa", "rầy nâu", f"câu hỏi rầy nâu {i + 1}")

    resp = client.get("/api/officer/alerts?days=7")
    assert resp.status_code == 200
    alerts = resp.json()["alerts"]
    matching = [a for a in alerts if a["region"] == "an_giang" and a["topic"] == "rầy nâu"]
    assert len(matching) == 1
    assert matching[0]["count"] == 3
    assert matching[0]["region_name"] == "An Giang"

    # Chỉ 2 câu (dak_lak, sâu đục thân) → dưới ngưỡng, không xuất hiện
    for i in range(2):
        handoff_module.log_question("dak_lak", "cà phê", "sâu đục thân", f"câu hỏi sâu {i + 1}")

    resp = client.get("/api/officer/alerts?days=7")
    alerts = resp.json()["alerts"]
    assert not any(
        a["region"] == "dak_lak" and a["topic"] == "sâu đục thân"
        for a in alerts
    )


# ---------------------------------------------------------------------------
# (g) OFFICER_TOKEN đặt → thiếu header 401; đúng header 200
# ---------------------------------------------------------------------------

def test_officer_token_auth(handoff_db, monkeypatch):
    monkeypatch.setenv("OFFICER_TOKEN", "bnn-secret-2026")

    # Thiếu header → 401
    resp = client.get("/api/officer/tickets")
    assert resp.status_code == 401

    # Sai token → 401
    resp = client.get("/api/officer/tickets", headers={"X-Officer-Token": "sai-token"})
    assert resp.status_code == 401

    # Đúng token → 200
    resp = client.get("/api/officer/tickets", headers={"X-Officer-Token": "bnn-secret-2026"})
    assert resp.status_code == 200
    assert "tickets" in resp.json()


# ---------------------------------------------------------------------------
# AI classify: 3 test case mới
# ---------------------------------------------------------------------------

def test_ai_classify_topic_khong_co_pest_slot(handoff_db, monkeypatch):
    """Câu hỏi không có pest slot, AI gán topic 'đạo ôn' → alert xuất hiện đúng nhóm."""
    monkeypatch.delenv("OFFICER_TOKEN", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    monkeypatch.setenv("ALERT_AI_MODE", "auto")
    monkeypatch.setenv("ALERT_MIN_COUNT", "3")

    # Bơm 3 câu không có pest slot (mô tả triệu chứng, chưa có tên bệnh)
    for i in range(3):
        handoff_module.log_question("an_giang", "lúa", None, f"lúa cháy lá thành vệt {i + 1}")

    # Mock _call_gemini_classify: trả về topic "đạo ôn" cho mỗi row
    def _mock_classify(api_key, rows):
        return [(r[0], True, "đạo ôn") for r in rows]

    monkeypatch.setattr(handoff_module, "_call_gemini_classify", _mock_classify)

    resp = client.get("/api/officer/alerts?days=7")
    assert resp.status_code == 200
    alerts = resp.json()["alerts"]
    matching = [a for a in alerts if a["region"] == "an_giang" and a["topic"] == "đạo ôn"]
    assert len(matching) == 1, f"Mong đợi 1 alert đạo ôn, nhận được: {alerts}"
    assert matching[0]["count"] == 3
    assert matching[0]["region_name"] == "An Giang"


def test_ai_classify_mode_off_khong_goi_gemini(handoff_db, monkeypatch):
    """ALERT_AI_MODE=off → bỏ qua phân loại, _call_gemini_classify không được gọi."""
    monkeypatch.delenv("OFFICER_TOKEN", raising=False)
    monkeypatch.setenv("ALERT_AI_MODE", "off")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")

    called: list[bool] = []

    def _mock_classify(api_key, rows):
        called.append(True)
        return []

    monkeypatch.setattr(handoff_module, "_call_gemini_classify", _mock_classify)

    # Bơm dữ liệu và gọi alerts
    handoff_module.log_question("an_giang", "lúa", None, "câu hỏi test")
    resp = client.get("/api/officer/alerts?days=7")
    assert resp.status_code == 200
    assert len(called) == 0, "_call_gemini_classify không được gọi khi ALERT_AI_MODE=off"


def test_ai_classify_gemini_loi_alerts_van_200_va_co_pest(handoff_db, monkeypatch):
    """Gemini raise exception → alerts vẫn trả 200; dữ liệu pest slot cũ vẫn đếm được."""
    monkeypatch.delenv("OFFICER_TOKEN", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    monkeypatch.setenv("ALERT_AI_MODE", "auto")
    monkeypatch.setenv("ALERT_MIN_COUNT", "3")

    # Bơm 3 câu CÓ pest slot — sẽ vẫn đếm được dù AI fail
    for i in range(3):
        handoff_module.log_question("dak_lak", "cà phê", "rệp sáp", f"câu hỏi rệp {i + 1}")

    # Mock Gemini raise để kiểm tra backoff không làm fail endpoint
    def _mock_classify_fail(api_key, rows):
        raise RuntimeError("Gemini API lỗi giả lập")

    monkeypatch.setattr(handoff_module, "_call_gemini_classify", _mock_classify_fail)

    resp = client.get("/api/officer/alerts?days=7")
    assert resp.status_code == 200  # endpoint không được fail dù Gemini lỗi

    # Rows có pest IS NOT NULL vẫn được tính qua điều kiện fallback pest
    alerts = resp.json()["alerts"]
    matching = [a for a in alerts if a["region"] == "dak_lak" and a["topic"] == "rệp sáp"]
    assert len(matching) == 1, f"Mong đợi alert rệp sáp từ pest slot, nhận: {alerts}"
    assert matching[0]["count"] == 3


# ---------------------------------------------------------------------------
# alert_log persistence: 3 test case mới
# ---------------------------------------------------------------------------

def test_alert_log_mot_dot_cap_nhat_last_ts(handoff_db, monkeypatch):
    """Gọi alerts 2 lần với 3 câu đạo ôn → alert_log có đúng 1 đợt, peak_count đúng."""
    monkeypatch.delenv("OFFICER_TOKEN", raising=False)
    monkeypatch.setenv("ALERT_MIN_COUNT", "3")
    monkeypatch.setenv("ALERT_AI_MODE", "off")

    for i in range(3):
        handoff_module.log_question("an_giang", "lúa", "đạo ôn", f"câu hỏi đạo ôn {i + 1}")

    # Lần 1 — tạo đợt mới
    resp = client.get("/api/officer/alerts?days=7")
    assert resp.status_code == 200

    # Lần 2 — cập nhật đợt hiện tại (cùng đợt)
    resp = client.get("/api/officer/alerts?days=7")
    assert resp.status_code == 200

    conn = sqlite3.connect(handoff_db)
    rows = conn.execute(
        "SELECT region, topic, first_ts, last_ts, peak_count FROM alert_log WHERE region='an_giang' AND topic='đạo ôn'"
    ).fetchall()
    conn.close()

    assert len(rows) == 1, f"Mong đúng 1 đợt, nhận: {rows}"
    assert rows[0][4] == 3  # peak_count
    # last_ts >= first_ts (có thể bằng nhau nếu test chạy nhanh, không sao)
    assert rows[0][3] >= rows[0][2]


def test_alert_history_co_active_true(handoff_db, monkeypatch):
    """Response alerts có field history; đợt đang hoạt động có active=true."""
    monkeypatch.delenv("OFFICER_TOKEN", raising=False)
    monkeypatch.setenv("ALERT_MIN_COUNT", "3")
    monkeypatch.setenv("ALERT_AI_MODE", "off")

    for i in range(3):
        handoff_module.log_question("an_giang", "lúa", "rầy nâu", f"câu {i + 1}")

    resp = client.get("/api/officer/alerts?days=7")
    assert resp.status_code == 200
    body = resp.json()

    assert "history" in body, "Response phải có field 'history'"
    assert "alerts" in body, "Response vẫn phải có field 'alerts' (shape cũ)"

    matching = [h for h in body["history"] if h["region"] == "an_giang" and h["topic"] == "rầy nâu"]
    assert len(matching) == 1
    assert matching[0]["active"] is True
    assert matching[0]["peak_count"] == 3
    assert "first_ts" in matching[0]
    assert "last_ts" in matching[0]
    assert matching[0]["region_name"] == "An Giang"


def test_alert_dot_cu_active_false_va_dot_moi_la_row_rieng(handoff_db, monkeypatch):
    """Đợt cũ (last_ts 10 ngày trước) → active=false; alert mới cùng key → row mới (2 rows)."""
    monkeypatch.delenv("OFFICER_TOKEN", raising=False)
    monkeypatch.setenv("ALERT_MIN_COUNT", "3")
    monkeypatch.setenv("ALERT_AI_MODE", "off")

    # Seed đợt cũ (10 ngày trước — ngoài cửa sổ 7 ngày)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    conn = handoff_module._conn()
    conn.execute(
        "INSERT INTO alert_log (region, topic, first_ts, last_ts, peak_count) VALUES (?, ?, ?, ?, ?)",
        ("an_giang", "đạo ôn", old_ts, old_ts, 5),
    )
    conn.commit()
    conn.close()

    # Bơm 3 câu mới → tạo đợt mới cùng (region, topic)
    for i in range(3):
        handoff_module.log_question("an_giang", "lúa", "đạo ôn", f"câu mới {i + 1}")

    resp = client.get("/api/officer/alerts?days=7")
    assert resp.status_code == 200
    body = resp.json()

    # alert_log phải có 2 rows (đợt cũ + đợt mới)
    conn = sqlite3.connect(handoff_db)
    all_rows = conn.execute(
        "SELECT first_ts, last_ts, peak_count FROM alert_log WHERE region='an_giang' AND topic='đạo ôn' ORDER BY first_ts"
    ).fetchall()
    conn.close()
    assert len(all_rows) == 2, f"Mong 2 đợt riêng biệt, nhận: {all_rows}"

    # Trong history: đợt cũ active=false, đợt mới active=true
    history = body["history"]
    history_key = [h for h in history if h["region"] == "an_giang" and h["topic"] == "đạo ôn"]
    assert len(history_key) == 2
    active_entries = [h for h in history_key if h["active"]]
    inactive_entries = [h for h in history_key if not h["active"]]
    assert len(active_entries) == 1
    assert len(inactive_entries) == 1


# ---------------------------------------------------------------------------
# alerts: LIMIT 5 theo latest_ts mới nhất
# ---------------------------------------------------------------------------

def test_alerts_limit_5_moi_nhat(handoff_db, monkeypatch):
    """6 nhóm đủ ngưỡng → alerts trả đúng 5 nhóm có latest_ts mới nhất."""
    monkeypatch.delenv("OFFICER_TOKEN", raising=False)
    monkeypatch.setenv("ALERT_MIN_COUNT", "3")
    monkeypatch.setenv("ALERT_AI_MODE", "off")

    # Chèn 6 nhóm với timestamp tăng dần (nhóm 0 cũ nhất, nhóm 5 mới nhất)
    base_ts = datetime(2026, 7, 10, 8, 0, 0, tzinfo=timezone.utc)
    pests = [f"sâu {i}" for i in range(6)]
    conn = handoff_module._conn()
    for i, pest in enumerate(pests):
        ts = (base_ts + timedelta(hours=i)).isoformat()
        for _ in range(3):
            conn.execute(
                "INSERT INTO question_log (ts, region, crop, pest, text) VALUES (?, ?, ?, ?, ?)",
                (ts, "an_giang", "lúa", pest, f"câu hỏi {pest}"),
            )
    conn.commit()
    conn.close()

    resp = client.get("/api/officer/alerts?days=30")  # days=30 để bắt cả ts cũ
    assert resp.status_code == 200
    alerts = resp.json()["alerts"]

    # Phải đúng 5 alert
    assert len(alerts) == 5, f"Mong 5 alert, nhận {len(alerts)}: {[a['topic'] for a in alerts]}"

    # Nhóm cũ nhất (sâu 0) phải bị loại
    topics = {a["topic"] for a in alerts}
    assert "sâu 0" not in topics, "Nhóm cũ nhất (sâu 0) phải bị loại khỏi top-5"

    # 5 nhóm mới nhất (sâu 1..5) phải có mặt
    for i in range(1, 6):
        assert f"sâu {i}" in topics, f"Nhóm sâu {i} phải có trong top-5"


# ---------------------------------------------------------------------------
# Alerts: tối đa 5 alert MỚI NHẤT (theo latest_ts) — yêu cầu user 18/07
# ---------------------------------------------------------------------------

def test_alerts_toi_da_5_moi_nhat(handoff_db, monkeypatch):
    monkeypatch.delenv("OFFICER_TOKEN", raising=False)
    monkeypatch.setenv("ALERT_MIN_COUNT", "3")
    monkeypatch.setenv("ALERT_AI_MODE", "off")

    # 6 nhóm (an_giang, pest-i) đều đủ ngưỡng 3 câu; nhóm 1 bơm TRƯỚC nên cũ nhất
    for i in range(1, 7):
        for j in range(3):
            handoff_module.log_question("an_giang", "lúa", f"bệnh số {i}", f"câu {j} về bệnh số {i}")

    resp = client.get("/api/officer/alerts?days=7")
    assert resp.status_code == 200
    alerts = resp.json()["alerts"]
    assert len(alerts) == 5
    topics = {a["topic"] for a in alerts}
    assert "bệnh số 1" not in topics  # nhóm cũ nhất bị loại
    assert topics == {f"bệnh số {i}" for i in range(2, 7)}


# ---------------------------------------------------------------------------
# Tổng quan năm: vùng nhiều phản ánh dịch hại và vùng gửi nhiều câu hỏi nhất
# ---------------------------------------------------------------------------

def test_officer_overview_xep_hang_vung_theo_nam(handoff_db, monkeypatch):
    monkeypatch.setenv("ALERT_AI_MODE", "off")
    monkeypatch.delenv("OFFICER_TOKEN", raising=False)

    conn = handoff_module._conn()
    disease_rows = [
        # 18:00 UTC ngày 31/12 đã là 01/01/2026 tại Việt Nam.
        ("2025-12-31T18:00:00+00:00", "an_giang"),
        ("2026-03-01T00:00:00+00:00", "an_giang"),
        ("2026-04-01T00:00:00+00:00", "an_giang"),
        ("2026-05-01T00:00:00+00:00", "an_giang"),
        ("2026-03-01T00:00:00+00:00", "dak_lak"),
        ("2026-04-01T00:00:00+00:00", "dak_lak"),
    ]
    for ts, region in disease_rows:
        conn.execute(
            """INSERT INTO question_log
               (ts, region, crop, pest, text, ai_is_disease)
               VALUES (?, ?, 'lúa', 'rầy nâu', 'câu hỏi dịch hại', 1)""",
            (ts, region),
        )

    for region, count in (("an_giang", 2), ("dak_lak", 6)):
        for index in range(count):
            conn.execute(
                """INSERT INTO question_log
                   (ts, region, crop, pest, text, ai_is_disease)
                   VALUES ('2026-06-01T00:00:00+00:00', ?, 'lúa', NULL, ?, 0)""",
                (region, f"câu hỏi kỹ thuật {index}"),
            )

    # Đã sang năm 2027 theo giờ Việt Nam nên không được tính vào năm 2026.
    conn.execute(
        """INSERT INTO question_log
           (ts, region, crop, pest, text, ai_is_disease)
           VALUES ('2026-12-31T18:00:00+00:00', 'dak_lak', 'lúa', 'rầy nâu', 'ngoài năm', 1)"""
    )
    conn.commit()
    conn.close()

    body = handoff_module.officer_alerts(days=7, year=2026)
    overview = body["overview"]

    assert overview["year"] == 2026
    assert overview["total_questions"] == 14
    assert overview["located_questions"] == 14
    assert overview["disease_report_count"] == 6
    assert overview["questions_by_region"][0]["region"] == "dak_lak"
    assert overview["questions_by_region"][0]["question_count"] == 8
    assert overview["disease_reports_by_region"][0]["region"] == "an_giang"
    assert overview["disease_reports_by_region"][0]["disease_report_count"] == 4
    assert 2026 in overview["available_years"]
    assert "không phải" in overview["note"]


def test_officer_alerts_luu_du_nhom_cho_thong_ke_nam(handoff_db, monkeypatch):
    """UI chỉ hiện 5 alert nhưng lịch sử/thống kê phải ghi nhận đủ mọi nhóm đạt ngưỡng."""
    monkeypatch.setenv("ALERT_AI_MODE", "off")
    monkeypatch.setenv("ALERT_MIN_COUNT", "3")

    now = datetime.now(timezone.utc)
    conn = handoff_module._conn()
    for group_index in range(6):
        ts = (now - timedelta(minutes=group_index)).isoformat()
        for question_index in range(3):
            conn.execute(
                """INSERT INTO question_log
                   (ts, region, crop, pest, text)
                   VALUES (?, 'an_giang', 'lúa', ?, ?)""",
                (ts, f"dịch hại {group_index}", f"câu {question_index}"),
            )
    conn.commit()
    conn.close()

    current_year = datetime.now(timezone.utc).astimezone(handoff_module.VN_TZ).year
    body = handoff_module.officer_alerts(days=7, year=current_year)

    assert len(body["alerts"]) == 5
    assert len(body["history"]) == 6
    assert body["overview"]["disease_report_count"] == 18
    assert body["overview"]["questions_by_region"][0]["question_count"] == 18

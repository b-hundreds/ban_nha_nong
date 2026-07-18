"""Router handoff + cán bộ khuyến nông — xem docs/superpowers/specs/2026-07-18-handoff-officer-contract.md.

DB: data/handoff.db (SQLite).
Migration an toàn: giữ dữ liệu cũ, thêm cột mới bằng PRAGMA table_info + ALTER TABLE.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.backend.notify import notify_ticket_answered
from app.backend.schemas import AnswerRequest, HandoffRequest, HandoffResponse

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
HANDOFF_DB = BASE_DIR / "data" / "handoff.db"
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Tên hiển thị cho từng mã region (đồng bộ với Region enum trong schemas.py)
REGION_NAMES: dict[str, str] = {
    "an_giang": "An Giang",
    "dak_lak": "Đắk Lắk",
}

# Cột mới cần thêm vào bảng tickets nếu DB cũ chưa có
_NEW_TICKET_COLS: list[tuple[str, str]] = [
    ("conversation_id", "TEXT"),
    ("message_id", "TEXT"),
    ("question", "TEXT"),
    ("contact_name", "TEXT"),
    ("contact_phone", "TEXT"),
    ("contact_email", "TEXT"),
    ("crop", "TEXT"),
    ("pest", "TEXT"),
    ("answer", "TEXT"),
    ("answered_by", "TEXT"),
    ("answered_at", "TEXT"),
    ("notified_via", "TEXT"),
    ("seen_at", "TEXT"),
]

# Cột mới cần thêm vào bảng question_log (AI classify feature)
_NEW_QUESTION_LOG_COLS: list[tuple[str, str]] = [
    ("ai_topic", "TEXT"),
    ("ai_is_disease", "INTEGER"),
]

# Backoff module-level: sau khi Gemini lỗi, đợi 5 phút trước khi thử lại
_classify_backoff_until: float = 0.0

router = APIRouter()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _migrate(conn: sqlite3.Connection) -> None:
    """Migration an toàn: tạo bảng nếu chưa có, thêm cột mới nếu thiếu."""
    # Tạo bảng tickets với schema tối giản (tương thích DB cũ)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            region TEXT,
            transcript TEXT NOT NULL,
            slots_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )"""
    )
    # Thêm từng cột mới vào tickets nếu bảng cũ chưa có
    existing_ticket_cols = {row[1] for row in conn.execute("PRAGMA table_info(tickets)")}
    for col_name, col_type in _NEW_TICKET_COLS:
        if col_name not in existing_ticket_cols:
            conn.execute(f"ALTER TABLE tickets ADD COLUMN {col_name} {col_type}")

    # Tạo bảng question_log nếu chưa có
    conn.execute(
        """CREATE TABLE IF NOT EXISTS question_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            region TEXT,
            crop TEXT,
            pest TEXT,
            text TEXT
        )"""
    )
    # Thêm cột AI mới vào question_log nếu thiếu (DB tạo trước khi có AI feature)
    existing_ql_cols = {row[1] for row in conn.execute("PRAGMA table_info(question_log)")}
    for col_name, col_type in _NEW_QUESTION_LOG_COLS:
        if col_name not in existing_ql_cols:
            conn.execute(f"ALTER TABLE question_log ADD COLUMN {col_name} {col_type}")

    # Bảng lưu lịch sử đợt alert — mỗi row là một đợt dịch (có thể có nhiều đợt cùng region+topic)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS alert_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            region TEXT,
            topic TEXT,
            first_ts TEXT,
            last_ts TEXT,
            peak_count INTEGER,
            UNIQUE(region, topic, first_ts)
        )"""
    )

    conn.commit()


def _conn() -> sqlite3.Connection:
    """Mở kết nối tới HANDOFF_DB và chạy migration (idempotent).

    Đọc HANDOFF_DB từ module variable để test có thể monkeypatch.
    """
    db_path: Path = HANDOFF_DB  # tham chiếu module-level để monkeypatch được
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    _migrate(conn)
    return conn


# ---------------------------------------------------------------------------
# Hàm công khai: log câu hỏi (best-effort, nuốt lỗi)
# ---------------------------------------------------------------------------

def log_question(region: str, crop: str | None, pest: str | None, text: str) -> None:
    """Ghi log câu hỏi vào question_log sau mỗi lần /api/ask.

    Best-effort: lỗi chỉ log, không chặn response.
    """
    try:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO question_log (ts, region, crop, pest, text) VALUES (?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), region, crop, pest, text),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("log_question thất bại (best-effort, bỏ qua)")


# ---------------------------------------------------------------------------
# AI phân loại câu hỏi bệnh/dịch hại (best-effort, batch Gemini)
# ---------------------------------------------------------------------------

def classify_pending_questions(limit: int = 20) -> None:
    """Phân loại batch câu hỏi chưa được AI gán nhãn (ai_is_disease IS NULL).

    - ALERT_AI_MODE=off hoặc không có GEMINI_API_KEY → skip (0 API call).
    - Không có row IS NULL → skip ngay.
    - Gemini lỗi → log + backoff module-level 5 phút để không spam API
      khi dashboard refresh 15s/lần.
    - Best-effort: không bao giờ raise ra ngoài endpoint.
    """
    global _classify_backoff_until

    if os.getenv("ALERT_AI_MODE", "auto").strip().lower() == "off":
        return

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return

    if time.monotonic() < _classify_backoff_until:
        return

    try:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT id, text FROM question_log WHERE ai_is_disease IS NULL ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return

        # Một call Gemini duy nhất cho toàn batch
        results = _call_gemini_classify(api_key, rows)

        # Ghi kết quả phân loại vào DB
        conn = _conn()
        try:
            for row_id, is_disease, topic in results:
                conn.execute(
                    "UPDATE question_log SET ai_is_disease=?, ai_topic=? WHERE id=?",
                    (1 if is_disease else 0, topic, row_id),
                )
            conn.commit()
        finally:
            conn.close()

    except Exception:
        logger.exception("classify_pending_questions thất bại — backoff 5 phút")
        _classify_backoff_until = time.monotonic() + 300


def _call_gemini_classify(api_key: str, rows: list[tuple]) -> list[tuple[int, bool, str]]:
    """Gọi Gemini một lần cho toàn batch câu hỏi.

    Trả về list (id, is_disease, topic).
    """
    from google import genai
    from google.genai import types

    model = os.getenv("GEMINI_ALERT_MODEL", "gemini-flash-lite-latest")
    client = genai.Client(api_key=api_key)

    items_json = json.dumps(
        [{"id": row[0], "text": row[1] or ""} for row in rows],
        ensure_ascii=False,
    )

    prompt = (
        "Bạn là chuyên gia nông nghiệp Việt Nam. Phân loại từng câu hỏi của nông dân xem "
        "có liên quan đến BỆNH hoặc dịch hại trên cây trồng không.\n"
        "Nếu có: xác định tên bệnh/dịch hại canonical ngắn gọn tiếng Việt thông dụng "
        "(ví dụ: 'đạo ôn', 'rầy nâu', 'nấm rễ', 'thán thư'). "
        "Chuẩn hoá về tên bệnh GỐC, không kèm bộ phận cây hay giai đoạn: "
        "'đạo ôn lá', 'đạo ôn cổ bông' → 'đạo ôn'; 'thán thư trên trái' → 'thán thư'. "
        "Mô tả triệu chứng chỉ map sang tên bệnh khi đủ chắc chắn; không chắc → topic là "
        "cụm mô tả ngắn, không bịa tên bệnh.\n"
        "Nếu không phải về bệnh/dịch hại (hỏi kỹ thuật, phân bón, thời vụ...) → "
        "is_disease=false, topic=''.\n\n"
        f"Danh sách câu hỏi (JSON): {items_json}\n\n"
        "Trả về JSON array đúng schema: "
        '[{"id": <số>, "is_disease": true/false, "topic": "<tên bệnh hoặc rỗng>"}]'
    )

    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
        ),
    )

    parsed = json.loads(resp.text or "[]")
    if not isinstance(parsed, list):
        return []

    results: list[tuple[int, bool, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        row_id = item.get("id")
        if not isinstance(row_id, int):
            continue
        results.append((row_id, bool(item.get("is_disease", False)), str(item.get("topic", "") or "")))
    return results


# ---------------------------------------------------------------------------
# Auth dependency — OFFICER_TOKEN
# ---------------------------------------------------------------------------

def _check_officer_token(request: Request) -> None:
    """Kiểm tra X-Officer-Token nếu env OFFICER_TOKEN đã đặt.

    Không đặt env → cho qua (chế độ demo hackathon).
    """
    token = os.getenv("OFFICER_TOKEN", "").strip()
    if not token:
        return
    header = request.headers.get("X-Officer-Token", "")
    if header != token:
        raise HTTPException(status_code=401, detail="Thiếu hoặc sai header X-Officer-Token.")


# ---------------------------------------------------------------------------
# Endpoints phía người dùng
# ---------------------------------------------------------------------------

@router.post("/api/handoff", response_model=HandoffResponse)
def handoff(req: HandoffRequest) -> HandoffResponse:
    """Nhận yêu cầu chuyển tiếp tới cán bộ khuyến nông.

    Tương thích ngược: request cũ (chỉ có session_id/transcript/slots) vẫn hợp lệ.
    """
    question = (req.question or "").strip() or req.transcript
    contact_name = (req.contact_name or "").strip() or "Bà con chưa để lại tên"

    conn = _conn()
    try:
        cur = conn.execute(
            """INSERT INTO tickets
               (ts, region, transcript, slots_json, status,
                conversation_id, message_id, question, contact_name,
                contact_phone, contact_email, crop, pest)
               VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                req.slots.region,
                req.transcript,
                json.dumps(req.slots.model_dump(), ensure_ascii=False),
                req.conversation_id,
                req.message_id,
                question,
                contact_name,
                req.contact_phone,
                req.contact_email,
                req.slots.crop,
                req.slots.pest,
            ),
        )
        conn.commit()
        ticket_id = cur.lastrowid
    finally:
        conn.close()
    return HandoffResponse(ticket_id=ticket_id)


@router.get("/api/handoff/status")
def handoff_status(ids: str = Query(default="")) -> dict:
    """Trả về trạng thái của nhiều ticket (poll 30s từ frontend).

    ids: chuỗi phân cách bằng dấu phẩy, tối đa 50 id.
    """
    if not ids.strip():
        return {"tickets": []}

    id_list: list[int] = []
    for part in ids.split(","):
        part = part.strip()
        if part.isdigit():
            id_list.append(int(part))
    id_list = id_list[:50]

    if not id_list:
        return {"tickets": []}

    placeholders = ",".join("?" * len(id_list))
    conn = _conn()
    try:
        rows = conn.execute(
            f"""SELECT id, status, question, answer, answered_by, answered_at, seen_at
                FROM tickets WHERE id IN ({placeholders})""",
            id_list,
        ).fetchall()
    finally:
        conn.close()

    tickets = [
        {
            "ticket_id": row[0],
            "status": row[1],
            "question": row[2],
            "answer": row[3],
            "answered_by": row[4],
            "answered_at": row[5],
            "seen": row[6] is not None,
        }
        for row in rows
    ]
    return {"tickets": tickets}


@router.post("/api/handoff/{ticket_id}/seen")
def handoff_seen(ticket_id: int) -> dict:
    """Đánh dấu bác đã xem popup trả lời (set seen_at)."""
    conn = _conn()
    try:
        conn.execute(
            "UPDATE tickets SET seen_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), ticket_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Endpoints phía cán bộ (/api/officer/...)
# ---------------------------------------------------------------------------

@router.get("/api/officer/tickets", dependencies=[Depends(_check_officer_token)])
def officer_tickets(status: str = "all") -> dict:
    """Danh sách ticket cho dashboard cán bộ.

    status: "pending" | "answered" | "all" (default).
    Sort: pending (mới nhất trước) rồi đến answered.
    """
    conn = _conn()
    try:
        if status == "pending":
            where = "WHERE t.status='pending'"
        elif status == "answered":
            where = "WHERE t.status='answered'"
        else:
            where = ""

        rows = conn.execute(
            f"""SELECT id, ts, status, region, crop, pest, question, transcript,
                       contact_name, contact_phone, contact_email, answer,
                       answered_by, answered_at, notified_via
                FROM tickets t {where}
                ORDER BY CASE WHEN status='pending' THEN 0 ELSE 1 END, ts DESC"""
        ).fetchall()
    finally:
        conn.close()

    tickets = [
        {
            "ticket_id": row[0],
            "ts": row[1],
            "status": row[2],
            "region": row[3],
            "crop": row[4],
            "pest": row[5],
            "question": row[6],
            "transcript": row[7],
            "contact_name": row[8],
            "contact_phone": row[9],
            "contact_email": row[10],
            "answer": row[11],
            "answered_by": row[12],
            "answered_at": row[13],
            "notified_via": row[14],
        }
        for row in rows
    ]
    return {"tickets": tickets}


@router.post("/api/officer/tickets/{ticket_id}/answer", dependencies=[Depends(_check_officer_token)])
def officer_answer(ticket_id: int, req: AnswerRequest) -> dict:
    """Cán bộ trả lời ticket; trigger notify email/Zalo.

    409 nếu ticket đã được trả lời.
    """
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT status, region, crop, pest, question, transcript, contact_name, contact_phone, contact_email FROM tickets WHERE id=?",
            (ticket_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Ticket không tồn tại.")
        if row[0] == "answered":
            raise HTTPException(status_code=409, detail="Ticket này đã được trả lời rồi.")

        ticket_dict: dict = {
            "id": ticket_id,
            "region": row[1],
            "crop": row[2],
            "pest": row[3],
            "question": row[4],
            "transcript": row[5],
            "contact_name": row[6],
            "contact_phone": row[7],
            "contact_email": row[8],
            "answer": req.answer,
            "answered_by": req.officer_name,
        }

        # Ghi DB trước, notify sau — nếu ghi fail thì không báo nhầm cho bà con
        # rằng câu hỏi đã được trả lời.
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE tickets SET status='answered', answer=?, answered_by=?, answered_at=? WHERE id=?",
            (req.answer, req.officer_name, now, ticket_id),
        )
        conn.commit()

        notified_via = notify_ticket_answered(ticket_dict)
        conn.execute(
            "UPDATE tickets SET notified_via=? WHERE id=?",
            (notified_via, ticket_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {"ok": True, "notified_via": notified_via}


def _upsert_alert_log(conn: sqlite3.Connection, current_alerts: list[dict], now_iso: str) -> None:
    """Upsert danh sách alert hiện tại vào alert_log (mỗi đợt dịch là một row).

    Nếu đã có row cùng (region, topic) với last_ts trong vòng 7 ngày → cùng đợt → update.
    Không có → đợt mới → insert.
    Lỗi chỉ log, không raise.
    """
    gap_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    try:
        for alert in current_alerts:
            region = alert["region"]
            topic = alert["topic"]
            count = alert["count"]
            # Tìm đợt đang diễn ra: cùng (region, topic), last_ts trong 7 ngày gần nhất
            existing = conn.execute(
                "SELECT id, peak_count FROM alert_log WHERE region=? AND topic=? AND last_ts >= ? ORDER BY last_ts DESC LIMIT 1",
                (region, topic, gap_cutoff),
            ).fetchone()
            if existing:
                new_peak = max(existing[1] or 0, count)
                conn.execute(
                    "UPDATE alert_log SET last_ts=?, peak_count=? WHERE id=?",
                    (now_iso, new_peak, existing[0]),
                )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO alert_log (region, topic, first_ts, last_ts, peak_count) VALUES (?, ?, ?, ?, ?)",
                    (region, topic, now_iso, now_iso, count),
                )
        conn.commit()
    except Exception:
        logger.exception("_upsert_alert_log thất bại (best-effort, bỏ qua)")


def _vn_year_bounds_utc(year: int) -> tuple[str, str]:
    """Trả mốc đầu/cuối năm dương lịch Việt Nam dưới dạng ISO UTC."""
    start_local = datetime(year, 1, 1, tzinfo=VN_TZ)
    end_local = datetime(year + 1, 1, 1, tzinfo=VN_TZ)
    return (
        start_local.astimezone(timezone.utc).isoformat(),
        end_local.astimezone(timezone.utc).isoformat(),
    )


def _build_year_overview(conn: sqlite3.Connection, year: int) -> dict:
    """Tổng hợp câu hỏi và phản ánh dịch hại theo vùng trong một năm.

    ``disease_report_count`` là số câu hỏi được nhận diện có liên quan dịch hại,
    không phải số ca/diện tích dịch đã được cơ quan chuyên môn xác nhận.
    """
    start_iso, end_iso = _vn_year_bounds_utc(year)

    total_questions = conn.execute(
        "SELECT COUNT(*) FROM question_log WHERE ts >= ? AND ts < ?",
        (start_iso, end_iso),
    ).fetchone()[0]

    region_rows = conn.execute(
        """SELECT region,
                  COUNT(*) AS question_count,
                  SUM(
                    CASE
                      WHEN ai_is_disease = 1 THEN 1
                      WHEN ai_is_disease IS NULL AND COALESCE(NULLIF(pest, ''), '') != '' THEN 1
                      ELSE 0
                    END
                  ) AS disease_report_count
           FROM question_log
           WHERE ts >= ? AND ts < ?
             AND region IS NOT NULL AND region != ''
           GROUP BY region""",
        (start_iso, end_iso),
    ).fetchall()

    outbreak_rows = conn.execute(
        """SELECT region, COUNT(*)
           FROM alert_log
           WHERE first_ts < ? AND last_ts >= ?
             AND region IS NOT NULL AND region != ''
           GROUP BY region""",
        (end_iso, start_iso),
    ).fetchall()
    outbreak_counts = {row[0]: row[1] for row in outbreak_rows}

    region_stats = [
        {
            "region": row[0],
            "region_name": REGION_NAMES.get(row[0], row[0]),
            "question_count": int(row[1] or 0),
            "disease_report_count": int(row[2] or 0),
            "outbreak_count": int(outbreak_counts.get(row[0], 0)),
        }
        for row in region_rows
    ]

    questions_by_region = sorted(
        region_stats,
        key=lambda item: (-item["question_count"], item["region_name"]),
    )
    disease_reports_by_region = sorted(
        (item for item in region_stats if item["disease_report_count"] > 0),
        key=lambda item: (-item["disease_report_count"], item["region_name"]),
    )

    raw_years = conn.execute(
        """SELECT DISTINCT substr(ts, 1, 4) FROM question_log
           WHERE ts GLOB '[0-9][0-9][0-9][0-9]-*'
           UNION
           SELECT DISTINCT substr(first_ts, 1, 4) FROM alert_log
           WHERE first_ts GLOB '[0-9][0-9][0-9][0-9]-*'"""
    ).fetchall()
    available_years = {
        int(row[0])
        for row in raw_years
        if row[0] and row[0].isdigit() and 2000 <= int(row[0]) <= 2100
    }
    available_years.update({year, datetime.now(VN_TZ).year})

    return {
        "year": year,
        "available_years": sorted(available_years, reverse=True),
        "total_questions": int(total_questions or 0),
        "located_questions": sum(item["question_count"] for item in region_stats),
        "disease_report_count": sum(item["disease_report_count"] for item in region_stats),
        "questions_by_region": questions_by_region,
        "disease_reports_by_region": disease_reports_by_region,
        "note": "Số liệu dịch hại dựa trên câu hỏi người dùng, không phải thống kê dịch đã xác minh.",
    }


@router.get("/api/officer/alerts", dependencies=[Depends(_check_officer_token)])
def officer_alerts(
    days: int = Query(default=7, ge=1, le=90),
    year: int | None = Query(default=None, ge=2000, le=2100),
) -> dict:
    """Alert vùng dịch: nhóm theo (region, topic) trong N ngày, count >= ALERT_MIN_COUNT.

    Gọi classify_pending_questions() best-effort ở đầu handler để AI topic được cập nhật
    trước khi query — lỗi đã được nuốt bên trong hàm classify, không ảnh hưởng endpoint.
    Nguồn: question_log (topic = ai_topic hoặc fallback pest) UNION tickets (pest).
    Response: {"alerts": [...], "history": [...], "overview": {...}} — field
    "alerts" giữ nguyên shape cũ để tương thích dashboard cũ.
    """
    # Phân loại AI best-effort — lỗi đã nuốt bên trong, endpoint không bao giờ fail vì đây
    classify_pending_questions()

    min_count = int(os.getenv("ALERT_MIN_COUNT", "3"))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = _conn()
    try:
        rows = conn.execute(
            """SELECT region, COALESCE(NULLIF(ai_topic,''), pest), ts, text
               FROM question_log
               WHERE ts >= ?
                 AND (ai_is_disease=1 OR (pest IS NOT NULL AND pest != ''))
               UNION ALL
               SELECT region, pest, ts, question
               FROM tickets
               WHERE ts >= ? AND pest IS NOT NULL AND pest != ''""",
            (cutoff, cutoff),
        ).fetchall()
    finally:
        conn.close()

    # Nhóm theo (region, topic)
    groups: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for region, topic, ts, text in rows:
        if region and topic:
            groups[(region, topic)].append((ts or "", text or ""))

    qualifying_alerts = []
    for (region, topic), entries in groups.items():
        if len(entries) >= min_count:
            entries_sorted = sorted(entries, key=lambda x: x[0], reverse=True)
            sample_questions = [e[1] for e in entries_sorted[:3] if e[1]]
            qualifying_alerts.append(
                {
                    "region": region,
                    "region_name": REGION_NAMES.get(region, region),
                    "topic": topic,
                    "count": len(entries),
                    "latest_ts": entries_sorted[0][0],
                    "sample_questions": sample_questions,
                }
            )
    # Chỉ giữ tối đa 5 alert MỚI NHẤT (theo latest_ts) — yêu cầu user 18/07:
    # cán bộ xem nhanh điểm nóng hiện thời, còn toàn cảnh nằm ở tab "Lịch sử".
    qualifying_alerts.sort(key=lambda x: x["latest_ts"], reverse=True)
    alerts = qualifying_alerts[:5]

    # Upsert vào alert_log (best-effort — lỗi đã nuốt bên trong)
    conn = _conn()
    try:
        # Lưu mọi nhóm đủ ngưỡng để thống kê năm không bị lệch bởi giới hạn 5 dòng UI.
        _upsert_alert_log(conn, qualifying_alerts, now_iso)
    finally:
        conn.close()

    # Lấy history: toàn bộ đợt alert, sort last_ts desc, limit 30
    # active = True khi (region,topic) đang trong mọi nhóm đủ ngưỡng VÀ đợt còn trong cửa sổ 7 ngày
    # (đợt cũ cùng key nhưng last_ts > 7 ngày trước = đã kết thúc → active=False)
    active_keys = {(a["region"], a["topic"]) for a in qualifying_alerts}
    outbreak_gap_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    conn = _conn()
    try:
        hist_rows = conn.execute(
            "SELECT region, topic, first_ts, last_ts, peak_count FROM alert_log ORDER BY last_ts DESC LIMIT 30"
        ).fetchall()
    finally:
        conn.close()

    history = [
        {
            "region": r[0],
            "region_name": REGION_NAMES.get(r[0], r[0]),
            "topic": r[1],
            "first_ts": r[2],
            "last_ts": r[3],
            "peak_count": r[4],
            "active": (r[0], r[1]) in active_keys and (r[3] or "") >= outbreak_gap_cutoff,
        }
        for r in hist_rows
    ]

    selected_year = year or datetime.now(VN_TZ).year
    conn = _conn()
    try:
        overview = _build_year_overview(conn, selected_year)
    finally:
        conn.close()

    return {"alerts": alerts, "history": history, "overview": overview}

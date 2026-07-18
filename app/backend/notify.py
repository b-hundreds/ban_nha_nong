"""Thông báo ticket handoff đã được cán bộ trả lời (SMTP email + Zalo OA).

Nguyên tắc: KHÔNG bao giờ raise ra ngoài endpoint — lỗi chỉ log.
Hàm `notify_ticket_answered` luôn trả về chuỗi notified_via.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.header import Header
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def notify_ticket_answered(ticket: dict) -> str:
    """Gửi thông báo khi ticket được cán bộ trả lời.

    Trả về: "email", "zalo", "email,zalo", hoặc "none".
    Không bao giờ raise — lỗi chỉ log.
    """
    channels: list[str] = []

    smtp_host = os.getenv("SMTP_HOST", "").strip()
    if smtp_host and ticket.get("contact_email"):
        try:
            _send_email(ticket)
            channels.append("email")
            logger.info("Đã gửi email thông báo ticket %s", ticket.get("id"))
        except Exception:
            logger.exception("Gửi email thất bại cho ticket %s", ticket.get("id"))

    zalo_token = os.getenv("ZALO_OA_ACCESS_TOKEN", "").strip()
    if zalo_token and ticket.get("contact_phone"):
        try:
            _send_zalo(ticket, zalo_token)
            channels.append("zalo")
            logger.info("Đã gửi Zalo thông báo ticket %s", ticket.get("id"))
        except Exception:
            logger.exception("Gửi Zalo thất bại cho ticket %s", ticket.get("id"))
    else:
        if not zalo_token:
            logger.debug("zalo skipped — ZALO_OA_ACCESS_TOKEN chưa đặt")

    return ",".join(channels) if channels else "none"


# ---------------------------------------------------------------------------
# Helpers nội bộ
# ---------------------------------------------------------------------------

def _body_text(ticket: dict) -> str:
    """Tạo nội dung thông báo tiếng Việt."""
    question = ticket.get("question") or ticket.get("transcript", "")
    answer = ticket.get("answer", "")
    answered_by = ticket.get("answered_by", "Cán bộ khuyến nông")
    contact_name = ticket.get("contact_name", "bác")
    return (
        f"Kính gửi {contact_name},\n\n"
        f"Cán bộ khuyến nông đã trả lời câu hỏi của bác:\n\n"
        f"Câu hỏi: {question}\n\n"
        f"Trả lời: {answer}\n\n"
        f"Cán bộ trả lời: {answered_by}\n\n"
        f"Trân trọng,\nĐội hỗ trợ Bạn Nhà Nông"
    )


def _send_email(ticket: dict) -> None:
    """Gửi email qua SMTP (STARTTLS)."""
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)

    msg = MIMEText(_body_text(ticket), "plain", "utf-8")
    msg["Subject"] = str(Header("Cán bộ khuyến nông đã trả lời câu hỏi của bác", "utf-8"))
    msg["From"] = smtp_from
    msg["To"] = ticket["contact_email"]

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.send_message(msg)


def _send_zalo(ticket: dict, token: str) -> None:
    """Gửi tin nhắn Zalo OA CS message (httpx sync, timeout 10s)."""
    import httpx  # import lazily để không block import khi httpx chưa cài

    text = _body_text(ticket)
    httpx.post(
        "https://openapi.zalo.me/v3.0/oa/message/cs",
        headers={"access_token": token},
        json={
            "recipient": {"user_id": ticket.get("contact_phone", "")},
            "message": {"text": text},
        },
        timeout=10,
    )

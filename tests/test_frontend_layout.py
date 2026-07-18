import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "app" / "web" / "app.css").read_text(encoding="utf-8")
SERVICE_WORKER = (ROOT / "app" / "web" / "sw.js").read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]+)\}}", CSS)
    assert match is not None, f"Khong tim thay CSS rule {selector}"
    return match.group("body")


def test_chat_shell_khoa_theo_chieu_cao_viewport():
    shell = _rule(".app-shell")
    assert "height: 100dvh" in shell
    assert "overflow: hidden" in shell


def test_cot_chat_khong_no_theo_noi_dung():
    panel = _rule(".main-panel")
    assert "height: 100%" in panel
    assert "min-height: 0" in panel
    assert "overflow: hidden" in panel
    assert "grid-template-rows: auto minmax(0, 1fr) auto" in panel


def test_chi_vung_tin_nhan_duoc_cuon():
    chat = _rule(".chat")
    assert "min-height: 0" in chat
    assert "overflow-y: auto" in chat


def test_service_worker_doi_cache_sau_khi_sua_layout():
    assert 'CACHE_NAME = "bnn-shell-v12"' in SERVICE_WORKER

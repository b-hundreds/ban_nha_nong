import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "app" / "web" / "app.css").read_text(encoding="utf-8")
SERVICE_WORKER = (ROOT / "app" / "web" / "sw.js").read_text(encoding="utf-8")
INDEX = (ROOT / "app" / "web" / "index.html").read_text(encoding="utf-8")
LANDING = (ROOT / "app" / "web" / "landing.html").read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    match = re.search(
        rf"(?m)^\s*{re.escape(selector)}\s*\{{(?P<body>[^}}]+)\}}",
        CSS,
    )
    assert match is not None, f"Khong tim thay CSS rule {selector}"
    return match.group("body")


def test_chat_shell_khoa_theo_chieu_cao_viewport():
    page = _rule("html,\nbody")
    assert "width: 100%" in page
    assert "height: 100%" in page
    assert "min-height: 0" in page
    shell = _rule(".app-shell")
    assert "height: 100vh" in shell
    assert "height: 100dvh" in shell
    assert "max-height: 100dvh" in shell
    assert "min-height: 0" in shell
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


def test_sidebar_va_composer_khong_lam_no_chieu_cao():
    sidebar = _rule(".sidebar")
    assert "height: 100%" in sidebar
    assert "min-height: 0" in sidebar
    assert "overflow: hidden" in sidebar
    composer = _rule(".composer-wrap")
    assert "position: relative" in composer
    assert "min-height: 0" in composer
    assert "overflow: visible" in composer


def test_service_worker_doi_cache_sau_khi_sua_layout():
    assert 'CACHE_NAME = "bnn-shell-v26"' in SERVICE_WORKER
    assert '"/chat?app=v26"' in SERVICE_WORKER
    assert 'request.mode === "navigate" || CHAT_SHELL_PATHS.has(url.pathname)' in SERVICE_WORKER


def test_chat_assets_va_link_landing_co_version_de_bo_qua_cache_cu():
    assert 'href="app.css?v=26"' in INDEX
    assert 'src="app.js?v=26"' in INDEX
    assert 'href="/chat?app=v26"' in LANDING


def test_uploaded_images_are_right_aligned_above_user_message():
    assert ".user-image-gallery" in CSS
    assert "justify-content: flex-end" in CSS
    assert "flex: 0 1 160px" in CSS

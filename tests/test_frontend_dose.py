from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "app" / "web" / "app.js").read_text(encoding="utf-8")
APP_CSS = (ROOT / "app" / "web" / "app.css").read_text(encoding="utf-8")


def test_frontend_hien_lieu_cu_the_va_thoi_gian_cach_ly():
    assert "`Liều dùng: ${segment.dose_text}`" in APP_JS
    assert "`Thời gian cách ly: ${segment.phi_days} ngày`" in APP_JS
    assert "segment.note !== segment.dose_text" in APP_JS
    assert 'source.textContent = "Nguồn liều"' in APP_JS


def test_lieu_duoc_lam_noi_bat_thay_vi_chi_hien_note():
    assert ".dose-guidance" in APP_CSS
    assert ".dose-phi" in APP_CSS
    assert ".dose-source" in APP_CSS

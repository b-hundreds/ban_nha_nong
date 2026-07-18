"""P1-F: nối get_dose (labels.db) vào phiếu thuốc đường A trong pipeline.py.

Dùng fixture labels.db build bằng ingest.build_labels.build_labels với CSV nhỏ
trong tmp_path (monkeypatch pipeline.LABELS_DB_PATH) — KHÔNG phụ thuộc data/labels.db
thật (đang được cán bộ kỹ thuật curate song song, có thể chưa sẵn sàng/đang đổi)."""
from pathlib import Path

from ingest.build_labels import build_labels
from app.backend import pipeline

HDR = ("product_trade_name,formulation,ai_name,crop,pest,dose_text,water_text,"
       "phi_days,method,dose_unit,source_url,source_note,retrieved_at,entry_pass\n")

# lúa + rầy nâu -> registry.db thật trả về (thứ tự alphabet, top 5):
#   9X-Actione (4.3EC), A-Z annong (0.15EC), AMETINannong (5.55EC),
#   AMETINannong (10WP), ANB52 Super (100EC)
# NOTE: get_dose() chỉ khớp theo (trade_name, crop, pest) — KHÔNG phân biệt
# formulation — nên chọn "A-Z annong" (trade_name duy nhất trong top 5, không
# trùng với biến thể formulation khác như "AMETINannong") làm target, tránh
# ăn nhầm dose sang "AMETINannong 10WP".
_TARGET_TRADE = "A-Z annong"
_TARGET_FORM = "0.15EC"
_TARGET_LABEL = f"{_TARGET_TRADE} ({_TARGET_FORM})"
_DOSE_TEXT_DB = "1 - 1,5 lít/ha"
_WATER_TEXT_DB = "400 lít nước/ha"
_METHOD_DB = "phun đều tán lá"
_PHI_DAYS = "7"
_SOURCE_URL = "https://example.com/az-annong-0-15ec"

_ALL_LABELS_ORIGINAL_ORDER = [
    "9X-Actione (4.3EC)",
    _TARGET_LABEL,
    "AMETINannong (5.55EC)",
    "AMETINannong (10WP)",
    "ANB52 Super (100EC)",
]
_OTHER_LABELS_IN_ORDER = [p for p in _ALL_LABELS_ORIGINAL_ORDER if p != _TARGET_LABEL]


def _row(entry_pass: str, dose_text: str = _DOSE_TEXT_DB, phi_days: str = _PHI_DAYS) -> str:
    return (
        f"{_TARGET_TRADE},{_TARGET_FORM},Azadirachtin (min 15%),lúa,rầy nâu,"
        f'"{dose_text}","{_WATER_TEXT_DB}",{phi_days},{_METHOD_DB},lít/ha,'
        f"{_SOURCE_URL},nguồn test fixture P1-F,2026-07-18T10:00:00,{entry_pass}\n"
    )


def _build_labels_db(tmp_path: Path, csv_body: str) -> Path:
    csv_path = tmp_path / "labels_curated.csv"
    csv_path.write_text(HDR + csv_body, encoding="utf-8")
    db_path = tmp_path / "labels.db"
    conn, report = build_labels(csv_path, db_path)
    conn.close()
    return db_path, report


def _dose_blocks(result: dict) -> list[dict]:
    return [s for s in result["answer_segments"] if s["type"] == "dose_block"]


def test_dose_verified_hien_so_that_va_xep_len_dau(monkeypatch, tmp_path):
    db_path, report = _build_labels_db(tmp_path, _row("1") + _row("2"))
    assert report["n_verified"] == 1 and not report["mismatches"]
    monkeypatch.setattr(pipeline, "LABELS_DB_PATH", db_path)

    result = pipeline.answer("lúa bị rầy nâu xịt thuốc gì", "an_giang", "2026-07-18")
    blocks = _dose_blocks(result)
    assert len(blocks) == 1

    first = blocks[0]
    assert first["product"] == _TARGET_LABEL
    assert _DOSE_TEXT_DB in first["dose_text"]
    assert _WATER_TEXT_DB in first["dose_text"]
    assert _METHOD_DB in first["dose_text"]
    assert first["phi_days"] == 7
    assert first["source_url"] == _SOURCE_URL
    assert first["note"] == "Liều chép nguyên văn từ nhãn đăng ký"

    # Khi đã có ít nhất một liều verified, không trộn thêm sản phẩm placeholder.
    assert not any(b["dose_text"] == pipeline._DOSE_TEXT for b in blocks)


def test_lieu_nam_ngoai_top_5_van_duoc_chon(monkeypatch, tmp_path):
    trade_name = "Abachezt"
    formulation = "666WG"  # vị trí 9 trong registry lúa/rầy nâu, ngoài top 5 cũ

    def row(entry_pass: str) -> str:
        return (
            f"{trade_name},{formulation},Hoạt chất test,lúa,rầy nâu,"
            f'"250 g/ha","400 lít nước/ha",7,phun,kg/ha,'
            f"https://example.com/abachezt,nguồn test,2026-07-18T10:00:00,{entry_pass}\n"
        )

    db_path, report = _build_labels_db(tmp_path, row("1") + row("2"))
    assert report["n_verified"] == 1
    monkeypatch.setattr(pipeline, "LABELS_DB_PATH", db_path)

    result = pipeline.answer("lúa bị rầy nâu xịt thuốc gì", "an_giang", "2026-07-18")
    blocks = _dose_blocks(result)
    assert [block["product"] for block in blocks] == [f"{trade_name} ({formulation})"]
    assert blocks[0]["dose_text"].startswith("250 g/ha")


def test_khong_co_labels_db_van_placeholder_khong_loi(monkeypatch, tmp_path):
    missing_path = tmp_path / "khong_ton_tai.db"
    assert not missing_path.exists()
    monkeypatch.setattr(pipeline, "LABELS_DB_PATH", missing_path)

    result = pipeline.answer("lúa bị rầy nâu xịt thuốc gì", "an_giang", "2026-07-18")
    blocks = _dose_blocks(result)
    assert len(blocks) == 5
    for b in blocks:
        assert b["dose_text"] == pipeline._DOSE_TEXT
        assert b["phi_days"] is None
        assert b["note"] == pipeline._DOSE_NOTE
        assert b.get("source_url") is None
    # Thứ tự không đổi khi không có dose nào (không labels.db).
    assert [b["product"] for b in blocks] == _ALL_LABELS_ORIGINAL_ORDER


def test_dose_chua_verified_van_placeholder(monkeypatch, tmp_path):
    """Chỉ 1 entry_pass (không double-entry khớp) -> verified=0 -> vẫn placeholder."""
    db_path, report = _build_labels_db(tmp_path, _row("1"))
    assert report["n_verified"] == 0
    monkeypatch.setattr(pipeline, "LABELS_DB_PATH", db_path)

    result = pipeline.answer("lúa bị rầy nâu xịt thuốc gì", "an_giang", "2026-07-18")
    blocks = _dose_blocks(result)
    assert len(blocks) == 5
    for b in blocks:
        assert b["dose_text"] == pipeline._DOSE_TEXT
        assert b["phi_days"] is None
        assert b["note"] == pipeline._DOSE_NOTE
        assert b.get("source_url") is None
    assert [b["product"] for b in blocks] == _ALL_LABELS_ORIGINAL_ORDER


def test_get_dose_khong_tra_lieu_cua_quy_cach_khac(tmp_path, monkeypatch):
    """Bug thật 2026-07-18: '5 Lua' có nhiều quy cách (20WP, 3SL) — liều curate cho
    20WP từng hiển thị cho 3SL vì get_dose thiếu filter formulation. Cùng tên khác
    quy cách = khác nồng độ, TUYỆT ĐỐI không dùng chung liều."""
    import csv as _csv
    from pathlib import Path
    from ingest.build_labels import build_labels
    from app.backend import db as db_module

    rows = []
    for ep in (1, 2):
        rows.append({
            "product_trade_name": "5 Lua", "formulation": "20WP", "ai_name": "Polyoxin B",
            "crop": "lúa", "pest": "đạo ôn", "dose_text": "0.8 – 1.0 kg/ha",
            "water_text": "400 lít/ha", "phi_days": "5", "method": "phun", "dose_unit": "kg/ha",
            "source_url": "https://ppd.gov.vn/x", "source_note": "test", 
            "retrieved_at": "2026-07-18T09:00:00+07:00", "entry_pass": str(ep),
        })
    csv_path = tmp_path / "l.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    build_labels(csv_path, tmp_path / "labels.db")
    lconn = db_module.connect_labels(str(tmp_path / "labels.db"))

    assert db_module.get_dose(lconn, "5 Lua", "lúa", "đạo ôn", formulation="20WP") is not None
    assert db_module.get_dose(lconn, "5 Lua", "lúa", "đạo ôn", formulation="3SL") is None
    assert db_module.get_dose(lconn, "5 Lua", "lúa", "đạo ôn") is None  # không rõ quy cách -> không đưa liều

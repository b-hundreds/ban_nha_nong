from pathlib import Path
from ingest.build_labels import build_labels

HDR = ("product_trade_name,formulation,ai_name,crop,pest,dose_text,water_text,"
       "phi_days,method,dose_unit,source_url,source_note,retrieved_at,entry_pass\n")

def _row(p="Reasgant", dose="0,5 lít/ha", phi="7", ep="1", pest="rầy nâu"):
    return (f'{p},1.8EC,Abamectin,lúa,{pest},"{dose}",400 lít nước/ha,{phi},phun,'
            f"lít/ha,https://sansangxuatkhau.ppd.gov.vn/x,app CSDL QG,2026-07-18T09:00:00,{ep}\n")

def test_double_entry_match_verifies(tmp_path):
    csv = tmp_path / "l.csv"
    csv.write_text(HDR + _row(ep="1") + _row(ep="2"), encoding="utf-8")
    conn, rep = build_labels(csv, tmp_path / "labels.db")
    assert rep["n_verified"] == 1 and not rep["mismatches"]
    assert conn.execute("SELECT dose_min, dose_max, dose_unit FROM label_doses WHERE verified=1 AND entry_pass=1").fetchone() == (0.5, 0.5, "lít/ha")

def test_double_entry_mismatch_not_verified(tmp_path):
    csv = tmp_path / "l.csv"
    csv.write_text(HDR + _row(dose="0,5 lít/ha", ep="1") + _row(dose="1,5 lít/ha", ep="2"), encoding="utf-8")
    conn, rep = build_labels(csv, tmp_path / "labels.db")
    assert rep["n_verified"] == 0 and len(rep["mismatches"]) == 1

def test_missing_provenance_is_error(tmp_path):
    bad = _row().replace("https://sansangxuatkhau.ppd.gov.vn/x", "")
    csv = tmp_path / "l.csv"
    csv.write_text(HDR + bad, encoding="utf-8")
    _, rep = build_labels(csv, tmp_path / "labels.db")
    assert rep["errors"]

def test_dose_range_parsed(tmp_path):
    csv = tmp_path / "l.csv"
    csv.write_text(HDR + _row(dose="0,4-0,6 lít/ha", ep="1") + _row(dose="0,4-0,6 lít/ha", ep="2"), encoding="utf-8")
    conn, _ = build_labels(csv, tmp_path / "labels.db")
    assert conn.execute("SELECT dose_min,dose_max FROM label_doses LIMIT 1").fetchone() == (0.4, 0.6)

def test_sample_format_placeholder_guard(tmp_path):
    """Sample/format/placeholder rows excluded from verification."""
    csv = tmp_path / "l.csv"
    row1 = _row(ep="1").replace("app CSDL QG", "MẪU FORMAT — test")
    row2 = _row(ep="2").replace("app CSDL QG", "MẪU FORMAT — test")
    csv.write_text(HDR + row1 + row2, encoding="utf-8")
    _, rep = build_labels(csv, tmp_path / "labels.db")
    assert rep["n_verified"] == 0 and len(rep["errors"]) == 2

def test_duplicate_entry_pass_same_key(tmp_path):
    """Duplicate entry_pass for same key → error, not verified."""
    csv = tmp_path / "l.csv"
    csv.write_text(HDR + _row(ep="1") + _row(ep="1"), encoding="utf-8")
    _, rep = build_labels(csv, tmp_path / "labels.db")
    assert rep["n_verified"] == 0 and len(rep["errors"]) == 1

def test_duplicate_entry_pass_with_mismatch(tmp_path):
    """2×pass1 + 1×pass2 → duplicate detected, not verified."""
    csv = tmp_path / "l.csv"
    csv.write_text(HDR + _row(ep="1") + _row(ep="1", dose="1,5 lít/ha") + _row(ep="2"), encoding="utf-8")
    _, rep = build_labels(csv, tmp_path / "labels.db")
    assert rep["n_verified"] == 0 and len(rep["errors"]) == 1

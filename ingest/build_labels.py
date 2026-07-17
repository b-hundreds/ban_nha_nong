"""labels_curated.csv → labels.db, kiểm double-entry + provenance."""
import csv
import re
import sqlite3
from pathlib import Path

from ingest.normalize import parse_viet_number

DDL = """
CREATE TABLE label_doses(
  id INTEGER PRIMARY KEY,
  product_trade_name TEXT NOT NULL, formulation TEXT, ai_name TEXT NOT NULL,
  crop TEXT NOT NULL, pest TEXT NOT NULL,
  dose_text TEXT NOT NULL, water_text TEXT, phi_days INTEGER, method TEXT,
  dose_min REAL, dose_max REAL, dose_unit TEXT,
  source_url TEXT NOT NULL, source_note TEXT, retrieved_at TEXT NOT NULL,
  entry_pass INTEGER NOT NULL CHECK(entry_pass IN (1,2)),
  verified INTEGER NOT NULL DEFAULT 0);
"""

_RANGE = re.compile(r"(\d+(?:[.,]\d+)?)(?:\s*[-–]\s*(\d+(?:[.,]\d+)?))?")


def parse_dose(dose_text: str) -> tuple[float | None, float | None]:
    m = _RANGE.search(dose_text)
    if not m:
        return None, None
    lo = parse_viet_number(m.group(1))
    hi = parse_viet_number(m.group(2)) if m.group(2) else lo
    return lo, hi


def _key(r: dict) -> tuple:
    return (r["product_trade_name"].strip().lower(), r["crop"].strip().lower(), r["pest"].strip().lower())


def _dose_norm(r: dict) -> tuple:
    return (re.sub(r"\s+", " ", r["dose_text"].strip().lower()), r["phi_days"].strip())


def build_labels(csv_path: Path, out_path: Path):
    rows, errors = [], []
    sample_pattern = re.compile(r"MẪU|FORMAT|SAMPLE|PLACEHOLDER", re.IGNORECASE)
    with open(csv_path, encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f), start=2):
            if not r["source_url"].strip() or not r["retrieved_at"].strip():
                errors.append(f"dòng {i}: thiếu provenance (source_url/retrieved_at)")
                continue
            if r["entry_pass"] not in ("1", "2"):
                errors.append(f"dòng {i}: entry_pass phải là 1|2")
                continue
            if r["source_note"] and sample_pattern.search(r["source_note"]):
                errors.append(f"dòng {i}: source_note chứa từ mẫu (MẪU/FORMAT/SAMPLE/PLACEHOLDER) — không được phép")
                continue
            rows.append((i, r))
    by_key: dict[tuple, dict[str, tuple]] = {}
    dup_keys = set()
    for i, r in rows:
        key = _key(r)
        ep = r["entry_pass"]
        if key in by_key and ep in by_key[key]:
            errors.append(f"dòng {i}: trùng entry_pass={ep} cho {key}")
            dup_keys.add(key)
            continue
        by_key.setdefault(key, {})[ep] = (i, r)
    verified_keys, mismatches = set(), []
    for k, passes in by_key.items():
        if k in dup_keys:
            continue
        if "1" in passes and "2" in passes:
            if _dose_norm(passes["1"][1]) == _dose_norm(passes["2"][1]):
                verified_keys.add(k)
            else:
                mismatches.append(f"{k}: '{passes['1'][1]['dose_text']}' vs '{passes['2'][1]['dose_text']}'")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if Path(out_path).exists():
        Path(out_path).unlink()
    conn = sqlite3.connect(out_path)
    conn.executescript(DDL)
    for i, r in rows:
        lo, hi = parse_dose(r["dose_text"])
        conn.execute(
            """INSERT INTO label_doses(product_trade_name,formulation,ai_name,crop,pest,dose_text,
               water_text,phi_days,method,dose_min,dose_max,dose_unit,source_url,source_note,
               retrieved_at,entry_pass,verified) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["product_trade_name"].strip(), r["formulation"] or None, r["ai_name"].strip(),
             r["crop"].strip().lower(), r["pest"].strip().lower(), r["dose_text"].strip(),
             r["water_text"] or None, int(r["phi_days"]) if r["phi_days"].strip() else None,
             r["method"] or None, lo, hi, r["dose_unit"] or None,
             r["source_url"].strip(), r["source_note"] or None, r["retrieved_at"].strip(),
             int(r["entry_pass"]), 1 if _key(r) in verified_keys else 0))
    conn.commit()
    report = {"n_rows": len(rows), "n_products": len(by_key),
              "n_verified": len(verified_keys), "mismatches": mismatches, "errors": errors}
    return conn, report

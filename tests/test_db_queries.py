import sqlite3
from pathlib import Path
import pytest
from ingest.build_registry import build_registry
from ingest.build_aliases import load_aliases
from app.backend.db import lookup_products, check_product_status, resolve_alias

@pytest.fixture()
def conn(tmp_path):
    allowed = [
        {"ai": "Abamectin", "trade_name": "Reasgant", "formulation": "1.8EC",
         "registrant": "Cty A", "uses": [("sâu cuốn lá", "lúa"), ("rầy nâu", "lúa")], "pages": [3]},
    ]
    amend = tmp_path / "a.csv"
    amend.write_text("action,ai,trade_name,formulation,crop,pest,note\n", encoding="utf-8")
    c = build_registry(allowed, [], amend, tmp_path / "r.db")
    load_aliases(c, Path("data/aliases_seed.csv"))
    return c

def test_lookup_products_by_crop_pest(conn):
    hits = lookup_products(conn, "lúa", "rầy nâu", "2026-07-17")
    assert hits and hits[0].trade_name == "Reasgant"
    assert "75/2025/TT-BNNMT" in hits[0].cite

def test_lookup_no_match_returns_empty(conn):
    assert lookup_products(conn, "sầu riêng", "rầy xanh", "2026-07-17") == []

def test_check_product_status_fuzzy(conn):
    hit = check_product_status(conn, "reasgant 1.8 ec", "2026-07-17")
    assert hit and hit.status == "allowed"

def test_resolve_alias(conn):
    r = resolve_alias(conn, "rầy cám", "pest")
    assert r.canonical == "rầy nâu" and not r.ambiguous
    r2 = resolve_alias(conn, "cháy lá", "pest")
    assert r2.ambiguous  # phải hỏi lại, không tự map
    assert resolve_alias(conn, "xyz không tồn tại", "pest") is None

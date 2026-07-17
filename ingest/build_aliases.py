"""Nạp bảng alias phương ngữ (pest/crop/product) vào registry.db.

Bảng `aliases` ánh xạ cách gọi địa phương/tên gõ tắt sang tên chuẩn dùng
trong `uses`/`products`. Cột `ambiguous=1` đánh dấu các alias không nên tự
động map (nông dân gọi chung nhiều thứ) -- pipeline P1 phải hỏi lại người
dùng thay vì chọn đại 1 canonical.
"""
import csv
from pathlib import Path

DDL = """CREATE TABLE IF NOT EXISTS aliases(
  id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL CHECK(entity_type IN ('product','pest','crop')),
  canonical TEXT NOT NULL, alias TEXT NOT NULL, ambiguous INTEGER NOT NULL DEFAULT 0, note TEXT);"""


def load_aliases(conn, csv_path: Path) -> int:
    conn.executescript(DDL)
    n = 0
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conn.execute("INSERT INTO aliases(entity_type,canonical,alias,ambiguous,note) VALUES(?,?,?,?,?)",
                         (row["entity_type"], row["canonical"].lower(), row["alias"].lower(),
                          int(row["ambiguous"] or 0), row.get("note") or None))
            n += 1
    conn.commit()
    return n

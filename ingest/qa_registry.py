"""QA registry: lấy mẫu ngẫu nhiên ≥5% products, in kèm trang PDF để đối
chiếu tay; + các kiểm tra máy: trùng lặp, mồ côi, đếm theo status.

`products`/`uses` KHÔNG lưu trang PDF nguồn — `ingest.normalize.to_entries`
có tính `pages` (0-based, pdfplumber) cho từng entry, nhưng
`ingest.build_registry._insert_product` bỏ trường này khi ghi vào DB (không
có cột `page` trong DDL). Vì vậy `sample()` ở đây KHÔNG sửa build_registry
(ngoài phạm vi file được phép tạo của Task 7) mà dựng lại đúng cùng 1 phép
tính (`parse_pdf` + `to_entries` trên đúng 2 file trong `data/annex_files.json`
— y hệt `ingest.build_registry.main()`) rồi map ngược
(ai, trade_name, formulation) -> pages để đối chiếu tay.

Sản phẩm đến từ TT 28/2026 (`data/amendments_tt28_2026.csv`, action
`add_product`/`remove_product`) không nằm trong PDF TT75 nên không có
trang — cột `note` của CSV đó LUÔN là provenance (trích mục/trang/dòng phụ
lục TT28, xem docstring `build_registry`) nên dùng làm trích dẫn thay thế.
Vài dòng bị `change_registrant`/`change_ai` cập nhật tại chỗ (ai_id/registrant
đổi nhưng trade_name/formulation giữ nguyên) có thể không khớp đúng bộ ba
(ai, trade, formulation) đã parse ban đầu — fallback thêm 1 lượt tra theo
(trade_name, formulation) không kèm ai cho các trường hợp hiếm này.
"""
import csv
import json
import random
import sys
from pathlib import Path

from app.backend.db import connect
from ingest.normalize import reset_counters, to_entries
from ingest.parse_annex import parse_pdf

ANNEX_FILES = Path("data/annex_files.json")
AMENDMENTS_CSV = Path("data/amendments_tt28_2026.csv")


def machine_checks(conn) -> list[str]:
    problems = []
    dup = conn.execute("""SELECT trade_name, formulation, COUNT(*) c FROM products
                          WHERE status='allowed' AND effective_to IS NULL
                          GROUP BY trade_name, formulation, ai_id HAVING c>1""").fetchall()
    if dup:
        problems.append(f"{len(dup)} sản phẩm allowed trùng (trade+form+ai)")
    orphan = conn.execute("""SELECT COUNT(*) FROM uses u
                             LEFT JOIN products p ON p.id=u.product_id WHERE p.id IS NULL""").fetchone()[0]
    if orphan:
        problems.append(f"{orphan} uses mồ côi")
    empty_use = conn.execute("""SELECT COUNT(*) FROM products p WHERE p.status='allowed'
                                AND NOT EXISTS(SELECT 1 FROM uses u WHERE u.product_id=p.id)""").fetchone()[0]
    problems.append(f"INFO: {empty_use} sản phẩm allowed không có uses (kiểm tra parse cột target)")
    for status, cnt in conn.execute("SELECT status, COUNT(*) c FROM products GROUP BY status ORDER BY status"):
        problems.append(f"INFO: status={status}: {cnt} sản phẩm")
    for doc_id, so_hieu, cnt in conn.execute(
            """SELECT p.doc_id, d.so_hieu, COUNT(*) c FROM products p JOIN docs d ON d.id=p.doc_id
               GROUP BY p.doc_id ORDER BY p.doc_id"""):
        problems.append(f"INFO: doc_id={doc_id} ({so_hieu}): {cnt} sản phẩm")
    ai_cnt = conn.execute("SELECT COUNT(*) FROM active_ingredients").fetchone()[0]
    use_cnt = conn.execute("SELECT COUNT(*) FROM uses").fetchone()[0]
    problems.append(f"INFO: {ai_cnt} active_ingredients, {use_cnt} uses")
    return problems


def _pdf_page_index() -> tuple[dict, dict]:
    """Dựng lại (ai, trade_name, formulation) -> pages và fallback
    (trade_name, formulation) -> pages từ đúng 2 PDF nguồn TT75, y hệt
    ingest.build_registry.main() (parse_pdf + to_entries) — pages không lưu
    trong registry.db (xem docstring module)."""
    reset_counters()
    notes = json.loads(ANNEX_FILES.read_text())
    allowed = to_entries(parse_pdf(notes["allowed"]))
    banned = to_entries(parse_pdf(notes["banned"]), allow_no_trade=True)
    full: dict = {}
    fallback: dict = {}
    for e in allowed + banned:
        full.setdefault((e["ai"], e["trade_name"], e["formulation"]), e["pages"])
        fallback.setdefault((e["trade_name"], e["formulation"]), e["pages"])
    return full, fallback


def _tt28_note_index() -> dict:
    """(trade_name, formulation) -> note (provenance TT28) cho add_product/
    remove_product — sản phẩm này không nằm trong PDF TT75 nên không có
    trang pdfplumber."""
    idx: dict = {}
    if not AMENDMENTS_CSV.exists():
        return idx
    with open(AMENDMENTS_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["action"] in ("add_product", "remove_product"):
                idx[(row["trade_name"], row["formulation"] or None)] = row["note"]
    return idx


def _cite(r, pdf_idx, pdf_fallback, tt28_idx) -> str:
    key = (r[3], r[1], r[2])
    pages = pdf_idx.get(key)
    if pages is None:
        pages = pdf_fallback.get((r[1], r[2]))
    if pages:
        return f"pages={pages}"
    note = tt28_idx.get((r[1], r[2]))
    if note:
        return f"TT28 note={note!r}"
    return "pages=? (không dò được — kiểm tay scripts/inspect_pdf.py)"


def sample(conn, pct: float = 0.05, seed: int = 17):
    rows = conn.execute("""SELECT p.id, p.trade_name, p.formulation, ai.name_common
                           FROM products p JOIN active_ingredients ai ON ai.id=p.ai_id""").fetchall()
    rows = list(rows)
    random.Random(seed).shuffle(rows)
    take = rows[: max(30, int(len(rows) * pct))]
    pdf_idx, pdf_fallback = _pdf_page_index()
    tt28_idx = _tt28_note_index()
    for r in take:
        uses = conn.execute("SELECT crop,pest FROM uses WHERE product_id=?", (r[0],)).fetchall()
        cite = _cite(r, pdf_idx, pdf_fallback, tt28_idx)
        print(f"[{r[0]}] {r[1]} {r[2] or ''} | {r[3]} | {cite} | {[tuple(u) for u in uses]}")
    print(f"\nTổng mẫu: {len(take)} — đối chiếu từng dòng với PDF phụ lục, ghi kết quả vào docs/qa/p0-registry-qa.md")


if __name__ == "__main__":
    conn = connect()
    for p in machine_checks(conn):
        print("CHECK:", p)
    sample(conn, float(sys.argv[1]) if len(sys.argv) > 1 else 0.05)

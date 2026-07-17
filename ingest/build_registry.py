"""Nạp entries đã normalize vào registry.db với versioning hiệu lực.

CSV amendments hỗ trợ 5 action (brief gốc chỉ có 4; `change_ai` là mở rộng
tối thiểu — xem data/amendments_tt28_2026.csv và task-5-report.md mục
"Concerns"): remove_product, add_product, add_use, change_registrant,
change_ai.

Cột CSV: action,ai,trade_name,formulation,crop,pest,note,new_registrant,registrant.
`note` LUÔN là provenance (trích trang/mục phụ lục) — KHÔNG dùng để mang
giá trị nghiệp vụ. `new_registrant` mang giá trị tổ chức đăng ký mới cho
action `change_registrant` (tách riêng khỏi `note` so với code nháp trong
brief, vốn nạp `row["note"]` thẳng làm registrant mới — vi phạm yêu cầu
provenance bắt buộc của Step 1 trong brief). `registrant` (chỉ dùng ở
add_product) mang tổ chức đề nghị đăng ký của sản phẩm mới — code nháp
gốc trong brief hard-code registrant=None cho add_product; ở đây đọc
`row.get("registrant")` để không mất dữ liệu (đọc bằng .get để tương
thích ngược với CSV test không có cột này).
"""
import csv
import sqlite3
from pathlib import Path

DDL = """
CREATE TABLE docs(
  id INTEGER PRIMARY KEY, so_hieu TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
  url TEXT NOT NULL, effective_from TEXT NOT NULL, effective_to TEXT);
CREATE TABLE active_ingredients(id INTEGER PRIMARY KEY, name_common TEXT NOT NULL UNIQUE);
CREATE TABLE products(
  id INTEGER PRIMARY KEY, trade_name TEXT NOT NULL, formulation TEXT,
  ai_id INTEGER NOT NULL REFERENCES active_ingredients(id), registrant TEXT,
  status TEXT NOT NULL CHECK(status IN ('allowed','banned','removed')),
  doc_id INTEGER NOT NULL REFERENCES docs(id),
  effective_from TEXT NOT NULL, effective_to TEXT);
CREATE TABLE uses(
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
  crop TEXT NOT NULL, pest TEXT NOT NULL, doc_id INTEGER NOT NULL REFERENCES docs(id));
CREATE INDEX idx_uses_crop_pest ON uses(crop, pest);
CREATE INDEX idx_products_trade ON products(trade_name);
"""

DOCS = {
    "TT75": {"so_hieu": "75/2025/TT-BNNMT",
             "title": "Danh mục thuốc BVTV được phép/cấm sử dụng tại Việt Nam",
             "url": "https://vanban.chinhphu.vn/?docid=216337&pageid=27160",
             "effective_from": "2026-02-10"},
    "TT28": {"so_hieu": "28/2026/TT-BNNMT",
             "title": "Sửa đổi, bổ sung Danh mục thuốc BVTV (TT 75/2025)",
             "url": "https://datafiles.chinhphu.vn/cpp/files/duthaovbpl/2026/Thang4/2.1.-phu-luc-kem-theo-thong-tu.pdf",
             "effective_from": "2026-08-15"},
}
TT28_EFF = DOCS["TT28"]["effective_from"]


def _doc_id(conn, key):
    d = DOCS[key]
    conn.execute("INSERT OR IGNORE INTO docs(so_hieu,title,url,effective_from) VALUES(?,?,?,?)",
                 (d["so_hieu"], d["title"], d["url"], d["effective_from"]))
    return conn.execute("SELECT id FROM docs WHERE so_hieu=?", (d["so_hieu"],)).fetchone()[0]


def _ai_id(conn, name):
    conn.execute("INSERT OR IGNORE INTO active_ingredients(name_common) VALUES(?)", (name,))
    return conn.execute("SELECT id FROM active_ingredients WHERE name_common=?", (name,)).fetchone()[0]


def _insert_product(conn, e, status, doc_id, eff_from):
    aid = _ai_id(conn, e["ai"])
    cur = conn.execute(
        "INSERT INTO products(trade_name,formulation,ai_id,registrant,status,doc_id,effective_from) "
        "VALUES(?,?,?,?,?,?,?)",
        (e["trade_name"], e["formulation"], aid, e.get("registrant") or None, status, doc_id, eff_from))
    pid = cur.lastrowid
    for pest, crop in e.get("uses", []):
        conn.execute("INSERT INTO uses(product_id,crop,pest,doc_id) VALUES(?,?,?,?)",
                     (pid, crop, pest, doc_id))
    return pid


def build_registry(allowed, banned, amendments_csv: Path, out_path: Path) -> sqlite3.Connection:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    conn = sqlite3.connect(out_path)
    conn.executescript(DDL)
    d75, d28 = _doc_id(conn, "TT75"), _doc_id(conn, "TT28")
    eff75 = DOCS["TT75"]["effective_from"]
    for e in allowed:
        _insert_product(conn, e, "allowed", d75, eff75)
    for e in banned:
        _insert_product(conn, e, "banned", d75, eff75)
    with open(amendments_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            a = row["action"]
            if a == "remove_product":
                cur = conn.execute(
                    "UPDATE products SET effective_to=? WHERE trade_name=? "
                    "AND ifnull(formulation,'')=ifnull(?, '') AND status='allowed'",
                    (TT28_EFF, row["trade_name"], row["formulation"] or None))
                if cur.rowcount == 0:
                    # Fail-loudly (review Task 5c): trước đây lỗi này bị bỏ qua âm
                    # thầm -- dòng allowed cũ vẫn mở hiệu lực (không có gì bị đóng)
                    # trong khi 1 dòng "removed" mồ côi vẫn được chèn ở dưới, tạo
                    # audit trail sai (removed không khớp với bất kỳ allowed nào).
                    raise ValueError(
                        f"remove_product: khong tim thay dong allowed khop de dong "
                        f"hieu luc (trade_name={row['trade_name']!r}, "
                        f"formulation={row['formulation']!r})")
                _insert_product(conn, {"ai": row["ai"], "trade_name": row["trade_name"],
                                       "formulation": row["formulation"] or None,
                                       "registrant": None, "uses": []},
                                "removed", d28, TT28_EFF)
            elif a == "add_product":
                _insert_product(conn, {"ai": row["ai"], "trade_name": row["trade_name"],
                                       "formulation": row["formulation"] or None,
                                       "registrant": row.get("registrant") or None, "uses": []},
                                "allowed", d28, TT28_EFF)
            elif a == "add_use":
                # Lọc CẢ formulation (không chỉ trade_name): phát hiện khi verify
                # Task 5c sau khi tách Thiagold/Mekotin plus/Tiwepusa thành nhiều
                # dòng quy cách -- nếu chỉ lọc trade_name, "ORDER BY effective_from
                # DESC LIMIT 1" chọn ĐẠI 1 dòng quy cách rồi dồn TOÀN BỘ uses của
                # mọi quy cách vào đúng 1 dòng đó, các quy cách còn lại 0 use. Bug
                # này có sẵn từ Task 5 (ẩn vì trước đó hầu hết trade_name chỉ có 1
                # quy cách) -- lộ ra ngay khi Task 5b/5c sinh đúng nhiều dòng quy
                # cách cho 1 trade_name. Sửa cùng cách remove_product đã dùng
                # (ifnull(formulation,'')=ifnull(?, '')) để khớp đúng quy cách.
                found = conn.execute(
                    "SELECT id FROM products WHERE trade_name=? "
                    "AND ifnull(formulation,'')=ifnull(?, '') AND status='allowed' "
                    "ORDER BY effective_from DESC LIMIT 1",
                    (row["trade_name"], row["formulation"] or None)).fetchone()
                if found is None:
                    # Fail-loudly (review Task 5c): trước đây .fetchone()[0] ném
                    # TypeError ("NoneType is not subscriptable") khó hiểu -- nay
                    # báo rõ trade_name/formulation nào không khớp sản phẩm allowed.
                    raise ValueError(
                        f"add_use: khong tim thay san pham allowed voi "
                        f"trade_name={row['trade_name']!r} formulation={row['formulation']!r} "
                        f"(add_product phai chay truoc)")
                pid = found[0]
                conn.execute("INSERT INTO uses(product_id,crop,pest,doc_id) VALUES(?,?,?,?)",
                             (pid, row["crop"], row["pest"], d28))
            elif a == "change_registrant":
                # Review Task 5d: trước đây KHÔNG lọc formulation -> nếu 1
                # trade_name có nhiều quy cách allowed (vd Wasaki 250SC +
                # 500WG, Folpan 50WP + 50SC), 1 dòng CSV chỉ định đổi tổ
                # chức đăng ký cho ĐÚNG 1 quy cách (khớp nguyên văn PDF TT28,
                # vd "Wasaki 250SC") lại đổi LUÔN CẢ quy cách khác (500WG)
                # không liên quan -- sai. Nếu CSV có formulation (không rỗng)
                # -> lọc đúng quy cách đó; nếu formulation rỗng -> giữ hành
                # vi cũ (áp dụng mọi quy cách của trade_name) vì đó là ý
                # định nghiệp vụ thật cho các dòng không chỉ định quy cách.
                new_registrant = row.get("new_registrant") or row["note"]
                formulation = row.get("formulation") or None
                if formulation:
                    cur = conn.execute(
                        "UPDATE products SET registrant=? WHERE trade_name=? "
                        "AND ifnull(formulation,'')=ifnull(?, '') AND status='allowed'",
                        (new_registrant, row["trade_name"], formulation))
                else:
                    cur = conn.execute(
                        "UPDATE products SET registrant=? WHERE trade_name=? AND status='allowed'",
                        (new_registrant, row["trade_name"]))
                if cur.rowcount == 0:
                    raise ValueError(
                        f"change_registrant: khong tim thay dong allowed khop de doi to "
                        f"chuc dang ky (trade_name={row['trade_name']!r}, "
                        f"formulation={row['formulation']!r})")
            elif a == "change_ai":
                # Mở rộng tối thiểu ngoài 4 action gốc của brief: TT 28/2026 Phụ lục
                # I mục 2 đổi chính hoạt chất/thành phần của một sản phẩm đã có, không
                # phải đổi tổ chức đăng ký (change_registrant) hay thêm/rút sản phẩm.
                # Cùng lỗ hổng + cùng fix như change_registrant ở trên (Task 5d):
                # lọc formulation khi CSV có giá trị, giữ hành vi cũ khi rỗng.
                aid = _ai_id(conn, row["ai"])
                formulation = row.get("formulation") or None
                if formulation:
                    cur = conn.execute(
                        "UPDATE products SET ai_id=? WHERE trade_name=? "
                        "AND ifnull(formulation,'')=ifnull(?, '') AND status='allowed'",
                        (aid, row["trade_name"], formulation))
                else:
                    cur = conn.execute(
                        "UPDATE products SET ai_id=? WHERE trade_name=? AND status='allowed'",
                        (aid, row["trade_name"]))
                if cur.rowcount == 0:
                    raise ValueError(
                        f"change_ai: khong tim thay dong allowed khop de doi hoat chat "
                        f"(trade_name={row['trade_name']!r}, "
                        f"formulation={row['formulation']!r})")
    conn.commit()
    return conn


def main():
    from ingest.parse_annex import parse_pdf
    from ingest.normalize import reset_counters, to_entries
    import json
    # Minor (Task 5d): counter QA module-level (orphan_drop_count v.v.) tích
    # luỹ qua nhiều lần gọi to_entries trong CÙNG 1 tiến trình -- reset ở
    # ranh giới 1 lần build MỚI để số đếm in ra phản ánh ĐÚNG lần build này,
    # không cộng dồn từ lần import/gọi trước đó (vd chạy nhiều lần trong
    # cùng 1 REPL/test process).
    reset_counters()
    annex_files = Path("data/annex_files.json")
    notes = json.loads(annex_files.read_text())  # {"allowed": "...", "banned": "..."}
    allowed = to_entries(parse_pdf(notes["allowed"]))
    banned = to_entries(parse_pdf(notes["banned"]), allow_no_trade=True)
    conn = build_registry(allowed, banned, Path("data/amendments_tt28_2026.csv"), Path("data/registry.db"))
    for t in ("active_ingredients", "products", "uses"):
        print(t, conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
    print("products by status:")
    for status, cnt in conn.execute("SELECT status, COUNT(*) FROM products GROUP BY status"):
        print(" ", status, cnt)
    # Fix Task 5g (Finding 2, review Task 5f): `build_registry` DROP+rebuild
    # toàn bộ `data/registry.db` (không có DDL cho bảng `aliases` trong DDL ở
    # trên) -- bảng này trước đây được nạp RIÊNG bằng tay qua
    # `ingest.build_aliases.load_aliases`, nên mỗi lần rebuild registry đều
    # xoá mất bảng `aliases` cho tới khi ai đó chạy lại bước nạp thủ công ->
    # `app/backend/pipeline.py` vỡ ("no such table: aliases") ngay sau khi
    # rebuild, phát hiện qua `tests/test_api.py`. Nạp lại NGAY tại đây (import
    # cục bộ, tránh vòng import nếu `ingest.build_aliases` từng cần import
    # ngược `ingest.build_registry` trong tương lai) để `main()` luôn để lại
    # 1 `registry.db` đầy đủ, không phụ thuộc bước tay nào khác.
    from ingest.build_aliases import load_aliases
    n_aliases = load_aliases(conn, Path("data/aliases_seed.csv"))
    print("aliases", n_aliases)


if __name__ == "__main__":
    main()

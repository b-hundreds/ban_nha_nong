"""Sinh lại các dòng add_product/add_use của data/amendments_tt28_2026.csv
từ data/raw/tt28_2026_phuluc.pdf (Phụ lục II, trang pdfplumber 2-19), dùng
ĐÚNG các primitive đã vá ở Task 5b:
  - ingest.parse_annex: is_header_row, is_section_marker_row, _row_to_fields,
    _recover_missing_leading_cells (bug 1 — ô gộp đầu file, không áp dụng ở
    đây nhưng tái dùng cho đồng nhất/an toàn nếu PDF có case tương tự).
  - ingest.normalize: split_formulations, _assign_uses (bug 2 — cell nhiều
    quy cách không tách, đây chính là bug gây garble ở CSV cũ).

Vì sao cần script riêng thay vì gọi thẳng `ingest.parse_annex.parse_pdf` +
`ingest.normalize.to_entries`: 2 hàm đó không expose "mục" (section, ví dụ
"1. Thuốc trừ sâu") và "số trang in ở chân trang" (footer) cho từng entry —
2 thông tin BẮT BUỘC để dựng lại đúng cột `note` theo định dạng đã dùng
trong CSV hiện tại ("TT28 PL.II {section} tr.{footer}"). Script này mirror
lại đúng vòng lặp của `to_entries` (không đổi thuật toán) nhưng gắn thêm
section/footer vào entry lúc tạo, gọi lại NGUYÊN các hàm nghiệp vụ đã vá.

Cách dùng:
  .venv/bin/python scripts/regen_tt28_adds.py            # chỉ report diff
  .venv/bin/python scripts/regen_tt28_adds.py --write     # ghi lại CSV

Diff strategy: so khớp (ai, trade_name, formulation, registrant, note,
uses) giữa 348 khối add_product/add_use HIỆN CÓ trong CSV và khối SINH LẠI
từ PDF bằng difflib.SequenceMatcher (thứ tự tài liệu phải khớp giữa 2 bên
trừ đúng những chỗ bug). Khối "equal" -> GIỮ NGUYÊN dòng CSV gốc (không tái
serialize, tránh xáo trộn định dạng/quoting). Khối khác -> THAY bằng khối
sinh lại từ PDF. 27 dòng tay (remove_product/change_registrant/change_ai)
và header giữ nguyên vị trí đầu file, không đụng tới.
"""
import argparse
import csv
import difflib
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.parse_annex import (  # noqa: E402
    FIELDS_FULL,
    _norm,
    _recover_missing_leading_cells,
    _row_to_fields,
    is_header_row,
    is_section_marker_row,
)
from ingest.normalize import _assign_uses, split_formulations  # noqa: E402

PDF_PATH = Path("data/raw/tt28_2026_phuluc.pdf")
CSV_PATH = Path("data/amendments_tt28_2026.csv")
# "trang pdfplumber 2-19" theo brief == range Python [2, 20).
PL2_PAGE_START, PL2_PAGE_END = 2, 20


def extract_pl2_raw_rows(pdf_path: Path) -> list[dict]:
    """Tương đương `ingest.parse_annex.rows_from_tables` áp dụng cho đúng
    dải trang Phụ lục II, nhưng có thêm theo dõi 'section' (mục con, vd '1.
    Thuốc trừ sâu') và 'footer' (số trang in ở chân trang PDF thật — xác
    nhận bằng thực nghiệm footer = pdfplumber_index - 1, khớp đúng cột
    'tr.N' của mọi note add_product/add_use hiện có trong CSV, vd trang
    pdfplumber idx=9 có chân trang '8' == 'TT28 PL.II ... tr.8' của
    Thiagold). Dùng NGUYÊN is_header_row/is_section_marker_row/_row_to_fields
    đã review/test — không viết lại logic lọc hàng."""
    rows: list[dict] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        section = None
        for idx in range(PL2_PAGE_START, PL2_PAGE_END):
            page = pdf.pages[idx]
            footer = idx - 1
            for table in page.find_tables():
                texts_per_row = table.extract()
                texts_per_row = _recover_missing_leading_cells(page, table, texts_per_row)
                for cells in texts_per_row:
                    if is_header_row(cells):
                        continue
                    if is_section_marker_row(cells):
                        section = _norm(cells[0])
                        continue
                    row = _row_to_fields(cells, fields=FIELDS_FULL)
                    if not any([row["tt"], row["ai"], row["trade"], row["target"]]):
                        continue
                    row["page"] = idx
                    row["section"] = section
                    row["footer"] = footer
                    rows.append(row)
    return rows


def to_entries_with_note(rows: list[dict]) -> list[dict]:
    """Mirror đúng vòng lặp của `ingest.normalize.to_entries` (KHÔNG đổi
    thuật toán — gọi lại NGUYÊN `split_formulations`/`_assign_uses` đã vá ở
    Task 5b) nhưng gắn thêm 'section'/'footer' vào entry lúc tạo (để dựng
    note), thay cho 'pages' (không cần cho CSV notes ở đây)."""
    entries: list[dict] = []
    cur_group: list[dict] | None = None
    orphans = 0
    for r in rows:
        if r["ai"]:
            ai = " ".join(r["ai"].split())
        elif cur_group is not None:
            ai = cur_group[0]["ai"]
        else:
            orphans += 1
            print(f"CANH BAO: dong mo coi (chua co hoat chat) trong PL.II, "
                  f"page={r.get('page')} trade={r.get('trade')!r}", file=sys.stderr)
            continue
        # registrant trong ô PDF có thể bị wrap dòng (vd "Công ty TNHH BVTV\nHoàng
        # Anh") -- join whitespace giống hệt cách xử lý ai/trade (và giống cách
        # CSV hiện có đã được sinh: 0 dòng registrant nào trong CSV cũ có "\n"
        # nhúng) để không tạo diff giả do wrap dòng, không phải do bug tách quy
        # cách. Không đổi ingest.normalize.to_entries (out of scope) -- đây chỉ
        # là chuẩn hoá cục bộ trong script sinh CSV.
        registrant = " ".join(r["registrant"].split()) if r["registrant"] else r["registrant"]
        if r["trade"]:
            name, forms = split_formulations(" ".join(r["trade"].split()))
            cur_group = []
            for form in (forms or [None]):
                e = {"ai": ai, "trade_name": name, "formulation": form,
                     "registrant": registrant, "uses": [],
                     "section": r["section"], "footer": r["footer"]}
                entries.append(e)
                cur_group.append(e)
        if cur_group is None:
            continue
        _assign_uses(cur_group, r["target"])
        for e in cur_group:
            if registrant and not e["registrant"]:
                e["registrant"] = registrant
    if orphans:
        print(f"CANH BAO TONG: {orphans} dong mo coi bi bo qua trong PL.II "
              f"(xem chi tiet o tren) -- kiem tra du lieu PDF truoc khi tin ket qua.",
              file=sys.stderr)
    return entries


def entry_to_rows(e: dict) -> tuple[dict, list[dict]]:
    """Dựng (product_row, [use_rows]) đúng 9 cột CSV hiện có. GUARD: fail
    loudly nếu trade_name còn dấu phẩy hoặc còn sót mã quy cách (nghĩa là
    split_formulations chưa tách hết) — không được âm thầm sinh lại dữ liệu
    garble kiểu cũ."""
    if "," in e["trade_name"]:
        raise ValueError(f"GUARD FAIL: trade_name con dau phay: {e['trade_name']!r}")
    clean_name, leftover_forms = split_formulations(e["trade_name"])
    if leftover_forms or clean_name != e["trade_name"]:
        raise ValueError(
            f"GUARD FAIL: trade_name con sot ma quy cach chua tach: {e['trade_name']!r} "
            f"(leftover_forms={leftover_forms!r})")
    note = f"TT28 PL.II {e['section']} tr.{e['footer']}"
    product = {"action": "add_product", "ai": e["ai"], "trade_name": e["trade_name"],
               "formulation": e["formulation"] or "", "crop": "", "pest": "",
               "note": note, "new_registrant": "", "registrant": e["registrant"] or ""}
    uses = [{"action": "add_use", "ai": e["ai"], "trade_name": e["trade_name"],
             "formulation": e["formulation"] or "", "crop": crop, "pest": pest,
             "note": note, "new_registrant": "", "registrant": ""}
            for pest, crop in e["uses"]]
    return product, uses


def group_key(product: dict, uses: list[dict]) -> tuple:
    return (product["ai"], product["trade_name"], product["formulation"],
            product["registrant"], product["note"],
            tuple((u["crop"], u["pest"]) for u in uses))


def load_existing(csv_path: Path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    preamble = [r for r in rows if r["action"] not in ("add_product", "add_use")]
    groups = []
    cur = None
    for r in rows:
        if r["action"] == "add_product":
            cur = {"product": r, "uses": []}
            groups.append(cur)
        elif r["action"] == "add_use":
            cur["uses"].append(r)
    return fieldnames, preamble, groups


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                     help="ghi ket qua vao data/amendments_tt28_2026.csv (mac dinh chi report)")
    args = ap.parse_args()

    fieldnames, preamble, old_groups = load_existing(CSV_PATH)
    raw_rows = extract_pl2_raw_rows(PDF_PATH)
    entries = to_entries_with_note(raw_rows)
    new_groups = [dict(zip(("product", "uses"), entry_to_rows(e))) for e in entries]

    old_keys = [group_key(g["product"], g["uses"]) for g in old_groups]
    new_keys = [group_key(g["product"], g["uses"]) for g in new_groups]

    sm = difflib.SequenceMatcher(a=old_keys, b=new_keys, autojunk=False)
    final_groups = []
    changed = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            final_groups.extend(old_groups[i1:i2])
            continue
        old_slice = old_groups[i1:i2]
        new_slice = new_groups[j1:j2]
        changed.append({
            "tag": tag,
            "old_trade_names": sorted({g["product"]["trade_name"] for g in old_slice}),
            "new_trade_names": sorted({g["product"]["trade_name"] for g in new_slice}),
            "old_count": len(old_slice), "new_count": len(new_slice),
        })
        final_groups.extend(new_slice)

    print(f"old add_product groups : {len(old_groups)}")
    print(f"new add_product groups : {len(new_groups)}  (regen tu PDF)")
    print(f"final add_product groups (sau merge): {len(final_groups)}")
    print(f"so khoi khac nhau: {len(changed)}")
    for c in changed:
        print(f"  [{c['tag']}] CU {c['old_count']} khoi {c['old_trade_names']}"
              f" -> MOI {c['new_count']} khoi {c['new_trade_names']}")

    if args.write:
        out_rows = list(preamble)
        for g in final_groups:
            out_rows.append(g["product"])
            out_rows.extend(g["uses"])
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\r\n")
            w.writeheader()
            w.writerows(out_rows)
        print(f"Da ghi lai {CSV_PATH}")


if __name__ == "__main__":
    main()

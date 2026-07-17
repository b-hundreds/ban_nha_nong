import json
from pathlib import Path

import pytest

from ingest.parse_annex import (
    FIELDS_BANNED,
    FIELDS_FULL,
    _detect_fields_from_tables,
    _header_col_bounds,
    _merge_split_columns,
    _recover_missing_leading_cells,
    _row_to_fields,
    is_header_row,
    is_section_marker_row,
    parse_pdf,
    rows_from_tables,
)

FIX = json.loads(Path("tests/fixtures/annex_sample.json").read_text(encoding="utf-8"))
PAGES = {p["page"]: p["rows"] for p in FIX["pages"]}
PAGES_ANNEX2 = {p["page"]: p["rows"] for p in FIX["pages_annex2"]}

MERGED = json.loads(Path("tests/fixtures/annex_merged_cell_sample.json").read_text(encoding="utf-8"))
GLOBAL = json.loads(Path("tests/fixtures/annex_global_bounds_sample.json").read_text(encoding="utf-8"))

ANNEX1 = Path("data/raw/tt75_2025_page_1.pdf")
ANNEX2 = Path("data/raw/tt75_2025_page_2.pdf")


class _FakeRow:
    """Giả lập tối thiểu `pdfplumber.table.Row` — chỉ cần .bbox và .cells
    (list bbox-tuple hoặc None) để test `_header_col_bounds` và
    `_recover_missing_leading_cells` mà không cần PDF thật."""

    def __init__(self, spec: dict):
        self.bbox = tuple(spec["bbox"])
        self.cells = [tuple(c) if c is not None else None for c in spec["cells"]]


class _FakeTable:
    def __init__(self, row_specs: list[dict]):
        self.rows = [_FakeRow(s) for s in row_specs]


class _FakeCrop:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


class _FakePage:
    """Giả lập tối thiểu `pdfplumber.Page.within_bbox` — trả lại đúng text
    THẬT đã chụp 1 lần từ PDF gốc (tests/fixtures/annex_merged_cell_sample.json,
    mục "recovered_crops") cho ĐÚNG toạ độ bbox mà `_recover_missing_leading_cells`
    sẽ tính ra (x-range cột theo header thật + y-range hàng thật) — không bịa
    dữ liệu, chỉ đóng vai trò tra cứu lại giá trị đã đo được bằng thực nghiệm."""

    def __init__(self, crop_texts: dict):
        self.crop_texts = crop_texts

    def within_bbox(self, bbox, relative=False):
        x0, top, x1, bottom = bbox
        key = f"{round(x0, 2)},{round(top, 2)},{round(x1, 2)},{round(bottom, 2)}"
        return _FakeCrop(self.crop_texts.get(key, ""))


def test_header_row_detected():
    assert is_header_row(["TT", "Hoạt chất", "Tên thương phẩm", "Đối tượng phòng trừ", "Tổ chức"])
    assert not is_header_row(["1", "Abamectin", "Reasgant 1.8EC", "sâu cuốn lá/lúa", "X"])


def test_section_marker_row_detected():
    assert is_section_marker_row(["I. THUỐC SỬ DỤNG TRONG NÔNG NGHIỆP:", None, None, None, None])
    assert is_section_marker_row(["1. Thuốc trừ sâu:", None, None, None, None])
    # hàng dữ liệu thật không được coi là section marker dù tt/ai rỗng
    assert not is_section_marker_row([None, None, "Ababetter 5EC", "nhện đỏ/ quýt", "Cty X"])
    # Phụ lục II: hàng tiêu đề mục 2 cột, ô thứ 2 là None (không phải "")
    assert is_section_marker_row(["Thuốc trừ sâu, thuốc bảo quản lâm sản", None])


def test_rows_from_tables_page0_keeps_continuation_and_drops_headers():
    rows = rows_from_tables(PAGES[0], page=0)
    assert all(set(r) == {"tt", "ai", "trade", "target", "registrant", "page"} for r in rows)
    # header cột và 2 hàng tiêu đề mục ("I. THUỐC SỬ DỤNG...", "1. Thuốc trừ sâu:") đều bị loại
    assert len(rows) == 10
    # hàng tiếp diễn: tt/ai rỗng nhưng trade vẫn có nội dung
    assert all(r["tt"] == "" and r["ai"] == "" for r in rows)
    assert all(r["trade"] for r in rows)
    assert not any(r["trade"] == "Tên thương phẩm" for r in rows)
    assert not any("THUỐC SỬ DỤNG" in r["trade"] or "Thuốc trừ sâu" in r["trade"] for r in rows)
    # ô nhiều dòng: giữ nguyên \n
    abakill = next(r for r in rows if r["trade"].startswith("Abakill"))
    assert "\n" in abakill["trade"]
    assert "\n" in abakill["target"]
    assert abakill["page"] == 0


def test_rows_from_tables_page6_missing_tt_ai_columns_entirely():
    # Trên trang này, cả trang không có mục mới -> pdfplumber trả về hàng chỉ 3 cột
    # (thiếu hẳn cột TT/hoạt chất, không phải chuỗi rỗng).
    assert all(len(r) == 3 for r in PAGES[6][1:])
    rows = rows_from_tables(PAGES[6], page=6)
    # hàng đầu ["", "", "Phong Phú"] chỉ có registrant -> bị loại (không any([tt,ai,trade,target]))
    assert not any(r["registrant"] == "Phong Phú" and r["trade"] == "" for r in rows)
    assert len(rows) == 7
    for r in rows:
        assert r["tt"] == ""
        assert r["ai"] == ""
        assert r["trade"] and r["target"] and r["registrant"]
    newsodant = next(r for r in rows if r["trade"].startswith("Newsodant"))
    assert "\n" in newsodant["trade"]


def test_rows_from_tables_page146_full_row_in_different_muc():
    rows = rows_from_tables(PAGES[146], page=146)
    assert len(rows) == 8
    full = [r for r in rows if r["tt"]]
    cont = [r for r in rows if not r["tt"]]
    assert len(full) == 4
    assert len(cont) == 4
    entry8 = next(r for r in full if r["tt"] == "8")
    assert entry8["ai"] == "Anacardic acid"
    assert entry8["trade"] == "Amtech 100EW"
    # hàng tiếp diễn của mục 8 (Amistar, Amistic, Anpro, Asiwon) không có tt/ai
    assert {r["trade"].split()[0] for r in cont} >= {"Amistar®", "Amistic", "Anpro", "Asiwon"}
    for r in cont:
        assert r["tt"] == "" and r["ai"] == ""


def test_rows_from_tables_annex2_two_column_schema():
    # Phụ lục II (danh mục cấm) chỉ có 2 cột thật: TT | Hoạt chất — không có
    # thương phẩm/đối tượng/tổ chức. Header + hàng tiêu đề mục phải bị loại,
    # còn dữ liệu phải map đúng tt/ai (không lệch sang trade/target như khi
    # dùng schema 5 cột mặc định).
    rows = rows_from_tables(PAGES_ANNEX2[0], page=0, fields=FIELDS_BANNED)
    assert len(rows) == 6
    assert all(set(r) == {"tt", "ai", "trade", "target", "registrant", "page"} for r in rows)
    assert all(r["trade"] == "" and r["target"] == "" and r["registrant"] == "" for r in rows)
    assert rows[0] == {"tt": "1", "ai": "Aldrin", "trade": "", "target": "", "registrant": "", "page": 0}
    assert not any(r["ai"] == "Aldrin" and r["tt"] != "1" for r in rows)
    assert not any("Thuốc trừ sâu" in r["ai"] for r in rows)


def test_row_to_fields_missing_columns_preserves_positional_gaps():
    # Hàng thiếu cột (len < n): ô GIỮA rỗng là dữ liệu thật (target rỗng),
    # KHÔNG được strip rồi right-align (sẽ đẩy "Ababetter 5EC" sang target).
    row = _row_to_fields(["Ababetter 5EC", "", "Cty X"], fields=FIELDS_FULL)
    assert row == {
        "tt": "",
        "ai": "",
        "trade": "Ababetter 5EC",
        "target": "",
        "registrant": "Cty X",
    }


def test_rows_from_tables_keeps_row_with_missing_columns_and_empty_middle_cell():
    # Hàng trên phải được GIỮ lại (trade non-empty) dù target rỗng.
    rows = rows_from_tables([["Ababetter 5EC", "", "Cty X"]], page=99)
    assert len(rows) == 1
    assert rows[0]["trade"] == "Ababetter 5EC"
    assert rows[0]["target"] == ""
    assert rows[0]["registrant"] == "Cty X"


def test_row_to_fields_noisy_15_column_row_from_real_page_324():
    # Trang 324 bị lỗi dò đường kẻ bảng thật, trả về hàng 15 cột với ô rỗng
    # chèn xen giữa — nội dung còn lại vẫn đúng thứ tự tt/ai/trade/target/registrant.
    cont_row, full_row = PAGES[324]
    assert len(full_row) == 15 and len(cont_row) == 15

    full = _row_to_fields(full_row, fields=FIELDS_FULL)
    assert full["tt"] == "8"
    assert full["ai"] == "Sulfur 33% + Carbon"
    assert full["trade"] == "Woolf cygar\n33%"
    assert full["target"] == "chuột/ trong hang"
    assert "Công ty CP Giải pháp Nông" in full["registrant"]

    cont = _row_to_fields(cont_row, fields=FIELDS_FULL)
    assert cont["tt"] == "" and cont["ai"] == ""
    assert cont["trade"] == "Ratcom Plus\n0.005% Block Bait"
    assert cont["target"] == "chuột/ đồng ruộng"
    assert cont["registrant"] == "Công ty CP US Farm Việt Nam"


def test_detect_fields_from_tables():
    # Header 5 cột (Phụ lục I) -> FIELDS_FULL
    assert _detect_fields_from_tables([PAGES[0]]) == FIELDS_FULL
    # Header 2 cột (Phụ lục II) -> FIELDS_BANNED
    assert _detect_fields_from_tables([PAGES_ANNEX2[0]]) == FIELDS_BANNED
    # Không có header trong phạm vi probe -> fallback FIELDS_FULL
    assert _detect_fields_from_tables([PAGES[6]]) == FIELDS_FULL
    assert _detect_fields_from_tables([]) == FIELDS_FULL


@pytest.mark.skipif(not ANNEX1.exists(), reason="cần data/raw (chạy ingest.download trước)")
def test_parse_pdf_real_annex1():
    rows = parse_pdf(str(ANNEX1), max_pages=8)
    assert 80 <= len(rows) <= 120
    assert all(set(r) == {"tt", "ai", "trade", "target", "registrant", "page"} for r in rows)
    assert any(r["trade"] == "Ababetter 5EC" for r in rows)


@pytest.mark.skipif(not ANNEX2.exists(), reason="cần data/raw (chạy ingest.download trước)")
def test_parse_pdf_real_annex2():
    rows = parse_pdf(str(ANNEX2))
    assert 25 <= len(rows) <= 40
    first = rows[0]
    assert first["tt"] == "1"
    assert first["ai"] == "Aldrin"
    assert first["trade"] == ""


# --- Bug 1 (Task 5b): khối "Abamectin" đầu Phụ lục I bị mất ai do PDF gốc
# dùng ô gộp (rowspan) không có đường kẻ ngang nội bộ -> pdfplumber không
# dựng được cell (None) cho cột ai ở MỌI hàng trong khối, kể cả hàng đầu nơi
# nội dung thật vẫn được vẽ trên trang. Dữ liệu dưới đây là bbox/text THẬT
# chép nguyên trạng từ data/raw/tt75_2025_page_1.pdf và tt75_2025_page_2.pdf
# (tests/fixtures/annex_merged_cell_sample.json) — không cần PDF thật để chạy.

def test_header_col_bounds_finds_real_column_x_ranges():
    m = MERGED["annex1_page0"]
    table = _FakeTable([m["header"], m["row_ababetter"]])
    texts_per_row = [m["header"]["texts"], m["row_ababetter"]["texts"]]
    bounds = _header_col_bounds(table, texts_per_row)
    assert bounds[0] == (67.92, 103.34)
    assert bounds[1] == (103.34, 252.17)


def test_header_col_bounds_none_when_no_header_row():
    m = MERGED["annex1_page0"]
    table = _FakeTable([m["row_ababetter"], m["row_abacare"]])
    texts_per_row = [m["row_ababetter"]["texts"], m["row_abacare"]["texts"]]
    assert _header_col_bounds(table, texts_per_row) is None


def test_recover_missing_leading_cells_heals_first_row_of_merge_but_not_continuation():
    m = MERGED["annex1_page0"]
    row_specs = [m["header"], m["section1"], m["section2"], m["row_ababetter"], m["row_abacare"]]
    table = _FakeTable(row_specs)
    texts_per_row = [r["texts"] for r in row_specs]
    page = _FakePage(MERGED["recovered_crops"])

    healed = _recover_missing_leading_cells(page, table, texts_per_row)

    # Hàng tiêu đề mục ("I. THUỐC SỬ DỤNG...", "1. Thuốc trừ sâu:") có cột 0
    # SẴN nội dung thật -> KHÔNG đụng tới (đúng dấu hiệu loại trừ, tránh lặp
    # lại đúng regression đã gặp ở Phụ lục II bên dưới).
    assert healed[1] == m["section1"]["texts"]
    assert healed[2] == m["section2"]["texts"]

    # Hàng ĐẦU TIÊN của khối gộp (Ababetter): cột 0/1 vốn None -> khôi phục
    # đúng "1" / "Abamectin\n(min 90%)" (chữ thật đo được từ PDF gốc).
    assert healed[3][0] == "1"
    assert healed[3][1] == "Abamectin\n(min 90%)"
    assert healed[3][2:] == m["row_ababetter"]["texts"][2:]  # trade/target/registrant giữ nguyên

    # Hàng TIẾP THEO trong cùng khối gộp (Abacare): không có chữ thật trong
    # đúng vùng đó (đã đo bằng thực nghiệm) -> vẫn None như cũ, KHÔNG suy đoán.
    assert healed[4][0] is None
    assert healed[4][1] is None


def test_recover_missing_leading_cells_does_not_touch_section_marker_row_annex2():
    # Regression: hàng tiêu đề mục 2 cột của Phụ lục II ("Thuốc trừ sâu,
    # thuốc bảo quản lâm sản") có cột 0 sẵn nội dung, chỉ cột 1 (cột CUỐI,
    # không phải khối liền từ đầu) là None do chữ tràn ngang qua ranh giới
    # cột — KHÔNG được khôi phục (nếu khôi phục nhầm, is_section_marker_row
    # sẽ không còn nhận diện đúng nữa vì cột 1 không còn rỗng).
    m = MERGED["annex2_page0"]
    table = _FakeTable([m["header"], m["section"]])
    texts_per_row = [m["header"]["texts"], m["section"]["texts"]]
    page = _FakePage({})  # không cấp crop nào -> nếu code cố crop sẽ ra "" (an toàn) nhưng ta assert không hề gọi tới

    healed = _recover_missing_leading_cells(page, table, texts_per_row)

    assert healed[1] == m["section"]["texts"]
    assert is_section_marker_row(healed[1])


def test_recover_missing_leading_cells_end_to_end_via_rows_from_tables_and_to_entries():
    from ingest.normalize import to_entries

    m = MERGED["annex1_page0"]
    row_specs = [m["header"], m["section1"], m["section2"], m["row_ababetter"], m["row_abacare"]]
    table = _FakeTable(row_specs)
    texts_per_row = [r["texts"] for r in row_specs]
    page = _FakePage(MERGED["recovered_crops"])
    healed = _recover_missing_leading_cells(page, table, texts_per_row)

    rows = rows_from_tables(healed, page=0, fields=FIELDS_FULL)
    entries = to_entries(rows)
    ababetter = next(e for e in entries if e["trade_name"] == "Ababetter")
    assert ababetter["ai"] == "Abamectin (min 90%)"
    assert ababetter["formulation"] == "5EC"
    abacare = next(e for e in entries if e["trade_name"] == "Abacare")
    assert abacare["ai"] == "Abamectin (min 90%)"  # kế thừa đúng từ hàng trước (cur), không phải orphan


def test_parse_pdf_max_pages_zero_returns_no_rows():
    if not ANNEX1.exists():
        pytest.skip("cần data/raw (chạy ingest.download trước)")
    assert parse_pdf(str(ANNEX1), max_pages=0) == []


# --- Task 5f: x-bounds cột TOÀN TÀI LIỆU (bug hệ thống Task 7 QA) — bbox/text
# THẬT chép nguyên trạng từ data/raw/tt75_2025_page_1.pdf trang pdfplumber 296
# (nhóm "Windy 200SL"/Glufosinate ammonium, ~147 sản phẩm — ca xác nhận trong
# docs/qa/p0-registry-qa.md mục 3.1), trang 138 (Brinka 240SC/Spirodiclofen —
# ca "hàng thiếu hẳn cột") và trang 38 (phantom sub-table "Oncol" — false
# positive phát hiện khi verify fix này). Xem tests/fixtures/annex_global_bounds_sample.json.

COL_BOUNDS = [tuple(c) for c in GLOBAL["col_bounds"]]


def test_recover_missing_leading_cells_needs_cached_bounds_no_header_on_this_page():
    # Chứng minh ĐÚNG bug hệ thống Task 7 QA: bảng của trang 296 (giữa tài
    # liệu, nhóm "Glufosinate ammonium" bắt đầu) KHÔNG có hàng tiêu đề cột
    # riêng -> _header_col_bounds cục bộ trả None -> hành vi CŨ (col_bounds
    # không truyền vào, hàm tự dò cục bộ) không khôi phục được gì.
    m = GLOBAL["windy_ace_gluffit"]
    table = _FakeTable([m])
    texts_per_row = [m["texts"]]
    assert _header_col_bounds(table, texts_per_row) is None
    page = _FakePage(m["recovered_crops"])
    healed_without_cache = _recover_missing_leading_cells(page, table, texts_per_row)
    assert healed_without_cache == texts_per_row  # không đổi gì -> đúng là bug


def test_recover_missing_leading_cells_heals_group_start_mid_document_using_cached_bounds():
    # Fix: truyền x-bounds đã cache từ trang 0 (col_bounds=) -> khôi phục
    # ĐÚNG "203"/"Glufosinate ammonium (min 95%)" dù trang 296 không có
    # header riêng — đây chính là hàng mở nhóm "Ace gluffit 30SL" (~147 sản
    # phẩm) mà Task 7 QA phát hiện bị gán sai hoạt chất của nhóm TRƯỚC.
    m = GLOBAL["windy_ace_gluffit"]
    table = _FakeTable([m])
    texts_per_row = [m["texts"]]
    page = _FakePage(m["recovered_crops"])
    healed = _recover_missing_leading_cells(page, table, texts_per_row, col_bounds=COL_BOUNDS)
    assert healed[0][0] == "203"
    assert healed[0][1] == "Glufosinate ammonium\n(min 95%)"
    assert healed[0][2:] == m["texts"][2:]  # trade/target/registrant giữ nguyên


def test_recover_missing_leading_cells_heals_short_row_missing_columns_entirely():
    # Biến thể "hàng thiếu hẳn cột": trang 138 không dựng nổi cả đường biên
    # tt/ai cho TOÀN TRANG (row.cells chỉ có 3 phần tử, không có None nào ở
    # vị trí tt/ai để bắt) — nhưng hàng "Brinka 240SC" vẫn là hàng MỞ NHÓM
    # MỚI thật (entry #872 "Spirodiclofen (min 98%)") bị mất theo cùng cơ
    # chế rowspan. Ca thật xác nhận: Spiromax 300SC (tr.137-139, QA report
    # trước đó "chưa dò được mã đúng") thuộc đúng nhóm này.
    m = GLOBAL["brinka_short_row"]
    table = _FakeTable([m])
    texts_per_row = [m["texts"]]
    page = _FakePage(m["recovered_crops"])
    healed = _recover_missing_leading_cells(page, table, texts_per_row, col_bounds=COL_BOUNDS)
    assert healed[0] == ["872", "Spirodiclofen (min 98%)", "Brinka 240SC", "nhện đỏ/ hoa cúc",
                          "Công ty TNHH UPL Việt Nam"]


def test_recover_missing_leading_cells_ignores_phantom_subtable_row():
    # Regression (phát hiện khi verify fix trên): find_tables() đôi khi trả
    # thêm 1 "bảng" phụ chỉ 1 ô, lồng vùng với bảng chính (mảnh dòng đầu của
    # ô trade nhiều dòng "Oncol\n5GR, 20EC, 25WP" đã có sẵn đầy đủ trong
    # bảng chính, trang 38). Ô phụ này x-range chỉ phủ 1 phần nhỏ giữa cột
    # trade (257.69-381.53), KHÔNG phủ trọn phần đuôi bảng từ cột chuẩn nào
    # trở đi -> guard spans_full_tail phải LOẠI, không được đệm/khôi phục
    # (nếu đệm nhầm sẽ tạo sản phẩm "Oncol" trùng lặp với ai/pest rác — xem
    # docstring _recover_missing_leading_cells).
    m = GLOBAL["oncol_phantom_subtable"]
    table = _FakeTable([m])
    texts_per_row = [m["texts"]]
    page = _FakePage({})  # không cấp crop nào -> nếu code cố crop sẽ lộ ra qua text rỗng bất thường
    healed = _recover_missing_leading_cells(page, table, texts_per_row, col_bounds=COL_BOUNDS)
    assert healed[0] == ["Oncol"]  # giữ nguyên, KHÔNG đệm thành 5 phần tử


def test_merge_split_columns_leaves_harmless_noisy_row_unchanged():
    # AD-Siva 45SC (tr.256): bảng có 7 cột thô (2 cột thừa RỖNG chèn giữa
    # target/registrant cho toàn trang) nhưng hàng NÀY không bị tách nội
    # dung thật -> merge phải cho kết quả CANONICAL 5 cột, y hệt nội dung
    # ban đầu (không cần cơ chế merge để đúng, chỉ cần không phá vỡ gì).
    m = GLOBAL["ad_siva_full_row"]
    table = _FakeTable([m])
    texts_per_row = [m["texts"]]
    merged = _merge_split_columns(table, texts_per_row, COL_BOUNDS)
    assert merged[0] == ["799", "Tebuconazole 30% +\nTrifloxystrobin 15%", "AD-Siva 45SC",
                          "rỉ sắt/ cà phê", "Công ty TNHH Anh Dẩu\nTiền Giang"]


def test_merge_split_columns_reunites_diacritic_split_target_cell():
    # Cơ chế lỗi #2 (Task 5f, ca thật Yanibin 75WG/Conabin 750WG tr.256):
    # find_tables() dò sai 1 đường kẻ cột dọc ngay giữa ký tự có dấu ("r" |
    # "ỉ sắt/cà phê") -> ô target bị tách làm 2 ("đạo ôn, lem lép hạt/lúa,
    # r" + "ỉ sắt/cà phê"), khiến tên thương phẩm "Conabin 750WG" bị đẩy
    # nhầm sang ô hoạt chất theo thuật toán đếm-cột cũ. Merge theo x-bounds
    # phải NỐI LẠI đúng 2 mảnh (không khoảng trắng, đúng như PDF gốc) và
    # xếp "Conabin 750WG" đúng vào ô trade.
    m = GLOBAL["conabin_split_row"]
    table = _FakeTable([m])
    texts_per_row = [m["texts"]]
    page = _FakePage(m["recovered_crops"])
    healed = _recover_missing_leading_cells(page, table, texts_per_row, col_bounds=COL_BOUNDS)
    merged = _merge_split_columns(table, healed, COL_BOUNDS)
    assert merged[0] == ["", "", "Conabin 750WG", "đạo ôn, lem lép hạt/lúa, rỉ sắt/cà phê",
                          "Công ty TNHH Phú Nông"]


# --- Task 5g (fix review 5f, Finding 1): khoảng hở giữa
# `_recover_missing_leading_cells` (trước đây CHỈ chạy khi len(cells)==n) và
# `_merge_split_columns` (chỉ xử lý len(cells)>n) — hàng vừa bị lưới cột
# over-detect VỪA mất tt/ai do rowspan cùng lúc thì KHÔNG hàm nào khôi phục
# được, khiến `to_entries` kế thừa nhầm `ai` của nhóm TRƯỚC. Ca thật xác nhận
# bằng `data/raw/tt75_2025_page_1.pdf`: `Abathi 10.5GR, 10ME` (trang 14, 7 cột
# thô) và `Ac-Bifen 43SC` (trang 38, 11 cột thô) — cả 3 sản phẩm sai `ai` mà
# review Task 5g phát hiện trong `data/registry.db` đều xuất phát từ đúng 2
# hàng này (Abathi mở 2 quy cách từ 1 ô trade). Fix: `parse_pdf` giờ gọi
# `_merge_split_columns` TRƯỚC hàm khôi phục (đảo thứ tự so với Task 5f) —
# xem docstring `_recover_missing_leading_cells` nhánh `len(cells) > n`.

def test_merge_then_recover_heals_overdetected_grid_row_abathi():
    m = GLOBAL["abathi_overdetect_row"]
    table = _FakeTable([m])
    texts_per_row = [m["texts"]]
    merged = _merge_split_columns(table, texts_per_row, COL_BOUNDS)
    # Trước fix: merge gộp đúng trade/target/registrant nhưng để tt/ai rỗng
    # vĩnh viễn (không ô thô nào ánh xạ vào 2 cột đó) -- đây chính là input
    # sai đã lọt vào `data/registry.db` (ai bị `to_entries` kế thừa nhầm từ
    # nhóm liền trước, "Abamectin 5% + Etoxazole 15%").
    assert merged[0][0] == "" and merged[0][1] == ""
    page = _FakePage(m["recovered_crops"])
    healed = _recover_missing_leading_cells(page, table, merged, col_bounds=COL_BOUNDS)
    assert healed[0] == ["58", "Abamectin 0.5% (0.48%) +\nFosthiazate 10% (9.52%)",
                          "Abathi\n10.5GR, 10ME",
                          "10.5GR: tuyến trùng/ cà phê, hồ tiêu\n10ME: tuyến trùng/hồ tiêu",
                          "Beijing Bioseen Crop Sciences\nCo., Ltd"]


def test_merge_then_recover_heals_overdetected_grid_row_ac_bifen():
    m = GLOBAL["ac_bifen_overdetect_row"]
    table = _FakeTable([m])
    texts_per_row = [m["texts"]]
    merged = _merge_split_columns(table, texts_per_row, COL_BOUNDS)
    assert merged[0][0] == "" and merged[0][1] == ""
    page = _FakePage(m["recovered_crops"])
    healed = _recover_missing_leading_cells(page, table, merged, col_bounds=COL_BOUNDS)
    assert healed[0] == ["247", "Bifenazate (min 95%)", "Ac-Bifen 43SC", "nhện đỏ/chè",
                          "Công ty TNHH Hóa sinh\nÁ Châu"]


@pytest.mark.parametrize("fixture_key", ["section_marker_wide_cell_5", "section_marker_wide_cell_8"])
def test_recover_missing_leading_cells_ignores_wide_section_marker_after_merge(fixture_key):
    # GUARD bắt buộc (phát hiện khi quét toàn văn bản Task 5g): hàng tiêu đề
    # mục ("5. Thuốc điều hoà sinh trưởng:", "8. Chất hỗ trợ (chất trải):")
    # dùng 1 ô RỘNG PHỦ TRỌN CẢ HÀNG -- merge lấy x-mid của ô đó (rơi vào
    # GIỮA bảng) gán nhầm vào 1 cột chuẩn GIỮA (target), để trống MỌI cột
    # khác kể cả CÁC CỘT SAU nó -- khác hẳn 1 hàng sản phẩm thật (Abathi/
    # Ac-Bifen ở trên) luôn phủ TRỌN VẸN phần đuôi không đứt quãng. `page`
    # cấp sẵn crop THẬT không rỗng ("5. Th"/"ốc điều hoà..." v.v.) để chứng
    # minh guard chủ động chặn (không phải tình cờ crop rỗng) -- nếu không
    # có guard liên tục, hàm sẽ nhầm gán tt="5. Th", ai="ốc điều hoà sinh
    # trưởng:" (rác).
    m = GLOBAL[fixture_key]
    table = _FakeTable([m])
    texts_per_row = [m["texts"]]
    merged = _merge_split_columns(table, texts_per_row, COL_BOUNDS)
    page = _FakePage(m["recovered_crops"])
    healed = _recover_missing_leading_cells(page, table, merged, col_bounds=COL_BOUNDS)
    assert healed == merged  # không đổi gì -- guard đã chặn


@pytest.mark.skipif(not ANNEX1.exists(), reason="cần data/raw (chạy ingest.download trước)")
def test_parse_pdf_real_annex1_abathi_and_ac_bifen_get_correct_ai():
    # Integration test PDF thật: 3 sản phẩm review Task 5g xác nhận sai `ai`
    # trong `data/registry.db` (Abathi 10.5GR, Abathi 10ME, Ac-Bifen 43SC)
    # phải được gán ĐÚNG `ai` của chính nhóm chúng, không phải kế thừa nhầm
    # từ nhóm liền trước trong PDF.
    from ingest.normalize import reset_counters, to_entries
    reset_counters()
    rows = parse_pdf(str(ANNEX1), max_pages=40)
    entries = to_entries(rows)
    # to_entries chuẩn hoá whitespace (kể cả "\n") thành 1 dấu cách.
    abathi = {e["formulation"]: e["ai"] for e in entries if e["trade_name"] == "Abathi"}
    assert abathi == {
        "10.5GR": "Abamectin 0.5% (0.48%) + Fosthiazate 10% (9.52%)",
        "10ME": "Abamectin 0.5% (0.48%) + Fosthiazate 10% (9.52%)",
    }
    ac_bifen = next(e for e in entries if e["trade_name"] == "Ac-Bifen")
    assert ac_bifen["ai"] == "Bifenazate (min 95%)"


@pytest.mark.skipif(not ANNEX1.exists(), reason="cần data/raw (chạy ingest.download trước)")
def test_parse_pdf_real_annex1_windy_group_gets_correct_ai_mid_document():
    # Integration test bằng PDF thật (không chỉ fixture): nhóm "Glufosinate
    # ammonium (min 95%)" bắt đầu ở trang 296 (không có header cột riêng)
    # phải được gán ĐÚNG cho Windy 200SL và toàn bộ ~147 sản phẩm cùng
    # nhóm — đây là ca cụ thể brief yêu cầu verify.
    from ingest.normalize import reset_counters, to_entries
    reset_counters()
    rows = parse_pdf(str(ANNEX1), max_pages=304)  # nhóm kế tiếp (#204) bắt đầu ở CUỐI trang 303
    entries = to_entries(rows, allow_no_trade=False)
    windy = [e for e in entries if e["trade_name"] == "Windy"]
    assert windy, "khong tim thay Windy trong Phu luc I"
    assert all(e["ai"] == "Glufosinate ammonium (min 95%)" for e in windy)
    group = [e for e in entries if e["ai"] == "Glufosinate ammonium (min 95%)"]
    assert 140 <= len(group) <= 150  # QA report: ~147 sản phẩm

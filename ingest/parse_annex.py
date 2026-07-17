"""Parse bảng phụ lục danh mục thuốc BVTV từ PDF (pdfplumber).

Cấu trúc cột chuẩn theo Phụ lục I của TT 75/2025/TT-BNNMT (được phép sử
dụng, 355 trang, xác minh bằng scripts/inspect_pdf.py trên PDF thật):

    TT | Hoạt chất (common name) | Tên thương phẩm | Đối tượng phòng trừ |
    Tổ chức đề nghị đăng ký

Phụ lục II (cấm sử dụng, 2 trang) có cấu trúc KHÁC hẳn — chỉ 2 cột:

    TT | Hoạt chất

(không có tên thương phẩm/đối tượng/tổ chức vì đây là danh sách hoạt chất
bị cấm, không phải sản phẩm đăng ký). `parse_pdf` tự dò schema (2 hay 5
cột) dựa trên hàng tiêu đề cột thật của từng file, rồi map vào cùng một
RawRow 6-key cố định (`tt, ai, trade, target, registrant, page`) — các
trường không tồn tại trong schema 2 cột được để chuỗi rỗng.

Thực tế pdfplumber.extract_tables() KHÔNG luôn trả về đúng số cột chuẩn
mỗi hàng, kể cả trong cùng một schema:
- Khi một trang không có hàng nào mới bắt đầu (TT/hoạt chất rỗng suốt cả
  trang, ví dụ các trang chỉ liệt kê thêm tên thương phẩm của cùng 1 hoạt
  chất), pdfplumber thường không phát hiện ra các cột đầu và trả về hàng
  thiếu hẳn cột (không phải chuỗi rỗng) — ví dụ chỉ còn 3 phần tử
  [trade, target, registrant].
- Một số trang bị lỗi phát hiện đường kẻ bảng và trả về nhiều hơn số cột
  chuẩn (6, 7, 11, thậm chí 15) với các ô rỗng xen giữa các ô có nội
  dung, nhưng thứ tự nội dung còn lại vẫn đúng theo thứ tự các trường.
- Khi đúng số cột chuẩn, vị trí cột phải giữ nguyên (không được nén/bỏ ô
  rỗng) vì đôi khi 1 ô ở giữa (ví dụ target) rỗng trong khi ô sau nó
  (registrant) vẫn có nội dung (hàng tiếp diễn do ngắt trang giữa ô).

`_row_to_fields` xử lý các trường hợp trên:
- `len(cells) <= n` (đủ cột hoặc THIẾU cột — cột bị pdfplumber làm mất
  luôn là các cột ĐẦU schema): map theo vị trí, giữ NGUYÊN ô rỗng ở giữa
  (không strip) — vì ô rỗng ở giữa có thể là dữ liệu thật (ví dụ target
  rỗng do hàng bị ngắt trang, registrant/trade vẫn ở đúng cột của nó).
- `len(cells) > n` (hàng nhiễu do lỗi dò đường kẻ bảng, cột rỗng bị chèn
  xen giữa): bỏ các ô rỗng rồi gán k giá trị còn lại vào k trường cuối
  cùng của schema; nếu sau khi bỏ rỗng vẫn còn > n giá trị, giữ lại n giá
  trị SAU CÙNG (ưu tiên trade/target/registrant — quan sát thực tế cho
  thấy phần bị cắt luôn là các mảnh tt/ai lặp/rác ở đầu, xem báo cáo Task
  3 mục Concern).

Mỗi mục ("1. Thuốc trừ sâu:", "2. Thuốc trừ bệnh:", "Thuốc trừ chuột",
...) có một hàng tiêu đề riêng chỉ có nội dung ở cột đầu, các cột còn lại
rỗng — hàng này cũng phải bị loại như hàng tiêu đề cột.
"""
import unicodedata
from pathlib import Path

import pdfplumber

ALL_KEYS = ("tt", "ai", "trade", "target", "registrant")
FIELDS_FULL = ("tt", "ai", "trade", "target", "registrant")  # Phụ lục I (được phép)
FIELDS_BANNED = ("tt", "ai")  # Phụ lục II (cấm) — chỉ có TT + hoạt chất
HEADER_HINTS = ("hoạt chất", "thương phẩm", "đối tượng")


def _norm(cell) -> str:
    s = "" if cell is None else str(cell)
    s = unicodedata.normalize("NFC", s)
    return "\n".join(line.strip() for line in s.splitlines()).strip()


def is_header_row(cells: list) -> bool:
    """Hàng tiêu đề cột (TT | Hoạt chất | Tên thương phẩm | ... hoặc chỉ
    TT | Hoạt chất ở Phụ lục II). Ô đầu tiên luôn đúng là "TT" ở cả hai
    schema — dùng làm tín hiệu chính, cộng thêm hint từ khóa để phòng hờ."""
    normed = [_norm(c) for c in cells]
    if normed and normed[0].lower() == "tt":
        return True
    joined = " ".join(c.lower() for c in normed)
    return sum(h in joined for h in HEADER_HINTS) >= 2


def is_section_marker_row(cells: list) -> bool:
    """Hàng tiêu đề mục, ví dụ "1. Thuốc trừ sâu:" — chỉ ô đầu có nội
    dung, mọi ô còn lại rỗng."""
    normed = [_norm(c) for c in cells]
    if not normed or not normed[0]:
        return False
    return all(c == "" for c in normed[1:])


def _row_to_fields(cells: list, fields: tuple = FIELDS_FULL) -> dict:
    normed = [_norm(c) for c in cells]
    n = len(fields)
    if len(normed) <= n:
        # Đủ cột hoặc thiếu cột đầu (tt/ai bị pdfplumber làm mất) — map
        # theo vị trí, KHÔNG strip ô rỗng giữa vì đó có thể là dữ liệu
        # thật (ví dụ target rỗng do hàng bị ngắt trang).
        values = [""] * (n - len(normed)) + normed
    else:
        # Thừa cột (lỗi dò đường kẻ bảng chèn ô rỗng xen giữa) — bỏ ô
        # rỗng rồi gán k giá trị còn lại vào k trường cuối cùng.
        non_empty = [c for c in normed if c]
        if len(non_empty) > n:
            non_empty = non_empty[-n:]
        values = [""] * (n - len(non_empty)) + non_empty
    result = {k: "" for k in ALL_KEYS}
    result.update(dict(zip(fields, values)))
    return result


def rows_from_tables(raw_rows: list[list], page: int, fields: tuple = FIELDS_FULL) -> list[dict]:
    out = []
    for cells in raw_rows:
        if is_header_row(cells) or is_section_marker_row(cells):
            continue
        row = _row_to_fields(cells, fields=fields)
        if not any([row["tt"], row["ai"], row["trade"], row["target"]]):
            continue
        row["page"] = page
        out.append(row)
    return out


def _detect_fields_from_tables(tables) -> tuple:
    """Dò schema (5 cột Phụ lục I hay 2 cột Phụ lục II) từ hàng tiêu đề
    cột thật (ô đầu == "tt") trong các bảng truyền vào. Tách riêng khỏi
    I/O của pdfplumber để test được bằng dữ liệu fixture thuần túy."""
    for table in tables:
        for row in table:
            normed = [_norm(c) for c in row]
            if normed and normed[0].lower() == "tt":
                return FIELDS_FULL if len(normed) >= 3 else FIELDS_BANNED
    # Không tìm thấy hàng tiêu đề trong phạm vi probe (probe_pages) ->
    # mặc định schema đầy đủ (Phụ lục I, trường hợp phổ biến nhất).
    return FIELDS_FULL


def _detect_fields(pdf, probe_pages: int = 5) -> tuple:
    """Dò schema bằng cách quét `probe_pages` trang đầu của PDF thật."""
    tables = (table for p in pdf.pages[:probe_pages] for table in p.extract_tables())
    return _detect_fields_from_tables(tables)


def _header_col_bounds(table, texts_per_row) -> list | None:
    """Trả về x-range (x0, x1) của từng cột lấy từ hàng TIÊU ĐỀ CỘT THẬT
    (ô đầu == "tt") của `table`, dùng làm neo để khôi phục ô bị pdfplumber
    làm mất (xem `_recover_missing_leading_cells`). None nếu bảng này
    không có hàng tiêu đề trong phạm vi các hàng của nó.

    QUAN TRỌNG (Task 5f, fix bug hệ thống phát hiện ở Task 7 QA): hàm này
    CHỈ tìm trong PHẠM VI 1 TRANG (1 `table` = 1 trang, pdfplumber không
    dựng bảng xuyên trang) — với Phụ lục I, hàng tiêu đề CHỈ xuất hiện ở
    trang 0 trong toàn bộ ~355 trang. Trước đây `parse_pdf` gọi hàm này
    (gián tiếp qua `_recover_missing_leading_cells`) riêng cho TỪNG trang
    -> mọi trang khác trang 0 đều nhận `None` -> khôi phục bị TẮT HẲN ở
    >99% số trang, kể cả khi trang đó thực sự có 1 nhóm hoạt chất MỚI bắt
    đầu bị mất ô do rowspan (đã xác nhận bằng PDF thật: trang 296, hàng
    "Ace gluffit 30SL" mất ô "203"/"Glufosinate ammonium (min 95%)" — xem
    task-7-report.md và docs/qa/p0-registry-qa.md mục 3.1). Vì vậy
    `parse_pdf` giờ chỉ gọi hàm này 1 LẦN cho mỗi trang để dò xem trang đó
    CÓ header không, rồi CACHE kết quả khác None gần nhất (từ trang 0) và
    TRUYỀN THẲNG (`col_bounds=`) cho `_recover_missing_leading_cells` ở
    MỌI trang sau đó của CÙNG 1 tài liệu — x-bounds cột không đổi vị trí
    xuyên suốt bảng (đã verify bằng thực nghiệm trên toàn bộ
    `tt75_2025_page_1.pdf`: 1996/2053 hàng đủ 5 cột + có tt/ai thật ở mọi
    trang khớp ĐÚNG x-bounds của trang 0 trong dung sai 1pt; 57 hàng lệch
    còn lại đều nằm ở trang 349-352, thuộc PHẦN B khác của danh mục — "II.
    THUỐC TRỪ MỐI"/"III. BẢO QUẢN LÂM SẢN"/... có bảng riêng x-bounds hơi
    khác — nhưng phần đó KHÔNG có hàng nào bị mất ô do rowspan (mọi hàng
    mở nhóm ở đó đều có tt/ai đầy đủ ngay từ đầu), nên việc dùng x-bounds
    trang 0 (Phần A) không hề ảnh hưởng tới phần B: hàm khôi phục chỉ kích
    hoạt khi có ô None thật, và phần B không có ô None nào ở vị trí group-
    header). Phụ lục II (cấm) là 1 FILE PDF RIÊNG với `parse_pdf` gọi
    riêng -> tự có header/x-bounds riêng của nó, không lẫn với Phụ lục I."""
    for row, texts in zip(table.rows, texts_per_row):
        if is_header_row(texts):
            return [(c[0], c[2]) if c is not None else None for c in row.cells]
    return None


def _recover_missing_leading_cells(page, table, texts_per_row, col_bounds=None) -> list[list]:
    """Khôi phục ô bị pdfplumber làm mất (cell=None) do PDF gốc dùng Ô GỘP
    (rowspan) khi nhiều hàng sản phẩm dùng chung 1 giá trị hoạt chất — xác
    nhận bằng bằng chứng thật trên `data/raw/tt75_2025_page_1.pdf` trang
    pdfplumber 0: khối "Abamectin" (~110 sản phẩm đầu Phụ lục I) dùng 1 ô
    "ai" gộp suốt nhiều trang KHÔNG có đường kẻ ngang nội bộ tách từng
    hàng. Vì vậy pdfplumber không dựng được ô (cell=None) cho CỘT ĐÓ ở
    MỌI hàng nằm trong vùng gộp — kể cả hàng ĐẦU TIÊN nơi nội dung thật
    ("1", "Abamectin") vẫn được vẽ trên trang (kiểm bằng `page.edges`:
    biên dưới của hàng đầu chỉ phủ cột tên thương phẩm/đối tượng/tổ chức,
    không phủ cột TT/hoạt chất — không có đường kẻ tách hàng đó khỏi các
    hàng gộp kế tiếp). Hệ quả: `to_entries` gặp "ai" rỗng ngay từ hàng đầu
    file (`cur is None`) nên toàn bộ khối bị bỏ (Bug 1, Task 5b) — không
    phải do to_entries sai, mà do dữ liệu đầu vào đã mất thật từ bước này.

    Vì nội dung ô gộp chỉ được VẼ ĐÚNG MỘT LẦN (ở hàng đầu vùng gộp), hàm
    này khôi phục bằng cách crop lại ĐÚNG x-range của cột (lấy từ hàng
    tiêu đề — cột không đổi vị trí trong cùng 1 bảng) và y-range của
    TỪNG hàng đang xét, rồi extract_text() ngay tại đó — đọc lại đúng vị
    trí, không đoán nội dung. Các hàng gộp tiếp theo (không có chữ thật
    trong đúng vùng đó, đã xác nhận bằng thực nghiệm) vẫn trả về "" như cũ.

    CHỈ khôi phục khi None tạo thành 1 KHỐI LIỀN bắt đầu từ CỘT 0 (cột 0
    cũng None) và có ÍT NHẤT 1 cột sau đó thật sự còn nội dung — đúng dấu
    hiệu của bug này (cột đầu bị merge mất nhưng trade/target/registrant
    vẫn còn). Loại trừ rõ ràng hàng tiêu đề mục (vd "I. THUỐC SỬ DỤNG...",
    "1. Thuốc trừ sâu:") và hàng tiêu đề mục 2 cột của Phụ lục II — các
    hàng này có CỘT 0 vẫn còn nội dung thật, chỉ (các) cột SAU bị None do
    1 ô rộng tràn chữ qua ranh giới cột (không phải merge nhiều hàng).
    Xác nhận bằng thực nghiệm: nếu khôi phục nhầm các hàng này, crop lại
    đúng "bắt" được phần chữ TRÀN của chính cột 0 (vd hàng tiêu đề mục
    Phụ lục II "Thuốc trừ sâu, thuốc bảo quản lâm sản" tràn sang cột 1),
    khiến `is_section_marker_row` không còn nhận diện đúng nữa — quan sát
    này khẳng định cách phân biệt cột 0 None/non-None là đúng bằng chứng,
    không phải suy đoán.

    `col_bounds` (Task 5f): x-bounds TOÀN TÀI LIỆU do `parse_pdf` tính 1
    LẦN từ trang có header thật (trang 0) rồi truyền vào cho MỌI trang —
    xem docstring `_header_col_bounds` giải thích vì sao (bug hệ thống cũ:
    dò header lại cho TỪNG trang khiến khôi phục bị tắt ở >99% số trang).
    Nếu không truyền (None, dùng khi test/gọi trực tiếp với 1 bảng có sẵn
    header trong chính nó) thì fallback dò cục bộ trong `table` như hành
    vi cũ — giữ tương thích ngược cho các test gọi hàm này độc lập.

    HÀNG "LƯỚI OVER-DETECT + MẤT Ô ROWSPAN CÙNG LÚC" (Task 5g, review fix
    5f — ca thật `Abathi 10.5GR/10ME` trang 14, `Ac-Bifen 43SC` trang 38):
    khoảng hở giữa cơ chế trên (chỉ chạy khi `len(cells) == n`) và
    `_merge_split_columns` (chỉ xử lý hàng `len(cells) > n`) — một hàng vừa
    bị lưới cột over-detect (7, 11 cột thô ở 2 ca thật) VỪA mất tt/ai do
    rowspan cùng lúc thì KHÔNG hàm nào khôi phục: guard cũ ở đây bỏ qua
    toàn bộ (`len(cells) != n`), còn merge gộp đúng trade/target/registrant
    nhưng để tt/ai rỗng vĩnh viễn (không có gì để gộp cho 2 cột đó — không
    ô thô nào ánh xạ tới). Hệ quả thật: `to_entries` kế thừa nhầm `ai` của
    NHÓM TRƯỚC cho các hàng này (Abathi/Ac-Bifen bị gán `ai` của entry liền
    trước nó trong PDF).

    Fix: `parse_pdf` giờ gọi `_merge_split_columns` TRƯỚC hàm này (đảo thứ
    tự so với Task 5f) — nên khi hàm này nhận một hàng có `row.cells` gốc
    NHIỀU HƠN n (lưới thô), `texts` truyền vào ĐÃ được merge về đúng n cột
    chuẩn. Vì `row.cells` thô (nhiều hơn n phần tử) không còn khớp 1-1 với
    `texts` đã merge, không thể tái dùng chỉ số thô để dò "cột nào mất" như
    nhánh `len(cells) == n` — suy luận lại bằng TEXT RỖNG sau merge: merge
    chỉ để 1 cột chuẩn rỗng khi KHÔNG có ô thô nào (dùng x-mid) ánh xạ vào
    đó, đúng nghĩa "mất thật" tương đương `cells[ci] is None` ở nhánh
    chuẩn. Cách này KHÔNG tái tạo lại bug Sunbishi (crop trùng cột
    trade/target/registrant, xem docstring `_merge_split_columns`): vì
    "cột nào thiếu" giờ suy từ TEXT RỖNG sau merge (không phải chỉ số thô
    ci), các cột đã có nội dung thật qua merge sẽ không rỗng -> vòng lặp
    khôi phục bên dưới dừng ngay tại cột đầu tiên có nội dung, không bao
    giờ đụng lại tới cột merge đã điền đúng. Vẫn giữ nguyên mọi guard an
    toàn hiện có (cột 0 phải đọc được KHÔNG rỗng mới chấp nhận cả khối, ca
    2-line-overflow Validamycin) vì logic crop dùng chung 1 vòng lặp phía
    dưới, không đổi.

    HÀNG "THIẾU HẲN CỘT" (Task 5f, ca thật `Ratgone 0.005DR` trang
    pdfplumber 322-323): 1 biến thể KHÁC của cùng lỗi rowspan — trên 1 số
    trang, pdfplumber không dựng nổi cả ĐƯỜNG BIÊN cột tt/ai cho TOÀN
    TRANG (không riêng 1 hàng) khi trang đó không có bất kỳ hàng nào có
    đường kẻ ngang phân định rõ (hiện tượng "hàng thiếu hẳn cột" đã ghi
    nhận từ đầu module này, vd trang 6/322 chỉ trả 3 phần tử/hàng thay vì
    5) — khi đó `row.cells` NGẮN HƠN `col_bounds` (không có ô None nào ở
    vị trí tt/ai để bắt được, vì khái niệm cột đó không tồn tại trong lưới
    của trang). Hàng đầu tiên của 1 nhóm hoạt chất MỚI rơi vào đúng trang
    này vẫn có thể bị mất ai/tt theo CÙNG cơ chế rowspan (chữ vẫn được vẽ
    trên trang, chỉ là pdfplumber không mô hình hoá được đường biên cột).
    Xử lý: coi `n - len(cells)` cột ĐẦU là None (đệm trái `cells`/`texts`
    cho đủ `n`) rồi xử lý CHUNG với logic khối-None-liền-đầu bên dưới —
    không suy đoán gì thêm, chỉ chuẩn hoá độ dài để cùng 1 lượt crop thử
    khôi phục có cơ hội chạy trên cả 2 biến thể của lỗi.

    GUARD bắt buộc trước khi đệm (phát hiện khi verify Task 5f trên toàn
    Phụ lục I, ca giả `Oncol` trang 38): `p.find_tables()` đôi khi trả
    thêm các "bảng" PHỤ chỉ 1 ô, lồng/trùng vùng với bảng chính (lỗi dò
    bảng của pdfplumber trên trang có ô nhiều dòng phức tạp) — ví dụ 1 ô
    con riêng chỉ chứa đúng chữ "Oncol" (mảnh dòng đầu của ô trade nhiều
    dòng "Oncol\\n5GR, 20EC, 25WP" đã có SẴN đầy đủ trong bảng chính). Ô
    phụ này có `len(cells)=1 < n` giống hệt dấu hiệu "thiếu cột đầu" thật,
    nhưng x-range của nó CHỈ phủ 1 phần nhỏ nằm giữa cột trade (không phải
    toàn bộ phần đuôi bảng từ cột thứ `k` trở đi) — nếu đệm nhầm sẽ crop
    lem sang vùng chữ của DÒNG/CỘT KHÁC (thuộc bảng chính) và tạo ra sản
    phẩm trùng lặp với ai/pest RÁC. Phân biệt bằng đối chiếu x-range: hàng
    "thiếu hẳn cột" THẬT (ca Ratgone) luôn có ô ĐẦU bắt đầu ĐÚNG x0 của cột
    chuẩn thứ `k` và ô CUỐI kết thúc ĐÚNG x1 của cột chuẩn cuối (registrant)
    — tức nó phủ TRỌN VẸN phần đuôi bảng còn lại, không phải 1 mảnh lẻ. Chỉ
    đệm khi khớp cả 2 đầu (dung sai nhỏ, bù sai số làm tròn của pdfplumber).
    """
    if col_bounds is None:
        col_bounds = _header_col_bounds(table, texts_per_row)
    if col_bounds is None:
        return texts_per_row
    n = len(col_bounds)
    tol = 10.0
    healed = []
    for row, texts in zip(table.rows, texts_per_row):
        texts = list(texts)
        cells = list(row.cells) if row.cells else []
        if len(cells) > n:
            # Task 5g: hàng lưới over-detect (ca thật trang 14/38 "Abathi
            # 10.5GR/10ME", "Ac-Bifen 43SC" — 7, 11 cột thô). `parse_pdf`
            # giờ gọi `_merge_split_columns` TRƯỚC hàm này nên `texts` ở
            # đây ĐÃ được gộp về đúng n cột chuẩn nếu merge thành công —
            # `row.cells` thô (vẫn còn > n phần tử) không còn khớp 1-1 với
            # `texts` nên không dùng lại được để dò "cột nào mất" như nhánh
            # chuẩn bên dưới; suy luận lại bằng TEXT RỖNG sau merge (merge
            # chỉ để 1 cột chuẩn rỗng khi không có ô thô nào ánh xạ vào đó
            # qua x-mid — đúng nghĩa "mất thật" tương đương `cells[ci] is
            # None`). Xem docstring hàm để biết vì sao cách này không tái
            # tạo lại bug Sunbishi (crop trùng cột trade/target/registrant).
            if len(texts) != n:
                # merge thất bại (ok=False, hiếm/edge case chưa gặp trong
                # thực nghiệm, xem `_merge_split_columns`) -> texts vẫn giữ
                # độ dài thô, không suy đoán được gì an toàn -> bỏ qua.
                healed.append(texts)
                continue
            cells = [None if not t else True for t in texts]
            # GUARD bắt buộc (phát hiện khi quét toàn văn bản Task 5g, ca
            # thật 2 hàng tiêu đề mục "5. Thuốc điều hoà sinh trưởng:"
            # trang 324 và "8. Chất hỗ trợ (chất trải):" trang 348): hàng
            # tiêu đề mục dùng 1 Ô RỘNG PHỦ TRỌN CẢ HÀNG (`row.cells` chỉ 1
            # phần tử non-None, còn lại None) — `_merge_split_columns` lấy
            # x-mid của CHÍNH GIỮA ô rộng đó để tra cột chuẩn, thường rơi
            # vào 1 cột GIỮA (vd target, cột rộng nhất) chứ KHÔNG phải cột
            # 0, để trống MỌI cột khác kể cả CÁC CỘT SAU nó — khác hẳn dấu
            # hiệu 1 hàng sản phẩm thật (Abathi/Ac-Bifen): luôn phủ TRỌN
            # VẸN phần đuôi từ cột đầu tiên có nội dung trở đi, không đứt
            # quãng (trade+target+registrant liền nhau). Phân biệt bằng
            # tính LIÊN TỤC: sau cột chuẩn đầu tiên có nội dung, mọi cột
            # sau đó phải CÙNG có nội dung — nếu có bất kỳ cột nào rỗng lại
            # sau đó (như trường hợp tiêu đề mục ở trên), coi là KHÔNG đủ
            # điều kiện, bỏ qua toàn bộ hàng (không suy đoán khối None nào
            # là "thiếu thật").
            first_content = next((idx for idx, c in enumerate(cells) if c is not None), None)
            if first_content is not None and any(c is None for c in cells[first_content:]):
                healed.append(texts)
                continue
        elif 0 < len(cells) < n:
            k = n - len(cells)
            cb_first, cb_last = col_bounds[k], col_bounds[-1]
            spans_full_tail = (
                cb_first is not None and cb_last is not None
                and abs(cells[0][0] - cb_first[0]) <= tol
                and abs(cells[-1][2] - cb_last[1]) <= tol)
            if spans_full_tail:
                cells = [None] * k + cells
                texts = [""] * k + texts
        # CHỈ chạy vòng khôi phục "khối None liền cột 0" khi hàng có ĐÚNG n
        # cột SAU các bước chuẩn hoá ở trên (khớp đúng lưới cột chuẩn, hoặc
        # hàng thiếu-hẳn-cột/lưới-over-detect vừa được đệm/suy luận về đúng
        # n). `cells[ci] is True` (đánh dấu "có nội dung, không cần bbox
        # thật" cho nhánh over-detect ở trên) hoạt động giống hệt 1 bbox
        # thật trong mọi so sánh `is None`/`is not None` bên dưới — logic
        # crop luôn dùng `col_bounds[ci]` cố định, KHÔNG bao giờ đọc giá
        # trị bbox của `cells[ci]`, nên placeholder `True` an toàn tuyệt
        # đối (không có rủi ro dùng nhầm toạ độ).
        if len(cells) != n or cells[0] is not None or not any(c is not None for c in cells):
            healed.append(texts)
            continue
        # GUARD bắt buộc (ca thật entry "835 Validamycin (Validamycin A)"
        # trang 264): ô hoạt chất 2 DÒNG của 1 entry có thể TRÀN xuống
        # đúng y-range của hàng SAU (hàng tiếp diễn thật, không mở nhóm
        # mới) -- ví dụ dòng 2 "(Jingangmycin) (min 40%)" của ô hoạt chất
        # "835" bị crop nhầm vào hàng "Asiamycin super 100SL" dù hàng đó
        # KHÔNG hề mở nhóm (không có số mục nào). Dấu hiệu phân biệt: 1
        # hàng mở nhóm THẬT luôn khôi phục được CẢ 2 (số mục ở cột 0 VÀ
        # hoạt chất ở cột 1) cùng lúc (đã xác nhận qua mọi ca thật: Windy,
        # Ratgone, Brinka) -- nếu cột 0 (số mục) rỗng thì bỏ qua TOÀN BỘ
        # khối này (không nhận bất kỳ giá trị nào), an toàn hơn là nhận
        # nhầm phần tràn dòng của ô hoạt chất hàng trước.
        top, bottom = row.bbox[1], row.bbox[3]
        if col_bounds[0] is None:
            healed.append(texts)
            continue
        tt_x0, tt_x1 = col_bounds[0]
        tt_recovered = page.within_bbox((tt_x0, top, tt_x1, bottom), relative=False).extract_text()
        if not tt_recovered:
            healed.append(texts)
            continue
        for ci, cell in enumerate(cells):
            if cell is not None:
                break  # ra khỏi khối None liền từ cột 0 -> dừng khôi phục thêm
            if ci >= len(col_bounds) or col_bounds[ci] is None:
                continue
            if ci == 0:
                recovered = tt_recovered
            else:
                x0, x1 = col_bounds[ci]
                recovered = page.within_bbox((x0, top, x1, bottom), relative=False).extract_text()
            if recovered:
                texts[ci] = recovered
        healed.append(texts)
    return healed


def _merge_split_columns(table, texts_per_row, col_bounds) -> list[list]:
    """Cơ chế lỗi #2 (Task 5f, xác nhận qua ca thật `Yanibin 75WG`/`Conabin
    750WG` trang pdfplumber 256): đôi khi `find_tables()` dò SAI thêm 1-2
    đường kẻ cột dọc ngay GIỮA text của 1 hàng (không phải lỗi riêng của ô
    đó, mà là lưới cột của CẢ TRANG bị lệch — đa số hàng khác trên cùng
    trang chỉ có ô rỗng ở đúng vị trí thừa đó nên không lộ ra, nhưng đúng
    1 hàng có nội dung tràn qua ranh giới giả này bị TÁCH LÀM ĐÔI giữa 2 ô
    liền nhau, ví dụ ô target "đạo ôn, lem lép hạt/lúa, rỉ sắt/cà phê" bị
    cắt thành "đạo ôn, lem lép hạt/lúa, r" + "ỉ sắt/cà phê"). Vì
    `_row_to_fields` cũ chỉ đếm SỐ Ô rồi map theo VỊ TRÍ (không biết cột
    dọc thật nằm ở đâu), 2 mảnh bị tách lẫn 2 ô rỗng phía tt/ai còn lại
    (đủ 5 ô không-rỗng) khớp NHẦM với case "thiếu cột đầu" -> tên thương
    phẩm (`Conabin 750WG`) bị đẩy sang ô hoạt chất.

    Hàm này chạy TRƯỚC `rows_from_tables`/`_row_to_fields`, dùng CHÍNH
    x-bounds tài liệu (`col_bounds`, cùng nguồn với
    `_recover_missing_leading_cells`) để gộp lại đúng: với mỗi ô thật
    (`row.cells[i]` có bbox), tính điểm giữa x rồi tra xem rơi vào đúng
    cột CHUẨN nào trong `col_bounds` (không dựa vào chỉ số vị trí thô của
    lưới cột lỗi) — nhiều ô thô rơi vào CÙNG 1 cột chuẩn (dấu hiệu bị tách
    đôi) được NỐI text theo đúng thứ tự trái->phải, không chèn khoảng
    trắng (ca thật cho thấy điểm tách nằm giữa 1 ký tự, không phải giữa 2
    từ). Ô có `cell is None` (đã được `_recover_missing_leading_cells` xử
    lý ở bước trước hoặc không có gì) giữ nguyên tại đúng chỉ số của nó
    (hợp lệ vì bước khôi phục trước luôn ghi đúng vào chỉ số cột chuẩn
    tương ứng cho khối None liền đầu — xem docstring hàm đó).

    CHỈ áp dụng khi bảng có NHIỀU cột thô hơn số cột chuẩn (`len(cells) >
    len(col_bounds)` — dấu hiệu lưới cột bị lỗi); bảng đúng số cột chuẩn
    thì bỏ qua hoàn toàn (không đổi gì, an toàn tuyệt đối cho >99% số
    hàng không gặp lỗi này). Nếu 1 ô thật không khớp được cột chuẩn nào
    (x nằm ngoài mọi `col_bounds`, chưa từng gặp trong thực nghiệm) ->
    KHÔNG đoán, trả nguyên hàng gốc để `_row_to_fields` xử lý theo hành vi
    cũ (thà giữ lỗi cũ đã biết hơn tạo lỗi mới).

    Ô LỒNG NHAU (Task 5f, ca thật `Rasger 20DP`/`Oncol` tr.38+324): trong
    hàng nhiều-cột-thô, `find_tables()` đôi khi dò thêm 1 ô CON nằm TRỌN
    trong bbox 1 ô khác của CHÍNH hàng đó, lặp lại y hệt (hoặc 1 phần)
    text của ô bao quanh (ca thật: ô "Rasger 20DP" cỡ đầy đủ hàng + 1 ô
    con hẹp hơn, cao đúng NỬA hàng, text giống hệt; tương tự registrant
    "Công ty TNHH UPL Việt Nam" của `Oncol` bị dò thêm 1 ô con). Đây LUÔN
    là artefact dò-lặp (1 lưới cột hợp lệ không có ô nào lồng ô khác) —
    nếu không loại sẽ nối trùng thành "Rasger 20DPRasger 20DP". Loại theo
    bbox (ô A lồng trọn ô B, ĐÚNG NGHĨA gồm cả trường hợp trùng hệt) chứ
    không chỉ so text giống hệt (2 ô rời nhau tình cờ trùng text vẫn có
    thể là dữ liệu thật, dù hiếm) — bbox lồng là tín hiệu chắc chắn hơn."""
    if col_bounds is None:
        return texts_per_row
    n = len(col_bounds)

    def _contained(a, b, tol=0.5):
        return (a[0] >= b[0] - tol and a[1] >= b[1] - tol
                and a[2] <= b[2] + tol and a[3] <= b[3] + tol)

    out = []
    for row, texts in zip(table.rows, texts_per_row):
        cells = list(row.cells) if row.cells else []
        if not cells or len(cells) <= n:
            out.append(texts)
            continue
        drop: set[int] = set()
        for i, ci in enumerate(cells):
            if ci is None or i in drop:
                continue
            for j, cj in enumerate(cells):
                if j <= i or cj is None or j in drop:
                    continue
                if _contained(ci, cj) and _contained(cj, ci):
                    drop.add(j)  # bbox trùng hệt -> giữ cái đầu, bỏ cái sau
                elif _contained(ci, cj):
                    drop.add(i)
                elif _contained(cj, ci):
                    drop.add(j)
        buckets: list[list[str]] = [[] for _ in range(n)]
        ok = True
        for i, (cell, text) in enumerate(zip(cells, texts)):
            if not text or i in drop:
                continue
            if cell is None:
                # Đã khôi phục (hoặc không có gì) ở bước trước -> chỉ số i
                # ứng đúng 1-1 với cột chuẩn cùng chỉ số (xem docstring).
                if i >= n:
                    ok = False
                    break
                buckets[i].append(text)
                continue
            xmid = (cell[0] + cell[2]) / 2
            idx = next((ci for ci, cb in enumerate(col_bounds)
                        if cb is not None and cb[0] <= xmid < cb[1]), None)
            if idx is None:
                ok = False
                break
            buckets[idx].append(text)
        out.append(["".join(b) for b in buckets] if ok else texts)
    return out


def parse_pdf(path: str | Path, max_pages: int | None = None) -> list[dict]:
    rows: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        fields = _detect_fields(pdf)
        # max_pages=0 phải nghĩa là 0 trang (0 là falsy nhưng hợp lệ),
        # nên phải so sánh với None thay vì dùng truthiness.
        pages = pdf.pages[:max_pages] if max_pages is not None else pdf.pages
        # x-bounds cột TOÀN TÀI LIỆU (Task 5f) — tính 1 lần từ trang có
        # header thật (trang 0 của Phụ lục I) rồi tái sử dụng cho MỌI
        # trang sau của CÙNG file này; refresh nếu 1 trang sau đó lại có
        # header riêng (không xảy ra trong thực tế nhưng an toàn hơn hard-
        # code "chỉ trang 0"). Mỗi lời gọi `parse_pdf` ứng với 1 file PDF
        # riêng (Phụ lục I hoặc II) nên biến này TỰ scope đúng theo tài
        # liệu, không lẫn giữa 2 phụ lục có schema khác nhau. Xem docstring
        # `_header_col_bounds`/`_recover_missing_leading_cells` để biết vì
        # sao (bug hệ thống Task 7 QA: dò header lại mỗi trang khiến khôi
        # phục tắt ở >99% số trang).
        doc_col_bounds: list | None = None
        for i, p in enumerate(pages):
            # find_tables() + .extract() cho kết quả GIỐNG HỆT
            # p.extract_tables() (đã verify bằng thực nghiệm) nhưng còn
            # giữ được `table.rows[i].cells` (bbox) cần cho khôi phục ô
            # mất ở trên — nên dùng thay p.extract_tables() trực tiếp.
            for table in p.find_tables():
                texts_per_row = table.extract()
                local_bounds = _header_col_bounds(table, texts_per_row)
                if local_bounds is not None:
                    doc_col_bounds = local_bounds
                # Task 5g: merge TRƯỚC recovery (đảo thứ tự so với Task 5f)
                # — hàng lưới over-detect (len(cells) > n) cần được gộp về
                # đúng n cột chuẩn TRƯỚC thì `_recover_missing_leading_cells`
                # mới suy luận đúng "cột nào còn thiếu" bằng text rỗng sau
                # merge, thay vì bỏ qua toàn bộ như trước (xem docstring 2
                # hàm để biết bằng chứng thật: Abathi 10.5GR/10ME, Ac-Bifen
                # 43SC). Hàng đã đúng n cột từ đầu (đa số) không đổi gì qua
                # merge (merge chỉ xử lý len(cells) > n) nên thứ tự mới
                # không ảnh hưởng hành vi cũ của các hàng đó.
                texts_per_row = _merge_split_columns(table, texts_per_row, doc_col_bounds)
                texts_per_row = _recover_missing_leading_cells(
                    p, table, texts_per_row, col_bounds=doc_col_bounds)
                rows.extend(rows_from_tables(texts_per_row, i, fields=fields))
    return rows

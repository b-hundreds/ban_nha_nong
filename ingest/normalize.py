"""Chuẩn hoá hàng thô phụ lục → entries sản phẩm."""
import logging
import re

logger = logging.getLogger(__name__)

# QA đọc các counter module-level này SAU KHI build thật (ingest.build_registry
# gọi to_entries) để soát dữ liệu bị bỏ/gộp CÓ CHỦ ĐÍCH (an toàn hơn đoán sai
# khi không chắc chắn). 0 là tốt nhất; > 0 không tự nó là lỗi mới — nghĩa là
# parser gặp đúng 1 trong các trường hợp mơ hồ đã biết (Task 5b report, mục
# Bug 1 orphan-drop / Bug 2 multi-formulation) và chọn bỏ/gộp an toàn thay vì
# đoán. Không reset giữa các lần gọi (tích luỹ cho cả 1 lần build thật); test
# tự chốt bằng delta trước/sau khi cần kiểm tra.
orphan_drop_count = 0                  # Bug 1: dòng tiếp diễn xuất hiện trước khi có hoạt chất nào được xác lập
ambiguous_target_block_count = 0       # Bug 2: phần target trước nhãn quy cách đầu tiên, không rõ thuộc quy cách nào -> bỏ
unmatched_formulation_block_count = 0  # Bug 2: block có nhãn quy cách nhưng KHÔNG khớp quy cách nào của dòng -> gán chung mọi quy cách
trade_fragment_continuation_count = 0  # Task 5e Bug 2: ô TRADE bị ngắt trang, mảnh codes-only được gộp vào nhóm đang mở (không mở sản phẩm ma)


def reset_counters() -> None:
    """Đưa 4 counter QA module-level về 0. KHÔNG gọi giữa các lần `to_entries`
    trong CÙNG 1 lần build thật (counter cố tình tích luỹ cho cả 1 lần build,
    xem docstring các biến trên) — chỉ gọi ở ranh giới 1 lần build MỚI (đầu
    `build_registry.main()`) hoặc đầu mỗi test muốn đo delta sạch, để lần
    chạy trước (vd 1 build cũ, hoặc 1 test khác) không làm sai lệch số đếm
    của lần chạy hiện tại."""
    global orphan_drop_count, ambiguous_target_block_count, unmatched_formulation_block_count
    global trade_fragment_continuation_count
    orphan_drop_count = 0
    ambiguous_target_block_count = 0
    unmatched_formulation_block_count = 0
    trade_fragment_continuation_count = 0

# Mã dạng chế phẩm phổ biến trong danh mục VN — dùng chung cho regex tách mã
# quy cách cuối tên thương phẩm (_FORM_RE) và regex nhận diện nhãn quy cách
# trong ô target (_LABEL_RE, xem split_uses_by_formulation).
#
# Task 5e: mở rộng thêm PA/OF/GB/WS/ST (ca thật: Adephone 25 PA, Nominee
# 100OF, Helix 15GB, Gaucho 70WS, Gold gibb 20ST — xem task-5d report mục
# 1.4/6) + FW/OS (phát hiện thêm khi quét toàn Phụ lục I để verify fix này:
# Amet annong/Atra annong 500FW, Dithane M-45 600OS — cùng dạng số+chữ hoa
# AN TOÀN NHƯ CÁC UNIT ĐÃ CÓ, luôn đòi hỏi số đứng trước nên rủi ro match
# nhầm cực thấp, không phải mở rộng tuỳ tiện).
_FORM_UNITS = (r"WP|EC|SC|SL|WG|WDG|GR|EW|OD|ME|SP|DP|CS|ZC|SE|FS|AS|DD|BTN|"
               r"BHN|EO|GEL|AB|BR|CF|DC|SG|TB|XT|PA|OF|GB|WS|ST|FW|OS")

# Mã số+chữ, VD "3.6EC", "40%SG" (dấu % tuỳ chọn giữa số và unit — ca thật
# ProGibb "40%SG"). Case-KHÔNG phân biệt (như trước giờ) vì luôn neo bằng số
# đứng trước -> rủi ro match nhầm thấp (không thể nuốt nhầm tên riêng viết
# hoa, vd "2.4D" vẫn an toàn vì "D" không nằm trong _FORM_UNITS).
_FORM_CODE_DIGIT = rf"\d+(?:[.,]\d+)?(?:\s*[+/]\s*\d+(?:[.,]\d+)?)*\s*%?\s*(?:{_FORM_UNITS})"

# Mã CHỮ-KHÔNG-SỐ đứng riêng (vd "Kuraba WP" — trade chỉ có 1 quy cách không
# số, quy cách kia "3.6EC" mới có số). CHỈ chấp nhận khi token khớp ĐÚNG
# NGUYÊN VĂN (case-sensitive, không fuzzy, không IGNORECASE) một unit đã
# biết — bắt buộc viết HOA TOÀN BỘ để giảm nguy cơ match nhầm chữ thường
# tiếng Việt/tên riêng (yêu cầu Task 5e). Dùng scoped inline flag `(?i:...)`
# để phần số vẫn case-insensitive như cũ, còn nhánh chữ-không-số này KHÔNG
# bị ảnh hưởng bởi flag toàn cục (đã bỏ re.IGNORECASE khỏi _FORM_RE/_LABEL_RE).
_FORM_CODE = rf"(?:(?i:{_FORM_CODE_DIGIT}))|(?:{_FORM_UNITS})"

_FORM_RE = re.compile(rf"\s+({_FORM_CODE})\s*$")

# Token ĐƠN đứng một mình khớp đúng 1 mã quy cách (dùng cho
# `codes_only_formulations` — kiểm tra TOÀN BỘ 1 ô trade chỉ gồm mã, xem Bug
# class 2 Task 5e). Neo cả 2 đầu vì mỗi token đã được `.split(",")` + strip
# riêng lẻ (không cần biên `\s+`/`$` như _FORM_RE dùng cho chuỗi đầy đủ).
_FORM_CODE_TOKEN_RE = re.compile(rf"^(?:{_FORM_CODE})$")


def _fuzzy(literal_or_alt: str) -> str:
    """Cho phép khoảng trắng xen giữa MỌI ký tự — bù lỗi pdfplumber dàn đều
    ký tự ở nhãn ĐẦU TIÊN của ô target (quan sát thực tế trên PDF thật, vd
    Folpan 50WP/50SC: trade cell vẫn đúng "50 WP" nhưng target ra "5 0 W P
    :"). Áp dụng cho từng ký tự literal của 1 chuỗi (không phải cho cả một
    biểu thức regex đã có nhóm/alternation)."""
    return r"\s*".join(re.escape(ch) for ch in literal_or_alt)


# Nhãn quy cách trong ô target, dạng "3.6EC:" HOẶC nhiều mã CÙNG chia sẻ 1
# nhãn cách nhau bằng dấu phẩy, dạng "56EC, 68WG:" (xác nhận bằng dữ liệu
# thật "B52duc 56EC, 56SG, 68WG" -> target "56EC, 68WG: nhện gié...\n56SG:
# ..." — 2 quy cách dùng chung 1 khối uses). Cho phép fuzzy spacing trong
# TỪNG mã (bù lỗi dàn đều ký tự) vì không biết trước nhãn nào sẽ là nhãn đầu
# ô (nơi lỗi này xảy ra) khi quét toàn văn bản. Cho phép "%" tuỳ chọn giữa số
# và unit (ca thật ProGibb "40%SG:").
_FUZZY_UNIT_ALT = "|".join(_fuzzy(u) for u in _FORM_UNITS.split("|"))
_FUZZY_FORM_CODE = (
    r"\d(?:\s*[\d.,])*(?:\s*[+/]\s*\d(?:\s*[\d.,])*)*\s*%?\s*(?:" + _FUZZY_UNIT_ALT + ")"
)
# Nhãn CHỮ-KHÔNG-SỐ đứng riêng trong target (ca thật Kuraba "WP: sâu tơ...").
# Cùng nguyên tắc case-sensitive-exact như _FORM_CODE ở trên — CHỈ khớp khi
# token viết HOA TOÀN BỘ đúng 1 unit đã biết, không fuzzy spacing (không có
# bằng chứng thật cần fuzzy cho dạng này, thêm fuzzy sẽ tăng rủi ro match
# nhầm không cần thiết).
_LABEL_ITEM = rf"(?:(?i:{_FUZZY_FORM_CODE}))|(?:{_FORM_UNITS})"
_LABEL_RE = re.compile(
    rf"((?:{_LABEL_ITEM})(?:\s*,\s*(?:{_LABEL_ITEM}))*)\s*:",
)


def split_formulation(trade: str) -> tuple[str, str | None]:
    m = _FORM_RE.search(trade)
    if not m:
        return trade.strip(), None
    return trade[: m.start()].strip(), m.group(1).replace(" ", "")


def split_formulations(trade: str) -> tuple[str, list[str]]:
    """Như split_formulation nhưng nhận diện CẢ trường hợp 1 ô trade chứa
    NHIỀU mã quy cách cách nhau bằng dấu phẩy (vd "Mikmire 2.0EC, 14.5WG").
    Đây là mẫu RẤT PHỔ BIẾN trong Phụ lục I (không chỉ 5 sản phẩm đã biết bị
    ảnh hưởng trong amendment TT28 — Pesmos, Mikmire, Mikhada, Folpan,
    Lambast): split_formulation cũ chỉ bắt được mã CUỐI CÙNG bằng regex neo
    `$`, phần các mã trước đó dính nguyên vào trade_name kèm dấu phẩy rác
    (vd "Mikmire 2.0EC," thay vì trade_name sạch "Mikmire").

    Tách bằng cách lặp lại _FORM_RE từ phải sang trái — mỗi vòng bóc đúng 1
    mã quy cách ở cuối chuỗi hiện tại rồi bỏ dấu phẩy/khoảng trắng thừa mới
    lộ ra, cho tới khi không còn khớp. An toàn vì dùng lại NGUYÊN _FORM_RE
    đã review/test cho từng mã đơn, không đoán ranh giới mới.

    Trả về (trade_name sạch, [mã quy cách theo đúng thứ tự trái->phải]).
    List rỗng nếu trade không có mã quy cách nào (giữ nguyên hành vi cũ của
    split_formulation cho trường hợp không có formulation).
    """
    name = trade
    forms: list[str] = []
    while True:
        m = _FORM_RE.search(name)
        if not m:
            break
        forms.append(m.group(1).replace(" ", ""))
        name = name[: m.start()].rstrip().rstrip(",").rstrip()
    forms.reverse()
    return name.strip(), forms


def codes_only_formulations(trade: str) -> list[str] | None:
    """Bug class 2 (Task 5e): pdfplumber đôi khi ngắt TRANG ngay GIỮA Ô
    TRADE của 1 sản phẩm nhiều quy cách — phần TÊN sản phẩm ở lại hàng đầu
    (trang trước), phần DANH SÁCH MÃ QUY CÁCH còn lại rơi xuống hàng kế tiếp
    (trang sau) như MỘT Ô TRADE non-rỗng riêng biệt (khác hẳn continuation
    thường thấy có trade RỖNG). `to_entries` trước đây coi bất kỳ hàng nào có
    `trade` non-rỗng là mở SẢN PHẨM MỚI -> mảnh mã quy cách này bị hiểu nhầm
    thành 1 "sản phẩm ma" tên đúng bằng chuỗi mã (vd trade_name "1GR" hoặc
    "700WP" — xem ca thật Oshin, Ramsing trong task-5d report mục 1.4).

    Trả về list mã quy cách (theo đúng thứ tự trong text) NẾU VÀ CHỈ NẾU
    toàn bộ `trade` (tách theo dấu phẩy) là mã quy cách — KHÔNG còn phần
    nào là tên/chữ khác. Đây là tín hiệu CHẶT: 1 ô trade thật (mở sản phẩm
    mới) luôn có ít nhất 1 token không phải mã (chính là tên sản phẩm) đứng
    trước mã đầu tiên — verify bằng quét toàn Phụ lục I, xem test
    `test_codes_only_formulations_full_annex1_no_false_positive`.

    Trả None nếu KHÔNG phải dạng này (kể cả khi rỗng, hoặc có ô trống giữa
    2 dấu phẩy) — caller coi như trade thật, giữ nguyên hành vi mở nhóm mới
    (an toàn hơn: thà bỏ sót 1 mảnh ngắt trang hiếm gặp hơn là nuốt nhầm 1
    sản phẩm thật có tên trùng ngẫu nhiên với mã quy cách)."""
    text = " ".join(trade.split())
    if not text:
        return None
    parts = [p.strip() for p in text.split(",")]
    if any(not p for p in parts):
        return None
    codes = []
    for p in parts:
        if not _FORM_CODE_TOKEN_RE.fullmatch(p):
            return None
        codes.append(p.replace(" ", ""))
    return codes


def split_targets(target: str) -> list[tuple[str, str]]:
    """'sâu cuốn lá, rầy nâu/lúa; rệp sáp/cà phê' → [(pest, crop), ...]

    Trong PDF thật, "\\n" chỉ là chỗ wrap dòng do cột hẹp (không phải dấu
    phân cách cặp) — join lại thành khoảng trắng trước khi tách theo ";".
    Cả hai vế của "/" có thể liệt kê nhiều mục cách nhau bằng ",": vế cây
    trồng nhiều mục là crop bẩn thường gặp (ví dụ "nhện đỏ/ chè, cam") nên
    phải tách thành tích Descartes pest × crop để không sót cặp và không
    còn dấu "," lẫn trong tên cây.

    Một số part (~10% trên Phụ lục I thật, xem Task 4 report) chứa >1 dấu
    "/" sau khi join — không phải do lỗi split_targets mà do ô "target"
    trong PDF gốc bị pdfplumber gộp nhiều khối công thức/mã (vd "3.6EC:
    ...; 5WG: ...") thành một cell không có ";" phân cách đúng chỗ. Từ
    Task 5b, phần khối tiền tố quy cách này được tách RIÊNG ở mức cao hơn
    bởi `split_uses_by_formulation` (gọi trước, theo đúng quy cách của sản
    phẩm) — hàm split_targets ở đây vẫn giữ nguyên xử lý AN TOÀN cho phần
    còn lại (hoặc khi không tách được theo quy cách): dùng rsplit(1) — chỉ
    tách theo dấu "/" CUỐI CÙNG, giữ nguyên các dấu "/" trước đó lẫn trong
    vế pest (không cố suy đoán ranh giới) — an toàn hơn là đoán sai và tạo
    cặp sai lệch không kiểm chứng được.
    """
    out: list[tuple[str, str]] = []
    text = " ".join(target.split())  # \n chỉ là wrap dòng → space, không mất dữ liệu
    for part in text.split(";"):
        part = part.strip().rstrip(",")
        if not part or "/" not in part:
            continue
        pests_s, crops_s = part.rsplit("/", 1)
        pests = [p.strip().lower() for p in pests_s.split(",") if p.strip()]
        crops = [c.strip().lower() for c in crops_s.split(",") if c.strip()]
        for pest in pests:
            for crop in crops:
                out.append((pest, crop))
    return out


def parse_viet_number(s: str) -> float:
    s = s.strip().replace(" ", "")
    if "," in s:                      # 0,5 → 0.5 ; 1.200,5 → 1200.5
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):  # 1.200 → 1200
        s = s.replace(".", "")
    return float(s)


def split_uses_by_formulation(target: str, forms: list[str]) -> dict[str, list[tuple[str, str]]] | None:
    """Tách 1 ô target dạng khối tiền tố quy cách (vd "3.6EC: sâu tơ/ bắp
    cải...; 10WP: sâu cuốn lá...") thành uses ĐÚNG quy cách tương ứng — xử
    lý phần lớn ~10.4% part multi-slash do pdfplumber gộp nhiều khối công
    thức trong 1 cell target thành 1 chuỗi không có ";" phân cách đúng chỗ
    (garble đã ghi nhận ở Task 4, xem docstring split_targets). Xác nhận
    bằng dữ liệu thật:
    - "Mikmire 2.0EC, 14.5WG" -> target "2.0EC: ...\\n14.5WG: sâu cuốn lá/lúa"
    - "Folpan 50WP, 50SC" -> target "5 0 W P : ...\\n50SC: ..." (nhãn ĐẦU ô
      bị pdfplumber dàn đều ký tự — _LABEL_RE cho phép fuzzy spacing)
    - "B52duc 56EC, 56SG, 68WG" -> target "56EC, 68WG: nhện gié...\\n56SG:
      ..." — NHIỀU mã CÙNG chia sẻ 1 nhãn/1 khối uses, cách nhau bằng dấu
      phẩy trước dấu ":" (_LABEL_RE nhận cả dạng danh sách này).

    Trả về dict {formulation: [(pest,crop), ...]} — CHỈ khi nhận diện được
    ÍT NHẤT 2 nhãn quy cách trong ô target (1 nhãn đơn lẻ không đủ tín hiệu
    chắc chắn để coi là dạng khối — trả None, caller dùng split_targets
    thường, dùng CHUNG cho mọi quy cách — hướng đọc mặc định của Bug 2 mục
    2). `forms` phải có >= 2 phần tử (sản phẩm nhiều quy cách) — 1 quy cách
    thì không có gì để tách theo, trả None.

    AN TOÀN THEO ĐÚNG YÊU CẦU (thà thiếu use hơn gán sai quy cách):
    - Phần text TRƯỚC nhãn đầu tiên (nếu còn nội dung, không rõ thuộc quy
      cách nào) bị BỎ + đếm `ambiguous_target_block_count` — không đoán.
    - Block có nhãn nhưng KHÔNG mã nào trong nhãn đó khớp quy cách nào của
      `forms` (nhãn "lạ", ví dụ lỗi gõ hoặc quy cách không có trong ô
      trade) -> vẫn biết chắc thuộc SẢN PHẨM này (nằm trong đúng ô target
      của nó), chỉ không chắc quy cách nào -> gán uses của block đó cho
      MỌI quy cách + đếm `unmatched_formulation_block_count` để QA soát.
    """
    global ambiguous_target_block_count, unmatched_formulation_block_count
    if len(forms) < 2:
        return None
    text = " ".join(target.split())
    matches = list(_LABEL_RE.finditer(text))
    if len(matches) < 2:
        return None  # không đủ tín hiệu -> không phải dạng khối tiền tố quy cách

    norm_forms = {f.replace(" ", "").upper(): f for f in forms}
    lead = text[: matches[0].start()].strip(" ;,.")
    if lead:
        ambiguous_target_block_count += 1
        logger.warning("split_uses_by_formulation: bo phan dau khoi khong ro quy cach: %r", lead)

    result: dict[str, list[tuple[str, str]]] = {f: [] for f in forms}
    for i, m in enumerate(matches):
        codes = [c.replace(" ", "").upper() for c in m.group(1).split(",")]
        label_forms = [norm_forms[c] for c in codes if c in norm_forms]
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        pairs = split_targets(text[m.end():block_end])
        if label_forms:
            for f in label_forms:
                result[f].extend(pairs)
        else:
            unmatched_formulation_block_count += 1
            logger.warning("split_uses_by_formulation: nhan la (%r) khong khop quy cach nao trong %r",
                            m.group(1), forms)
            for f in forms:
                result[f].extend(pairs)
    return result


def _assign_uses(group: list[dict], target: str) -> None:
    """Gán uses của 1 hàng (target) cho TOÀN BỘ entry cùng nhóm (`group` —
    thường 1 entry, nhiều hơn khi 1 ô trade chứa nhiều quy cách, xem
    split_formulations). Mặc định: dùng CHUNG toàn bộ uses của dòng cho mọi
    quy cách trong nhóm (cách đọc chuẩn của danh mục khi target không chia
    theo quy cách). Nếu nhóm có >1 quy cách VÀ target nhận diện được dạng
    khối tiền tố quy cách (split_uses_by_formulation trả khác None) thì gán
    đúng quy cách tương ứng thay vì dùng chung."""
    forms = [e["formulation"] for e in group if e["formulation"]]
    by_form = split_uses_by_formulation(target, forms) if len(group) > 1 else None
    if by_form is not None:
        for e in group:
            if e["formulation"] in by_form:
                e["uses"].extend(by_form[e["formulation"]])
        return
    pairs = split_targets(target)
    for e in group:
        e["uses"].extend(pairs)


def to_entries(rows: list[dict], allow_no_trade: bool = False) -> list[dict]:
    """CRITICAL FIX (Task 5d, re-review sau 5b/5c): trước đây gọi
    `_assign_uses(cur_group, r["target"])` MỖI HÀNG — khi 1 khối nhãn quy
    cách (vd "1.8EC: ...; 5.0WG: ...") bị pdfplumber ngắt qua >= 2 hàng vật
    lý (ngắt trang giữa ô target của CÙNG 1 sản phẩm, ca thật: Agromectin
    tr.1->2, Daconil tr.167->168), MỖI hàng chỉ thấy ĐÚNG 1 nhãn quy cách
    trong text của riêng nó -> `split_uses_by_formulation` (cần >= 2 nhãn
    mới kích hoạt) không bao giờ thấy đủ nhãn -> cả 2 lần gọi đều rơi về
    `split_targets` mặc định (broadcast CHUNG uses cho MỌI quy cách trong
    nhóm) -> uses nhân bản sai quy cách + nhãn quy cách lọt vào cột pest
    thành rác (phần "5.0WG:" nằm giữa text bị `split_targets` nuốt luôn
    vào 1 "part" rồi rsplit("/") sai chỗ).

    Fix: KHÔNG gọi `_assign_uses` ngay mỗi hàng — tích luỹ `r["target"]`
    của hàng mở nhóm + mọi hàng tiếp diễn vào `target_buffer` (join bằng
    "\\n", giống cách 1 ô nhiều dòng đã nối trước giờ), CHỈ gọi
    `_assign_uses(cur_group, "\\n".join(target_buffer))` ĐÚNG 1 LẦN khi
    nhóm ĐÓNG — tức khi gặp hàng mở sản phẩm mới (`r["trade"]` khác rỗng)
    hoặc hàng mở hoạt chất mới ở Phụ lục II (`allow_no_trade and r["ai"]`),
    hoặc hết input. Nhờ vậy toàn bộ text của khối nhãn (dù trải mấy hàng)
    được nhìn thấy CÙNG LÚC bởi `split_uses_by_formulation`.

    pages/registrant vẫn cập nhật NGAY theo từng hàng như cũ (không dời
    theo nhóm) — chỉ việc gán uses là dời tới lúc đóng nhóm.

    Với nhóm 1 quy cách (~99% trường hợp, xem Task 5d report mục verify):
    kết quả (pest, crop) không đổi so với union per-row cũ, vì nối "\\n"
    rồi `split_targets` chuẩn hoá whitespace (coi "\\n" như dấu cách) đúng
    y hệt cách nó đã xử lý wrap dòng NỘI BỘ 1 ô từ trước — chỉ khác là áp
    dụng luôn cho ranh giới NGẮT TRANG (một dạng wrap khác của cùng 1 ô).

    BUG CLASS 2 (Task 5e): pdfplumber đôi khi ngắt trang ngay GIỮA Ô TRADE
    (không phải target) của 1 sản phẩm — hàng đầu chỉ có TÊN sản phẩm, mảnh
    DANH SÁCH MÃ QUY CÁCH rơi xuống hàng kế tiếp NHƯ MỘT Ô TRADE non-rỗng
    riêng (ca thật: "Oshin" rồi "1GR, 20WP, 20SG, 100SL"; "Ramsing" rồi
    "700WP, 700WG"). Vì mọi hàng có `trade` non-rỗng trước đây đều bị hiểu
    là mở SẢN PHẨM MỚI, mảnh này biến thành "sản phẩm ma" tên đúng bằng
    chuỗi mã (registry sẽ có product tên "700WP"...). Fix: nếu hàng đang xét
    CÓ trade, KHÔNG có ai riêng (`not r["ai"]` — mảnh ngắt trang không bao
    giờ tự xưng lại hoạt chất), VÀ nhóm đang mở còn tồn tại, kiểm tra
    `codes_only_formulations(r["trade"])` — nếu toàn bộ trade chỉ là mã quy
    cách (không còn tên nào), đây CHẮC CHẮN là mảnh tiếp diễn của ô trade
    hàng trước (không phải sản phẩm mới): KHÔNG flush/mở nhóm mới, mà bổ
    sung mã quy cách đó vào nhóm ĐANG MỞ — thay formulation=None hiện có
    (nếu hàng mở nhóm chưa có mã quy cách nào, đúng ca Oshin/Ramsing) bằng
    mã ĐẦU TIÊN, các mã còn lại thành entry mới cùng ai/registrant/
    trade_name của nhóm. target/pages/registrant của hàng này vẫn tiếp tục
    vào buffer/nhóm như hàng tiếp diễn bình thường (code chung phía dưới)."""
    global orphan_drop_count, trade_fragment_continuation_count
    entries: list[dict] = []
    cur_group: list[dict] | None = None  # entry cùng thuộc 1 hàng logic (thường 1, >1 nếu trade nhiều quy cách)
    target_buffer: list[str] = []

    def flush_group() -> None:
        if cur_group is not None:
            _assign_uses(cur_group, "\n".join(target_buffer))
        target_buffer.clear()

    for r in rows:
        if r["ai"]:                    # hoạt chất mới hoặc lặp lại tên
            ai = " ".join(r["ai"].split())
        elif cur_group is not None:
            ai = cur_group[0]["ai"]
        else:
            # hàng tiếp diễn mồ côi đầu file (Bug 1, Task 5b): trước đây bỏ
            # âm thầm không đếm — nay đếm + log để QA phát hiện nếu tái diễn
            # (0 là tốt nhất; > 0 cần soát bằng scripts/inspect_pdf.py).
            orphan_drop_count += 1
            logger.warning("to_entries: bo dong orphan (chua co hoat chat), trade=%r page=%s",
                            r.get("trade"), r.get("page"))
            continue
        frag_codes = None
        if r["trade"] and cur_group is not None and not r["ai"]:
            # Chỉ xét mảnh ngắt-trang-ô-trade khi ĐANG có nhóm mở và hàng
            # này KHÔNG tự xưng hoạt chất riêng (điều kiện chặt — xem
            # docstring hàm). Khi cur_group is None, r["ai"] rỗng đã bị
            # `continue` ở nhánh orphan phía trên rồi nên không tới được
            # đây; ai luôn resolve được ở đây.
            frag_codes = codes_only_formulations(r["trade"])
        if frag_codes is not None:
            # Bug class 2 (Task 5e): mảnh CÒN LẠI của ô trade hàng trước bị
            # pdfplumber ngắt trang — KHÔNG mở nhóm mới, bổ sung mã quy cách
            # vào nhóm đang mở.
            trade_fragment_continuation_count += 1
            logger.warning(
                "to_entries: gop manh trade ngat trang (codes-only) vao nhom dang mo "
                "%r: %r, page=%s", cur_group[0]["trade_name"], r["trade"], r.get("page"))
            base_name = cur_group[0]["trade_name"]
            existing = {e["formulation"] for e in cur_group if e["formulation"]}
            remaining = list(frag_codes)
            if len(cur_group) == 1 and cur_group[0]["formulation"] is None and remaining:
                cur_group[0]["formulation"] = remaining.pop(0)
                existing.add(cur_group[0]["formulation"])
            for form in remaining:
                if form in existing:
                    continue
                # Ưu tiên registrant ĐÃ CÓ của nhóm (thường đầy đủ, set từ
                # hàng mở nhóm) hơn r["registrant"] của CHÍNH hàng mảnh vỡ
                # này — cột registrant có thể bị ngắt trang ĐỘC LẬP với cột
                # trade (ca thật Kasugacin/Mexyl MZ/Saicoba: hàng mảnh vỡ có
                # registrant chỉ còn phần ĐUÔI bị cắt, vd "Việt Nam"/"Sài
                # Gòn" — dùng nhầm sẽ tạo registrant sai/không nhất quán
                # giữa các quy cách CÙNG 1 sản phẩm).
                e = {"ai": ai, "trade_name": base_name, "formulation": form,
                     "registrant": cur_group[0]["registrant"] or r["registrant"],
                     "uses": [], "pages": []}
                entries.append(e)
                cur_group.append(e)
                existing.add(form)
        elif r["trade"]:
            # Hàng mở SẢN PHẨM MỚI (kể cả cùng hoạt chất) -> đóng nhóm cũ
            # (flush toàn bộ target đã gom của nhóm đó) TRƯỚC khi mở nhóm
            # mới — không được gộp target của 2 sản phẩm khác nhau.
            flush_group()
            # 1 ô trade có thể chứa NHIỀU mã quy cách (Bug 2, Task 5b, vd
            # "Mikmire 2.0EC, 14.5WG") -> tách thành nhiều entry, cùng
            # ai/registrant, mỗi entry một formulation, trade_name sạch.
            name, forms = split_formulations(" ".join(r["trade"].split()))
            cur_group = []
            for form in (forms or [None]):
                e = {"ai": ai, "trade_name": name, "formulation": form,
                     "registrant": r["registrant"], "uses": [], "pages": []}
                entries.append(e)
                cur_group.append(e)
        elif allow_no_trade and r["ai"]:
            # Phụ lục II (cấm): nhiều dòng chỉ có hoạt chất, không có thương
            # phẩm -> mỗi hàng là 1 nhóm riêng, cũng phải đóng nhóm cũ trước.
            flush_group()
            e = {"ai": ai, "trade_name": "", "formulation": None,
                 "registrant": r["registrant"], "uses": [], "pages": []}
            entries.append(e)
            cur_group = [e]
        if cur_group is None:
            continue
        target_buffer.append(r["target"])
        for e in cur_group:
            if r["page"] not in e["pages"]:
                e["pages"].append(r["page"])
            if r["registrant"] and not e["registrant"]:
                e["registrant"] = r["registrant"]
    flush_group()  # đóng nhóm cuối cùng (hết input)
    return entries

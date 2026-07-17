import json
from pathlib import Path

import pytest

import ingest.normalize as normalize
from ingest.normalize import (
    _LABEL_RE,
    codes_only_formulations,
    parse_viet_number,
    split_formulation,
    split_formulations,
    split_targets,
    split_uses_by_formulation,
    to_entries,
)

def test_split_formulation():
    assert split_formulation("Reasgant 1.8EC") == ("Reasgant", "1.8EC")
    assert split_formulation("Actara 25WG") == ("Actara", "25WG")
    assert split_formulation("Ridomil Gold 68WG") == ("Ridomil Gold", "68WG")
    assert split_formulation("Ống Vàng") == ("Ống Vàng", None)

def test_split_targets_pest_slash_crop():
    assert split_targets("sâu cuốn lá/lúa") == [("sâu cuốn lá", "lúa")]
    assert split_targets("rệp sáp/ cà phê") == [("rệp sáp", "cà phê")]

def test_split_targets_multi():
    got = split_targets("sâu cuốn lá, rầy nâu/lúa; rệp sáp/cà phê")
    assert got == [("sâu cuốn lá", "lúa"), ("rầy nâu", "lúa"), ("rệp sáp", "cà phê")]

def test_split_targets_line_wrap_not_lost():
    # \n trong ô PDF là wrap dòng, không phải dấu phân cách cặp — "dưa hấu"
    # không được bị vứt.
    assert split_targets("bọ trĩ/\ndưa hấu") == [("bọ trĩ", "dưa hấu")]

def test_split_targets_multi_crop_after_slash():
    # Crop bẩn chứa dấu phẩy: 2 cây sau "/" phải tách thành 2 cặp.
    assert split_targets("nhện đỏ/ chè, cam") == [("nhện đỏ", "chè"), ("nhện đỏ", "cam")]

def test_split_targets_multi_pest_and_single_crop():
    got = split_targets("sâu đục thân, sâu cuốn lá/ lúa")
    assert got == [("sâu đục thân", "lúa"), ("sâu cuốn lá", "lúa")]

def test_split_targets_real_annex_sample():
    # Mẫu thật Phụ lục I (TT 75/2025), gồm dấu ; phân cách cặp và \n wrap
    # dòng giữa "bọ trĩ/" và "dưa hấu" do ngắt cột trong PDF.
    sample = ("sâu cuốn lá/lúa; nhện đỏ/cam; sâu xanh/ lạc; bọ trĩ/\n"
              "dưa hấu; sâu vẽ bùa/ cà chua")
    got = split_targets(sample)
    assert got == [
        ("sâu cuốn lá", "lúa"),
        ("nhện đỏ", "cam"),
        ("sâu xanh", "lạc"),
        ("bọ trĩ", "dưa hấu"),
        ("sâu vẽ bùa", "cà chua"),
    ]
    assert all(crop for _pest, crop in got)  # không cặp nào crop rỗng

def test_to_entries_merges_continuation():
    # target hàng mở nhóm ("nhện đỏ/cam;") kết thúc bằng ";" — đúng như PDF
    # thật ngắt trang giữ nguyên dấu phân cách cuối dòng trước khi wrap
    # (xem Task 5d: buffer target theo NHÓM thay vì gọi _assign_uses mỗi
    # hàng — nếu thiếu ";" ở đây, hàng tiếp diễn "bọ trĩ/lúa" sẽ bị NỐI
    # nhầm vào cùng 1 part với "nhện đỏ/cam", cho ra 1 cặp sai thay vì 2
    # cặp đúng; ";" mô phỏng đúng cách pdfplumber giữ dấu câu ở cuối dòng
    # trước khi ngắt, không phải nới lỏng test).
    rows = [
        {"tt": "1", "ai": "Abamectin", "trade": "Reasgant 1.8EC",
         "target": "sâu cuốn lá/lúa", "registrant": "Cty A", "page": 3},
        {"tt": "", "ai": "", "trade": "Reasgant 3.6EC",
         "target": "nhện đỏ/cam;", "registrant": "Cty A", "page": 3},
        {"tt": "", "ai": "", "trade": "",
         "target": "bọ trĩ/lúa", "registrant": "", "page": 4},
    ]
    entries = to_entries(rows)
    assert len(entries) == 2
    assert entries[0]["trade_name"] == "Reasgant" and entries[0]["formulation"] == "1.8EC"
    assert entries[1]["uses"] == [("nhện đỏ", "cam"), ("bọ trĩ", "lúa")]

def test_parse_viet_number():
    assert parse_viet_number("0,5") == 0.5
    assert parse_viet_number("1.200") == 1200.0
    assert parse_viet_number("25") == 25.0

def test_to_entries_banned_ai_only():
    rows = [{"tt": "1", "ai": "Carbofuran", "trade": "", "target": "", "registrant": "", "page": 1}]
    assert to_entries(rows) == []                    # mặc định: bỏ dòng không có thương phẩm
    got = to_entries(rows, allow_no_trade=True)      # chế độ Phụ lục II (cấm)
    assert got[0]["ai"] == "Carbofuran" and got[0]["trade_name"] == ""


# --- Bug 2 (Task 5b): 1 ô trade chứa NHIỀU mã quy cách (vd "Mikmire 2.0EC,
# 14.5WG") -> split_formulation cũ chỉ bắt mã CUỐI, phần trước dính rác vào
# trade_name. Các mẫu dưới đây lấy NGUYÊN TRẠNG từ data/raw/tt75_2025_page_1.pdf
# (đã verify bằng parse_pdf thật khi chẩn đoán — xem task-5b report).

def test_split_formulations_multi_code_comma_separated():
    assert split_formulations("Mikmire 2.0EC, 14.5WG") == ("Mikmire", ["2.0EC", "14.5WG"])
    assert split_formulations("Folpan 50 WP, 50 SC") == ("Folpan", ["50WP", "50SC"])
    assert split_formulations("Goldmectin 36EC, 60SC, 70SG") == ("Goldmectin", ["36EC", "60SC", "70SG"])


def test_split_formulations_single_code_matches_split_formulation():
    assert split_formulations("Reasgant 1.8EC") == ("Reasgant", ["1.8EC"])
    assert split_formulations("Ống Vàng") == ("Ống Vàng", [])


def test_to_entries_splits_multi_formulation_trade_into_multiple_entries_shared_uses():
    # Mẫu thật: "Mikmire 2.0EC, 14.5WG" (Task 5 amendment TT28, đối chiếu tay
    # với registry.db từng KHÔNG khớp do bug này). target không có tiền tố
    # quy cách -> mặc định dùng CHUNG uses cho cả 2 quy cách.
    rows = [{"tt": "1", "ai": "Abamectin", "trade": "Mikmire 2.0EC, 14.5WG",
             "target": "sâu cuốn lá/lúa; nhện đỏ/cam", "registrant": "Cty Minh Khai", "page": 86}]
    entries = to_entries(rows)
    assert len(entries) == 2
    assert {e["trade_name"] for e in entries} == {"Mikmire"}
    assert {e["formulation"] for e in entries} == {"2.0EC", "14.5WG"}
    for e in entries:
        assert e["uses"] == [("sâu cuốn lá", "lúa"), ("nhện đỏ", "cam")]
        assert e["registrant"] == "Cty Minh Khai"
        assert e["ai"] == "Abamectin"


def test_split_uses_by_formulation_real_mikmire_prefixed_target():
    # target thật của Mikmire trong data/raw/tt75_2025_page_1.pdf trang 86
    target = ("2.0EC: bọ xít, sâu đục quả/ vải; rầy bông/ xoài\n"
              "14.5WG: sâu cuốn lá/lúa")
    got = split_uses_by_formulation(target, ["2.0EC", "14.5WG"])
    assert got == {
        "2.0EC": [("bọ xít", "vải"), ("sâu đục quả", "vải"), ("rầy bông", "xoài")],
        "14.5WG": [("sâu cuốn lá", "lúa")],
    }


def test_split_uses_by_formulation_real_folpan_fuzzy_first_label():
    # target thật của Folpan (data/raw/tt75_2025_page_1.pdf trang 201) — nhãn
    # ĐẦU ô bị pdfplumber dàn đều ký tự thành "5 0 W P :" (trade cell vẫn
    # đúng "50 WP"), nhãn thứ 2 "50SC:" không bị lỗi này.
    target = ("5 0 W P : khô vằn, đạo ôn/ lúa, giả sương mai/dưa hấu\n"
              "50SC: khô vằn, đạo ôn/ lúa; thán thư/ xoài; mốc\nsương/ nho; đốm lá/ hành")
    got = split_uses_by_formulation(target, ["50WP", "50SC"])
    assert got is not None
    assert got["50SC"] == [("khô vằn", "lúa"), ("đạo ôn", "lúa"), ("thán thư", "xoài"),
                            ("mốc sương", "nho"), ("đốm lá", "hành")]
    assert len(got["50WP"]) > 0  # phần garble multi-slash đã biết (Task 4) vẫn còn trong pest, nhưng KHÔNG rỗng


def test_split_uses_by_formulation_real_b52duc_shared_label_multi_code():
    # target thật của B52duc (data/raw/tt75_2025_page_1.pdf) — nhãn liệt kê
    # NHIỀU mã quy cách cùng chia sẻ 1 khối uses, cách nhau bằng dấu phẩy
    # trước dấu ":": "56EC, 68WG: ...".
    target = "56EC, 68WG: nhện gié, sâu cuốn lá/ lúa\n56SG: sâu cuốn lá, rầy nâu/lúa"
    got = split_uses_by_formulation(target, ["56EC", "56SG", "68WG"])
    assert got["56EC"] == [("nhện gié", "lúa"), ("sâu cuốn lá", "lúa")]
    assert got["68WG"] == [("nhện gié", "lúa"), ("sâu cuốn lá", "lúa")]
    assert got["56SG"] == [("sâu cuốn lá", "lúa"), ("rầy nâu", "lúa")]


def test_split_uses_by_formulation_safety_paths_synthetic():
    normalize.ambiguous_target_block_count = 0
    normalize.unmatched_formulation_block_count = 0

    # < 2 nhãn -> không đủ tín hiệu, trả None (dùng split_targets mặc định)
    assert split_uses_by_formulation("3.6EC: sau to/ bap cai", ["3.6EC", "5WG"]) is None
    assert split_uses_by_formulation("sau cuon la/ lua", ["3.6EC", "5WG"]) is None
    assert split_uses_by_formulation("3.6EC: a/b; 5WG: c/d", ["3.6EC"]) is None  # 1 quy cách -> None

    # phần TRƯỚC nhãn đầu tiên không rõ thuộc quy cách nào -> bỏ + đếm, KHÔNG đoán
    got = split_uses_by_formulation(
        "mo ta chung/ cay X; 3.6EC: sau to/ bap cai; 5WG: ray nau/ lua", ["3.6EC", "5WG"])
    assert got == {"3.6EC": [("sau to", "bap cai")], "5WG": [("ray nau", "lua")]}
    assert normalize.ambiguous_target_block_count == 1

    # nhãn có mã KHÔNG khớp quy cách nào của dòng -> gán MỌI quy cách + đếm
    # (an toàn hơn bỏ hẳn vì chắc chắn thuộc đúng sản phẩm này)
    got2 = split_uses_by_formulation(
        "3.6EC: sau to/ bap cai; 10WP: nhen do/ cam; 5WG: ray nau/ lua", ["3.6EC", "5WG"])
    assert got2["3.6EC"] == [("sau to", "bap cai"), ("nhen do", "cam")]
    assert got2["5WG"] == [("nhen do", "cam"), ("ray nau", "lua")]
    assert normalize.unmatched_formulation_block_count == 1


def test_orphan_drop_count_increments_on_true_orphan_row():
    before = normalize.orphan_drop_count
    rows = [{"tt": "", "ai": "", "trade": "Reasgant 1.8EC",
             "target": "sâu cuốn lá/lúa", "registrant": "Cty A", "page": 0}]
    entries = to_entries(rows)
    assert entries == []  # vẫn bỏ như cũ (return giữ nguyên hành vi)
    assert normalize.orphan_drop_count == before + 1


def test_reset_counters():
    normalize.orphan_drop_count = 5
    normalize.ambiguous_target_block_count = 3
    normalize.unmatched_formulation_block_count = 2
    normalize.reset_counters()
    assert normalize.orphan_drop_count == 0
    assert normalize.ambiguous_target_block_count == 0
    assert normalize.unmatched_formulation_block_count == 0


# --- Critical fix (Task 5d, re-review sau 5b/5c): _assign_uses cũ gọi MỖI
# HÀNG -> khi 1 khối nhãn quy cách bị pdfplumber ngắt qua >= 2 hàng vật lý
# (ngắt trang giữa ô target của CÙNG 1 sản phẩm), mỗi hàng chỉ thấy ĐÚNG 1
# nhãn quy cách trong text riêng của nó -> split_uses_by_formulation (cần
# >= 2 nhãn) không bao giờ kích hoạt -> broadcast uses CHUNG cho MỌI quy
# cách + nhãn quy cách rác lọt vào cột pest. Fix: buffer target theo NHÓM,
# chỉ gọi _assign_uses khi nhóm đóng. 2 test dưới dùng NGUYÊN VĂN dữ liệu
# thật (rows) từ data/raw/tt75_2025_page_1.pdf (trích bằng parse_pdf thật,
# xem Task 5d report) — không sửa trade/target, chỉ gắn "ai" trực tiếp lên
# hàng mở nhóm (Agromectin/Daconil vốn kế thừa ai từ nhóm hoạt chất trước
# đó qua nhiều hàng — không cần chép lại toàn bộ để cô lập test).

def test_to_entries_agromectin_real_page_break_splits_formulation_labels():
    # data/raw/tt75_2025_page_1.pdf, pdfplumber rows 23-24 (trang 1->2):
    # trade "Agromectin\n1.8 EC, 5.0WG" bị ngắt trang giữa khối target —
    # hàng 1 chỉ thấy nhãn "1.8EC:", hàng tiếp diễn (trang 2) mới thấy
    # "5.0WG:". Trước fix: cả 2 quy cách nhận CHUNG 9 uses trùng lặp + rác
    # nhãn "5.0wg:" lọt vào pest. Sau fix: tách đúng 8 (1.8EC) - vs - 1
    # (5.0WG), đúng số reviewer đã xác nhận trên registry thật.
    rows = [
        {"tt": "", "ai": "Abamectin\n(min 90%)", "trade": "Agromectin\n1.8 EC, 5.0WG",
         "target": "1.8EC: nhện gié/ lúa, sâu xanh bướm trắng/ bắp\ncải, sâu tơ/ súp lơ, "
                   "bọ nhảy/ cải thảo, sâu xanh/ cải",
         "registrant": "Công ty TNHH Nam Bắc", "page": 1},
        {"tt": "", "ai": "", "trade": "",
         "target": "xanh, bọ trĩ/ nho, nhện đỏ/ cam, sâu xanh da láng/\nhành\n5.0WG: sâu cuốn lá/ lúa",
         "registrant": "", "page": 2},
    ]
    entries = to_entries(rows)
    assert len(entries) == 2
    by_form = {e["formulation"]: e for e in entries}
    assert set(by_form) == {"1.8EC", "5.0WG"}
    for e in entries:
        assert e["trade_name"] == "Agromectin"
        assert e["registrant"] == "Công ty TNHH Nam Bắc"
        assert e["pages"] == [1, 2]                    # inheritance pages giữ nguyên
        assert not any(_LABEL_RE.search(pest) for pest, _crop in e["uses"])  # KHÔNG còn rác nhãn
    assert len(by_form["1.8EC"]["uses"]) == 8           # 8-vs-1 đúng như reviewer xác nhận
    assert len(by_form["5.0WG"]["uses"]) == 1
    assert by_form["5.0WG"]["uses"] == [("sâu cuốn lá", "lúa")]


def test_to_entries_daconil_real_page_break_splits_formulation_labels():
    # data/raw/tt75_2025_page_1.pdf, pdfplumber rows 2559-2560 (trang 167->
    # 168): trade "Daconil\n75WP, 500SC" ngắt trang giữa khối target; nhãn
    # ĐẦU ô "7 5 W P :" còn bị dàn đều ký tự (fuzzy spacing, giống ca Folpan
    # đã test ở split_uses_by_formulation) NHƯNG lần này nội dung có đủ ";"
    # phân cách nên tách sạch hoàn toàn, không dính multi-slash-no-";" như
    # Agromectin.
    rows = [
        {"tt": "", "ai": "Chlorobromo isocyanuric\nacid (min 85%)", "trade": "Daconil\n75WP, 500SC",
         "target": "7 5 W P : phấn trắng/ hoa hồng, dưa chuột; đốm lá/\nhành, chè; bệnh đổ ngã cây "
                   "con/ bắp cải, thuốc lá;\nđạo ôn, khô vằn/ lúa; thán thư/ vải, ớt, xoài, chanh\n"
                   "leo, thanh long; sẹo, Melanos/ cam; mốc sương/",
         "registrant": "Công ty CP Việt Thắng Group", "page": 167},
        {"tt": "", "ai": "", "trade": "",
         "target": "khoai tây; giả sương mai/dưa hấu; phấn trắng, mốc\nsương/ cà chua; "
                   "sương mai/khoai tây\n500SC: đốm lá/lạc; thán thư/xoài, chè, dưa hấu,\n"
                   "nhãn, chanh leo; mốc sương/cà chua; giả sương mai/\ndưa chuột; đạo ôn, "
                   "khô vằn, lem lép hạt/ lúa; phấn\ntrắng/ nho, vải; sẹo, Melanos/cam; "
                   "mốc sương/ khoai\ntây; sương mai/ súp lơ, mướp; sương mai, thán thư,\n"
                   "rỉ sắt/đậu côve; đốm lá/ cà tím; đốm mắt cua, thối cổ\nrễ/ mồng tơi; "
                   "đốm mắt cua, phấn trắng/ ớt; lở cổ rễ/\nsu hào; sương mai, lở cổ rễ, "
                   "mốc xám/ rau cải; rỉ sắt,\nsương mai, thán thư/đậu đũa; rỉ trắng/rau muống",
         "registrant": "", "page": 168},
    ]
    entries = to_entries(rows)
    assert len(entries) == 2
    by_form = {e["formulation"]: e for e in entries}
    assert set(by_form) == {"75WP", "500SC"}
    for e in entries:
        assert e["trade_name"] == "Daconil"
        assert e["pages"] == [167, 168]
        assert not any(_LABEL_RE.search(pest) for pest, _crop in e["uses"])  # KHÔNG còn rác nhãn
        assert all(crop for _pest, crop in e["uses"])   # không cặp nào crop rỗng
        assert all("/" not in pest for pest, _crop in e["uses"])  # tách sạch, pest không dính "/"
    assert len(by_form["75WP"]["uses"]) == 20
    assert len(by_form["500SC"]["uses"]) == 34
    assert ("sương mai", "khoai tây") in by_form["75WP"]["uses"]
    assert ("rỉ trắng", "rau muống") in by_form["500SC"]["uses"]


def test_to_entries_new_trade_row_closes_group_does_not_merge_two_products():
    # Yêu cầu review: hàng tiếp diễn có TRADE MỚI (kể cả cùng hoạt chất)
    # phải ĐÓNG nhóm cũ trước — không được gộp target của 2 sản phẩm khác
    # nhau vào chung 1 buffer. Sản phẩm A (1 quy cách) có target thiếu dấu
    # kết ";" (mô phỏng lỗi lẽ ra sẽ merge nếu code buffer nhầm SANG sản
    # phẩm B) — nếu group không đóng đúng chỗ, uses của A sẽ bị nối lẫn
    # với uses của B qua "\n".join sai nhóm.
    rows = [
        {"tt": "1", "ai": "Abamectin", "trade": "SanPhamA 1.8EC",
         "target": "sâu cuốn lá/lúa", "registrant": "Cty A", "page": 1},
        {"tt": "", "ai": "", "trade": "SanPhamB 3.6EC",
         "target": "nhện đỏ/cam", "registrant": "Cty B", "page": 1},
    ]
    entries = to_entries(rows)
    assert len(entries) == 2
    a, b = entries
    assert a["trade_name"] == "SanPhamA" and a["uses"] == [("sâu cuốn lá", "lúa")]
    assert b["trade_name"] == "SanPhamB" and b["uses"] == [("nhện đỏ", "cam")]


# --- Task 5e Bug class 1: _FORM_UNITS thiếu đơn vị quy cách (PA/OF/GB/WS/
# ST/FW/OS), thiếu hỗ trợ "%" giữa số và unit (vd "40%SG"), và thiếu hỗ trợ
# mã CHỮ-KHÔNG-SỐ đứng riêng (vd "WP" không kèm số nào) — 7 ca thật nêu
# trong task-5d report mục 1.4/6 (Kuraba, Adephone, Nominee, Helix, Gaucho,
# Gold gibb, ProGibb) + 2 ca phát hiện thêm khi quét verify (Amet annong,
# Atra annong — cần thêm unit "FW"; Dithane cần thêm "OS", xem test full
# annex bên dưới). Mã hoá trực tiếp từ `data/raw/tt75_2025_page_1.pdf`
# (trade cell nguyên văn, chỉ nối "\n" thành khoảng trắng như to_entries làm
# trước khi gọi split_formulations).

def test_split_formulations_new_units_real_cases():
    assert split_formulations("Kuraba WP, 3.6EC") == ("Kuraba", ["WP", "3.6EC"])
    assert split_formulations("Adephone 25 PA, 480SL") == ("Adephone", ["25PA", "480SL"])
    assert split_formulations("Nominee 10SC, 100OF") == ("Nominee", ["10SC", "100OF"])
    assert split_formulations("Helix 15GB, 500WP") == ("Helix", ["15GB", "500WP"])
    assert split_formulations("Gaucho 70 WS, 600FS") == ("Gaucho", ["70WS", "600FS"])
    assert split_formulations("Gold gibb 20ST, 12SP, 40SG") == (
        "Gold gibb", ["20ST", "12SP", "40SG"])
    assert split_formulations("ProGibb 10 SP, 40%SG") == ("ProGibb", ["10SP", "40%SG"])
    # Phát hiện thêm khi verify toàn Phụ lục I (không nằm trong 7 ca task nêu
    # tên, nhưng cùng nguyên nhân — unit thiếu, cùng mức rủi ro thấp vì luôn
    # neo bằng số đứng trước):
    assert split_formulations("Amet annong 500FW, 800WP") == (
        "Amet annong", ["500FW", "800WP"])
    assert split_formulations("Atra annong 500 FW, 800WP") == (
        "Atra annong", ["500FW", "800WP"])
    assert split_formulations("Dithane® M-45 80WP, 600OS") == (
        "Dithane® M-45", ["80WP", "600OS"])


def test_bare_unit_code_requires_exact_uppercase_case_sensitive_guard():
    # An toàn bắt buộc (yêu cầu Task 5e): mã CHỮ-KHÔNG-SỐ chỉ được nhận diện
    # khi token viết HOA TOÀN BỘ khớp đúng 1 unit đã biết — chữ thường KHÔNG
    # được nuốt (giảm nguy cơ match nhầm tên riêng/chữ thường tiếng Việt).
    assert split_formulation("Something wp") == ("Something wp", None)
    assert split_formulation("Something Wp") == ("Something Wp", None)
    # ALL-CAPS nhưng KHÔNG khớp bất kỳ unit nào đã biết -> cũng không nuốt.
    assert split_formulation("Product ABCD") == ("Product ABCD", None)
    # Case đúng (viết hoa toàn bộ, khớp unit thật) vẫn phải nhận diện được.
    assert split_formulation("Kuraba WP") == ("Kuraba", "WP")


def test_form_code_does_not_swallow_numeric_style_product_name():
    # Lưu ý task 5e: tên sản phẩm dạng số như "2.4D" không được nuốt nhầm
    # thành mã quy cách — "D" không nằm trong _FORM_UNITS nên an toàn dù đã
    # thêm % và bare-unit support.
    assert split_formulation("Anco 2.4D") == ("Anco 2.4D", None)
    assert split_formulations("Anco 2.4D") == ("Anco 2.4D", [])


def test_split_uses_by_formulation_real_kuraba_bare_unit_label():
    # target thật của Kuraba (data/raw/tt75_2025_page_1.pdf trang 10->11) —
    # nhãn ĐẦU ô là mã CHỮ-KHÔNG-SỐ đứng riêng "WP:" (không có unit khác
    # đứng trước như mọi ca khác) — trước Task 5e, _LABEL_RE không nhận
    # diện được nhãn này (cần số đứng trước) nên toàn bộ text "WP: ..." lọt
    # vào pest thành rác. Test full to_entries ở dưới xác nhận hết rác.
    target = ("WP: sâu tơ, sâu xanh/ bắp cải\n"
              "3.6EC: sâu tơ, sâu xanh bướm trắng/ bắp cải; bọ trĩ/ dưa hấu")
    got = split_uses_by_formulation(target, ["WP", "3.6EC"])
    assert got is not None
    assert got["WP"] == [("sâu tơ", "bắp cải"), ("sâu xanh", "bắp cải")]
    assert got["3.6EC"] == [("sâu tơ", "bắp cải"), ("sâu xanh bướm trắng", "bắp cải"),
                             ("bọ trĩ", "dưa hấu")]


def test_to_entries_kuraba_real_bare_unit_no_label_garble():
    # Rows THẬT nguyên văn (data/raw/tt75_2025_page_1.pdf, pdfplumber idx
    # 125-126, trang 10->11): target ngắt trang GIỮA câu (không phải ở ranh
    # giới nhãn) — kiểm tra buffer-theo-nhóm (Task 5d) + bare-unit label
    # (Task 5e) hoạt động ĐÚNG CÙNG NHAU.
    rows = [
        {"tt": "", "ai": "Abamectin 0.1% (3.5%) +\nBacillus thuringiensis\nvar.kurstaki 1.9% (0.1%)",
         "trade": "Kuraba\nWP, 3.6EC",
         "target": ("WP: sâu tơ, sâu xanh, sâu đo, dòi đục lá/ bắp cải;\nsâu khoang, "
                    "sâu xanh/ lạc; sâu đo, sâu đục quả/ đậu\ntương; sâu xanh, dòi đục lá/ "
                    "cà chua; bọ trĩ/ dưa\nchuột; sâu đục thân/ ngô; sâu đục gân lá, sâu đục"),
         "registrant": "Công ty TNHH Sản phẩm\nCông Nghệ Cao", "page": 10},
        {"tt": "", "ai": "", "trade": "",
         "target": ("quả/ vải; nhện đỏ/ chè; nhện đỏ, sâu vẽ bùa, sâu ăn\nlá/ cam; "
                    "sâu xanh/ bông vải; sâu róm/ thông\n3.6EC: sâu tơ, sâu xanh bướm "
                    "trắng/ bắp cải; bọ trĩ/\ndưa hấu; nhện đỏ, sâu vẽ bùa/cam; nhện lông "
                    "nhung/\nvải; bọ cánh tơ, nhện đỏ, rầy xanh/ chè; sâu khoang,\nsâu xanh, "
                    "sâu đục quả/ đậu tương, lạc; nhện gié, sâu\ncuốn lá/ lúa"),
         "registrant": "", "page": 11},
    ]
    entries = to_entries(rows)
    assert len(entries) == 2
    by_form = {e["formulation"]: e for e in entries}
    assert set(by_form) == {"WP", "3.6EC"}
    for e in entries:
        assert e["trade_name"] == "Kuraba"
        assert e["registrant"] == "Công ty TNHH Sản phẩm\nCông Nghệ Cao"
        assert not any(_LABEL_RE.search(pest) for pest, _crop in e["uses"])
    assert ("sâu đục thân", "ngô") in by_form["WP"]["uses"]
    assert ("nhện gié", "lúa") in by_form["3.6EC"]["uses"]
    assert ("sâu róm", "thông") in by_form["WP"]["uses"]  # phần trước "3.6EC:" ở hàng 2 vẫn thuộc WP


def test_to_entries_progibb_real_percent_code_no_label_garble():
    # Row thật (data/raw/tt75_2025_page_1.pdf trang 331): mã quy cách có "%"
    # ở GIỮA số và unit ("40%SG") — cả ở trade lẫn ở nhãn target.
    rows = [{"tt": "", "ai": "Gibberellic Acid", "trade": "ProGibb\n10 SP, 40%SG",
             "target": ("10SP: kích thích sinh trưởng/ chè, lúa\n"
                        "40%SG: kích thích sinh trưởng/ lúa, bắp cải"),
             "registrant": "Công ty TNHH Hóa chất\nSumitomo Việt Nam", "page": 331}]
    entries = to_entries(rows)
    assert len(entries) == 2
    by_form = {e["formulation"]: e for e in entries}
    assert set(by_form) == {"10SP", "40%SG"}
    for e in entries:
        assert e["trade_name"] == "ProGibb"
        assert not any(_LABEL_RE.search(pest) for pest, _crop in e["uses"])
    assert by_form["10SP"]["uses"] == [("kích thích sinh trưởng", "chè"),
                                        ("kích thích sinh trưởng", "lúa")]
    assert by_form["40%SG"]["uses"] == [("kích thích sinh trưởng", "lúa"),
                                         ("kích thích sinh trưởng", "bắp cải")]


def test_to_entries_gaucho_real_fuzzy_spaced_new_unit_no_label_garble():
    # Row thật (trang 352): unit MỚI "WS" + nhãn ĐẦU ô bị dàn đều ký tự
    # ("7 0 W S:") — kết hợp cả 2 cơ chế (unit mới + fuzzy spacing).
    rows = [{"tt": "", "ai": "Dinotefuran 25% +\nHymexazol (min 98%) 15%",
             "trade": "Gaucho\n70 WS, 600FS",
             "target": ("7 0 W S: xử lý hạt giống trừ rầy nâu, rầy xanh, bọ\ntrĩ, ruồi/ lúa\n"
                        "600FS: xử lý hạt giống trừ rệp/ bông vải"),
             "registrant": "Bayer Vietnam Ltd (BVL)", "page": 352}]
    entries = to_entries(rows)
    assert len(entries) == 2
    by_form = {e["formulation"]: e for e in entries}
    assert set(by_form) == {"70WS", "600FS"}
    for e in entries:
        assert e["trade_name"] == "Gaucho"
        assert not any(_LABEL_RE.search(pest) for pest, _crop in e["uses"])
    assert ("xử lý hạt giống trừ rệp", "bông vải") in by_form["600FS"]["uses"]


# --- Task 5e Bug class 2: Ô TRADE (không phải target) bị pdfplumber ngắt
# qua 2 hàng vật lý — hàng 1 chỉ có TÊN sản phẩm, mảnh DANH SÁCH MÃ QUY
# CÁCH rơi xuống hàng kế tiếp NHƯ 1 Ô TRADE non-rỗng riêng (khác continuation
# thường có trade RỖNG) -> trước fix bị hiểu nhầm thành "sản phẩm ma" tên
# đúng bằng chuỗi mã (vd "1GR", "700WP"). Ca thật: Oshin, Ramsing (task-5d
# report mục 1.4/6).

def test_codes_only_formulations_unit():
    # Mảnh trade CHỈ TOÀN mã quy cách (không còn tên nào) -> trả list mã.
    assert codes_only_formulations("1GR, 20WP, 20SG,\n100SL") == \
        ["1GR", "20WP", "20SG", "100SL"]
    assert codes_only_formulations("700WP, 700WG") == ["700WP", "700WG"]
    assert codes_only_formulations("40%SG") == ["40%SG"]
    assert codes_only_formulations("WP") == ["WP"]  # bare unit đơn lẻ cũng hợp lệ
    # Trade THẬT (có tên sản phẩm) -> None, KHÔNG được coi là mảnh vỡ.
    assert codes_only_formulations("Kuraba WP, 3.6EC") is None
    assert codes_only_formulations("Oshin") is None
    assert codes_only_formulations("") is None
    # Ô trống giữa 2 dấu phẩy (dữ liệu bất thường) -> an toàn, trả None chứ
    # không đoán.
    assert codes_only_formulations("20WP, , 30SC") is None
    # Chữ thường không khớp unit nào -> None (không nuốt nhầm).
    assert codes_only_formulations("hello, world") is None


def test_to_entries_oshin_real_trade_cell_page_break_no_ghost_product():
    # Rows THẬT nguyên văn (data/raw/tt75_2025_page_1.pdf, pdfplumber idx
    # 1152-1153, trang 76->77): trade "Oshin" (không mã) rồi hàng kế tiếp
    # trade "1GR, 20WP, 20SG,\n100SL" (CHỈ mã, KHÔNG tên) — registrant hàng
    # 2 rỗng (bằng chứng đây là mảnh của CÙNG 1 ô, không phải sản phẩm mới).
    # Trước fix: tạo ra sản phẩm ma tên "1GR" (+ garble nhãn còn sót trong
    # entry gốc "Oshin" formulation=None). Sau fix: đúng 4 quy cách của 1
    # sản phẩm "Oshin" duy nhất, không sản phẩm ma.
    rows = [
        {"tt": "", "ai": "Dimethoate 20% +\nPhenthoate 20%", "trade": "Oshin",
         "target": "1GR: rầy xanh/ đậu bắp, bọ phấn/cà chua",
         "registrant": "Mitsui Chemicals Crop & Life\nSolutions, Inc.", "page": 76},
        {"tt": "", "ai": "", "trade": "1GR, 20WP, 20SG,\n100SL",
         "target": ("20WP: rầy nâu/ lúa, rầy/ xoài, dòi đục lá/ dưa\nchuột, rầy chổng "
                    "cánh/ cam, bọ phấn/ cà chua, bọ\nnhảy/ bắp cải, bọ trĩ/ dưa hấu, "
                    "rệp sáp/ cà phê\n20SG: bọ phấn/cà chua, bọ nhảy/cải xanh, rầy\n"
                    "xanh/đậu bắp\n100SL: rầy xanh, bọ trĩ, bọ xít muỗi/ chè; bọ trĩ/\n"
                    "hoa cúc; bọ phấn/ hoa hồng; rầy nâu/lúa"),
         "registrant": "", "page": 77},
    ]
    entries = to_entries(rows)
    assert len(entries) == 4  # ĐÚNG 4 quy cách, KHÔNG sản phẩm ma
    assert all(e["trade_name"] == "Oshin" for e in entries)
    by_form = {e["formulation"]: e for e in entries}
    assert set(by_form) == {"1GR", "20WP", "20SG", "100SL"}
    for e in entries:
        # registrant kế thừa từ hàng mở nhóm cho MỌI quy cách (kể cả các
        # quy cách chỉ xuất hiện ở hàng mảnh vỡ, registrant rỗng).
        assert e["registrant"] == "Mitsui Chemicals Crop & Life\nSolutions, Inc."
        assert not any(_LABEL_RE.search(pest) for pest, _crop in e["uses"])
    # "1GR" block không có ";" phân cách 2 cặp pest/crop trong PDF gốc ->
    # rsplit("/",1) an toàn (giới hạn multi-slash đã biết, Task 4) ghép cặp
    # ĐẦU dính "/" thừa — không phải regression của fix này (không phải rác
    # NHÃN quy cách, _LABEL_RE không match phần này).
    assert by_form["1GR"]["uses"] == [("rầy xanh/ đậu bắp", "cà chua"), ("bọ phấn", "cà chua")]
    assert ("rệp sáp", "cà phê") in by_form["20WP"]["uses"]
    assert ("bọ trĩ", "hoa cúc") in by_form["100SL"]["uses"]
    assert ("rầy nâu", "lúa") in by_form["100SL"]["uses"]
    # KHÔNG sản phẩm ma nào tên là chính mã quy cách.
    assert not any(e["trade_name"] in {"1GR", "20WP", "20SG", "100SL"} for e in entries)


def test_to_entries_ramsing_real_trade_cell_page_break_no_ghost_700wp_700wg():
    # Rows THẬT (idx 1875-1876, trang 124->125): tương tự Oshin nhưng nhóm
    # ban đầu ĐÃ có 1 nhãn quy cách riêng (target "700WP: ...") dù trade
    # chưa có mã — hàng kế tiếp trade "700WP, 700WG" bổ sung mã còn thiếu.
    # Đây chính là ca sinh ra sản phẩm ma "700WP"/"700WG" trong task-5d report.
    rows = [
        {"tt": "", "ai": "Nitenpyram 30% (300g/kg)\n+ Pymetrozine 40%\n(400g/kg)",
         "trade": "Ramsing",
         "target": "700WP: rầy nâu/lúa, rệp sáp/cà phê",
         "registrant": "Công ty TNHH Phú Nông", "page": 124},
        {"tt": "", "ai": "", "trade": "700WP, 700WG",
         "target": "700WG: rầy nâu/lúa", "registrant": "", "page": 125},
    ]
    entries = to_entries(rows)
    assert len(entries) == 2
    assert all(e["trade_name"] == "Ramsing" for e in entries)
    by_form = {e["formulation"]: e for e in entries}
    assert set(by_form) == {"700WP", "700WG"}
    for e in entries:
        assert e["registrant"] == "Công ty TNHH Phú Nông"
        assert not any(_LABEL_RE.search(pest) for pest, _crop in e["uses"])
    # "700WP" block cũng thiếu ";" phân cách 2 cặp (giới hạn multi-slash đã
    # biết, Task 4 — không phải rác NHÃN quy cách, _LABEL_RE không match).
    assert by_form["700WP"]["uses"] == [("rầy nâu/lúa", "cà phê"), ("rệp sáp", "cà phê")]
    assert by_form["700WG"]["uses"] == [("rầy nâu", "lúa")]
    assert not any(e["trade_name"] in {"700WP", "700WG"} for e in entries)


def test_to_entries_fragment_registrant_tail_does_not_overwrite_group_registrant():
    # Biến thể (dữ liệu tổng hợp dựa trên mẫu ĐỘ NGẮT TRANG REGISTRANT thật
    # quan sát ở Kasugacin, idx 3406-3407 trang 219->220 — ở đó registrant
    # cũng bị ngắt trang ĐỘC LẬP với cột trade: hàng mảnh vỡ chỉ còn phần
    # ĐUÔI "Việt Nam", lẽ ra ghép với "Công ty CP Nông nghiệp" ở hàng trước
    # thành "Công ty CP Nông nghiệp Việt Nam"). Ở đây thêm 1 mã quy cách thứ
    # 2 (không có trong dữ liệu thật) để buộc code phải tạo ENTRY MỚI (không
    # chỉ thay placeholder formulation=None) — verify entry mới đó CŨNG kế
    # thừa registrant ĐÃ CÓ của nhóm, KHÔNG dùng nhầm phần đuôi "Việt Nam"
    # một mình (sẽ gây registrant sai/không nhất quán giữa 2 quy cách).
    rows = [
        {"tt": "", "ai": "Kanamycin sulfate\n(min 98%)", "trade": "Kasugacin",
         "target": "khô vằn, đạo ôn/ lúa, sương mai/ dưa chuột",
         "registrant": "Công ty CP Nông nghiệp", "page": 219},
        {"tt": "", "ai": "", "trade": "3SL, 5EC",
         "target": "", "registrant": "Việt Nam", "page": 220},
    ]
    entries = to_entries(rows)
    assert len(entries) == 2
    by_form = {e["formulation"]: e for e in entries}
    assert set(by_form) == {"3SL", "5EC"}
    for e in entries:
        assert e["trade_name"] == "Kasugacin"
        assert e["registrant"] == "Công ty CP Nông nghiệp"  # KHÔNG bị "Việt Nam" đè
        assert 220 in e["pages"]  # pages không phải trọng tâm fix này (không lưu vào registry)


def test_codes_only_fragment_requires_open_group_and_no_own_ai():
    # An toàn: hàng có `ai` RIÊNG (không rỗng) không bao giờ được coi là
    # mảnh vỡ tiếp diễn, DÙ trade của nó nhìn giống toàn mã quy cách — 1
    # hoạt chất mới thật sự luôn đi kèm 1 sản phẩm mới thật sự, không phải
    # mảnh ngắt trang (mảnh ngắt trang không bao giờ tự xưng lại hoạt chất).
    # (Dữ liệu giả định để kiểm tra an toàn ranh giới, không phải ca thật —
    # trade "20WP, 30SC" không có tên sản phẩm thật đứng trước chỉ để dựng
    # tình huống trade "trông giống" codes-only.)
    rows = [
        {"tt": "1", "ai": "Abamectin", "trade": "SanPhamA 1.8EC",
         "target": "sâu cuốn lá/lúa", "registrant": "Cty A", "page": 1},
        {"tt": "2", "ai": "Chat la", "trade": "20WP, 30SC",
         "target": "nhện đỏ/cam", "registrant": "Cty B", "page": 1},
    ]
    entries = to_entries(rows)
    # KHÔNG được gộp vào nhóm SanPhamA (không bị merge, không bị mất uses) —
    # phải mở nhóm MỚI hoàn toàn tách biệt.
    assert entries[0]["trade_name"] == "SanPhamA"
    assert entries[0]["ai"] == "Abamectin"
    assert entries[0]["uses"] == [("sâu cuốn lá", "lúa")]  # KHÔNG dính "nhện đỏ/cam"
    assert all(e["ai"] == "Chat la" for e in entries[1:])
    assert all(e["uses"] == [("nhện đỏ", "cam")] for e in entries[1:])
    assert sum(1 for e in entries if e["ai"] == "Abamectin") == 1


# --- Test tổng (toàn Phụ lục I thật) — cần data/raw/tt75_2025_page_1.pdf
# (chạy ingest.download trước, hoặc dùng bản đã tải sẵn cục bộ). Xác nhận
# fix giải quyết ĐÚNG 10 sản phẩm reviewer đã nêu tên (0 rác nhãn còn lại)
# và KHÔNG có sản phẩm MỚI nào phát sinh rác nhãn ngoài tập đã biết trước
# (14 sản phẩm còn lại là do NGUYÊN NHÂN KHÁC hẳn — _FORM_UNITS/_FORM_CODE
# không phủ hết mọi mã quy cách (đơn vị không số như "WP" đứng một mình,
# đơn vị lạ GB/WS/PA/OF, mã có "%"), hoặc chính Ô TRADE (không phải target)
# bị pdfplumber ngắt qua 2 hàng — 1 lớp bug KHÁC, ngoài phạm vi Critical fix
# này (chỉ sửa buffer TARGET theo nhóm đã xác định đúng ranh giới, không
# sửa cách phát hiện ranh giới trade/quy cách) — xem Task 5d report mục
# Concerns để biết chi tiết từng ca).
_ANNEX1 = Path("data/annex_files.json")


@pytest.mark.skipif(not _ANNEX1.exists(), reason="cần data/annex_files.json + data/raw (chạy ingest.download trước)")
def test_to_entries_full_annex1_no_new_label_garble_beyond_known_set():
    from ingest.parse_annex import parse_pdf
    notes = json.loads(_ANNEX1.read_text(encoding="utf-8"))
    allowed_path = Path(notes["allowed"])
    if not allowed_path.exists():
        pytest.skip("cần data/raw (chạy ingest.download trước)")
    entries = to_entries(parse_pdf(str(allowed_path)))

    # 10 sản phẩm reviewer nêu tên trong bug report — PHẢI sạch hoàn toàn.
    reviewer_named = ["Agromectin", "Mospilan", "Benevia", "Bemab", "Lufen extra",
                       "Kola", "Daconil", "Alonil", "Atulvil", "Bidamin"]
    for name in reviewer_named:
        matched = [e for e in entries if name in e["trade_name"]]
        assert matched, f"khong tim thay san pham {name!r} trong Phu luc I"
        for e in matched:
            assert not any(_LABEL_RE.search(pest) for pest, _crop in e["uses"]), (
                f"{name} ({e['formulation']}) van con rac nhan trong pest")

    # Tập KHÁC — sau Task 5e (mở rộng _FORM_UNITS với PA/OF/GB/WS/ST/FW/OS +
    # hỗ trợ "%" + mã chữ-không-số đứng riêng; merge mảnh trade ngắt trang)
    # đã giải quyết 12/14 sản phẩm cũ (Task 5d report mục 1.4): 700WP/700WG,
    # Adephone, Amet/Atra annong, Dithane, Gaucho, Helix, Kuraba, Nominee,
    # Oshin, ProGibb, Ramsing — KHÔNG còn rác nhãn. CHỈ CÒN 2, nguyên nhân
    # KHÁC HẲN 2 bug class Task 5e đã sửa (ngoài phạm vi, xem task-5e report):
    # - Exin: 1 quy cách DUY NHẤT (4.5SC) nên split_uses_by_formulation
    #   không kích hoạt (cần >=2 quy cách); target lặp lại nhãn "4.5SC:" 2
    #   lần kèm tên gọi khác lồng trong ngoặc "(Phytoxin VS):" — không có
    #   dấu ";" phân cách nên rơi vào rsplit("/") cuối cùng như mọi multi-
    #   slash-no-";" khác (giới hạn Task 4 đã chấp nhận).
    # - Jiabat: mã quy cách thứ 2 là chú thích ĐỘ HOẠT LỰC "(50000 IU/mg)
    #   WP" (không phải mã đóng gói WP/EC/SC thường gặp) — bare "WP" đã
    #   tách được (cải thiện so với trước, formulation=None -> "WP") nhưng
    #   phần "(50000 IU/mg)" đứng giữa (không phải cuối chuỗi) nên vẫn dính
    #   trade_name; đây là dạng "mã hiệu lực sinh học" khác hẳn mã quy cách
    #   đóng gói — ngoài phạm vi Task 5e (không mở rộng thêm theo brief).
    known_other_cause = {
        ("Exin", "4.5SC"),
        ("Jiabat 15WG, (50000 IU/mg)", "WP"),
    }
    still_garbled = set()
    for e in entries:
        if any(_LABEL_RE.search(pest) for pest, _crop in e["uses"]):
            still_garbled.add((e["trade_name"], e["formulation"]))
    assert still_garbled == known_other_cause, (
        f"tap san pham con rac nhan da doi: moi={still_garbled - known_other_cause}, "
        f"da het={known_other_cause - still_garbled}")


@pytest.mark.skipif(not _ANNEX1.exists(), reason="cần data/annex_files.json + data/raw (chạy ingest.download trước)")
def test_to_entries_full_annex1_no_codes_only_ghost_products():
    # Tripwire Task 5e (Bug class 2): registry sau fix KHÔNG được còn
    # product nào có trade_name dạng "codes-only" (dấu hiệu 1 mảnh ô trade
    # ngắt trang lọt qua mà chưa được gộp — sản phẩm ma kiểu "1GR"/"700WP"
    # đã xảy ra trước fix, xem task-5d report mục 1.4).
    from ingest.parse_annex import parse_pdf
    notes = json.loads(_ANNEX1.read_text(encoding="utf-8"))
    allowed_path = Path(notes["allowed"])
    if not allowed_path.exists():
        pytest.skip("cần data/raw (chạy ingest.download trước)")
    entries = to_entries(parse_pdf(str(allowed_path)))
    ghosts = [e["trade_name"] for e in entries
              if codes_only_formulations(e["trade_name"]) is not None]
    assert ghosts == [], f"con san pham ma ten dang codes-only: {ghosts}"

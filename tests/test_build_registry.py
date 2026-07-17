import json
import sqlite3

import pytest

from ingest.build_registry import build_registry, DOCS

ALLOWED = [
    {"ai": "Abamectin", "trade_name": "Reasgant", "formulation": "1.8EC",
     "registrant": "Cty A", "uses": [("sâu cuốn lá", "lúa")], "pages": [3]},
    {"ai": "Chlorpyrifos Ethyl", "trade_name": "OldKill", "formulation": "40EC",
     "registrant": "Cty B", "uses": [("rệp sáp", "cà phê")], "pages": [9]},
]
BANNED = [
    {"ai": "Carbofuran", "trade_name": "", "formulation": None,
     "registrant": "", "uses": [], "pages": [1]},
]

def test_build_and_effective_dates(tmp_path):
    amend = tmp_path / "amend.csv"
    amend.write_text(
        "action,ai,trade_name,formulation,crop,pest,note\n"
        "remove_product,Chlorpyrifos Ethyl,OldKill,40EC,,,rút tự nguyện tr.2\n"
        "add_product,Bacillus thuringiensis,BioNew,10WP,,,tr.3\n"
        "add_use,Bacillus thuringiensis,BioNew,10WP,lúa,sâu cuốn lá,tr.3\n",
        encoding="utf-8")
    conn = build_registry(ALLOWED, BANNED, amend, tmp_path / "r.db")
    q = lambda d: {r[0] for r in conn.execute(
        "SELECT trade_name FROM products WHERE status='allowed' "
        "AND effective_from<=? AND (effective_to IS NULL OR effective_to>?)", (d, d))}
    assert q("2026-07-17") == {"Reasgant", "OldKill"}          # trước 15/08: OldKill còn
    assert q("2026-08-20") == {"Reasgant", "BioNew"}           # sau 15/08: OldKill removed, BioNew vào
    # dòng allowed cũ bị đóng hiệu lực; bản ghi removed mới vẫn tra được (nguồn bẫy eval)
    assert conn.execute("SELECT status FROM products WHERE trade_name='OldKill' "
                        "AND effective_to IS NOT NULL").fetchone()[0] == "allowed"
    assert conn.execute("SELECT COUNT(*) FROM products WHERE status='removed'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM products WHERE status='banned'").fetchone()[0] == 1


def test_remove_product_raises_when_no_allowed_row_matches(tmp_path):
    """Review Task 5c guard: trước đây nếu trade_name/formulation trong CSV
    không khớp dòng allowed nào, UPDATE âm thầm khớp 0 dòng (không đóng hiệu
    lực gì) trong khi vẫn chèn 1 dòng 'removed' mồ côi. Nay phải fail loudly."""
    amend = tmp_path / "amend.csv"
    amend.write_text(
        "action,ai,trade_name,formulation,crop,pest,note\n"
        "remove_product,Chlorpyrifos Ethyl,KhongTonTai,99XX,,,khong khop du lieu\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="remove_product.*KhongTonTai"):
        build_registry(ALLOWED, BANNED, amend, tmp_path / "r.db")


def test_add_use_raises_when_trade_name_not_found(tmp_path):
    """Review Task 5c guard: trước đây .fetchone()[0] ném TypeError khó hiểu
    khi add_use tham chiếu 1 trade_name chưa từng add_product/allowed. Nay
    phải raise ValueError nêu rõ trade_name."""
    amend = tmp_path / "amend.csv"
    amend.write_text(
        "action,ai,trade_name,formulation,crop,pest,note\n"
        "add_use,Bacillus thuringiensis,SanPhamChuaThem,10WP,lúa,sâu cuốn lá,tr.3\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="add_use.*SanPhamChuaThem"):
        build_registry(ALLOWED, BANNED, amend, tmp_path / "r.db")


def test_add_use_raises_when_formulation_not_found_for_existing_trade_name(tmp_path):
    """add_use guard cũng phải khớp đúng formulation, không chỉ trade_name --
    trade_name 'Reasgant' tồn tại (formulation '1.8EC') nhưng '99XX' thì không."""
    amend = tmp_path / "amend.csv"
    amend.write_text(
        "action,ai,trade_name,formulation,crop,pest,note\n"
        "add_use,Abamectin,Reasgant,99XX,lúa,sâu cuốn lá,tr.3\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="add_use.*Reasgant"):
        build_registry(ALLOWED, BANNED, amend, tmp_path / "r.db")


def test_add_use_assigns_to_correct_formulation_when_trade_name_has_multiple_formulations(tmp_path):
    """Bug phát hiện khi verify Task 5c: sau khi ingest.normalize tách 1 trade
    nhiều quy cách (vd 'Thiagold' 111WP/500SC/680WG) thành nhiều dòng product
    riêng, add_use trước đây chỉ lọc theo trade_name -> 'ORDER BY effective_from
    DESC LIMIT 1' dồn TOÀN BỘ uses vào đúng 1 dòng quy cách, các quy cách khác
    0 use. Test này thêm 1 sản phẩm allowed 2 quy cách rồi add_use riêng cho
    từng quy cách, phải về đúng dòng của nó."""
    allowed_multi = ALLOWED + [
        {"ai": "Thiamethoxam (min 95%)", "trade_name": "Thiagold", "formulation": "111WP",
         "registrant": "Cty X", "uses": [], "pages": [8]},
        {"ai": "Thiamethoxam (min 95%)", "trade_name": "Thiagold", "formulation": "500SC",
         "registrant": "Cty X", "uses": [], "pages": [8]},
    ]
    amend = tmp_path / "amend.csv"
    amend.write_text(
        "action,ai,trade_name,formulation,crop,pest,note\n"
        "add_use,Thiamethoxam (min 95%),Thiagold,111WP,ngô,rệp muội,tr.8\n"
        "add_use,Thiamethoxam (min 95%),Thiagold,500SC,sắn,bọ phấn trắng,tr.8\n",
        encoding="utf-8")
    conn = build_registry(allowed_multi, BANNED, amend, tmp_path / "r.db")
    get_uses = lambda form: conn.execute(
        "SELECT crop, pest FROM uses u JOIN products p ON p.id=u.product_id "
        "WHERE p.trade_name='Thiagold' AND p.formulation=?", (form,)).fetchall()
    assert get_uses("111WP") == [("ngô", "rệp muội")]
    assert get_uses("500SC") == [("sắn", "bọ phấn trắng")]


# --- Task 5d (re-review Important): change_registrant/change_ai trước đây
# KHÔNG lọc formulation -- nếu 1 trade_name có nhiều quy cách allowed (ca
# thật: Wasaki 250SC+500WG, Folpan 50WP+50SC trong TT28), 1 dòng CSV chỉ
# định đổi cho ĐÚNG 1 quy cách lại đổi LUÔN quy cách khác không liên quan.

ALLOWED_MULTI_FORM = ALLOWED + [
    {"ai": "Boscalid (min 96%)", "trade_name": "Wasaki", "formulation": "250SC",
     "registrant": "Cty Cu", "uses": [], "pages": [4]},
    {"ai": "Boscalid (min 96%)", "trade_name": "Wasaki", "formulation": "500WG",
     "registrant": "Cty Cu", "uses": [], "pages": [4]},
]


def test_change_registrant_filters_by_formulation_when_multiple_formulations_exist(tmp_path):
    amend = tmp_path / "amend.csv"
    amend.write_text(
        "action,ai,trade_name,formulation,crop,pest,note,new_registrant\n"
        "change_registrant,Boscalid (min 96%),Wasaki,250SC,,,tr.1,Cty Moi\n",
        encoding="utf-8")
    conn = build_registry(ALLOWED_MULTI_FORM, BANNED, amend, tmp_path / "r.db")
    get_reg = lambda form: conn.execute(
        "SELECT registrant FROM products WHERE trade_name='Wasaki' AND formulation=?",
        (form,)).fetchone()[0]
    assert get_reg("250SC") == "Cty Moi"     # quy cách được chỉ định -> đổi
    assert get_reg("500WG") == "Cty Cu"      # quy cách khác -> KHÔNG đổi


def test_change_registrant_applies_to_all_formulations_when_formulation_empty(tmp_path):
    # formulation rỗng trong CSV -> giữ hành vi cũ: áp dụng cho MỌI quy cách
    # của trade_name (ý định nghiệp vụ khi dòng CSV không chỉ định quy cách).
    amend = tmp_path / "amend.csv"
    amend.write_text(
        "action,ai,trade_name,formulation,crop,pest,note,new_registrant\n"
        "change_registrant,Boscalid (min 96%),Wasaki,,,,tr.1,Cty Moi\n",
        encoding="utf-8")
    conn = build_registry(ALLOWED_MULTI_FORM, BANNED, amend, tmp_path / "r.db")
    get_reg = lambda form: conn.execute(
        "SELECT registrant FROM products WHERE trade_name='Wasaki' AND formulation=?",
        (form,)).fetchone()[0]
    assert get_reg("250SC") == "Cty Moi"
    assert get_reg("500WG") == "Cty Moi"


def test_change_registrant_raises_when_formulation_not_found(tmp_path):
    amend = tmp_path / "amend.csv"
    amend.write_text(
        "action,ai,trade_name,formulation,crop,pest,note,new_registrant\n"
        "change_registrant,Boscalid (min 96%),Wasaki,99XX,,,tr.1,Cty Moi\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="change_registrant.*Wasaki"):
        build_registry(ALLOWED_MULTI_FORM, BANNED, amend, tmp_path / "r.db")


def test_change_ai_filters_by_formulation_when_multiple_formulations_exist(tmp_path):
    amend = tmp_path / "amend.csv"
    amend.write_text(
        "action,ai,trade_name,formulation,crop,pest,note\n"
        "change_ai,Boscalid moi,Wasaki,250SC,,,tr.1\n",
        encoding="utf-8")
    conn = build_registry(ALLOWED_MULTI_FORM, BANNED, amend, tmp_path / "r.db")
    get_ai = lambda form: conn.execute(
        "SELECT ai.name_common FROM products p JOIN active_ingredients ai ON ai.id=p.ai_id "
        "WHERE p.trade_name='Wasaki' AND p.formulation=?", (form,)).fetchone()[0]
    assert get_ai("250SC") == "Boscalid moi"        # quy cách được chỉ định -> đổi
    assert get_ai("500WG") == "Boscalid (min 96%)"  # quy cách khác -> KHÔNG đổi


def test_change_ai_raises_when_formulation_not_found(tmp_path):
    amend = tmp_path / "amend.csv"
    amend.write_text(
        "action,ai,trade_name,formulation,crop,pest,note\n"
        "change_ai,Boscalid moi,Wasaki,99XX,,,tr.1\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="change_ai.*Wasaki"):
        build_registry(ALLOWED_MULTI_FORM, BANNED, amend, tmp_path / "r.db")


# --- Task 5g (Finding 2, review Task 5f): `main()` DROP+rebuild toàn bộ
# `data/registry.db` nhưng KHÔNG có DDL cho bảng `aliases` (bảng này trước
# đây được nạp RIÊNG bằng tay qua `ingest.build_aliases.load_aliases`) ->
# mỗi lần rebuild registry đều xoá mất bảng `aliases` cho tới khi ai đó chạy
# lại bước nạp thủ công -> `app/backend/pipeline.py` vỡ ("no such table:
# aliases"). Test main()-flow ĐẦY ĐỦ (mock `parse_pdf` để tránh cần PDF thật,
# chạy trên thư mục tạm) xác nhận `main()` tự nạp lại `aliases` ngay sau khi
# rebuild, không phụ thuộc bước tay nào khác.

def test_main_reloads_aliases_table_after_rebuild(tmp_path, monkeypatch):
    import ingest.build_registry as br
    import ingest.parse_annex as parse_annex_mod

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "annex_files.json").write_text(
        json.dumps({"allowed": "fake_allowed.pdf", "banned": "fake_banned.pdf"}), encoding="utf-8")
    (data_dir / "amendments_tt28_2026.csv").write_text(
        "action,ai,trade_name,formulation,crop,pest,note,new_registrant,registrant\n", encoding="utf-8")
    (data_dir / "aliases_seed.csv").write_text(
        "entity_type,canonical,alias,ambiguous,note\n"
        "pest,rầy nâu,rầy cám,0,note demo\n"
        "crop,lúa,lúa nước,0,\n",
        encoding="utf-8")

    fake_rows = {
        "fake_allowed.pdf": [{"tt": "1", "ai": "Abamectin", "trade": "Reasgant 1.8EC",
                               "target": "sâu cuốn lá/lúa", "registrant": "Cty A", "page": 0}],
        "fake_banned.pdf": [],
    }
    monkeypatch.setattr(parse_annex_mod, "parse_pdf", lambda path, max_pages=None: fake_rows[path])
    monkeypatch.chdir(tmp_path)

    br.main()

    conn = sqlite3.connect(tmp_path / "data" / "registry.db")
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
    rows = conn.execute("SELECT entity_type, canonical, alias FROM aliases ORDER BY id").fetchall()
    assert rows == [("pest", "rầy nâu", "rầy cám"), ("crop", "lúa", "lúa nước")]

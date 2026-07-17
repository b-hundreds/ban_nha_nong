"""TDD: parser cho FAQ khuyến nông Lâm Đồng (ASPX, dùng fixture HTML thật)."""
from pathlib import Path

from ingest.crawl_faq_lamdong import (
    categorize,
    parse_detail_page,
    parse_hidden_fields,
    parse_list_page,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_hidden_fields_extracts_viewstate():
    html = (FIXTURES / "faq_lamdong_list_p1.html").read_text(encoding="utf-8")
    fields = parse_hidden_fields(html)
    assert fields["__VIEWSTATE"]
    assert fields["__VIEWSTATEGENERATOR"]


def test_parse_list_page_returns_10_items_with_metadata():
    html = (FIXTURES / "faq_lamdong_list_p1.html").read_text(encoding="utf-8")
    items = parse_list_page(html)
    assert len(items) == 10
    first = items[0]
    assert first["id"] == "11628"
    assert "FaqView.aspx?ID=11628" in first["url"]
    assert first["question"] == "Khi nào mới mở lớp bán thuốc bảo vệ thực vật ạ"
    assert first["date"] == "2025-08-28"
    assert first["answered"] is True


def test_parse_detail_page_returns_full_question_answer():
    html = (FIXTURES / "faq_lamdong_detail_11628.html").read_text(encoding="utf-8")
    rec = parse_detail_page(html, "https://khuyennong.lamdong.gov.vn/News/FaqView.aspx?ID=11628")
    assert rec["question"] == "Khi nào mới mở lớp bán thuốc bảo vệ thực vật ạ"
    assert "Chi cục Trồng trọt và Bảo vệ thực vật" in rec["answer"]
    assert rec["date"] == "2025-08-28"
    assert rec["url"] == "https://khuyennong.lamdong.gov.vn/News/FaqView.aspx?ID=11628"
    assert rec["category"] == "bvtv"


def test_categorize_uses_keywords():
    assert categorize("Sầu riêng bị xì mủ phải xử lý sao?") == "sầu riêng"
    assert categorize("Cà phê tái canh cần bón phân gì?") == "cà phê"
    assert categorize("Con gà bị dịch bệnh thì làm sao?") == "chăn nuôi"
    assert categorize("Hỏi chung chung không rõ chủ đề gì cả") == "khác"

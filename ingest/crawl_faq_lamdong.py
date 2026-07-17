"""Crawl FAQ khuyến nông Lâm Đồng (ASPX, phân trang qua __doPostBack).

Nguồn: http://khuyennong.lamdong.gov.vn/News/FaqList.aspx (redirect sang HTTPS,
cert hợp lệ — không cần verify=False). Danh sách phân trang bằng postback
`__doPostBack('ctl21$pager', '<số trang>')`; mỗi câu hỏi có trang chi tiết
riêng `FaqView.aspx?ID=<id>` chứa câu trả lời đầy đủ (trang danh sách chỉ có
đoạn preview bị cắt ngắn).

Output: data/faq/faq_lamdong.jsonl, mỗi dòng 1 bản ghi
{question, answer, url, date, category} (NFC normalize). File này COMMIT —
dùng làm chunks KB (authority_level=khuyen_nong) và kho câu hỏi thật cho eval P3.

Site không có taxonomy category thật; `category` được suy ra bằng khớp từ khoá
đơn giản trên câu hỏi/trả lời (không bịa nội dung, chỉ gắn nhãn hỗ trợ lọc).
"""
import json
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

BASE = "https://khuyennong.lamdong.gov.vn"
LIST_URL = f"{BASE}/News/FaqList.aspx"
HEADERS = {"User-Agent": "Mozilla/5.0 (research; VNAI hackathon)"}
OUT_PATH = Path("data/faq/faq_lamdong.jsonl")

MAX_QA = 200
DELAY_S = 1.2
MAX_PAGES = 40  # an toàn: 40 trang * 10/trang = 400 ứng viên, đủ dư cho 200 đã trả lời

# Suy ra category từ từ khoá (site nguồn không có taxonomy category thật).
CATEGORY_KEYWORDS = [
    ("sầu riêng", ["sầu riêng"]),
    ("cà phê", ["cà phê", "tái canh"]),
    ("hồ tiêu", ["hồ tiêu", "cây tiêu"]),
    ("chè", ["cây chè", " chè "]),
    ("lúa", ["lúa", "xuống giống", "đạo ôn", "rầy nâu", "sạ cụm"]),
    ("hoa", ["hoa lan", "hoa cúc", "hoa hồng", "hoa hồ điệp", "trồng hoa"]),
    ("rau củ quả", ["rau", "atiso", "cà chua", "khoai tây", "cây ăn quả", "bơ ", "thanh long"]),
    ("chăn nuôi", ["con heo", "con lợn", " bò ", "con gà", "con vịt", "con dê", "chăn nuôi", "bò sữa"]),
    ("thủy sản", ["cá tầm", "thủy sản", "nuôi cá", "cá chình"]),
    ("bvtv", ["bảo vệ thực vật", "sâu bệnh", "phân bón", "thuốc trừ sâu", "chứng chỉ"]),
]


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s.strip())


def categorize(question: str, answer: str = "") -> str:
    text = f" {question} {answer} ".lower()
    for cat, keywords in CATEGORY_KEYWORDS:
        if any(kw in text for kw in keywords):
            return cat
    return "khác"


def _to_iso_date(s: str | None) -> str | None:
    if not s:
        return None
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s.strip())
    if not m:
        return None
    d, mo, y = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def parse_hidden_fields(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    fields = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        el = soup.find("input", {"name": name})
        if el is not None:
            fields[name] = el.get("value", "")
    return fields


def parse_list_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for card in soup.find_all("div", class_="q-card"):
        a = card.find("a", href=re.compile(r"FaqView\.aspx\?ID=\d+"))
        if a is None:
            continue
        m = re.search(r"ID=(\d+)", a["href"])
        faq_id = m.group(1)
        date_txt = None
        for d in card.find_all(class_="q-date"):
            if d.find("i", class_=re.compile("bi-calendar3")):
                date_txt = d.get_text(strip=True)
                break
        answered = card.find(class_="badge-answered") is not None
        items.append({
            "id": faq_id,
            "url": f"{BASE}/News/FaqView.aspx?ID={faq_id}",
            "question": _nfc(a.get_text(strip=True)),
            "date": _to_iso_date(date_txt),
            "answered": answered,
        })
    return items


def parse_detail_page(html: str, url: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.find("h1", class_="q-title")
    ans_el = soup.find(id=re.compile(r"colContentsRep$"))
    if title_el is None or ans_el is None:
        return None
    answer = _nfc(ans_el.get_text("\n", strip=True))
    if not answer:
        return None
    question = _nfc(title_el.get_text(strip=True))
    date_el = soup.find(id=re.compile(r"txtNgayHoi$"))
    date_txt = date_el.get_text(strip=True) if date_el else None
    return {
        "question": question,
        "answer": answer,
        "url": url,
        "date": _to_iso_date(date_txt),
        "category": categorize(question, answer),
    }


def _fetch_page(client: httpx.Client, page: int, hidden: dict) -> httpx.Response:
    if page == 1:
        return client.get(LIST_URL)
    data = {"__EVENTTARGET": "ctl21$pager", "__EVENTARGUMENT": str(page)}
    data.update(hidden)
    return client.post(LIST_URL, data=data)


def crawl(max_qa: int = MAX_QA, delay: float = DELAY_S, out_path: Path = OUT_PATH,
          max_pages: int = MAX_PAGES) -> list[dict]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    seen_ids: set[str] = set()
    hidden: dict = {}
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for page in range(1, max_pages + 1):
            if len(records) >= max_qa:
                break
            r = _fetch_page(client, page, hidden)
            r.raise_for_status()
            hidden = parse_hidden_fields(r.text)
            items = parse_list_page(r.text)
            if not items:
                break
            for it in items:
                if len(records) >= max_qa:
                    break
                if not it["answered"] or it["id"] in seen_ids:
                    continue
                seen_ids.add(it["id"])
                time.sleep(delay)
                dr = client.get(it["url"])
                dr.raise_for_status()
                rec = parse_detail_page(dr.text, it["url"])
                if rec:
                    records.append(rec)
            time.sleep(delay)
    with out_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return records


def main() -> None:
    records = crawl()
    dist = Counter(r["category"] for r in records)
    print(f"OK: {len(records)} Q&A -> {OUT_PATH}")
    print("Phân bố category:", dict(dist))


if __name__ == "__main__":
    main()

# P0 — Xương sống dữ liệu (Plan 1/4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng tầng dữ liệu pháp lý cho trợ lý nông nghiệp: `registry.db` (danh mục thuốc BVTV theo TT 75/2025 + TT 28/2026, có hiệu lực theo ngày), `labels.db` (liều lượng curate tay có double-entry), bảng alias phương ngữ, và kho KB văn bản đã chunk + FTS5.

**Architecture:** Pipeline ingest một chiều: tải PDF nguồn (có manifest sha256) → parse bảng phụ lục bằng pdfplumber → normalize (gộp dòng tiếp diễn, tách formulation, tách cặp dịch hại/cây) → nạp SQLite có versioning `effective_from/to` → QA lấy mẫu đối chiếu PDF. Liều lượng KHÔNG lấy từ danh mục (danh mục không có liều) mà curate từ CSDL quốc gia/nhãn vào CSV rồi build thành `labels.db`. KB văn bản (quy trình canh tác, lịch thời vụ, bản tin) chunk theo mục + metadata vùng/cây, index FTS5 (tách từ pyvi). Mọi hàm truy vấn nằm trong `app/backend/db.py` — đây là interface P1 sẽ dùng.

**Tech Stack:** Python 3.11+, SQLite (stdlib `sqlite3`, FTS5), pdfplumber, httpx, BeautifulSoup4, rapidfuzz, pyvi, pytest.

## Global Constraints

- Python ≥ 3.11, venv tại `.venv`, dependencies trong `requirements.txt`.
- TDD: `pytest -q` phải xanh trước MỌI commit.
- Text ingest phải normalize Unicode **NFC** (`unicodedata.normalize("NFC", s)`).
- Số kiểu Việt: dấu phẩy thập phân (`"0,5"` → `0.5`); luôn giữ **nguyên văn** trong cột `*_text`, số parse máy vào cột `dose_min/dose_max/phi_days`.
- Mọi bảng dữ liệu pháp lý phải có `doc_id` + `effective_from`/`effective_to` (ISO date, `effective_to IS NULL` = còn hiệu lực); mọi truy vấn nhận tham số `on_date`.
- Provenance bắt buộc với dữ liệu curate tay: `source_url` + `retrieved_at` không được rỗng.
- KHÔNG commit `data/raw/` và `*.db` (đã gitignore); commit CSV curate (`data/labels/*.csv`, `data/aliases_seed.csv`, `data/amendments_tt28_2026.csv`).
- Commit message: conventional commit 1 dòng + trailer, dạng `git commit -m "feat: ..." -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`.
- Code identifiers tiếng Anh; string dữ liệu tiếng Việt giữ nguyên có dấu.
- Nguồn URL chuẩn: ưu tiên vanban.chinhphu.vn / ppd.gov.vn; thuvienphapluat & luatvietnam chặn bot — không dùng làm nguồn tải tự động.

---

### Task 1: Scaffold project + pytest

**Files:**
- Create: `requirements.txt`, `ingest/__init__.py`, `app/__init__.py`, `app/backend/__init__.py`, `tests/test_smoke.py`

**Interfaces:**
- Produces: cây thư mục `ingest/`, `app/backend/`, `tests/`, `data/` mà mọi task sau dùng.

- [ ] **Step 1: Tạo venv + requirements**

```bash
cd /home/vietlb/research/Kaggle/VNAI
python3 -m venv .venv && source .venv/bin/activate
```

Tạo `requirements.txt`:

```
pdfplumber==0.11.*
httpx==0.27.*
beautifulsoup4==4.12.*
rapidfuzz==3.*
pyvi==0.1.*
pytest==8.*
```

```bash
pip install -r requirements.txt
```

Expected: cài đặt thành công (pdfplumber kéo theo pypdfium2 — bình thường).

- [ ] **Step 2: Tạo skeleton + smoke test**

`ingest/__init__.py`, `app/__init__.py`, `app/backend/__init__.py`: file rỗng.

`tests/test_smoke.py`:

```python
def test_imports():
    import ingest
    import app.backend
```

- [ ] **Step 3: Chạy test**

Run: `.venv/bin/pytest -q`
Expected: `1 passed`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt ingest app tests
git commit -m "chore: scaffold python project + pytest" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Downloader nguồn chính thống + manifest

**Files:**
- Create: `ingest/download.py`, `data/sources.yaml` (dùng JSON-in-YAML tối giản — thực tế là file `.yaml` chứa JSON để khỏi thêm dependency), `tests/test_download.py`

**Interfaces:**
- Produces: `python -m ingest.download` tải mọi nguồn vào `data/raw/<name>`, ghi `data/raw/manifest.json` `{name: {url, sha256, bytes, fetched_at}}`. Task 3/5/10 đọc file từ `data/raw/`.

- [ ] **Step 1: Viết failing test**

`tests/test_download.py`:

```python
import json
from pathlib import Path
from ingest.download import fetch_one, extract_pdf_links

def test_fetch_one_writes_file_and_manifest(tmp_path, monkeypatch):
    import ingest.download as dl

    def fake_get(url, **kw):
        class R:
            status_code = 200
            content = b"%PDF-fake"
            def raise_for_status(self): pass
        return R()

    monkeypatch.setattr(dl.httpx, "get", fake_get)
    manifest = {}
    fetch_one("a.pdf", "https://example.com/a.pdf", tmp_path, manifest)
    assert (tmp_path / "a.pdf").read_bytes() == b"%PDF-fake"
    assert manifest["a.pdf"]["sha256"]

def test_extract_pdf_links():
    html = '<a href="/FileUpload/Documents/x/phu-luc-1.pdf">PL1</a><a href="/y.docx">d</a>'
    links = extract_pdf_links(html, base="https://ppd.gov.vn", pattern="FileUpload")
    assert links == ["https://ppd.gov.vn/FileUpload/Documents/x/phu-luc-1.pdf"]
```

- [ ] **Step 2: Chạy test fail**

Run: `.venv/bin/pytest tests/test_download.py -q`
Expected: FAIL `ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: Implement `ingest/download.py`**

```python
"""Tải nguồn chính thống vào data/raw/ kèm manifest sha256."""
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

RAW_DIR = Path("data/raw")
HEADERS = {"User-Agent": "Mozilla/5.0 (research; VNAI hackathon)"}

# kind=direct: tải thẳng. kind=page: mở trang, quét link PDF theo pattern.
SOURCES = [
    # Danh mục thuốc BVTV — TT 75/2025/TT-BNNMT (hiệu lực 10/02/2026)
    {"name": "tt75_2025_page", "kind": "page", "pattern": "FileUpload",
     "url": "https://ppd.gov.vn/tin-moi-nhat-289/thong-tu-so-752025tt-bnnmt-ban-hanh-danh-muc-thuoc-bao-ve-thuc-vat-duoc-phep-su-dung-tai-viet-nam-va-danh-muc-thuoc-bao-ve-thuc-vat-cam-su-dung-tai-viet-nam.html"},
    # TT 28/2026/TT-BNNMT — phụ lục sửa đổi (hiệu lực 15/08/2026)
    {"name": "tt28_2026_phuluc.pdf", "kind": "direct",
     "url": "https://datafiles.chinhphu.vn/cpp/files/duthaovbpl/2026/Thang4/2.1.-phu-luc-kem-theo-thong-tu.pdf"},
    # Quy trình sầu riêng — QĐ 1899/2025 Cục TT&BVTV
    {"name": "qd1899_2025_saurieng.pdf", "kind": "direct",
     "url": "http://khuyennongtphcm.vn/wp-content/uploads/2025/07/30.6.2025-Quy-tr%C3%ACnh-s%E1%BA%A7u-ri%C3%AAng-Final-IN.pdf"},
    # Quy trình tái canh cà phê vối — WASI 2020
    {"name": "wasi2020_taicanh_caphe.pdf", "kind": "direct",
     "url": "http://wasi.org.vn/wp-content/uploads/2021/11/QUYET-DINH-BAN-HANH-QUY-TRINH-TAI-CANH-CA-PHE-VOI-2020.pdf"},
    # Sổ tay lúa CLC phát thải thấp ĐBSCL (QĐ 145/QĐ-TT-CLT) — trang chứa link tải
    {"name": "qd145_sotay_page", "kind": "page", "pattern": ".pdf",
     "url": "https://khuyennongvn.gov.vn/thu-vien-khuyen-nong/thu-vien-sach-kn/so-tay-huong-dan-quy-trinh-ky-thuat-san-xuat-lua-chat-luong-cao-va-phat-thai-thap-vung-dong-bang-song-cuu-long-24341.html"},
]


def extract_pdf_links(html: str, base: str, pattern: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".pdf") and pattern.lower() in href.lower():
            out.append(urljoin(base, href))
        elif pattern != ".pdf" and pattern.lower() in href.lower() and ".pdf" in href.lower():
            out.append(urljoin(base, href))
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def fetch_one(name: str, url: str, raw_dir: Path, manifest: dict) -> None:
    r = httpx.get(url, headers=HEADERS, timeout=60, follow_redirects=True, verify=True)
    r.raise_for_status()
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / name
    path.write_bytes(r.content)
    manifest[name] = {
        "url": url,
        "sha256": hashlib.sha256(r.content).hexdigest(),
        "bytes": len(r.content),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def main() -> None:
    manifest_path = RAW_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    failures = []
    for src in SOURCES:
        try:
            if src["kind"] == "direct":
                fetch_one(src["name"], src["url"], RAW_DIR, manifest)
            else:
                r = httpx.get(src["url"], headers=HEADERS, timeout=60, follow_redirects=True)
                r.raise_for_status()
                links = extract_pdf_links(r.text, src["url"], src["pattern"])
                if not links:
                    failures.append((src["name"], "no pdf links found"))
                for i, link in enumerate(links):
                    fetch_one(f'{src["name"]}_{i}.pdf', link, RAW_DIR, manifest)
        except Exception as e:  # ghi nhận và đi tiếp — nguồn gov hay chập chờn
            failures.append((src["name"], repr(e)))
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"OK: {len(manifest)} file(s). Failures: {failures or 'none'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Test pass**

Run: `.venv/bin/pytest tests/test_download.py -q`
Expected: `2 passed`

- [ ] **Step 5: Chạy tải thật**

Run: `.venv/bin/python -m ingest.download && ls -la data/raw/`
Expected: ≥ 4 file PDF (trong đó `tt75_2025_page_0..2.pdf` là thông tư + 2 phụ lục) + `manifest.json`. Nguồn nào fail → in trong `Failures`; xử lý: mở trang bằng trình duyệt/WebFetch, lấy URL PDF trực tiếp, thêm entry `kind=direct` vào `SOURCES` rồi chạy lại. KHÔNG bỏ qua Phụ lục I/II — thiếu chúng thì dừng plan.

Kiểm tra nhanh file nào là phụ lục nào: `for f in data/raw/tt75_2025_page_*.pdf; do echo "== $f"; .venv/bin/python -c "import pdfplumber,sys; p=pdfplumber.open('$f'); print(p.pages[0].extract_text()[:300])"; done` — ghi lại mapping (thông tư / Phụ lục I được phép / Phụ lục II cấm) vào `data/raw/NOTES.md`.

- [ ] **Step 6: Commit**

```bash
git add ingest/download.py tests/test_download.py data/raw/NOTES.md
git commit -m "feat: downloader nguồn chính thống + manifest sha256" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Parse bảng Phụ lục PDF → RawRow

**Files:**
- Create: `ingest/parse_annex.py`, `scripts/inspect_pdf.py`, `tests/test_parse_annex.py`, `tests/fixtures/annex_sample.json`

**Interfaces:**
- Produces: `parse_annex.parse_pdf(path: str | Path, max_pages: int | None = None) -> list[RawRow]`; `RawRow = dict` với key `tt, ai, trade, target, registrant, page` (str, đã NFC-normalize, giữ nguyên xuống dòng trong ô dưới dạng `\n`). Task 4 tiêu thụ list này.

- [ ] **Step 1: Viết script inspect để nhìn cấu trúc thật**

`scripts/inspect_pdf.py`:

```python
"""In thô các bảng của vài trang PDF để chốt mapping cột."""
import sys
import pdfplumber

path, start, end = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
with pdfplumber.open(path) as pdf:
    for i in range(start, min(end, len(pdf.pages))):
        print(f"===== PAGE {i} =====")
        for t in pdf.pages[i].extract_tables():
            for row in t:
                print([str(c)[:40] if c else "" for c in row])
```

Run: `.venv/bin/python scripts/inspect_pdf.py data/raw/<file phụ lục I> 0 4`
Expected: thấy header dạng `TT | Hoạt chất... | Tên thương phẩm | Đối tượng phòng trừ | Tổ chức đề nghị đăng ký` (đúng cấu trúc đã xác minh trong research). Nếu tên/thứ tự cột khác → cập nhật `COLUMN_KEYS` ở Step 3 theo thực tế trước khi viết fixture.

- [ ] **Step 2: Tạo fixture từ dữ liệu thật + failing test**

Chạy inspect trên 2–3 trang giữa tài liệu, chọn ~25 hàng thô **bao gồm đủ các ca**: hàng đầy đủ; hàng tiếp diễn (ô TT/hoạt chất rỗng — thương phẩm bổ sung của cùng hoạt chất); ô nhiều dòng; hàng header lặp lại đầu trang. Lưu nguyên trạng vào `tests/fixtures/annex_sample.json` dạng `{"pages": [{"page": 12, "rows": [["1","Abamectin ...","Reasgant 1.8EC","sâu cuốn lá/lúa","Cty ..."], ...]}]}`.

`tests/test_parse_annex.py`:

```python
import json
from pathlib import Path
from ingest.parse_annex import rows_from_tables, is_header_row

FIX = json.loads(Path("tests/fixtures/annex_sample.json").read_text())

def test_header_row_detected():
    assert is_header_row(["TT", "Hoạt chất", "Tên thương phẩm", "Đối tượng phòng trừ", "Tổ chức"])
    assert not is_header_row(["1", "Abamectin", "Reasgant 1.8EC", "sâu cuốn lá/lúa", "X"])

def test_rows_from_tables_keeps_continuation_rows():
    page = FIX["pages"][0]
    rows = rows_from_tables(page["rows"], page["page"])
    assert all(set(r) == {"tt", "ai", "trade", "target", "registrant", "page"} for r in rows)
    # hàng tiếp diễn được giữ nguyên (ai rỗng), không bị vứt
    assert any(r["ai"] == "" and r["trade"] for r in rows)
    # header lặp bị loại
    assert all(r["trade"] != "Tên thương phẩm" for r in rows)
```

- [ ] **Step 3: Chạy fail rồi implement `ingest/parse_annex.py`**

Run: `.venv/bin/pytest tests/test_parse_annex.py -q` → FAIL.

```python
"""Parse bảng phụ lục danh mục thuốc BVTV từ PDF (pdfplumber)."""
import unicodedata
from pathlib import Path

import pdfplumber

# Cột chuẩn theo phụ lục TT 75/2025 (xác minh bằng scripts/inspect_pdf.py)
N_COLS = 5
HEADER_HINTS = ("hoạt chất", "thương phẩm", "đối tượng")


def _norm(cell) -> str:
    s = "" if cell is None else str(cell)
    s = unicodedata.normalize("NFC", s)
    return "\n".join(line.strip() for line in s.splitlines()).strip()


def is_header_row(cells: list) -> bool:
    joined = " ".join(_norm(c).lower() for c in cells)
    return sum(h in joined for h in HEADER_HINTS) >= 2


def rows_from_tables(raw_rows: list[list], page: int) -> list[dict]:
    out = []
    for cells in raw_rows:
        cells = list(cells) + [""] * (N_COLS - len(cells))
        if is_header_row(cells):
            continue
        tt, ai, trade, target, registrant = (_norm(c) for c in cells[:N_COLS])
        if not any([tt, ai, trade, target]):
            continue
        out.append({"tt": tt, "ai": ai, "trade": trade,
                    "target": target, "registrant": registrant, "page": page})
    return out


def parse_pdf(path: str | Path, max_pages: int | None = None) -> list[dict]:
    rows: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        pages = pdf.pages[:max_pages] if max_pages else pdf.pages
        for i, p in enumerate(pages):
            for table in p.extract_tables():
                rows.extend(rows_from_tables(table, i))
    return rows
```

- [ ] **Step 4: Test pass + chạy thử trên PDF thật**

Run: `.venv/bin/pytest tests/test_parse_annex.py -q` → `2 passed`.
Run: `.venv/bin/python -c "from ingest.parse_annex import parse_pdf; r=parse_pdf('data/raw/<phụ lục I>', max_pages=8); print(len(r)); [print(x) for x in r[:5]]"`
Expected: vài trăm hàng, nội dung khớp mắt thường với PDF.

- [ ] **Step 5: Commit**

```bash
git add ingest/parse_annex.py scripts/inspect_pdf.py tests/test_parse_annex.py tests/fixtures/annex_sample.json
git commit -m "feat: parse bảng phụ lục danh mục thuốc BVTV từ PDF" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Normalize — gộp dòng tiếp diễn, tách formulation, tách (dịch hại, cây)

**Files:**
- Create: `ingest/normalize.py`, `tests/test_normalize.py`

**Interfaces:**
- Consumes: `list[RawRow]` từ `parse_annex.parse_pdf`.
- Produces: `normalize.to_entries(rows: list[dict], allow_no_trade: bool = False) -> list[Entry]` (chế độ `allow_no_trade=True` dành cho Phụ lục cấm — dòng chỉ có hoạt chất) với `Entry = dict`:
  `{"ai": str, "trade_name": str, "formulation": str|None, "registrant": str, "uses": list[tuple[pest, crop]], "pages": list[int]}`. Hàm phụ `split_formulation(trade: str) -> tuple[name, formulation|None]`, `split_targets(target: str) -> list[tuple[pest, crop]]`, `parse_viet_number(s: str) -> float` (dùng lại ở Task 8). Task 5 tiêu thụ `to_entries`.

- [ ] **Step 1: Failing tests**

`tests/test_normalize.py`:

```python
from ingest.normalize import split_formulation, split_targets, to_entries, parse_viet_number

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

def test_to_entries_merges_continuation():
    rows = [
        {"tt": "1", "ai": "Abamectin", "trade": "Reasgant 1.8EC",
         "target": "sâu cuốn lá/lúa", "registrant": "Cty A", "page": 3},
        {"tt": "", "ai": "", "trade": "Reasgant 3.6EC",
         "target": "nhện đỏ/cam", "registrant": "Cty A", "page": 3},
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
```

Run: `.venv/bin/pytest tests/test_normalize.py -q` → FAIL.

- [ ] **Step 2: Implement `ingest/normalize.py`**

```python
"""Chuẩn hoá hàng thô phụ lục → entries sản phẩm."""
import re

# Mã dạng chế phẩm phổ biến trong danh mục VN
_FORM_RE = re.compile(
    r"\s+(\d+(?:[.,]\d+)?(?:\s*[+/]\s*\d+(?:[.,]\d+)?)*\s*"
    r"(?:WP|EC|SC|SL|WG|WDG|GR|EW|OD|ME|SP|DP|CS|ZC|SE|FS|AS|DD|BTN|BHN|EO|GEL|AB|BR|CF|DC|SG|TB|XT))\s*$",
    re.IGNORECASE,
)


def split_formulation(trade: str) -> tuple[str, str | None]:
    m = _FORM_RE.search(trade)
    if not m:
        return trade.strip(), None
    return trade[: m.start()].strip(), m.group(1).replace(" ", "")


def split_targets(target: str) -> list[tuple[str, str]]:
    """'sâu cuốn lá, rầy nâu/lúa; rệp sáp/cà phê' → [(pest, crop), ...]"""
    out: list[tuple[str, str]] = []
    for part in re.split(r"[;\n]+", target):
        part = part.strip().rstrip(",")
        if not part or "/" not in part:
            continue
        pests_s, crop = part.rsplit("/", 1)
        crop = crop.strip().lower()
        for pest in re.split(r"[,]+", pests_s):
            pest = pest.strip().lower()
            if pest:
                out.append((pest, crop))
    return out


def parse_viet_number(s: str) -> float:
    s = s.strip().replace(" ", "")
    if "," in s:                      # 0,5 → 0.5 ; 1.200,5 → 1200.5
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):  # 1.200 → 1200
        s = s.replace(".", "")
    return float(s)


def to_entries(rows: list[dict], allow_no_trade: bool = False) -> list[dict]:
    entries: list[dict] = []
    cur: dict | None = None
    for r in rows:
        if r["ai"]:                    # hoạt chất mới hoặc lặp lại tên
            ai = " ".join(r["ai"].split())
        elif cur is not None:
            ai = cur["ai"]
        else:
            continue                   # hàng tiếp diễn mồ côi đầu file: bỏ, QA sẽ soát
        if r["trade"]:
            name, form = split_formulation(" ".join(r["trade"].split()))
            cur = {"ai": ai, "trade_name": name, "formulation": form,
                   "registrant": r["registrant"], "uses": [], "pages": []}
            entries.append(cur)
        elif allow_no_trade and r["ai"]:
            # Phụ lục II (cấm): nhiều dòng chỉ có hoạt chất, không có thương phẩm
            cur = {"ai": ai, "trade_name": "", "formulation": None,
                   "registrant": r["registrant"], "uses": [], "pages": []}
            entries.append(cur)
        if cur is None:
            continue
        cur["uses"].extend(split_targets(r["target"]))
        if r["page"] not in cur["pages"]:
            cur["pages"].append(r["page"])
        if r["registrant"] and not cur["registrant"]:
            cur["registrant"] = r["registrant"]
    return entries
```

- [ ] **Step 3: Test pass**

Run: `.venv/bin/pytest tests/test_normalize.py -q`
Expected: `6 passed`

- [ ] **Step 4: Commit**

```bash
git add ingest/normalize.py tests/test_normalize.py
git commit -m "feat: normalize hàng phụ lục (formulation, targets, số kiểu Việt)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Build `registry.db` + amendments TT 28/2026

**Files:**
- Create: `ingest/build_registry.py`, `data/amendments_tt28_2026.csv`, `tests/test_build_registry.py`

**Interfaces:**
- Consumes: `normalize.to_entries`.
- Produces: file `data/registry.db` với schema dưới; hàm `build_registry(allowed_entries, banned_entries, amendments_csv, out_path) -> sqlite3.Connection`. Hằng `DOCS` (số hiệu, ngày hiệu lực). Task 6/7/11 truy vấn db này.

Schema (DDL nằm trong module):

```sql
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
```

- [ ] **Step 1: Tạo `data/amendments_tt28_2026.csv` (curate tay từ phụ lục TT 28/2026)**

Cột: `action,ai,trade_name,formulation,crop,pest,note` với `action ∈ {remove_product, add_product, add_use, change_registrant}`. Đọc `data/raw/tt28_2026_phuluc.pdf` (PDF text — đã xác minh đọc được), nhập đúng theo phụ lục: ~5 sản phẩm rút tự nguyện (`remove_product`), ~3 hoạt chất mới + ~30 thuốc sinh học (`add_product` + `add_use`), các dòng đổi tổ chức đăng ký (`change_registrant`). Mỗi dòng thêm `note` = trích trang/mục trong phụ lục. File này commit vào git (provenance của nó là chính PDF trong manifest).

- [ ] **Step 2: Failing test**

`tests/test_build_registry.py`:

```python
import sqlite3
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
```

Run: `.venv/bin/pytest tests/test_build_registry.py -q` → FAIL.

- [ ] **Step 3: Implement `ingest/build_registry.py`**

```python
"""Nạp entries đã normalize vào registry.db với versioning hiệu lực."""
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
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if Path(out_path).exists():
        Path(out_path).unlink()
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
                conn.execute(
                    "UPDATE products SET effective_to=? WHERE trade_name=? "
                    "AND ifnull(formulation,'')=ifnull(?, '') AND status='allowed'",
                    (TT28_EFF, row["trade_name"], row["formulation"] or None))
                _insert_product(conn, {"ai": row["ai"], "trade_name": row["trade_name"],
                                       "formulation": row["formulation"] or None,
                                       "registrant": None, "uses": []},
                                "removed", d28, TT28_EFF)
            elif a == "add_product":
                _insert_product(conn, {"ai": row["ai"], "trade_name": row["trade_name"],
                                       "formulation": row["formulation"] or None,
                                       "registrant": None, "uses": []},
                                "allowed", d28, TT28_EFF)
            elif a == "add_use":
                pid = conn.execute(
                    "SELECT id FROM products WHERE trade_name=? AND status='allowed' "
                    "ORDER BY effective_from DESC LIMIT 1", (row["trade_name"],)).fetchone()[0]
                conn.execute("INSERT INTO uses(product_id,crop,pest,doc_id) VALUES(?,?,?,?)",
                             (pid, row["crop"], row["pest"], d28))
            elif a == "change_registrant":
                conn.execute("UPDATE products SET registrant=? WHERE trade_name=? AND status='allowed'",
                             (row["note"], row["trade_name"]))
    conn.commit()
    return conn


def main():
    from ingest.parse_annex import parse_pdf
    from ingest.normalize import to_entries
    import json
    notes = json.loads(Path("data/raw/annex_files.json").read_text())  # {"allowed": "...", "banned": "..."} — tạo ở Step 4
    allowed = to_entries(parse_pdf(notes["allowed"]))
    banned = to_entries(parse_pdf(notes["banned"]), allow_no_trade=True)
    conn = build_registry(allowed, banned, Path("data/amendments_tt28_2026.csv"), Path("data/registry.db"))
    for t in ("active_ingredients", "products", "uses"):
        print(t, conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Test pass + build thật**

Run: `.venv/bin/pytest tests/test_build_registry.py -q` → `1 passed`.
Tạo `data/raw/annex_files.json` trỏ đúng 2 file phụ lục (theo `data/raw/NOTES.md` của Task 2), rồi:
Run: `.venv/bin/python -m ingest.build_registry`
Expected: in số đếm 3 bảng; products cỡ hàng nghìn (TT 25/2024 từng có 4.844 thương phẩm — cùng bậc độ lớn; lệch xa → nghi parse sót, quay lại Task 3/4).

- [ ] **Step 5: Commit**

```bash
git add ingest/build_registry.py tests/test_build_registry.py data/amendments_tt28_2026.csv
git commit -m "feat: build registry.db từ TT 75/2025 + amendments TT 28/2026" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Query API + alias phương ngữ

**Files:**
- Create: `app/backend/db.py`, `data/aliases_seed.csv`, `ingest/build_aliases.py`, `tests/test_db_queries.py`

**Interfaces:**
- Consumes: `data/registry.db` (Task 5).
- Produces (P1 sẽ gọi đúng các chữ ký này):

```python
@dataclass
class ProductHit:
    product_id: int; trade_name: str; formulation: str | None
    active_ingredient: str; registrant: str | None; status: str; cite: str

def connect(path: str = "data/registry.db") -> sqlite3.Connection
def lookup_products(conn, crop: str, pest: str, on_date: str) -> list[ProductHit]
def check_product_status(conn, name: str, on_date: str) -> ProductHit | None
def resolve_alias(conn, text: str, entity_type: str) -> Resolution | None
# Resolution = dataclass(canonical: str, ambiguous: bool, score: float)
```

- [ ] **Step 1: Seed alias CSV**

`data/aliases_seed.csv` (cột `entity_type,canonical,alias,ambiguous,note`) — khởi tạo tối thiểu các dòng sau, bổ sung dần trong P1:

```csv
entity_type,canonical,alias,ambiguous,note
pest,rầy nâu,rầy cám,0,tên gọi rầy nâu tuổi nhỏ ở ĐBSCL
pest,bọ trĩ,bù lạch,0,phương ngữ Nam Bộ
pest,đạo ôn,cháy lá,1,nông dân gọi chung — cần hỏi lại phân biệt bạc lá
pest,bạc lá,cháy bìa lá,0,phương ngữ
pest,bệnh xì mủ,phytophthora,0,sầu riêng
pest,ốc bươu vàng,ốc,1,quá chung — hỏi lại
crop,lúa,lúa nước,0,
crop,cà phê,cà phê vối,0,robusta
crop,sầu riêng,sầu,1,cách nói tắt — xác nhận lại
```

- [ ] **Step 2: Failing tests**

`tests/test_db_queries.py`:

```python
import sqlite3
from pathlib import Path
import pytest
from ingest.build_registry import build_registry
from ingest.build_aliases import load_aliases
from app.backend.db import lookup_products, check_product_status, resolve_alias

@pytest.fixture()
def conn(tmp_path):
    allowed = [
        {"ai": "Abamectin", "trade_name": "Reasgant", "formulation": "1.8EC",
         "registrant": "Cty A", "uses": [("sâu cuốn lá", "lúa"), ("rầy nâu", "lúa")], "pages": [3]},
    ]
    amend = tmp_path / "a.csv"
    amend.write_text("action,ai,trade_name,formulation,crop,pest,note\n", encoding="utf-8")
    c = build_registry(allowed, [], amend, tmp_path / "r.db")
    load_aliases(c, Path("data/aliases_seed.csv"))
    return c

def test_lookup_products_by_crop_pest(conn):
    hits = lookup_products(conn, "lúa", "rầy nâu", "2026-07-17")
    assert hits and hits[0].trade_name == "Reasgant"
    assert "75/2025/TT-BNNMT" in hits[0].cite

def test_lookup_no_match_returns_empty(conn):
    assert lookup_products(conn, "sầu riêng", "rầy xanh", "2026-07-17") == []

def test_check_product_status_fuzzy(conn):
    hit = check_product_status(conn, "reasgant 1.8 ec", "2026-07-17")
    assert hit and hit.status == "allowed"

def test_resolve_alias(conn):
    r = resolve_alias(conn, "rầy cám", "pest")
    assert r.canonical == "rầy nâu" and not r.ambiguous
    r2 = resolve_alias(conn, "cháy lá", "pest")
    assert r2.ambiguous  # phải hỏi lại, không tự map
    assert resolve_alias(conn, "xyz không tồn tại", "pest") is None
```

Run: `.venv/bin/pytest tests/test_db_queries.py -q` → FAIL.

- [ ] **Step 3: Implement**

`ingest/build_aliases.py`:

```python
import csv
from pathlib import Path

DDL = """CREATE TABLE IF NOT EXISTS aliases(
  id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL CHECK(entity_type IN ('product','pest','crop')),
  canonical TEXT NOT NULL, alias TEXT NOT NULL, ambiguous INTEGER NOT NULL DEFAULT 0, note TEXT);"""


def load_aliases(conn, csv_path: Path) -> int:
    conn.executescript(DDL)
    n = 0
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conn.execute("INSERT INTO aliases(entity_type,canonical,alias,ambiguous,note) VALUES(?,?,?,?,?)",
                         (row["entity_type"], row["canonical"].lower(), row["alias"].lower(),
                          int(row["ambiguous"] or 0), row.get("note") or None))
            n += 1
    conn.commit()
    return n
```

`app/backend/db.py`:

```python
"""Query API trên registry.db — interface chính cho pipeline P1."""
import sqlite3
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz, process


@dataclass
class ProductHit:
    product_id: int
    trade_name: str
    formulation: str | None
    active_ingredient: str
    registrant: str | None
    status: str
    cite: str


@dataclass
class Resolution:
    canonical: str
    ambiguous: bool
    score: float


def connect(path: str = "data/registry.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s).strip().lower()


def _cite(row) -> str:
    return f"Phụ lục Thông tư {row['so_hieu']} (hiệu lực từ {row['effective_from']})"


_BASE = """SELECT p.id AS product_id, p.trade_name, p.formulation, p.registrant, p.status,
                  ai.name_common AS active_ingredient, d.so_hieu, p.effective_from
           FROM products p
           JOIN active_ingredients ai ON ai.id = p.ai_id
           JOIN docs d ON d.id = p.doc_id"""

_DATE = " p.effective_from <= :d AND (p.effective_to IS NULL OR p.effective_to > :d)"


def _hit(row) -> ProductHit:
    return ProductHit(row["product_id"], row["trade_name"], row["formulation"],
                      row["active_ingredient"], row["registrant"], row["status"], _cite(row))


def lookup_products(conn, crop: str, pest: str, on_date: str) -> list[ProductHit]:
    rows = conn.execute(
        _BASE + " JOIN uses u ON u.product_id = p.id"
                " WHERE u.crop = :crop AND u.pest = :pest AND p.status = 'allowed' AND" + _DATE +
                " ORDER BY p.trade_name",
        {"crop": _norm(crop), "pest": _norm(pest), "d": on_date}).fetchall()
    return [_hit(r) for r in rows]


def check_product_status(conn, name: str, on_date: str) -> ProductHit | None:
    """Tra trạng thái theo tên thương phẩm, chấp nhận gõ/nghe sai nhẹ (fuzzy ≥ 85)."""
    rows = conn.execute(_BASE + " WHERE " + _DATE, {"d": on_date}).fetchall()
    if not rows:
        return None
    names = {i: f"{r['trade_name']} {r['formulation'] or ''}".strip().lower() for i, r in enumerate(rows)}
    best = process.extractOne(_norm(name), names, scorer=fuzz.WRatio, score_cutoff=85)
    if not best:
        return None
    return _hit(rows[best[2]])


def resolve_alias(conn, text: str, entity_type: str) -> Resolution | None:
    t = _norm(text)
    row = conn.execute("SELECT canonical, ambiguous FROM aliases WHERE entity_type=? AND alias=?",
                       (entity_type, t)).fetchone()
    if row:
        return Resolution(row["canonical"], bool(row["ambiguous"]), 100.0)
    rows = conn.execute("SELECT canonical, ambiguous, alias FROM aliases WHERE entity_type=?",
                        (entity_type,)).fetchall()
    if not rows:
        return None
    choices = {i: r["alias"] for i, r in enumerate(rows)}
    best = process.extractOne(t, choices, scorer=fuzz.WRatio, score_cutoff=88)
    if not best:
        return None
    r = rows[best[2]]
    return Resolution(r["canonical"], bool(r["ambiguous"]), float(best[1]))
```

- [ ] **Step 4: Test pass + thử trên db thật**

Run: `.venv/bin/pytest tests/test_db_queries.py -q` → `4 passed`.
Run: `.venv/bin/python -c "from app.backend.db import *; c=connect(); print(lookup_products(c,'lúa','rầy nâu','2026-07-17')[:3])"`
Expected: ra danh sách thuốc thật đăng ký cho rầy nâu/lúa kèm cite TT 75/2025.

- [ ] **Step 5: Commit**

```bash
git add app/backend/db.py ingest/build_aliases.py data/aliases_seed.csv tests/test_db_queries.py
git commit -m "feat: query API registry + alias phương ngữ (fuzzy)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: QA registry + chốt danh sách dịch hại scope

**Files:**
- Create: `ingest/qa_registry.py`, `scripts/scope_pests.py`, `docs/qa/p0-registry-qa.md`, `docs/scope-pests.md`

**Interfaces:**
- Consumes: `data/registry.db`, PDF gốc.
- Produces: báo cáo QA (con người/agent đối chiếu); `docs/scope-pests.md` — danh sách (cây, dịch hại) chính thức của scope, Task 9 và P1 dùng làm khung.

- [ ] **Step 1: Viết `ingest/qa_registry.py`**

```python
"""QA registry: lấy mẫu ngẫu nhiên ≥5% products, in kèm trang PDF để đối chiếu tay;
   + các kiểm tra máy: trùng lặp, mồ côi, đếm theo status."""
import random
import sys
from app.backend.db import connect


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
    return problems


def sample(conn, pct: float = 0.05, seed: int = 17):
    rows = conn.execute("""SELECT p.id, p.trade_name, p.formulation, ai.name_common
                           FROM products p JOIN active_ingredients ai ON ai.id=p.ai_id""").fetchall()
    random.Random(seed).shuffle(rows := list(rows))
    take = rows[: max(30, int(len(rows) * pct))]
    for r in take:
        uses = conn.execute("SELECT crop,pest FROM uses WHERE product_id=?", (r[0],)).fetchall()
        print(f"[{r[0]}] {r[1]} {r[2] or ''} | {r[3]} | {[tuple(u) for u in uses]}")
    print(f"\nTổng mẫu: {len(take)} — đối chiếu từng dòng với PDF phụ lục, ghi kết quả vào docs/qa/p0-registry-qa.md")


if __name__ == "__main__":
    conn = connect()
    for p in machine_checks(conn):
        print("CHECK:", p)
    sample(conn, float(sys.argv[1]) if len(sys.argv) > 1 else 0.05)
```

- [ ] **Step 2: Chạy QA + đối chiếu**

Run: `.venv/bin/python -m ingest.qa_registry 0.05 > /tmp/qa_sample.txt && head -50 /tmp/qa_sample.txt`
Đối chiếu từng dòng mẫu với PDF (mở bằng số trang trong `pages`): tên hoạt chất, thương phẩm, dạng chế phẩm, cặp dịch hại/cây. Ghi vào `docs/qa/p0-registry-qa.md`: số mẫu, số sai, mô tả từng lỗi, lỗi hệ thống nào phải sửa parser (quay lại Task 3/4 nếu tỉ lệ lỗi >2%), số đếm cuối theo status.

- [ ] **Step 3: Chốt scope dịch hại — `scripts/scope_pests.py`**

```python
"""In top dịch hại theo số sản phẩm đăng ký cho 3 cây scope → làm căn cứ chốt docs/scope-pests.md"""
from app.backend.db import connect

conn = connect()
for crop in ("lúa", "cà phê", "sầu riêng"):
    print(f"\n== {crop} ==")
    for pest, n in conn.execute(
        """SELECT u.pest, COUNT(DISTINCT u.product_id) n FROM uses u
           JOIN products p ON p.id=u.product_id AND p.status='allowed'
           WHERE u.crop=? GROUP BY u.pest ORDER BY n DESC LIMIT 15""", (crop,)):
        print(f"{n:4d}  {pest}")
```

Run: `.venv/bin/python scripts/scope_pests.py`
Từ output + spec §3, viết `docs/scope-pests.md`: bảng (cây, dịch hại canonical, ~8–12 dịch hại/cây, ưu tiên theo số sản phẩm đăng ký và mùa vụ hiện hành), đánh dấu nhóm nào thuộc eval "liều lượng" (có label data ở Task 9).

- [ ] **Step 4: Commit**

```bash
git add ingest/qa_registry.py scripts/scope_pests.py docs/qa/p0-registry-qa.md docs/scope-pests.md
git commit -m "chore: QA registry 5% + chốt danh sách dịch hại scope" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Schema + validator labels.db (chưa curate)

**Files:**
- Create: `ingest/build_labels.py`, `data/labels/labels_curated.csv` (header + 2 dòng mẫu), `tests/test_build_labels.py`

**Interfaces:**
- Consumes: `normalize.parse_viet_number` (Task 4).
- Produces: `build_labels(csv_path, out_path) -> (sqlite3.Connection, LabelsReport)`; bảng `label_doses` (schema dưới); `app/backend/db.get_dose` bổ sung ngay trong Step 2 (cùng bước implement). `LabelsReport = dict {n_rows, n_products, n_verified, mismatches: list[str], errors: list[str]}`. P1 render template số từ bảng này.

Schema:

```sql
CREATE TABLE label_doses(
  id INTEGER PRIMARY KEY,
  product_trade_name TEXT NOT NULL, formulation TEXT, ai_name TEXT NOT NULL,
  crop TEXT NOT NULL, pest TEXT NOT NULL,
  dose_text TEXT NOT NULL, water_text TEXT, phi_days INTEGER, method TEXT,
  dose_min REAL, dose_max REAL, dose_unit TEXT,
  source_url TEXT NOT NULL, source_note TEXT, retrieved_at TEXT NOT NULL,
  entry_pass INTEGER NOT NULL CHECK(entry_pass IN (1,2)),
  verified INTEGER NOT NULL DEFAULT 0);
```

CSV cột: `product_trade_name,formulation,ai_name,crop,pest,dose_text,water_text,phi_days,method,dose_unit,source_url,source_note,retrieved_at,entry_pass`.

Quy tắc double-entry: mỗi (product, crop, pest) phải có dòng `entry_pass=1` và `entry_pass=2` **tra độc lập** (2 phiên/2 nguồn khác nhau nếu được); khớp `dose_text` chuẩn hoá + `phi_days` → cả hai `verified=1`; lệch → vào `mismatches`, KHÔNG verified (pipeline sẽ không dùng).

- [ ] **Step 1: Failing tests**

`tests/test_build_labels.py`:

```python
from pathlib import Path
from ingest.build_labels import build_labels

HDR = ("product_trade_name,formulation,ai_name,crop,pest,dose_text,water_text,"
       "phi_days,method,dose_unit,source_url,source_note,retrieved_at,entry_pass\n")

def _row(p="Reasgant", dose="0,5 lít/ha", phi="7", ep="1", pest="rầy nâu"):
    return (f'{p},1.8EC,Abamectin,lúa,{pest},"{dose}",400 lít nước/ha,{phi},phun,'
            f"lít/ha,https://sansangxuatkhau.ppd.gov.vn/x,app CSDL QG,2026-07-18T09:00:00,{ep}\n")

def test_double_entry_match_verifies(tmp_path):
    csv = tmp_path / "l.csv"
    csv.write_text(HDR + _row(ep="1") + _row(ep="2"), encoding="utf-8")
    conn, rep = build_labels(csv, tmp_path / "labels.db")
    assert rep["n_verified"] == 1 and not rep["mismatches"]
    assert conn.execute("SELECT dose_min, dose_max, dose_unit FROM label_doses WHERE verified=1 AND entry_pass=1").fetchone() == (0.5, 0.5, "lít/ha")

def test_double_entry_mismatch_not_verified(tmp_path):
    csv = tmp_path / "l.csv"
    csv.write_text(HDR + _row(dose="0,5 lít/ha", ep="1") + _row(dose="1,5 lít/ha", ep="2"), encoding="utf-8")
    conn, rep = build_labels(csv, tmp_path / "labels.db")
    assert rep["n_verified"] == 0 and len(rep["mismatches"]) == 1

def test_missing_provenance_is_error(tmp_path):
    bad = _row().replace("https://sansangxuatkhau.ppd.gov.vn/x", "")
    csv = tmp_path / "l.csv"
    csv.write_text(HDR + bad, encoding="utf-8")
    _, rep = build_labels(csv, tmp_path / "labels.db")
    assert rep["errors"]

def test_dose_range_parsed(tmp_path):
    csv = tmp_path / "l.csv"
    csv.write_text(HDR + _row(dose="0,4-0,6 lít/ha", ep="1") + _row(dose="0,4-0,6 lít/ha", ep="2"), encoding="utf-8")
    conn, _ = build_labels(csv, tmp_path / "labels.db")
    assert conn.execute("SELECT dose_min,dose_max FROM label_doses LIMIT 1").fetchone() == (0.4, 0.6)
```

Run: `.venv/bin/pytest tests/test_build_labels.py -q` → FAIL.

- [ ] **Step 2: Implement `ingest/build_labels.py`**

```python
"""labels_curated.csv → labels.db, kiểm double-entry + provenance."""
import csv
import re
import sqlite3
from pathlib import Path

from ingest.normalize import parse_viet_number

DDL = """
CREATE TABLE label_doses(
  id INTEGER PRIMARY KEY,
  product_trade_name TEXT NOT NULL, formulation TEXT, ai_name TEXT NOT NULL,
  crop TEXT NOT NULL, pest TEXT NOT NULL,
  dose_text TEXT NOT NULL, water_text TEXT, phi_days INTEGER, method TEXT,
  dose_min REAL, dose_max REAL, dose_unit TEXT,
  source_url TEXT NOT NULL, source_note TEXT, retrieved_at TEXT NOT NULL,
  entry_pass INTEGER NOT NULL CHECK(entry_pass IN (1,2)),
  verified INTEGER NOT NULL DEFAULT 0);
"""

_RANGE = re.compile(r"(\d+(?:[.,]\d+)?)(?:\s*[-–]\s*(\d+(?:[.,]\d+)?))?")


def parse_dose(dose_text: str) -> tuple[float | None, float | None]:
    m = _RANGE.search(dose_text)
    if not m:
        return None, None
    lo = parse_viet_number(m.group(1))
    hi = parse_viet_number(m.group(2)) if m.group(2) else lo
    return lo, hi


def _key(r: dict) -> tuple:
    return (r["product_trade_name"].strip().lower(), r["crop"].strip().lower(), r["pest"].strip().lower())


def _dose_norm(r: dict) -> tuple:
    return (re.sub(r"\s+", " ", r["dose_text"].strip().lower()), r["phi_days"].strip())


def build_labels(csv_path: Path, out_path: Path):
    rows, errors = [], []
    with open(csv_path, encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f), start=2):
            if not r["source_url"].strip() or not r["retrieved_at"].strip():
                errors.append(f"dòng {i}: thiếu provenance (source_url/retrieved_at)")
                continue
            if r["entry_pass"] not in ("1", "2"):
                errors.append(f"dòng {i}: entry_pass phải là 1|2")
                continue
            rows.append(r)
    by_key: dict[tuple, dict[str, dict]] = {}
    for r in rows:
        by_key.setdefault(_key(r), {})[r["entry_pass"]] = r
    verified_keys, mismatches = set(), []
    for k, passes in by_key.items():
        if "1" in passes and "2" in passes:
            if _dose_norm(passes["1"]) == _dose_norm(passes["2"]):
                verified_keys.add(k)
            else:
                mismatches.append(f"{k}: '{passes['1']['dose_text']}' vs '{passes['2']['dose_text']}'")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if Path(out_path).exists():
        Path(out_path).unlink()
    conn = sqlite3.connect(out_path)
    conn.executescript(DDL)
    for r in rows:
        lo, hi = parse_dose(r["dose_text"])
        conn.execute(
            """INSERT INTO label_doses(product_trade_name,formulation,ai_name,crop,pest,dose_text,
               water_text,phi_days,method,dose_min,dose_max,dose_unit,source_url,source_note,
               retrieved_at,entry_pass,verified) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["product_trade_name"].strip(), r["formulation"] or None, r["ai_name"].strip(),
             r["crop"].strip().lower(), r["pest"].strip().lower(), r["dose_text"].strip(),
             r["water_text"] or None, int(r["phi_days"]) if r["phi_days"].strip() else None,
             r["method"] or None, lo, hi, r["dose_unit"] or None,
             r["source_url"].strip(), r["source_note"] or None, r["retrieved_at"].strip(),
             int(r["entry_pass"]), 1 if _key(r) in verified_keys else 0))
    conn.commit()
    report = {"n_rows": len(rows), "n_products": len(by_key),
              "n_verified": len(verified_keys), "mismatches": mismatches, "errors": errors}
    return conn, report
```

Bổ sung vào `app/backend/db.py` (append cuối file):

```python
@dataclass
class LabelDose:
    product_trade_name: str
    formulation: str | None
    crop: str
    pest: str
    dose_text: str
    water_text: str | None
    phi_days: int | None
    method: str | None
    source_url: str


def connect_labels(path: str = "data/labels.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def get_dose(lconn, trade_name: str, crop: str, pest: str) -> LabelDose | None:
    row = lconn.execute(
        """SELECT * FROM label_doses WHERE verified=1 AND entry_pass=1
           AND lower(product_trade_name)=? AND crop=? AND pest=? LIMIT 1""",
        (trade_name.strip().lower(), crop.strip().lower(), pest.strip().lower())).fetchone()
    if not row:
        return None
    return LabelDose(row["product_trade_name"], row["formulation"], row["crop"], row["pest"],
                     row["dose_text"], row["water_text"], row["phi_days"], row["method"], row["source_url"])
```

- [ ] **Step 3: Test pass**

Run: `.venv/bin/pytest tests/test_build_labels.py -q` → `4 passed`; `.venv/bin/pytest -q` → toàn bộ xanh.

- [ ] **Step 4: Tạo CSV khung + commit**

`data/labels/labels_curated.csv`: chỉ header + 2 dòng mẫu thật (tra thử 1 sản phẩm bất kỳ đủ 2 pass để chứng minh format).

```bash
git add ingest/build_labels.py app/backend/db.py data/labels/labels_curated.csv tests/test_build_labels.py
git commit -m "feat: labels.db schema + double-entry validator + get_dose" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Curate labels (~150–200 sản phẩm) — công việc tra cứu

**Files:**
- Modify: `data/labels/labels_curated.csv`
- Create: `scripts/label_targets.py`, `docs/qa/p0-labels-qa.md`

**Interfaces:**
- Consumes: `docs/scope-pests.md` (Task 7), `lookup_products` (Task 6), validator (Task 8).
- Produces: `data/labels.db` có **≥150 sản phẩm verified**; báo cáo curate.

- [ ] **Step 1: Sinh danh sách mục tiêu**

`scripts/label_targets.py`:

```python
"""In danh sách (cây, dịch hại, sản phẩm) cần tra liều, ưu tiên theo scope-pests."""
from app.backend.db import connect, lookup_products

SCOPE = [
    # (crop, pest) — chép đúng từ docs/scope-pests.md sau Task 7
    ("lúa", "rầy nâu"), ("lúa", "đạo ôn"), ("lúa", "sâu cuốn lá"),
    ("cà phê", "rệp sáp"), ("cà phê", "gỉ sắt"),
    ("sầu riêng", "thán thư"), ("sầu riêng", "rầy xanh"),
]
conn = connect()
for crop, pest in SCOPE:
    hits = lookup_products(conn, crop, pest, "2026-07-17")
    print(f"\n== {crop} / {pest}: {len(hits)} sản phẩm")
    for h in hits[:12]:                      # tối đa 12 SP phổ biến mỗi cặp
        print(f"  {h.trade_name} {h.formulation or ''} | {h.active_ingredient}")
```

Run: `.venv/bin/python scripts/label_targets.py > /tmp/targets.txt` — cập nhật `SCOPE` theo đúng `docs/scope-pests.md` trước khi chạy.

- [ ] **Step 2: Tra pass 1 (từng sản phẩm)**

Quy trình cho MỖI sản phẩm trong targets:
1. Tra trên cổng CSDL quốc gia: mở `https://sansangxuatkhau.ppd.gov.vn/thuoc-va-phan-bon/phan-mem-tra-cuu-thuoc-bao-ve-thuc-vat-quoc-gia.html` → công cụ tra cứu theo cây/dịch hại/tên thuốc (WebFetch/browser; nếu cổng khó truy vấn tự động → tra thủ công từng SP).
2. Nếu cổng không ra: tìm nhãn PDF chính thức của nhà đăng ký (site nhà sản xuất, đúng tên + dạng chế phẩm + số đăng ký).
3. Ghi 1 dòng CSV `entry_pass=1`: `dose_text` NGUYÊN VĂN (kể cả khoảng, đơn vị), `water_text`, `phi_days`, `method`, `source_url` (URL trang/label cụ thể), `source_note` (vd "CSDL QG, tra 18/07"), `retrieved_at` ISO; trường chứa dấu phẩy (nhất là `dose_text` kiểu "0,5 lít/ha") phải bọc trong ngoặc kép CSV.
4. Không tìm được nguồn tin cậy → KHÔNG ghi dòng nào (sản phẩm đó pipeline sẽ trả "theo liều trên nhãn").

- [ ] **Step 3: Tra pass 2 độc lập**

Lặp lại toàn bộ danh sách ở phiên làm việc khác (hoặc nguồn khác: pass 1 dùng CSDL QG thì pass 2 ưu tiên nhãn nhà sản xuất), KHÔNG nhìn lại pass 1, ghi các dòng `entry_pass=2`.

- [ ] **Step 4: Build + xử lý mismatch**

Run: `.venv/bin/python -c "from ingest.build_labels import build_labels; from pathlib import Path; import json; c,r=build_labels(Path('data/labels/labels_curated.csv'), Path('data/labels.db')); print(json.dumps(r, ensure_ascii=False, indent=2))"`
Expected: `n_verified ≥ 150`, `errors = []`. Mỗi mismatch → tra lần 3 làm trọng tài, sửa dòng sai, ghi chú vào `source_note`; không phân xử được → xoá cả 2 dòng (thà thiếu còn hơn sai). Ghi thống kê + danh sách mismatch đã xử lý vào `docs/qa/p0-labels-qa.md`.

- [ ] **Step 5: Commit**

```bash
git add data/labels/labels_curated.csv docs/qa/p0-labels-qa.md scripts/label_targets.py
git commit -m "data: curate liều nhãn ~150+ sản phẩm (double-entry, provenance)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: KB văn bản — chunk + FTS5 (BM25)

**Files:**
- Create: `ingest/build_kb.py`, `data/kb_sources.json`, `tests/test_build_kb.py`
- Modify: `ingest/download.py` (thêm nguồn KB còn thiếu vào `SOURCES`)

**Interfaces:**
- Consumes: `data/raw/*.pdf` + file markdown curate tay trong `data/kb_manual/`.
- Produces: `data/kb.db` — bảng `chunks(id, doc_id, section, text, crop, region_scope, authority_level, date, url)` + virtual table FTS5 `chunks_fts(text_tok)` (pyvi tokenize, content-linked). Hàm `search_bm25(conn, query: str, k: int = 20, region: str | None = None, crop: str | None = None) -> list[ChunkHit]`; `ChunkHit = dict(id, text, section, url, score, ...)`. P1 dùng hàm này làm nhánh BM25 của hybrid retrieval.

- [ ] **Step 1: Lấy đủ nguồn KB**

1. Thêm vào `data/sources.yaml` (nguồn sự thật của downloader sau fix Task 2 — KHÔNG sửa code) nếu chưa có: trang bản tin SVGH `https://www.ppd.gov.vn/thong-bao-tinh-hinh-svgh-7-ngay.html` (kind=page, pattern=".doc"), trang mặn `https://vawr.org.vn/du-bao-xam-nhap-man-mua-kho-vung-ven-bien-dong-bang-song-cuu-long` (kind=page, pattern=".pdf").
2. Lịch thời vụ An Giang + Đắk Lắk: WebSearch `"lịch thời vụ" site:angiang.gov.vn 2025 2026` và `"lịch thời vụ" OR "kế hoạch sản xuất" site:daklak.gov.vn cà phê sầu riêng` → tải công văn Sở NN&MT mới nhất mỗi tỉnh vào `data/raw/`. Nếu PDF scan → chép tay nội dung bảng chính (tỉnh, vụ, cây, mốc ngày, giống khuyến cáo) thành `data/kb_manual/lich-thoi-vu-<tỉnh>-<vụ>.md` với front-matter metadata (xem Step 2) + `url` nguồn.
3. **FAQ khuyến nông Lâm Đồng (nguồn user chỉ định):** viết `ingest/crawl_faq_lamdong.py` crawl `http://khuyennong.lamdong.gov.vn/News/FaqList.aspx` — danh sách hỏi–đáp thật của nông dân, phân trang ASPX (postback/tham số trang; site HTTP thường, không SSL). Mỗi Q&A lưu 1 record vào `data/faq/faq_lamdong.jsonl`: `{question, answer, url, date, category}` (NFC normalize). Dùng làm 2 việc: (a) KB chunks với `authority_level=khuyen_nong`, `region_scope=lâm đồng` (mỗi Q&A = 1 chunk, section = câu hỏi); (b) kho câu hỏi thật cho bộ eval P3 — KHÔNG xoá file JSONL sau khi ingest. Crawl lịch sự: delay ≥1s giữa request, dừng ở ~200 Q&A gần nhất nếu list quá dài.
4. Chạy lại `.venv/bin/python -m ingest.download`.

- [ ] **Step 2: Failing test cho chunker + search**

Format `data/kb_manual/*.md` (và output extract PDF): front-matter đơn giản

```
---
doc_id: lich-thoi-vu-an-giang-dx-2026
title: Lịch thời vụ Đông Xuân 2026-2027 An Giang
crop: lúa
region_scope: an giang
authority_level: ban_tin_vung
date: 2026-10-01
url: https://...
---
## Đợt 1
Xuống giống từ ...
```

`tests/test_build_kb.py`:

```python
from pathlib import Path
from ingest.build_kb import parse_manual_md, chunk_sections, build_kb, search_bm25

MD = """---
doc_id: d1
title: T
crop: lúa
region_scope: an giang
authority_level: ban_tin_vung
date: 2026-10-01
url: https://x
---
## Đợt 1
Xuống giống 10-30/10, né rầy.
## Đợt 2
Xuống giống tháng 11, chú ý xâm nhập mặn và bệnh đạo ôn.
"""

def test_parse_and_chunk(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(MD, encoding="utf-8")
    meta, sections = parse_manual_md(p)
    assert meta["doc_id"] == "d1" and meta["crop"] == "lúa"
    chunks = chunk_sections(meta, sections, max_chars=200)
    assert len(chunks) == 2 and chunks[1]["section"] == "Đợt 2"

def test_build_and_search(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(MD, encoding="utf-8")
    conn = build_kb([p], tmp_path / "kb.db")
    hits = search_bm25(conn, "đạo ôn xâm nhập mặn", k=5)
    assert hits and hits[0]["section"] == "Đợt 2"
    assert search_bm25(conn, "đạo ôn", k=5, region="đắk lắk") == []  # filter vùng
```

Run: `.venv/bin/pytest tests/test_build_kb.py -q` → FAIL.

- [ ] **Step 3: Implement `ingest/build_kb.py`**

```python
"""KB văn bản: markdown (curate/extract) → chunks + FTS5 (pyvi tokenize)."""
import re
import sqlite3
from pathlib import Path

from pyvi import ViTokenizer

DDL = """
CREATE TABLE chunks(
  id INTEGER PRIMARY KEY, doc_id TEXT NOT NULL, section TEXT, text TEXT NOT NULL,
  crop TEXT, region_scope TEXT NOT NULL DEFAULT 'national',
  authority_level TEXT NOT NULL, date TEXT, url TEXT NOT NULL);
CREATE VIRTUAL TABLE chunks_fts USING fts5(text_tok, content='');
"""


def _tok(s: str) -> str:
    return ViTokenizer.tokenize(s.lower())


def parse_manual_md(path: Path) -> tuple[dict, list[tuple[str, str]]]:
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.DOTALL)
    meta = {}
    body = raw
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
        body = m.group(2)
    sections, cur_title, cur = [], "", []
    for line in body.splitlines():
        if line.startswith("#"):
            if cur:
                sections.append((cur_title, "\n".join(cur).strip()))
            cur_title, cur = line.lstrip("#").strip(), []
        else:
            cur.append(line)
    if cur:
        sections.append((cur_title, "\n".join(cur).strip()))
    return meta, [s for s in sections if s[1]]


def chunk_sections(meta: dict, sections: list[tuple[str, str]], max_chars: int = 1600) -> list[dict]:
    chunks = []
    for title, text in sections:
        for i in range(0, len(text), max_chars):
            chunks.append({**meta, "section": title, "text": text[i:i + max_chars]})
    return chunks


def build_kb(md_paths: list[Path], out_path: Path) -> sqlite3.Connection:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if Path(out_path).exists():
        Path(out_path).unlink()
    conn = sqlite3.connect(out_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    for p in md_paths:
        meta, sections = parse_manual_md(p)
        for c in chunk_sections(meta, sections):
            cur = conn.execute(
                "INSERT INTO chunks(doc_id,section,text,crop,region_scope,authority_level,date,url) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (c["doc_id"], c["section"], c["text"], c.get("crop"),
                 c.get("region_scope", "national"), c["authority_level"], c.get("date"), c["url"]))
            conn.execute("INSERT INTO chunks_fts(rowid, text_tok) VALUES(?,?)",
                         (cur.lastrowid, _tok(c["text"])))
    conn.commit()
    return conn


def search_bm25(conn, query: str, k: int = 20, region: str | None = None, crop: str | None = None):
    q = " OR ".join(t for t in _tok(query).split() if len(t) > 1)
    rows = conn.execute(
        f"""SELECT c.*, bm25(chunks_fts) AS score FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?""", (q, k * 3)).fetchall()
    out = []
    for r in rows:
        if region and r["region_scope"] not in ("national", region.lower()):
            continue
        if crop and r["crop"] and r["crop"] != crop.lower():
            continue
        out.append(dict(r))
        if len(out) >= k:
            break
    return out
```

- [ ] **Step 4: Test pass + build KB thật**

Run: `.venv/bin/pytest tests/test_build_kb.py -q` → `2 passed`.
Extract PDF quy trình thành markdown: với mỗi PDF quy trình (QĐ 1899 sầu riêng, sổ tay QĐ 145, WASI cà phê), chạy pdfplumber `extract_text` → lưu `data/kb_manual/<doc>.md` giữ heading, thêm front-matter đúng metadata (authority_level=`quy_trinh_cuc`, crop, region_scope=`national` hoặc `đbscl`/`tây nguyên`). Bản tin SVGH/mặn tuần gần nhất: extract tương tự, `authority_level=ban_tin_vung`, `date` = ngày bản tin.
Run: `.venv/bin/python -c "from ingest.build_kb import build_kb, search_bm25; from pathlib import Path; c=build_kb(sorted(Path('data/kb_manual').glob('*.md')), Path('data/kb.db')); print([h['section'] for h in search_bm25(c,'bón phân đợt 1 cho lúa', k=3)])"`
Expected: chunk liên quan bón phân trong sổ tay lúa.

- [ ] **Step 5: Commit**

```bash
git add ingest/build_kb.py data/kb_manual data/kb_sources.json tests/test_build_kb.py ingest/download.py
git commit -m "feat: KB chunks + FTS5 pyvi (BM25) với metadata vùng/cây/thẩm quyền" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 11: Cổng DoD P0 — 20 truy vấn đối chiếu end-to-end

**Files:**
- Create: `scripts/p0_dod_check.py`, `docs/qa/p0-dod.md`

**Interfaces:**
- Consumes: toàn bộ Task 5–10.
- Produces: bằng chứng DoD P0 (spec §9): 20 cặp cây–dịch hại tra ra đúng thuốc/liều đối chiếu nguồn.

- [ ] **Step 1: Viết `scripts/p0_dod_check.py`**

```python
"""DoD P0: chạy 20 truy vấn chuẩn, in thuốc + liều + trích dẫn để đối chiếu tay."""
from app.backend.db import connect, connect_labels, lookup_products, get_dose

QUERIES = [  # 20 cặp lấy từ docs/scope-pests.md — chỉnh theo bản chốt
    ("lúa", "rầy nâu"), ("lúa", "đạo ôn"), ("lúa", "sâu cuốn lá"), ("lúa", "bạc lá"),
    ("lúa", "ốc bươu vàng"), ("lúa", "cỏ lồng vực"), ("lúa", "bọ trĩ"), ("lúa", "sâu đục thân"),
    ("cà phê", "rệp sáp"), ("cà phê", "gỉ sắt"), ("cà phê", "mọt đục cành"), ("cà phê", "tuyến trùng"),
    ("cà phê", "rệp vảy xanh"), ("sầu riêng", "thán thư"), ("sầu riêng", "rầy xanh"),
    ("sầu riêng", "bệnh xì mủ"), ("sầu riêng", "sâu đục trái"), ("sầu riêng", "nhện đỏ"),
    ("lúa", "vàng lùn"), ("cà phê", "khô cành")]

rc, lc = connect(), connect_labels()
n_products = n_doses = 0
for crop, pest in QUERIES:
    hits = lookup_products(rc, crop, pest, "2026-07-17")
    n_products += bool(hits)
    dosed = [(h, get_dose(lc, h.trade_name, crop, pest)) for h in hits]
    dosed = [(h, d) for h, d in dosed if d]
    n_doses += bool(dosed)
    print(f"\n== {crop} / {pest}: {len(hits)} thuốc, {len(dosed)} có liều verified")
    for h, d in dosed[:3]:
        print(f"  {h.trade_name} {h.formulation or ''} ({h.active_ingredient}) — {d.dose_text}, "
              f"PHI {d.phi_days} ngày | {h.cite} | nhãn: {d.source_url}")
print(f"\nTỔNG: {n_products}/20 cặp có thuốc; {n_doses}/20 cặp có liều verified")
```

- [ ] **Step 2: Chạy + đối chiếu + ghi báo cáo**

Run: `.venv/bin/python scripts/p0_dod_check.py | tee /tmp/dod.txt`
Expected: ≥18/20 cặp có thuốc (cặp nào 0 → kiểm tra alias/chuẩn hoá tên dịch hại); ≥14/20 cặp có liều verified. Đối chiếu tay từng dòng in ra với PDF/nguồn nhãn. Ghi `docs/qa/p0-dod.md`: bảng kết quả, cặp thiếu + lý do, kết luận ĐẠT/KHÔNG ĐẠT DoD. KHÔNG ĐẠT → mở lại task tương ứng, không đi tiếp P1.

- [ ] **Step 3: Chạy full test + commit**

Run: `.venv/bin/pytest -q` → toàn bộ xanh.

```bash
git add scripts/p0_dod_check.py docs/qa/p0-dod.md
git commit -m "chore: cổng DoD P0 — 20 truy vấn đối chiếu nguồn" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Sau plan này

P0 xong → viết Plan 2/4 (P1 — pipeline text-first: router, tools, hybrid RAG + Citations, validator chuỗi, abstain/handoff, eval v0 50 câu) dựa trên dữ liệu thật vừa dựng. Interface P1 tiêu thụ từ P0: `lookup_products`, `check_product_status`, `resolve_alias`, `get_dose`, `search_bm25` (chữ ký ở các block Interfaces phía trên).

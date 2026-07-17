# Onboarding — Bạn Nhà Nông (team VNAI)

Chào bạn! Tài liệu này dành cho thành viên mới nhận project qua **file zip** (hoặc
clone từ GitHub khi repo đã public). Làm theo từ trên xuống, ~10 phút là chạy được demo.

## 1. Lấy code + dữ liệu

**Code** kéo từ GitHub; **dữ liệu là PRIVATE** — nhận file zip riêng từ trưởng nhóm,
tuyệt đối không đưa lên GitHub hay chia sẻ ra ngoài (đây là lợi thế cạnh tranh của team):

```bash
git clone <url-github> && cd <tên-repo>
unzip ~/Downloads/ban-nha-nong-DATA-*.zip   # giải nén NGAY TẠI GỐC repo -> tạo thư mục data/
ls data/   # phải thấy: registry.db, kb.db, labels.db, labels/labels_curated.csv, kb_manual/...
```

Zip dữ liệu gồm: `data/registry.db` (danh mục 6.883 sản phẩm thuốc BVTV đã parse từ
Thông tư), `data/kb.db` (412 đoạn tài liệu chính thống + vectors), `data/labels.db` +
`data/labels/labels_curated.csv` (liều đã kiểm chứng kèm nguồn), KB markdown, FAQ.
Git đã ignore sẵn toàn bộ `data/` — bạn không thể lỡ tay commit dữ liệu.

## 2. Cài đặt môi trường

Yêu cầu: Python ≥ 3.11, Linux/macOS (Windows dùng WSL).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 3. Tạo `.env`

```bash
cp .env.example .env
```

Điền theo hướng dẫn trong file. Tối thiểu nên có `GEMINI_API_KEY` (free tier được —
dùng cho phần tư vấn canh tác RAG). Không có key nào vẫn chạy được phần tra thuốc.
**Tuyệt đối không commit `.env`** (đã gitignore sẵn).

## 4. Chạy thử

```bash
.venv/bin/pytest -q                                        # toàn bộ test phải xanh
.venv/bin/uvicorn app.backend.api:app --reload --port 8010 # rồi mở http://localhost:8010
```

Hỏi thử: "Lúa bị rầy nâu thì xịt thuốc gì?" — phải ra phiếu thuốc kèm trích dẫn
Thông tư. Xem thêm câu thử trong [README.md](README.md).

## 5. Quy trình làm việc với git (worktree)

Repo dùng nhánh chính `p0-data-spine` (sẽ merge về `main` khi khoá phase). Mỗi người
làm trên **nhánh riêng**, khuyến nghị dùng `git worktree` để mỗi việc một thư mục,
không phải stash qua lại:

```bash
# Tạo nhánh + thư mục làm việc riêng cho việc của bạn:
git worktree add ../VNAI-lieu-thuoc -b data/lieu-<tên-bạn>
cd ../VNAI-lieu-thuoc
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt  # venv riêng cho worktree

# Làm việc, commit như bình thường trong thư mục đó.
# Xong việc: đẩy nhánh + mở PR (khi có GitHub), hoặc gửi patch:
git format-patch p0-data-spine --stdout > ~/lieu-<tên-bạn>.patch

# Dọn worktree khi xong:
cd ../VNAI && git worktree remove ../VNAI-lieu-thuoc
```

Quy tắc commit:

- `pytest -q` **phải xanh** trước khi commit.
- Message: conventional commit tiếng Việt (`data: ...`, `fix: ...`, `feat: ...`).
- Không commit: `.env`, `data/raw/`, `*.db` (gitignore lo sẵn — đừng dùng `git add -f`).

## 6. Việc đang cần người làm nhất

1. **Bổ sung liều lượng thuốc** — đọc kỹ [docs/huong-dan-bo-sung-lieu.md](docs/huong-dan-bo-sung-lieu.md).
   Đây là dữ liệu an toàn cao nhất: chỉ CHÉP từ nguồn chính thống, double-entry 2 lần
   độc lập, thà bỏ trống còn hơn sai.
2. **Lịch thời vụ các tỉnh** — thêm file markdown vào `data/kb_manual/` theo format
   front-matter sẵn có (xem file `lich-thoi-vu-an-giang-*.md` làm mẫu), nguồn là công
   văn Sở NN&MT tỉnh; xong chạy `python -m ingest.build_kb && python -m ingest.build_kb_dense`.
3. **Test với nông dân/cán bộ khuyến nông thật** — ghi lại câu hỏi thật, câu nào trả
   lời sai/kém thì tạo issue kèm nguyên văn câu hỏi + ảnh chụp.

## 7. Bản đồ repo (đọc khi cần sửa code)

| Thư mục | Vai trò |
|---|---|
| `app/backend/pipeline.py` | Não điều phối: small-talk → slot → product guard → tra danh mục (A) / RAG (B) |
| `app/backend/validators.py` | Chống bịa số: quote check + đối chiếu mọi con số với evidence |
| `app/backend/db.py` | Query danh mục thuốc (`lookup_products`, `check_product_status`, `get_dose`) |
| `ingest/` | Parse thông tư PDF → registry; build KB; validator liều (`build_labels.py`) |
| `eval/` | Bộ 50 câu đo hallucination + runner (`python3 eval/run_eval.py --tag <tên>`) |
| `docs/superpowers/specs/` | Spec thiết kế đầy đủ (đọc trước khi sửa kiến trúc) |
| `.superpowers/sdd/progress.md` | Nhật ký tiến độ chi tiết của quá trình build |

Thắc mắc kiến trúc: đọc spec trước, sau đó hỏi trong nhóm. Chúc vui!

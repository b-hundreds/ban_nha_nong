# Bạn Nhà Nông — trợ lý nông nghiệp tiếng Việt

Trợ lý voice-first cho nông dân, xây quanh một nguyên tắc: **mọi khuyến nghị kỹ thuật
phải truy được về nguồn chính thống — không bịa, đặc biệt là con số liều lượng.**

Tính năng chính (đã chạy):

- **Tra thuốc BVTV theo danh mục pháp lý hiện hành** (Thông tư 75/2025/TT-BNNMT +
  28/2026/TT-BNNMT, versioned theo ngày hiệu lực): hỏi "lúa bị rầy nâu xịt thuốc gì"
  → phiếu thuốc kèm hoạt chất + trích dẫn thông tư; sản phẩm đã có liều kiểm chứng
  trong `labels.db` sẽ hiện **liều + ngày cách ly chép nguyên văn từ nhãn** (số không
  bao giờ do AI sinh ra).
- **Đính chính pháp lý**: hỏi về thuốc bị cấm/bị loại khỏi danh mục → trả lời đúng mốc
  hiệu lực ("Folpan 50WP còn dùng được đến 15/08/2026, sau đó bị loại theo TT 28/2026").
- **Tư vấn canh tác (RAG)**: trả lời từ kho tài liệu chính thống (quy trình của Cục
  Trồng trọt & BVTV, lịch thời vụ An Giang/Đắk Lắk, FAQ khuyến nông Lâm Đồng) kèm
  trích dẫn; số liệu chỉ được nêu khi chép nguyên văn từ nguồn (validator đối chiếu máy).
- **Biết từ chối + chuyển người thật**: không đủ căn cứ → nói rõ phạm vi hỗ trợ + nút
  "Gặp cán bộ khuyến nông" (tạo phiếu trong `data/handoff.db`).
- **Voice**: nhận giọng nói qua Google Cloud STT v2 (Chirp 3, ưu tiên) hoặc OpenAI
  whisper (fallback); không có key vẫn gõ chữ được.
- **Lịch sử hội thoại lưu server-side** (SQLite `data/history.db`), UI chat có sidebar.
- **Bộ eval hallucination** (`eval/`): bộ v0 50 câu + bộ v1 dùng SQLite làm oracle
  và red-team RAG (thuốc/cây/bệnh/liều/PHI/citation/prompt injection...) — không chỉ
  kiểm tra schema mà đối chiếu từng claim có cấu trúc với nguồn thật.

## Cài đặt

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # rồi điền key theo hướng dẫn trong file
```

Key trong `.env` (mức tối thiểu để đủ tính năng):

| Key | Bắt buộc? | Dùng cho |
|---|---|---|
| `GEMINI_API_KEY` | Nên có | Tư vấn canh tác RAG (đường B) + embeddings. Free tier dùng được (model mặc định `gemini-flash-lite-latest`) |
| `GOOGLE_APPLICATION_CREDENTIALS` + `GOOGLE_CLOUD_PROJECT` | Không | Nhận giọng nói Google STT v2 Chirp 3 (khuyến nghị chính thức) |
| `OPENAI_API_KEY` | Không | Fallback nhận giọng nói (whisper-1) |

Không có key nào: vẫn tra thuốc/danh mục được (đường A không dùng LLM), gõ chữ thay mic.

## Dữ liệu

**Dữ liệu là private, không nằm trong repo này** — nhận zip `ban-nha-nong-DATA-*.zip`
từ trưởng nhóm và giải nén vào gốc repo (xem `data/README.md`). Zip kèm sẵn
`data/registry.db` (danh mục 6.883 sản phẩm), `data/kb.db` (412 chunks + vectors),
`data/labels.db` + CSV liều đã kiểm chứng — có zip là chạy được ngay.

Muốn build lại từ đầu (ví dụ khi thông tư mới ban hành):

```bash
.venv/bin/python -m ingest.download        # tải PDF nguồn vào data/raw/
.venv/bin/python -m ingest.build_registry  # parse phụ lục -> data/registry.db (tự nạp aliases)
.venv/bin/python -m ingest.build_kb        # tài liệu kb_manual + FAQ -> data/kb.db
.venv/bin/python -m ingest.build_kb_dense  # embeddings Gemini (cần GEMINI_API_KEY; resume được khi bị rate limit)
.venv/bin/python -m ingest.build_labels    # data/labels/labels_curated.csv -> data/labels.db
```

**Bổ sung dữ liệu liều lượng thuốc** (việc cần nhiều người làm nhất): đọc
[docs/huong-dan-bo-sung-lieu.md](docs/huong-dan-bo-sung-lieu.md).

## Chạy demo

```bash
.venv/bin/uvicorn app.backend.api:app --reload --port 8010
```

Mở <http://localhost:8010>. Câu thử nhanh:

- "Lúa bị rầy nâu thì xịt thuốc gì?" → phiếu thuốc thật + trích dẫn (+ liều nếu SP đã curate)
- "Folpan 50WP còn dùng được không?" → đính chính mốc pháp lý 15/08/2026
- "Cho tôi liều gấp đôi cho nhanh" → từ chối + cảnh báo an toàn
- "Tháng 11 này xuống giống lúa chưa?" (vùng An Giang) → RAG từ lịch thời vụ Sở NN thật
- "Xin chào" → giới thiệu năng lực; "trồng táo" → minh bạch phạm vi hỗ trợ

Sửa `app/web/*` xong nhớ bump `CACHE_NAME` trong `app/web/sw.js` (service worker
cache-first) rồi hard-refresh (Ctrl+Shift+R).

## Test & Eval

```bash
.venv/bin/pytest -q                             # toàn bộ unit/integration tests
.venv/bin/python3 eval/run_eval.py --tag local  # bộ eval 50 câu (đường B tốn ~10-16 call Gemini)
.venv/bin/python eval/run_hallucination.py --tag local          # audit v1 offline, không gọi model thật
.venv/bin/python eval/run_hallucination.py --tag release --strict # gate release, known gap cũng làm fail
```

Quy tắc: **pytest phải xanh trước mọi commit.** Eval exit code 1 nếu có câu high-risk fail.
Chi tiết ma trận và cách thêm case: [docs/hallucination-testing.md](docs/hallucination-testing.md).

## Cấu trúc

- `app/backend/` — FastAPI (`api.py`), input review + xác nhận sai chính tả/phiên âm
  (`input_resolver.py`, `clarifications.py`), LLM tool planner + API/service truy vấn DB
  (`registry_agent.py`, `registry_api.py`, `registry_service.py`), pipeline (`pipeline.py`:
  safety guard → tool DB / path B RAG), RAG (`retrieval.py`, `generate.py`),
  validator chống bịa số (`validators.py`), lịch sử (`history.py`), ASR (`asr.py`),
  query API registry (`db.py`).
- `app/web/` — PWA chat tĩnh (không build step, không CDN).
- `ingest/` — pipeline dữ liệu: tải nguồn, parse phụ lục thông tư, build registry/KB/labels.
- `data/` — DB + CSV curate (`labels/labels_curated.csv` commit vào git, DB thì không).
- `eval/` — bộ câu + runner đo hallucination.
- `docs/` — spec thiết kế (`docs/superpowers/specs/`), plan, hướng dẫn dữ liệu, QA reports.

Thiết kế đầy đủ: `docs/superpowers/specs/2026-07-17-agri-voice-assistant-design.md`.
Onboarding cho thành viên mới: [ONBOARDING.md](ONBOARDING.md).

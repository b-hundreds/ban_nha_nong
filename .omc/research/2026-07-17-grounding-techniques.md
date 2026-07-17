# Research: Menu kỹ thuật grounding nghiêm ngặt (SOTA 2024–2026)

> Nguồn: agent grounding-research, 17/07/2026. Phục vụ design doc trợ lý nông nghiệp voice-first VNAI.

## 1. Truy xuất có cấu trúc vs vector RAG cho bảng danh mục

Kết luận: dữ liệu bảng quy chuẩn (hoạt chất → cây trồng → dịch hại → liều) **không nên nhét vào vector store**. Chunk hoá bảng phá vỡ ràng buộc hàng–cột, retriever dễ ghép liều của thuốc A sang thuốc B — đúng kiểu lỗi nguy hiểm nhất của domain này.

- **Function calling / parameterized lookup (khuyên dùng)**: nạp danh mục vào SQLite/Postgres, expose 2–3 tool schema cứng kiểu `lookup_products(crop, pest)`, `get_dose(product_id)`. LLM chỉ chọn tham số, không viết SQL. Độ phức tạp: **thấp**, rất hợp hackathon.
- **Text-to-SQL tự do**: thêm một tầng có thể sai; chỉ cần nếu có câu hỏi tổng hợp phức tạp (LlamaIndex router SQL+semantic: https://www.llamaindex.ai/blog/combining-text-to-sql-with-semantic-search-for-retrieval-augmented-generation-c60af30ec3b). **Vừa**.
- **TableRAG** (NeurIPS 2024, https://arxiv.org/abs/2410.04739): overkill khi danh mục ~vài chục nghìn dòng vừa RAM.
- **Alias/fuzzy matching tên** (bắt buộc, thấp): bảng alias tên thương mại + tên địa phương sâu bệnh, match bằng rapidfuzz/trigram trước khi lookup.

## 2. Hybrid retrieval tiếng Việt (tài liệu phi cấu trúc)

Hybrid **BM25 + dense + cross-encoder rerank** là default; BM25 tiếng Việt cần tách từ (pyvi/underthesea) hoặc ICU tokenizer.

- **Benchmark**: VN-MTEB (https://arxiv.org/abs/2507.21500, EACL Findings 2026: https://aclanthology.org/2026.findings-eacl.86/) — 41 dataset tiếng Việt; model LLM-based instruct vượt nhóm bge-m3/multilingual-e5-large.
- **Embedding**: API — **gemini-embedding-001** (đứng đầu MTEB Multilingual, hỗ trợ vi: https://developers.googleblog.com/gemini-embedding-available-gemini-api/); OpenAI text-embedding-3-large kém hơn trên đa ngữ. Self-host — **BAAI/bge-m3** (https://huggingface.co/BAAI/bge-m3, dense+sparse+ColBERT). Thuần Việt nhẹ: bkai-foundation-models/vietnamese-bi-encoder, VoVanPhuc/sup-SimCSE-VietNamese-phobert-base.
- **Reranker**: BAAI/bge-reranker-v2-m3 (https://huggingface.co/BAAI/bge-reranker-v2-m3); chuyên Việt **ViRanker** (https://arxiv.org/abs/2509.09131) báo cáo vượt bge-reranker-v2-m3 trên MMARCO-VI (checkpoint: chưa xác minh).

## 3. Citation enforcement

- **Structured output JSON schema**: mỗi khuyến nghị = `{claim, source_id, quote}`; ép bằng structured outputs (OpenAI/Gemini) hoặc tool-use (Claude). Thấp.
- **Quote verification hậu kiểm**: chuẩn hoá unicode → exact match quote vào evidence, fallback fuzzy (rapidfuzz partial_ratio ≥ ~90); fail → regenerate hoặc abstain. Thấp (~50 dòng).
- **Anthropic Citations API** (https://www.anthropic.com/news/introducing-citations-api): quote được re-inject từ chunk gốc, không thể bịa. Thấp nhất nếu dùng Claude.
- Quy tắc "extractive cho phần định lượng": mọi con số phải trích nguyên văn từ nguồn (mục 5).

## 4. Faithfulness verification sau sinh

- **LLM-as-judge kiểu FACTS Grounding** (https://deepmind.google/blog/facts-grounding-a-new-benchmark-for-evaluating-the-factuality-of-large-language-models/ + https://www.kaggle.com/benchmarks/google/facts-grounding): tách claim, judge từng claim theo context; model đa ngữ (Gemini Flash/Claude Haiku) → **chạy tốt tiếng Việt**; +1 call ~0.5–2s. **Khuyên dùng làm verifier runtime.** Thấp.
- **RAGAS faithfulness** (https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/): hợp **eval offline**. Thấp.
- **MiniCheck** (https://github.com/Liyan06/MiniCheck, https://arxiv.org/abs/2404.10774): 770M ngang GPT-4, rẻ ~400×; train tiếng Anh — tiếng Việt **chưa xác minh**. Vừa.
- **HHEM-2.1-Open** chỉ tiếng Anh → loại. **Lynx-70B** quá nặng. **AlignScore** tiếng Anh.
- Lớp rẻ tiếng Việt: NLI đa ngữ XNLI (mDeBERTa-v3/XLM-R) — gần miễn phí, kém LLM-judge với claim dài.

## 5. Numeric fidelity

- **Số không do LLM sinh — mạnh nhất**: phần định lượng render bằng template từ DB row (`{dose} {unit} / {water_volume}, cách ly {phi} ngày`), LLM chỉ sinh diễn giải. Hallucination số = 0 theo thiết kế. Pattern chuẩn hệ compliance.
- **Post-hoc number matching**: trích mọi cặp (số, đơn vị) trong answer (dấu thập phân kiểu Việt "0,5"; ml/lít, kg/ha, ngày), đối chiếu tập số cho phép từ evidence; số lạ → block/regenerate. Thấp (~100 dòng). Tham khảo: https://www.sciencedirect.com/science/article/pii/S0957417426018786, https://arxiv.org/pdf/2512.16189.
- **Constrained decoding** (Outlines https://github.com/dottxt-ai/outlines; vLLM structured outputs): đảm bảo format/enum (tên thuốc chỉ từ danh mục), không đảm bảo số đúng nguồn — bổ trợ. Vừa.

## 6. Abstention / selective answering

- **Gating theo evidence (mạnh, rẻ nhất)**: DB không có row khớp → từ chối + chuyển cán bộ khuyến nông; không để LLM "suy ra" liều cho tổ hợp chưa đăng ký. Thấp.
- **Risk classifier đầu vào**: phân loại high-stakes vs thường → route pipeline nghiêm ngặt vs thường. Thấp.
- **Verifier-as-gate**: judge fail → abstain.
- **Đo**: risk–coverage curve, AURC (survey "Know Your Limits", TACL 2024: https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00754/131566/). False-refusal trên tập low-stakes target < ~10–15%.
- Verbalized confidence calibration kém — ưu tiên gating theo evidence.

## 7. Guardrails framework

- **Tự viết validator pipeline — khuyên dùng**: quote-check → number-check → judge → abstain-router, vài trăm dòng Python. Thấp.
- **NeMo Guardrails** (https://github.com/NVIDIA-NeMo/Guardrails): overkill cho 2–4 tuần.
- **Guardrails AI** (https://www.guardrailsai.com/blog/nemoguardrails-integration): +50–200ms/validator; dùng nếu muốn khung sẵn.
- **LlamaFirewall** (https://arxiv.org/abs/2505.03574): trọng tâm security, không phải groundedness. Bỏ.

## 8. Voice-specific

- **LLM query rewriting trước retrieval**: chuẩn hoá transcript ASR — thêm dấu, sửa tên thuốc/sâu bệnh bằng glossary-in-prompt (retrieval-augmented ASR correction: https://arxiv.org/abs/2409.06062), resolve đại từ đa lượt thành standalone query (Amazon conversational QA: https://assets.amazon.science/8c/e8/8384303b4f28a424d47fd9d4dc95/learning-when-to-retrieve-what-to-rewrite-and-how-to-respond-in-conversational-qa.pdf). Thấp.
- **Phonetic entity resolution**: fuzzy/phiên âm vào bảng alias; giới hạn LLM "chỉ sửa theo glossary" tránh over-correct.
- **Slot state đa lượt**: giữ `{crop, pest, product}` cập nhật mỗi lượt. Thấp.
- **Voice UX cho số**: đọc chậm liều + đơn vị, yêu cầu xác nhận trước khuyến nghị high-stakes. Thấp.

## STACK TỐI THIỂU ĐỀ XUẤT (2–4 tuần)

1. **Liều lượng = SQLite + tool-use lookup** (không text-to-SQL, không vector): `lookup_products(crop, pest)` + alias fuzzy. Không có row khớp → **abstain + handoff** (rule cứng số 1).
2. **Tài liệu phi cấu trúc = hybrid**: BM25 (pyvi) + bge-m3 (hoặc gemini-embedding-001), top-20 → bge-reranker-v2-m3 → top-5.
3. **Sinh**: LLM đa ngữ mạnh (Claude/Gemini) với JSON schema `{explanation, recommendations[{product_id, quote, source_id}]}`; **mọi con số render bằng template từ DB row**.
4. **Verify 3 lớp rẻ → đắt**: (a) quote match; (b) number matcher; (c) LLM-judge FACTS (chỉ câu high-stakes). Fail lớp nào → abstain template.
5. **Đo**: eval ~100–200 câu (nửa high-stakes), hallucination rate + risk-coverage/AURC; RAGAS offline.
6. **Voice**: ASR → 1 call rewrite (glossary, slot đa lượt) → pipeline trên → TTS xác nhận số.

Sai số liều bị loại theo kiến trúc (số đi thẳng từ DB); rủi ro còn lại ở phần diễn giải — có judge + abstention chặn. Phần tự viết ~500–800 dòng, khả thi hackathon.

**Chưa xác minh**: MiniCheck tiếng Việt; checkpoint ViRanker; latency NeMo/Guardrails AI (nguồn bên thứ ba: https://generalanalysis.com/guides/best-ai-guardrails, https://is4.ai/blog/our-blog-1/guardrails-ai-vs-nemo-guardrails-comparison-2026-352).

# Research: Hệ thống tương tự & Blueprint bộ eval hallucination

> Nguồn: agent eval-research, 17/07/2026. Phục vụ design doc trợ lý nông nghiệp voice-first VNAI.

## PHẦN A — Trợ lý AI nông nghiệp đã có & bài học

| Hệ thống | Kiến trúc & grounding | Số liệu eval công bố | Bài học |
|---|---|---|---|
| **Farmer.Chat** (Digital Green + Gooey.AI, Ấn Độ/Phi) | RAG nhiều bước: hiểu ý định → rephrase/decompose → retrieve+rerank → generate. GPT-4 rerank, GPT-3.5 sinh. KB "expert-vetted", tài liệu do Bộ NN Ấn Độ thẩm định | Query response rate ~75%; readability FK 60-80; dùng **GPT-4 làm judge** phân loại câu; Bloom's taxonomy. **KHÔNG công bố hallucination/faithfulness** | Trust tăng khi biết nguồn từ Bộ NN. Hệ thống lớn nhất ngành **chưa công bố số hallucination câu hệ quả cao** → whitespace để mình vượt |
| **KissanAI/Dhenu** (Ấn Độ) | Dhenu 1.0 LLM song ngữ; Dhenu-vision fine-tune Qwen-VL | Vision: **36,13% acc/500 ảnh** (*nguồn thứ cấp*) | Fine-tune không đủ; câu hệ quả cao cần retrieval + abstention chứ không tin model |
| **PlantVillage Nuru** (Penn State+FAO+CGIAR) | CNN detection offline, đa ngữ | **74-88% nhận triệu chứng** (6 lá), ngang chuyên gia, gấp 1,5x cán bộ khuyến nông | Gold standard = **so với chuyên gia trên field**; gộp nhiều ảnh tăng acc |
| **CGIAR AgriLLM/GAIA-IFPRI** | Grounded trong tri thức CGIAR; 500 Q&A/center; prototype COP30 | Bài "Beyond the model": eval vượt accuracy → **usability, đa ngôn ngữ, trust, equity** | Eval đa chiều, không chỉ accuracy |
| **AgroAskAI** (arXiv 2512.14910, 12/2025) | Framework **đa-agent** toàn cầu | *Không trích xuất được số — chưa xác minh* | Tham khảo kiến trúc multi-agent mới |
| **VN: mobiAgri** (MobiFone) | AI cây trồng (1000+ cây, 500+ dịch hại) + tra cứu + chuyên gia | **Không công bố eval** | App VN mạnh chẩn đoán ảnh + chuyển chuyên gia |
| **VN: Đom Đóm AI** | Trợ lý ảo tiếng Việt: sâu bệnh, giá, thời tiết | **Không công bố eval** | Có đối thủ nội địa nhưng chưa nghiêm về grounding → eval + trích dẫn pháp lý là điểm khác biệt |

**Bài học xuyên suốt:** (1) Tất cả dùng RAG + KB do cơ quan chức năng thẩm định; trust = trích dẫn nguồn có thẩm quyền. (2) **Gần như không ai công bố hallucination rate cấp claim trên câu hệ quả cao** — whitespace + điểm ăn với BGK. (3) Chuẩn vàng = so với chuyên gia. (4) Lĩnh vực hệ quả cao (Med-HALT): **abstention > trả lời sai tự tin**.

## PHẦN B — Blueprint bộ eval

### 1. Taxonomy & phân bố (đề xuất 200 câu — Wilson 95% CI ±3,5-7pp; 100 tối thiểu)
- **Trả lời được (có gold) 120 câu (60%):** liều/cách pha 30, PHI cách ly 25, an toàn người phun/PPE 20, chọn đúng thuốc 25, tank-mix 20.
- **Bẫy đối kháng (đúng = từ chối/đính chính) 80 câu (40%):** thuốc cấm/đã loại khỏi danh mục 20, tiền đề sai (sâu bệnh không có trên cây đó) 15, yêu cầu nguy hiểm "liều gấp đôi" 15, đúng thuốc sai cây/off-label 20, ngoài phạm vi 10.
- **Đối chứng dễ ~20 câu:** đo **false-refusal**.
- **Bẫy vàng có sẵn:** diff **Thông tư 25/2024/TT-BNNPTNT** (hiệu lực 30/01/2025; 1.918 hoạt chất/4.844 thương phẩm; danh mục cấm 23+6+1+1) ↔ **Thông tư 75/2025/TT-BNNMT** (mới hơn, sau sáp nhập thành Bộ NN&MT) → hoạt chất bị loại giữa 2 văn bản = bẫy "thuốc đã loại nhưng hỏi như còn dùng", có căn cứ pháp lý.

### 2. Gold answers & annotate
Nguồn = TT 25/2024 & 75/2025 (được phép + cấm), **nhãn thuốc đã đăng ký** (liều, PHI), quy trình canh tác/VietGAP, tài liệu Cục BVTV. Mỗi câu = gold + trích dẫn (điều/phụ lục/nhãn) + **"must-not-say" list** + nhãn hành vi (trả lời/đính chính/từ chối). 2 kỹ sư NN annotate + 1 phân xử, đo **Cohen's kappa**. Phân rã gold thành **atomic claims** (FActScore).

### 3. Metrics
**Chính:**
- **Safety-critical hallucination rate** = % câu chứa ≥1 claim làm theo sẽ gây hại (sai liều vượt nhãn, thuốc cấm, PHI quá ngắn) → **headline metric**.
- **Hallucination cấp claim** (FActScore): % atomic claim không được nguồn hỗ trợ; phân biệt unsupported vs contradicted; báo cả answer-level.
- **Groundedness/faithfulness** (RAGAS), **citation precision/recall**, **retrieval recall@k/hit@k/context precision**.

**Phụ:** risk-coverage + AURC (abstention), false-refusal rate, trap-handling rate, WER ASR tổng + theo phương ngữ + **entity-WER trên slot then chốt** (tên thuốc, hoạt chất, con số liều).

### 4. Judge protocol
**Reference-based LLM-judge** (đưa gold + must-not-say), rubric riêng từng metric. **Jury 3 model khác họ** (Claude+Gemini+GPT) — theo FACTS Grounding, triệt self-preference; judge khác họ với model test. Giảm bias: randomize thứ tự, pointwise, chấm theo rubric, tách model sinh/chấm. **Human verify:** soát toàn bộ safety-critical fail + 20% random; báo kappa + Wilson CI; chỉ công bố khi kappa >0,6-0,7. Báo **Wilson 95% CI + bootstrap CI** mọi số headline.

### 5. Tooling
**promptfoo** (chính — YAML, bộ bẫy đối kháng, red-team, CI, assertion LLM-judge) + **RAGAS** (faithfulness/context precision-recall). Đều open-source, chi phí 0.

### 6. Mượn từ benchmark
FActScore (atomic claim), FACTS Grounding (judge 2 pha + jury 3), HaluEval (nhiễu loạn câu đúng → sinh bẫy), RGB (negative rejection/counterfactual), Med-HALT (False Confidence Test).

### 7. Trình bày BGK
Headline "Safety-Critical Hallucination Rate" + 95% CI + đường risk-coverage; **so cột grounded vs LLM thô** trên cùng 200 câu; gallery 3-4 bẫy side-by-side; phân rã theo category; số agreement human-judge.

## Nguồn
- Farmer.Chat: https://arxiv.org/html/2409.08916v1
- Dhenu: https://analyticsindiamag.com/kissanai-unveils-dhenu-1-0-llm-for-indias-agricultural-challenges/
- Nuru: https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2020.590889/full
- CGIAR: https://www.cgiar.org/news-events/news/agrillm-how-cgiar-is-developing-an-ai-powered-agricultural-advisory-service-for-global-south + https://www.ifpri.org/blog/beyond-the-model-evaluating-ai-agricultural-advisory-systems-so-they-work-in-the-field/
- AgroAskAI: https://arxiv.org/pdf/2512.14910
- mobiAgri: https://solutions.mobifone.vn/vi/nen-tang-nong-nghiep-mobiagri
- Đom Đóm: https://vnexpress.net/tro-ly-ao-dom-dom-ai-ho-tro-nong-dan-viet-4912155.html
- TT 25/2024: https://ppd.gov.vn/van-ban-chinh-sach/thong-tu-so-252024tt-bnnptnt-cua-bo-nong-nghiep-va-phat-trien-nong-thon-ban-hanh-danh-muc-thuoc-bao-ve-thuc-vat-duoc-phep-su-dung-tai-viet-nam-va-danh-muc-thuoc-bao-ve-thuc-vat.html
- TT 75/2025: https://ppd.gov.vn/tin-moi-nhat-289/thong-tu-so-752025tt-bnnmt-ban-hanh-danh-muc-thuoc-bao-ve-thuc-vat-duoc-phep-su-dung-tai-viet-nam-va-danh-muc-thuoc-bao-ve-thuc-vat-cam-su-dung-tai-viet-nam.html
- FACTS Grounding: https://arxiv.org/abs/2501.03200 | FActScore: https://arxiv.org/html/2305.14251 | Med-HALT: https://arxiv.org/abs/2307.15343 | Abstention survey: https://arxiv.org/html/2407.18418v3 | LLM-judge bias: https://arxiv.org/pdf/2604.23178 | Tooling: https://helpmetest.com/blog/llm-evaluation-frameworks/ | Sample size: https://cameronrwolfe.substack.com/p/stats-llm-evals

**Chưa xác minh:** số AgroAskAI; 36,13% Dhenu-vision (nguồn thứ cấp); Farmer.Chat không công bố hallucination rate; mobiAgri/Đom Đóm không công bố eval.

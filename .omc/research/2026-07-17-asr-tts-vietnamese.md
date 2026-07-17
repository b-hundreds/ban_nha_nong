# Research: API ASR/TTS tiếng Việt cho trợ lý nông nghiệp voice-first (07/2026)

> Nguồn: agent asr-research, 17/07/2026. Phục vụ design doc trợ lý nông nghiệp voice-first VNAI.

**TL;DR:** Không tồn tại benchmark công khai nào đo API thương mại theo phương ngữ Nam Bộ/Tây Nguyên — mọi lựa chọn phải qua bake-off nội bộ (dùng ViMD + audio tự thu). Shortlist: **Google Chirp 3** (primary), **Deepgram Nova-3** (challenger, mới hỗ trợ vi 2026), **ElevenLabs Scribe hoặc Viettel AI** (phương án 3). Zalo AI coi như không còn API công khai. PhoWhisper chỉ là checkpoint open-source. TTS giọng miền Nam xác minh rõ nhất: FPT.AI (lannhi/linhsan).

## 1. Bảng so sánh ASR tiếng Việt

| Provider | vi-VN & chất lượng | Phương ngữ Nam/Trung–Tây Nguyên | Streaming | Custom vocab | Giá | API |
|---|---|---|---|---|---|---|
| [Google Chirp 3 (STT v2)](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3) | GA | Không công bố theo miền | Streaming + sync + batch | **Speech adaptation/biasing GA** | [$0.016/phút, giảm theo volume; 60 phút free/tháng; làm tròn 15s](https://cloud.google.com/speech-to-text/pricing) | REST/gRPC; region us/eu (chirp_2 batch có asia-southeast1) |
| [Deepgram Nova-3](https://deepgram.com/learn/deepgram-expands-nova-3-with-11-new-languages-across-europe-and-asia) | Mới thêm vi (2026); blog nêu xử lý 6 thanh điệu, "strong regional variation" | Tuyên bố hãng, chưa có review độc lập | Streaming + batch | **Keyterm prompting cho vi** (+$0.0013/phút) | [~$0.0048–0.0092/phút PAYG](https://deepgram.com/pricing) | REST/WebSocket |
| [ElevenLabs Scribe](https://elevenlabs.io/speech-to-text/vietnamese) | Tự công bố WER vi 3.5% FLEURS (đọc sạch) | Không công bố | [Scribe v2 Realtime ~150ms](https://elevenlabs.io/realtime-speech-to-text) | Keyterm prompting (+$0.05/giờ) | [$0.22/giờ batch, $0.39/giờ realtime](https://elevenlabs.io/pricing/api) | REST/WS |
| [Azure AI Speech](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support) | vi-VN: realtime + fast + batch | Không công bố | Có | [Phrase list ≤500 cụm](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/improve-accuracy-phrase-list) + Custom Speech plain-text | [$1/giờ realtime; batch $0.18–0.36/giờ](https://azure.microsoft.com/en-us/pricing/details/speech/) | SDK trưởng thành |
| [OpenAI whisper-1 / gpt-4o-transcribe](https://developers.openai.com/api/docs/models/gpt-4o-transcribe) | Có; WER vi không công bố | Không công bố | gpt-4o-transcribe stream qua Realtime API | Chỉ prompt biasing (~224 token) | $0.006/phút; mini $0.003/phút | REST/WS |
| [Gemini (audio vào LLM)](https://ai.google.dev/gemini-api/docs/pricing) | Có; không phải ASR chuyên dụng | Không công bố | Live API | **Prompt tự do** — nhét danh mục thuốc/giống | 2.5 Flash ≈ $0.0019/phút audio-in + output | REST/SDK |
| [AssemblyAI](https://www.assemblyai.com/pricing) | vi batch (Universal) | Không công bố | **Chưa có vi streaming** | Chưa xác minh | $0.15/giờ batch | REST |
| [Speechmatics](https://docs.speechmatics.com/speech-to-text/languages) | vi Standard+Enhanced; [trang vi nêu realtime](https://www.speechmatics.com/speech-to-text/vietnamese) | Marketing, không số liệu | Có | Custom dictionary (phạm vi vi chưa xác minh) | [Từ $0.129/giờ; free 50 giờ/tháng](https://www.speechmatics.com/pricing) | REST/WS |
| [FPT.AI Speech](https://docs.fpt.ai/docs/en/speech/api/speech-to-text/) | Chuyên tiếng Việt | Không công bố | REST upload; streaming **chưa xác minh** | Không thấy trong docs | [~700đ/phút; free 60 phút/năm](https://docs.fpt.ai/docs/vi/speech/documentation/stt-pricing/) | REST |
| [Viettel AI](https://viettelai.vn/en/speech-to-text) | Hãng tuyên bố ~96%, **giọng 3 miền + tiếng lóng** | Tuyên bố rõ nhất nhóm nội địa | Chi tiết chưa xác minh | Chưa xác minh | Liên hệ; free 60 phút | REST |
| [VNPT SmartVoice](https://smartvoice.vnpt.vn/vi/price) | Có; [live-stream + file ≤2h](https://smartvoice.vnpt.vn/vi/experience/speech-to-text) | Chưa xác minh | Live stream | Chưa xác minh | ~700đ/phút; free 30 phút/tháng | REST |
| Zalo AI | Không còn docs/giá công khai → **coi như không khả dụng** | — | — | — | — | — |
| [VinAI PhoWhisper](https://github.com/VinAIResearch/PhoWhisper) | **Checkpoint open-source (BSD-3), không có API**; large 8.14% WER CMV-vi; train 844h đa giọng miền | Có chủ đích đa phương ngữ | Tự host | Tự xử lý | Free model, tốn GPU | HF transformers |

## 2. Shortlist đề xuất (phương ngữ > custom vocab > streaming > giá)

1. **Google Chirp 3 — primary.** Duy nhất hội đủ: vi GA streaming + batch, speech adaptation GA (bơm tên thuốc BVTV, OM5451, ST25 làm phrase hints), SDK trưởng thành. Rủi ro: region us/eu (độ trễ), [làm tròn 15s làm câu ngắn đắt lên](https://brasstranscripts.com/blog/google-cloud-speech-to-text-pricing-2025-gcp-integration-costs), chất lượng giọng miền Tây/Tây Nguyên chưa ai đo công khai.
2. **Deepgram Nova-3 — challenger.** Vi mới (2026) + keyterm prompting; streaming; rẻ (~1/3 Google); bên quốc tế duy nhất viết riêng về thanh điệu/vùng miền tiếng Việt. Rủi ro: quá mới.
3. **ElevenLabs Scribe** (WER + realtime 150ms + keyterm) **hoặc Viettel AI** (đối chứng nội địa, tuyên bố 3 miền, data ở VN). Đưa cả hai vào bake-off, giữ một.

**Bắt buộc bake-off trước khi chốt:** ~2–4 giờ audio gồm (a) subset ViMD miền Nam + Tây Nguyên, (b) 100–200 câu tự thu ngoài đồng (ồn quạt/gió/máy nổ) chứa thuật ngữ (Filia, Chess, OM5451, ST25, đạm/lân/kali). Đo WER + keyword-recall theo miền. Bằng chứng chênh lệch phương ngữ là thật ([VN ASR Revisit, 03/2026](https://arxiv.org/abs/2603.14779)): N-WER Bắc 16.32% / Nam 17.22% / **Trung 22.46%**. Phương án phụ: gpt-4o-transcribe (rẻ, prompt biasing), Gemini Flash (audio thẳng vào LLM — rủi ro hallucination, cần eval riêng).

## 3. Dataset đánh giá có nhãn vùng miền

- **[ViMD](https://huggingface.co/datasets/nguyendv02/ViMD_Dataset)** — 102.56h, ~19k câu, **63 tỉnh, field region/province/speaker/gender**; công khai trên HF; license **CC BY-NC-ND 4.0** (eval nội bộ ổn). [Paper EMNLP 2024](https://aclanthology.org/2024.emnlp-main.426/). → Nguồn eval phương ngữ tốt nhất.
- **[Bud500](https://huggingface.co/datasets/linhtran92/viet_bud500)** — ~500h (VietAI), phủ 3 miền nhưng **không có nhãn miền từng mẫu**; CC BY-NC-SA.
- **[VIVOS](https://huggingface.co/datasets/AILAB-VNUHCM/vivos)** — 15h studio; không nhãn miền, không ồn thực địa.
- **Common Voice vi** — ~17h validated (CC0), metadata accent thưa ([khảo sát](https://arxiv.org/html/2603.01894v1)).
- **VLSP ASR 2020/2021** — ~100–250h, giới hạn đơn vị đăng ký VLSP.
- **[LSVSC](https://www.mdpi.com/2079-9292/13/5/977)** — 100.5h, có phân tích phương ngữ; cách tải công khai chưa xác minh.

## 4. TTS tiếng Việt — giọng miền Nam

| Provider | Giọng Nam Bộ | Giá | Ghi chú |
|---|---|---|---|
| [FPT.AI](https://docs.fpt.ai/docs/en/speech/api/text-to-speech/) | **Có, xác minh: lannhi, linhsan (nữ Nam)**; banmai/thuminh/leminh (Bắc), myan/giahuy (Trung) | [Free 100k ký tự; 500k–5tr VND/tháng](https://docs.fpt.ai/docs/vi/speech/documentation/tts-pricing/) | An toàn nhất cho giọng Nam qua API |
| Viettel AI | Đa giọng 3 miền — danh sách chưa xác minh ([TTS](https://viettelai.vn/en/chuyen-giong-noi)) | Liên hệ | |
| [VNPT SmartVoice](https://smartvoice.vnpt.vn/vi/price) | "Giọng vùng miền" | Free 30k ký tự/tháng; 190k VND/500k ký tự | |
| [Google Cloud TTS](https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types) | Không có giọng Nam chính thức; có [Chirp 3 HD](https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd) | Theo ký tự | Chuẩn Bắc |
| [Azure](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support) | HoaiMy, [NamMinh](https://json2video.com/ai-voices/azure/voices/vi-vn-namminhneural/); giọng Nam không công bố | [~$16/1M ký tự (nguồn thứ ba)](https://texttolab.com/blog/azure-text-to-speech-pricing) | |
| [ElevenLabs](https://elevenlabs.io/blog/introducing-vietnamese-norwegian-and-hungarian) | vi trong Flash v2.5 & v3; **clone giọng Nam được (cần consent)** | Subscription credits | Cần test phát âm vi |
| OpenAI TTS | vi không tối ưu, accent không đảm bảo | ~$0.015/phút (chưa xác minh) | Không khuyến nghị chính |

**Đề xuất TTS:** FPT.AI lannhi/linhsan mặc định; ElevenLabs phương án chất lượng cao.

**Caveat:** giá lấy từ trang chính thức ngày 17/07/2026, có thể đổi; các mục "chưa xác minh" đã ghi tại chỗ.

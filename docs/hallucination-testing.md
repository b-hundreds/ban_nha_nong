# Kiểm thử hallucination / grounding

Bộ v1 kiểm tra luồng hiện tại theo hai lớp độc lập, hoàn toàn offline:

1. **DB oracle cho đường A**: lấy `registry.db` và `labels.db` làm đáp án chuẩn, rồi
   đối chiếu từng crop/pest, tên + quy cách sản phẩm, hoạt chất, trạng thái pháp lý,
   nguồn Thông tư, URL, liều và PHI. Vì vậy một response có đủ `dose_block` và
   `citation` nhưng chứa sản phẩm sai vẫn fail.
2. **RAG red-team cho đường B**: giả lập model cố tình trả JSON độc hại để thử quote
   giả, URL giả, section giả, số bịa, số lấy từ chunk không cite, JSON hỏng, không
   evidence, và claim định tính không được nguồn hỗ trợ. Citation phải khớp chính
   xác tài liệu–mục, URL được lấy lại từ chunk canonical; mỗi câu được đối chiếu
   riêng với một quote về token nội dung, hành động, phủ định và mức độ chắc chắn.
   Không gọi Gemini thật.

## Lớp duyệt đầu vào đang được kiểm thử

Trước khi pipeline tra thuốc, `input_resolver.py` tạo một allow-list nhỏ từ
`registry.db`, alias phiên âm đã duyệt và fuzzy match crop/pest. Nếu có
`GEMINI_API_KEY`, model nhẹ chỉ được chọn `candidate_id` trong allow-list này;
model không được tạo tên thuốc/cây/dịch hại mới. Lỗi model, timeout, JSON sai hoặc
ID ngoài allow-list đều rơi về kết quả deterministic.

Mọi match không chính xác đều chỉ tạo câu hỏi xác nhận, chưa trả thuốc và chưa có
`dose_block`. Pending confirmation được lưu theo `session_id` trong 15 phút:

- Người dùng trả lời `đúng`/`phải` → câu hỏi được canonicalize rồi mới chạy lại
  product guard và DB oracle.
- Người dùng trả lời `không` → bỏ candidate, yêu cầu đọc/gõ lại hoặc gửi ảnh nhãn.
- Triệu chứng chưa rõ như `HẠT LÉP` → dù xác nhận đúng cây vẫn phải mô tả thêm,
  không tự gán bệnh để chọn thuốc.
- Tên có dạng sản phẩm nhưng không có trong danh mục → fail closed, không lấy một
  thuốc khác thay thế.

Sau xác nhận, audit chạy thêm lượt `đúng` và bắt buộc response chỉ chứa đúng một
sản phẩm/quy cách đã xác nhận. Việc sản phẩm đó chỉ tình cờ xuất hiện trong top-5
không còn được tính là pass. Luồng DB chi tiết được mô tả tại
[`registry-tool-architecture.md`](registry-tool-architecture.md).

Cấu hình runtime trong `.env`:

```dotenv
INPUT_REVIEW_MODE=auto
GEMINI_INPUT_REVIEW_MODEL=
```

`auto` dùng Gemini khi có key. Đặt `INPUT_REVIEW_MODE=off` để chỉ chạy resolver
deterministic. Runner hallucination luôn ép `off`, vì gate release phải tái lập
được và không phụ thuộc mạng/model.

## Chạy

Từ thư mục gốc repo:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_hallucination_audit.py -q
.\.venv\Scripts\python.exe eval\run_hallucination.py --tag local
```

Gate release nghiêm ngặt (mọi lỗ hổng đã biết cũng làm exit code = 1):

```powershell
.\.venv\Scripts\python.exe eval\run_hallucination.py --tag release --strict
```

Trên Linux/macOS đổi phần gọi Python thành `.venv/bin/python`.

Kết quả chi tiết được ghi vào
`eval/results/hallucination-v1-<tag>.json`. Chế độ mặc định chỉ trả exit code 1
khi có regression mới hoặc lỗi DB/oracle; các case có `known_gap` vẫn hiện là fail
trong báo cáo nhưng không làm CI đỏ. `--strict` biến toàn bộ fail thành release
blocker.

## Đọc báo cáo

Phần bảng đầu chỉ là tổng quan theo nhóm:

- `pass`: hệ thống xử lý đúng theo oracle.
- `fail`: số case đang trả lời sai hoặc chưa đáp ứng đầy đủ câu hỏi.
- `known_gap`: số case fail đã được ghi nhận từ trước. Đây **không phải pass**;
  chế độ `--strict` vẫn trả exit code 1 để chặn release.
- `Unexpected regressions`: lỗi mới, chưa có `known_gap`.

Ngay sau bảng, report in mục **CHI TIẾT CÁC TRƯỜNG HỢP HỆ THỐNG TRẢ LỜI
SAI / CHƯA ĐỦ**. Mỗi case gồm:

- `Tình huống`: câu hỏi thật của người dùng hoặc payload red-team.
- `Kỳ vọng`: hành vi an toàn cần có.
- `Thực tế`: nội dung mà pipeline hiện trả về.
- `Sai ở đâu`: assertion cụ thể bị vi phạm.
- `Ảnh hưởng`: rủi ro đối với người dùng (đối với red-team).
- `Nguyên nhân đã biết`: lý do case đang mang nhãn `known_gap`.

File JSON còn lưu `actual_response`, `expected`, `adversarial_payloads` và toàn bộ
failure reason để có thể lọc hoặc đưa vào dashboard sau này.

## Ma trận hiện có

- Sản phẩm được phép và cặp cây–dịch hại có đăng ký.
- Cặp sai cây/sai dịch hại, hoạt chất cấm, thuốc đang chuyển tiếp hoặc đã bị loại.
- Yêu cầu tăng/gấp đôi liều, alias mơ hồ và prompt injection.
- Câu hỏi công ty đăng ký và tên sản phẩm không tồn tại (kiểm tra semantic
  completeness, không chỉ schema).
- Tên thuốc bị đọc/viết sai: phiên âm tiếng Việt (`a mít chưa`, `mô ven tô`),
  typo, ASR thay âm, tên bị tách từ và formulation đọc thành chữ (`ét xê`,
  `ô đê`). Tiêu chí: nhận đúng canonical hoặc hỏi xác nhận; không được âm thầm
  hiểu một âm tiết thành cây trồng khác.
- Tên cây/dịch hại nhập sai trên điện thoại: Telex dở dang (`sầu riEENG`),
  thiếu/sai dấu, lặp hoặc kéo dài ký tự, typo gần phím, câu không dấu và viết hoa
  hỗn hợp. Với triệu chứng mơ hồ như `HẠT LÉP`, hệ thống phải hỏi lại thay vì tự
  gán thành một bệnh rồi đưa thuốc.
- Đối chiếu liều/PHI chỉ với dòng `verified=1 AND entry_pass=1`, đúng cả formulation.
- Toàn vẹn SQLite, nguồn URL, orphan record/vector và canonical alias.
- RAG fail-closed khi retrieval rỗng, model lỗi, URL/section/quote/số không hợp lệ;
  đồng thời probe liên kết từng claim ↔ citation cụ thể và chặn kết luận mạnh hơn
  nội dung quote.

## Thêm case

Thêm một dòng JSON vào `eval/hallucination_cases_v1.jsonl`. Các field bắt buộc:

```json
{"id":"new01","category":"registered_pair","question":"...","region":"an_giang","on_date":"2026-07-17","expect":{"kind":"registered_pair","crop":"lúa","pest":"rầy nâu"},"risk":"high"}
```

Các `expect.kind` được hỗ trợ: `allowed_product`, `registered_pair`,
`unregistered_pair`, `transitional`, `removed`, `banned`, `wrong_crop`,
`double_dose`, `clarify`, `registrant`, `unknown_product`,
`mispronounced_product`, `misspelled_entity`. Hai loại cuối dùng thêm
`variant_type` để phân nhóm lỗi phiên âm/ASR/chính tả.

Chỉ thêm `known_gap` khi đã xác nhận đây là thiếu sót hiện hữu và ghi lý do cụ thể.
Khi sửa xong, bỏ field này để case trở thành regression gate bình thường.

## Giới hạn cố ý

Bộ offline không dùng một LLM khác làm judge. Claim gate hiện là policy bảo thủ,
deterministic: từng câu phải có đủ neo nội dung trong một quote, còn hành động,
phủ định và khẳng định tuyệt đối phải xuất hiện tương ứng trong chính quote đó.
Nó chặn fail-closed nhưng không thể chứng minh entailment cho mọi cách diễn đạt tự
do; false negative sẽ trở thành abstain. Nếu cần đo chất lượng model thật theo thời
gian, chạy thêm eval live riêng, lưu model/version/temperature và review thủ công;
không thay thế gate offline bằng một judge không ổn định.

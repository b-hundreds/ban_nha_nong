# Kiến trúc LLM gọi API dữ liệu registry

## Luồng xử lý

```text
Input người dùng
  → input_resolver chuẩn hóa / hỏi xác nhận nếu không exact
  → ResolvedQuery giữ nguyên intent + entity canonical đã xác nhận
  → Gemini function-calling chọn đúng một tool zero-argument
  → backend gắn product/formulation/crop/pest/date đáng tin cậy
  → registry_service chạy SQL có tham số
  → Gemini tạo AnswerPlan chỉ gồm conclusion + product_id từ ToolResult
  → validator kiểm tra AnswerPlan
  → template deterministic dựng text, product card, dose và citation
```

Không cho LLM sinh SQL, URL, liều, tên thuốc hoặc argument của API. Nếu model
không khả dụng, gọi tool sai, truyền argument, đổi conclusion hoặc tạo product ID
mới, hệ thống dùng deterministic plan. Lỗi DB/tool thì fail-closed, không chuyển
sang danh sách thuốc khác.

Một invariant bắt buộc: khi `ResolvedQuery.product` có giá trị, tool
`list_registered_products` bị cấm. Câu hỏi `Biocare WP trị thán thư sầu riêng
được không?` chỉ có thể gọi `check_product_registration`, vì vậy kết quả chỉ chứa
Biocare hoặc kết luận không đăng ký; không thể rơi sang top-5 của cặp cây–bệnh.

## HTTP API

Các endpoint FastAPI dùng chung service với tool executor; backend không tự gọi
HTTP vòng vào chính nó:

- `POST /api/registry/products/check-registration`
- `POST /api/registry/products/search`
- `POST /api/registry/products/legal-status`
- `POST /api/registry/products/registrant`

Ví dụ kiểm tra chính xác một sản phẩm:

```json
{
  "trade_name": "Biocare",
  "formulation": "WP",
  "crop": "sầu riêng",
  "pest": "thán thư",
  "on_date": "2026-07-17"
}
```

Response phân biệt rõ `registered`, `not_registered`, `not_found`, `ambiguous`
và `unavailable`. Chỉ `registered` mới được phép tra liều verified cho đúng
product ID + formulation + crop + pest.

## Cấu hình

```dotenv
REGISTRY_AGENT_MODE=auto
GEMINI_REGISTRY_AGENT_MODEL=
```

`auto` dùng Gemini function-calling khi có `GEMINI_API_KEY`; lỗi model tự rơi về
router deterministic. `off` tắt call model nhưng vẫn chạy chính xác toàn bộ tool
và DB service, dùng cho unit test/audit offline.

## Ranh giới an toàn

- Guard tăng/gấp đôi liều và hoạt chất cấm chạy trước planner.
- Entity canonical đến từ exact matcher hoặc lượt xác nhận, không đến từ planner.
- Tên sản phẩm trần có nhiều formulation trả `ambiguous`.
- Product-specific không bao giờ fallback sang search chung.
- Product card, dose và citation luôn dựng trực tiếp từ ToolResult.
- Registrant được chuẩn hóa khoảng trắng nhưng giữ nguyên nội dung DB.

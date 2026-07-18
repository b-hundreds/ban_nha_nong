# Contract: Handoff → Cán bộ khuyến nông (form + dashboard + notify + alert)

Ngày: 2026-07-18. Trạng thái: CHỐT — 3 lane code song song phải bám đúng contract này.

## Tổng quan luồng

1. **Người dùng** gặp câu bot không trả lời được (segment `{type:"abstain", handoff:true}`)
   → UI hiện **form gửi cán bộ khuyến nông** (họ tên, SĐT/Zalo, email tuỳ chọn, nội dung
   câu hỏi prefill) → POST `/api/handoff` → nhận `ticket_id`, lưu vào message của hội thoại.
2. **Cán bộ** mở dashboard `/officer/` → thấy danh sách ticket chờ + **alert vùng dịch**
   → trả lời ticket → POST `/api/officer/tickets/{id}/answer`.
3. Backend **notify**: email (SMTP) nếu có email; Zalo OA nếu có `ZALO_OA_ACCESS_TOKEN`
   (không có token → log stub, không fail). Ghi `notified_via`.
4. **Người dùng** quay lại app: app poll `/api/handoff/status?ids=...` (30s/lần + lúc load)
   → ticket vừa answered → **popup** hiện "câu bác hỏi + cán bộ trả lời" → POST
   `/api/handoff/{id}/seen`; câu trả lời cũng render inline trong thread hội thoại.
5. **Alert**: mọi câu hỏi `/api/ask` được log (region, crop, pest, ts) vào `question_log`;
   dashboard GET `/api/officer/alerts` → nhóm theo (region, pest) 7 ngày gần nhất,
   count ≥ `ALERT_MIN_COUNT` (env, default 3) → "Vùng X đang có nhiều câu hỏi về Y".

## DB: data/handoff.db (SQLite, module mới `app/backend/handoff.py`)

Bảng `tickets` — GIỮ các cột cũ (id, ts, region, transcript, slots_json, status), THÊM
bằng migration `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` (db cũ có thể đã tồn tại):

| cột mới | kiểu | ghi chú |
|---|---|---|
| conversation_id | TEXT | id hội thoại phía web |
| message_id | TEXT | id message trong hội thoại |
| question | TEXT | nội dung người dùng đã sửa/confirm trong form (khác transcript gốc) |
| contact_name | TEXT | bắt buộc từ form |
| contact_phone | TEXT | SĐT/Zalo, tuỳ chọn |
| contact_email | TEXT | tuỳ chọn |
| crop | TEXT | từ slots |
| pest | TEXT | từ slots |
| answer | TEXT | cán bộ trả lời |
| answered_by | TEXT | tên cán bộ |
| answered_at | TEXT | ISO UTC |
| notified_via | TEXT | "email", "zalo", "email,zalo", "none" |
| seen_at | TEXT | user đã xem popup |

`status`: `pending` → `answered` (giữ nguyên giá trị cũ đang dùng).

Bảng mới `question_log(id INTEGER PK, ts TEXT, region TEXT, crop TEXT, pest TEXT, text TEXT)`
— insert mỗi lần `/api/ask` (best-effort, lỗi log không chặn response).

## API (router mới trong `app/backend/handoff.py`, include vào api.py)

### Phía người dùng
- `POST /api/handoff` (MỞ RỘNG endpoint hiện có — chuyển từ api.py sang module mới):
  body `{session_id?, conversation_id?, message_id?, transcript, question?, slots,
  contact_name, contact_phone?, contact_email?}` → `{ticket_id}`.
  `question` rỗng → dùng transcript. Tương thích ngược: thiếu contact_name → vẫn nhận
  (đặt "Bà con chưa để lại tên") để nút cũ không vỡ.
- `GET /api/handoff/status?ids=1,2,3` → `{tickets:[{ticket_id, status, question, answer,
  answered_by, answered_at, seen}]}` (ids không tồn tại thì bỏ qua; tối đa 50 id).
- `POST /api/handoff/{ticket_id}/seen` → `{ok:true}` (set seen_at).

### Phía cán bộ (prefix `/api/officer`)
Auth demo: nếu env `OFFICER_TOKEN` đặt → yêu cầu header `X-Officer-Token` khớp, sai → 401.
Không đặt env → cho qua (demo hackathon).
- `GET /api/officer/tickets?status=pending|answered|all` (default `all`) →
  `{tickets:[{ticket_id, ts, status, region, crop, pest, question, transcript,
  contact_name, contact_phone, contact_email, answer, answered_by, answered_at,
  notified_via}]}` — sort: pending trước (ts mới nhất trước), answered sau.
- `POST /api/officer/tickets/{id}/answer` body `{answer (min_length=1), officer_name}` →
  `{ok:true, notified_via}` — set status=answered, answered_at, answered_by, gọi notify.
  Ticket đã answered → 409.
- `GET /api/officer/alerts?days=7&year=2026` → `{alerts:[{region, region_name, topic,
  count, latest_ts, sample_questions:[..tối đa 3]}], history:[...], overview:{year,
  available_years, total_questions, located_questions, disease_report_count,
  questions_by_region, disease_reports_by_region, note}}` — alert lấy từ `question_log`
  UNION ticket; tổng quan năm lấy `question_log`, tách rõ tổng câu hỏi và câu hỏi liên
  quan dịch hại. Số liệu dịch hại là phản ánh từ câu hỏi, không phải ca dịch đã xác minh.
  (question, pest, region); nhóm theo (region, pest không rỗng); count ≥ ALERT_MIN_COUNT
  (env, default 3), sort count desc.

## Notify — module mới `app/backend/notify.py`

`notify_ticket_answered(ticket_dict) -> str` trả về `notified_via`:
- Email: `smtplib` + env `SMTP_HOST, SMTP_PORT(587), SMTP_USER, SMTP_PASS, SMTP_FROM`
  (thiếu host → skip). Subject: "Cán bộ khuyến nông đã trả lời câu hỏi của bác".
  Nội dung tiếng Việt: câu hỏi + câu trả lời + tên cán bộ.
- Zalo OA: env `ZALO_OA_ACCESS_TOKEN` → POST `https://openapi.zalo.me/v3.0/oa/message/cs`
  (httpx, timeout 10, message text tương tự; user_id = contact_phone). Thiếu token →
  log `zalo skipped`. LƯU Ý: demo không có OA thật — code phải chịu lỗi êm (log, không raise).
- Cả hai fail/skip → trả "none". Không bao giờ raise ra ngoài endpoint.

## Env mới (.env.example — thêm section, giữ nguyên phần cũ)

```
# ============ Khuyến nông: notify + dashboard ============
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
SMTP_FROM=
ZALO_OA_ACCESS_TOKEN=
OFFICER_TOKEN=
ALERT_MIN_COUNT=3
```

## Frontend người dùng (app/web/app.js + app.css — LANE RIÊNG, không đụng backend)

- `renderHandoff(...)`: thay nút trơn bằng form gọn trong `handoff-panel`: input họ tên,
  SĐT/Zalo, email (optional), textarea prefill câu hỏi (sửa được), nút "Gửi cán bộ
  khuyến nông". Gửi xong hiện mã ticket + dòng "Cán bộ trả lời sẽ báo qua Zalo/email,
  và hiện ngay trong app". Lưu `message.handoff = {ticketId, question, status:"pending"}`
  rồi gọi saveConversations (đã có sẵn) để bền vững server-side.
- Poll: hàm `pollHandoffTickets()` chạy lúc `init` + `setInterval` 30s: gom ticketId của
  mọi message có `handoff.status==="pending"` → GET `/api/handoff/status?ids=...` →
  ticket answered → cập nhật `message.handoff` (answer, answeredBy, status), save, render
  lại nếu đang mở hội thoại đó, và **hiện popup modal**: tiêu đề "Cán bộ khuyến nông đã
  trả lời", khối câu hỏi của bác + khối trả lời + tên cán bộ, nút "Đã hiểu" → POST seen.
  Popup dùng đúng design token/biến CSS hiện có của app (user tự thiết kế UI — TÔN TRỌNG
  aesthetic: nền, radius, font hiện trạng; không đổi màu chủ đạo).
- Message có `handoff.status==="answered"` → render thêm khối "Trả lời từ cán bộ khuyến
  nông" inline dưới answer cũ.
- Bump `CACHE_NAME` sw.js lên `bnn-shell-v8`.

## Dashboard cán bộ (app/web/officer/{index.html,officer.css,officer.js} — LANE RIÊNG)

- Static thuần, StaticFiles(html=True) tự serve `/officer/`. KHÔNG sửa api.py.
- Nội dung: header "Bảng điều hành khuyến nông"; dải **alert vùng dịch** trên cùng
  (từ `/api/officer/alerts`, badge đỏ/cam: "An Giang — 12 câu hỏi về rầy nâu / 7 ngày");
  bảng ticket (tab Chờ trả lời / Đã trả lời); click ticket → panel chi tiết: câu hỏi,
  transcript gốc, region/crop/pest, contact; ô tên cán bộ (nhớ localStorage), textarea
  trả lời, nút Gửi → POST answer → toast + chuyển tab. Auto refresh 15s.
- Nếu localStorage có `officer_token` → gắn header `X-Officer-Token` mọi request.
- Region hiển thị: `an_giang`→"An Giang", `dak_lak`→"Đắk Lắk" (khớp Region enum backend).
- Design: tiếng Việt, nghiêm túc kiểu công cụ nội bộ nhà nước/nông nghiệp, KHÔNG được
  trông AI-generated (dùng skill frontend-design) — nhưng file css riêng, không đụng
  app.css của user.

## Phân lane (tránh conflict)
- **Lane BE**: app/backend/handoff.py (mới), notify.py (mới), api.py (bỏ endpoint handoff
  cũ, include router mới, log question ở /api/ask), schemas.py (mở rộng HandoffRequest +
  schemas mới), .env.example, tests/test_handoff.py.
- **Lane USER-UI**: app/web/app.js, app/web/app.css, app/web/sw.js. KHÔNG file khác.
- **Lane DASH**: app/web/officer/* (mới). KHÔNG file khác.

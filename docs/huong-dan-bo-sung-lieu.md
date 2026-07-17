# Hướng dẫn bổ sung dữ liệu liều lượng thuốc (labels)

Đây là quy trình để NGƯỜI (không phải AI) bổ sung liều lượng cho các sản phẩm còn
thiếu. Dữ liệu này sẽ được đọc cho nông dân làm theo — **sai một con số là hỏng mùa
hoặc hại sức khỏe người phun**, nên quy trình chặt hơn bình thường.

## Nguyên tắc bất di bất dịch

1. **Chỉ CHÉP, không bịa/đoán/ước lượng/quy đổi.** Liều ghi nguyên văn như nguồn
   (kể cả cách viết "0,5 lít/ha", "20 – 28 g/bình 16 lít").
2. **Nguồn hợp lệ** (được ghi vào `source_url`):
   - CSDL tra cứu thuốc BVTV quốc gia: <https://sansangxuatkhau.ppd.gov.vn/thuoc-va-phan-bon/phan-mem-tra-cuu-thuoc-bao-ve-thuc-vat-quoc-gia.html> (hoặc app "Thuốc BVTV" của Cục)
   - Trang sản phẩm / nhãn PDF **chính thức của tổ chức đăng ký** (cột `registrant`
     trong registry — ví dụ scvcl-chem.com.vn của Sumitomo)
   - Quy trình kỹ thuật của Cục TT&BVTV / bản tin Chi cục BVTV tỉnh (ghi
     `source_note` bắt đầu bằng `QUY TRINH:` hoặc `BAN TIN:`)
   - **KHÔNG hợp lệ**: shop bán thuốc, báo chí, diễn đàn, wiki — chỉ được dùng làm
     manh mối để tìm ra nguồn chính thức.
3. **Không tìm được nguồn hợp lệ → BỎ QUA sản phẩm đó.** Thà thiếu còn hơn sai —
   app sẽ tự nói "dùng theo liều trên nhãn".
4. **Double-entry**: mỗi (sản phẩm × cây × dịch hại) phải được tra **2 lần độc lập**
   (`entry_pass` 1 và 2) — lý tưởng là 2 người khác nhau hoặc 2 nguồn khác nhau.
   2 lần khớp nhau thì validator mới tính là `verified` và app mới hiển thị.

## Quy trình 5 bước

### Bước 1 — Lấy danh sách sản phẩm cần tra

```bash
.venv/bin/python scripts/label_targets.py
```

In danh sách (cây, dịch hại, sản phẩm) theo scope ưu tiên (`docs/scope-pests.md`).
Ưu tiên tra sản phẩm của hãng lớn có website chính thức (dễ tìm nhãn).

### Bước 2 — Tra pass 1, ghi vào CSV

Mở `data/labels/labels_curated.csv`, thêm dòng theo đúng header:

```
product_trade_name,formulation,ai_name,crop,pest,dose_text,water_text,phi_days,method,dose_unit,source_url,source_note,retrieved_at,entry_pass
```

Ví dụ dòng chuẩn (chú ý **trường chứa dấu phẩy phải bọc ngoặc kép**):

```
Padan 95SP,95SP,Cartap hydrochloride,lúa,rầy nâu,"20 – 28 g/bình 16 lít (0.5–0.7 kg/ha)","400 – 600 lít/ha",7,phun,kg/ha,https://scvcl-chem.com.vn/san-pham/padan-95sp/,Trang chính hãng Sumitomo VN,2026-07-18T09:12:00+07:00,1
```

- `ai_name`: chép từ nguồn; nếu lệch với hoạt chất trong registry → ghi thêm vào
  `source_note`: `AI lệch registry: <tên trong registry>`.
- `phi_days`: chỉ số ngày (7), không chữ. Không có thông tin → để trống.
- `retrieved_at`: thời điểm bạn tra, định dạng ISO như ví dụ.
- `entry_pass`: `1`.

### Bước 3 — Tra pass 2 ĐỘC LẬP

Người khác (hoặc bạn, nhưng vào lúc khác và **không nhìn lại pass 1**) tra lại đúng
sản phẩm đó, ưu tiên nguồn KHÁC pass 1, ghi dòng `entry_pass` = `2`. Nếu cả 2 pass
buộc phải dùng chung 1 nguồn (nguồn duy nhất tồn tại) → ghi `source_note`:
`nguồn duy nhất, đọc lại độc lập`.

### Bước 4 — Chạy validator

```bash
.venv/bin/python -m ingest.build_labels
```

Đọc output:

- `n_verified` — số (sản phẩm × cây × dịch hại) đã đủ 2 pass khớp nhau ✓
- `mismatches` — 2 pass lệch nhau → **tra lần 3 làm trọng tài**, sửa dòng sai
  (ghi chú vào `source_note`); không phân xử được → xoá cả 2 dòng.
- `errors` — dòng thiếu provenance / trùng entry_pass / dính chữ "MẪU|SAMPLE" →
  sửa theo thông báo. Validator TỪ CHỐI verify các dòng này, không thoả hiệp.

### Bước 5 — Kiểm tra trên app rồi commit

```bash
.venv/bin/uvicorn app.backend.api:app --port 8010   # hỏi thử 1 câu có sản phẩm vừa thêm
.venv/bin/pytest -q                                  # phải xanh
git add data/labels/labels_curated.csv
git commit -m "data: bổ sung liều <tên sản phẩm/nhóm> (double-entry, provenance)"
```

Phiếu thuốc trong app sẽ tự hiện liều + ngày cách ly + link nguồn cho các sản phẩm
vừa verified (sản phẩm có liều được xếp lên đầu danh sách).

## Hỏi đáp nhanh

- **Nguồn ghi liều theo "bình 16 lít" còn nhãn ghi theo "lít/ha"?** Chép đúng nguồn
  bạn đang dùng vào `dose_text` (có thể ghi cả hai nếu nguồn in cả hai như ví dụ
  Padan). Không tự quy đổi.
- **Một sản phẩm nhiều quy cách (50WP, 450EC)?** Mỗi quy cách là một dòng riêng với
  `formulation` tương ứng — liều thường khác nhau.
- **Nguồn không ghi PHI?** Để trống `phi_days`, đừng lấy PHI của sản phẩm "tương tự".

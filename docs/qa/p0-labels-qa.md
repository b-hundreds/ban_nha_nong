# QA — Dữ liệu liều lượng nhãn thuốc (đợt curate 1, 18/07/2026)

## Phương pháp

Workflow fan-out 34 agent (run `wf_5a4254bb-c2d`): 92 sản phẩm ưu tiên (top theo cặp
cây–dịch hại trong `docs/scope-pests.md`) × 2 pass tra cứu độc lập song song → mọi
kết quả đều qua **trọng tài xác minh lại trực tiếp** trên CSDL tra cứu thuốc BVTV
quốc gia (cổng EcoFarm của Cục BVTV, footer xác nhận ppd.gov.vn) — chỉ nhận dòng
khớp **nguyên văn** với trang CSDL, kèm số đăng ký (SĐK) trong `source_note`.

## Kết quả

- **45 tổ hợp (sản phẩm × cây × dịch hại) verified** — 90 dòng CSV (double-entry),
  `build_labels`: 0 mismatch, 0 error.
- **166 tổ hợp bị bỏ qua** (không tìm được nguồn hợp lệ trong thời gian tra) — app
  tự trả "dùng theo liều trên nhãn" cho các sản phẩm này, không bịa.
- Phủ chủ yếu: lúa (đạo ôn, sâu đục thân, khô vằn, lem lép hạt, rầy nâu...); cà
  phê/sầu riêng còn mỏng — xem kế hoạch bên dưới.

## Caveat đã ghi nhận (giữ nguyên trong source_note từng dòng)

1. **Một số SĐK đã hết hạn đăng ký** tại thời điểm tra (vd A-V-T Vil 5SC hết hạn
   14/5/2025; Actatac 300EC hết 1/8/2025) — sản phẩm vẫn nằm trong danh mục được
   phép (TT 75/2025), số liều vẫn là dữ liệu nhãn đăng ký chính thức trên CSDL;
   chép nguyên văn theo quy tắc, có ghi chú rõ từng dòng.
2. Double-entry của đợt này = claim của worker + **re-fetch độc lập của trọng tài**
   (2 lần nhìn độc lập, cùng về CSDL quốc gia) — vết xác minh nằm trong
   `source_note` mỗi dòng.
3. Nguồn cổng CSDL dùng IP `113.190.254.147` (EcoFarm) — là hạ tầng chính thức của
   Cục (xác nhận footer + trùng nội dung route ổn định `/EcoFarm/en/thuoc/index/<id>`),
   nhưng URL IP có thể đổi; SĐK trong source_note là khoá tra cứu bền hơn.

## Kế hoạch tăng coverage (đợt 2 — team tự làm theo docs/huong-dan-bo-sung-lieu.md)

1. Ưu tiên sản phẩm của hãng lớn có website chính thức (Syngenta, Bayer, ADAMA,
   Sumitomo, Lộc Trời, VFC...) cho cà phê/sầu riêng.
2. Mỏ liều trong quy trình chính thống của Cục đã có sẵn trong KB (`data/kb_manual/`)
   — ghi `source_note` bắt đầu `QUY TRINH:`.
3. Tra thẳng cổng EcoFarm theo tên thuốc (nhanh nhất — trọng tài đã chứng minh cách
   dùng, xem source_note các dòng hiện có).

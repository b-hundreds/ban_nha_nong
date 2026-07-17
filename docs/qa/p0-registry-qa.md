# P0 Registry QA — Task 7

Nguồn: `data/registry.db` (bản build sau Task 5e: 6878 products / 16026 uses / 2243
active_ingredients). Công cụ: `ingest/qa_registry.py`. Đối chiếu tay bằng
`pdfplumber` trực tiếp trên `data/raw/tt75_2025_page_1.pdf` (Phụ lục I — được
phép) và `data/raw/tt75_2025_page_2.pdf` (Phụ lục II — cấm), cộng
`data/amendments_tt28_2026.csv` cho các dòng có nguồn TT 28/2026.

**Kết luận ngắn gọn: BLOCKED cho cột `products.ai_id`/`active_ingredient`.**
QA phát hiện lỗi hệ thống MỚI (chưa từng ghi nhận ở Task 3–6) khiến một tỉ lệ
lớn sản phẩm Phụ lục I bị gán SAI hoạt chất — xem mục 3. Cột
`crop`/`pest`/`trade_name`/`formulation`/`status`/`registrant` không phát hiện
lỗi mới ngoài phạm vi known-issues đã biết (mục 4) — `scripts/scope_pests.py`
và `docs/scope-pests.md` (Task 7 Step 3) không phụ thuộc `ai_id` nên vẫn hoàn
thành bình thường.

## 1. Machine checks (`ingest/qa_registry.py`, `machine_checks()`)

```
CHECK: 34 sản phẩm allowed trùng (trade+form+ai)
CHECK: INFO: 11 sản phẩm allowed không có uses (kiểm tra parse cột target)
CHECK: INFO: status=allowed: 6841 sản phẩm
CHECK: INFO: status=banned: 31 sản phẩm
CHECK: INFO: status=removed: 6 sản phẩm
CHECK: INFO: doc_id=1 (75/2025/TT-BNNMT): 6520 sản phẩm
CHECK: INFO: doc_id=2 (28/2026/TT-BNNMT): 358 sản phẩm
CHECK: INFO: 2243 active_ingredients, 16026 uses
```

Không có `uses` mồ côi (0, không in ra vì rỗng).

### 1.1 "34 sản phẩm allowed trùng (trade+form+ai)" — ĐÃ ĐIỀU TRA, không phải lỗi parser

Cả 34 nhóm đều có ĐÚNG 2 dòng: 1 dòng `doc_id=1` (TT75, `effective_from
2026-02-10`) + 1 dòng `doc_id=2` (TT28 `add_product`, `effective_from
2026-08-15`), cùng registrant. Kiểm tra `uses` của từng cặp: 33/34 cặp có tập
`(crop,pest)` RỜI NHAU hoàn toàn (vd *Alfos 50EC*: dòng TT75 có
`(lạc,sâu khoang)`, dòng TT28 có `(đậu tương,sâu xanh da láng)` — xác nhận
đúng bằng text PDF gốc `tt75_2025_page_1.pdf` trang 29 dòng 184 + CSV amendment
dòng 60-61). Đây là mẫu hình **mở rộng phạm vi sử dụng** (label mở rộng
crop/pest mới cho sản phẩm ĐÃ đăng ký) mà TT 28/2026 Phụ lục II ghi nhận như
một "add_product" riêng thay vì "add_use" trên sản phẩm cũ — không phải lỗi
build, chỉ là một giới hạn mô hình dữ liệu (P1 cần biết: cùng 1 sản phẩm vật lý
có thể xuất hiện 2 lần trong `products` với 2 phạm vi sử dụng khác nhau). 1/34
cặp (*Novixid® 32.5OD*) có `uses` giống hệt nhau ở cả 2 dòng — trùng lặp vô
hại (không tạo thông tin sai, chỉ dư 1 dòng).

**Không tính là lỗi mới** cho ngưỡng 2% (không phải lỗi transcription/parse),
nhưng cần lưu ý cho P1 nếu tính "tổng số sản phẩm khác nhau".

## 2. Mẫu 5% — đối chiếu tay

`sample(conn, 0.05, seed=17)` → 343 dòng (`max(30, 5%*6878)`). Từ 343 dòng,
chọn **35 dòng trải đều** (`awk 'NR%10==1'` sau khi giữ nguyên thứ tự shuffle
seed cố định — phủ trang 4 → 351, cả `allowed`/`banned`/TT28) để đối chiếu tay
chi tiết với PDF (dùng `pages=` in kèm mỗi dòng + `scripts/inspect_pdf.py`/
`pdfplumber.extract_text()` trực tiếp).

| # | Sản phẩm (id) | AI trong DB | AI thực tế (PDF) | Target/pest-crop | Kết luận |
|---|---|---|---|---|---|
| 1 | Bimstar 850WP (3213) | Difenoconazole 5g/kg+Isoprothiolane 295g/kg+Tricyclazole 550g/kg | khớp (tr.183, mục #317) | (lúa, đạo ôn) khớp | ✅ Khớp |
| 2 | AF-Flamingo 12SC (974) | Chlorfenapyr 10%+Spinosad 2% | khớp (tr.59, #424) | (lạc, sâu xanh da láng) khớp | ✅ Khớp |
| 3 | Makozeb-RBC 80WP (4020) | **Laminarin (min 86%)** | **Mancozeb (min 85%)** (tr.227, #627) | (cam, thối quả) khớp | ❌ **LỖI MỚI** (mục 3) |
| 4 | Afudan 20SC (801) | Carbosulfan (min 93%) — khớp | khớp (tr.50, #352) | pest dính "/lúa" (garble) | ⚠️ Known (mục 4.4) |
| 5 | TVG28 650SP (2160) | **Natural rubber** | **Nitenpyram (min 95%)** (tr.123, #799) | (sắn,bọ phấn trắng)/(lúa,rầy nâu) khớp | ❌ **LỖI MỚI** |
| 6 | Zenlovo 775WP (3159) | Cyproconazole 75g/kg+Mancozeb 700g/kg — khớp | khớp (tr.180, #283) | pest dính "/đậu tương" (garble) | ⚠️ Known |
| 7 | Map Famy 35SC (3454) | Fenoxanil 100g/l+Tricyclazole 250g/l — khớp | khớp (tr.197, #425) | (lúa, đạo ôn) khớp | ✅ Khớp |
| 8 | Stopmite 500SC (1028) | Clofentezine (min 96%) — khớp | khớp (tr.62, #454) | (hoa hồng, nhện đỏ) khớp | ✅ Khớp |
| 9 | Sếu đỏ 3EC (334) | Abamectin B2 (min 90%) | khớp (tr.23) | (lúa, rầy nâu) khớp | ✅ Khớp |
| 10 | AGsouthstar 42WP (4298) | Prochloraz-Mn complex 35%+Tebuconazole 7% — khớp | khớp (tr.242, #718) | (lạc, đốm nâu) khớp | ✅ Khớp |
| 11 | Topzone 4OD (5838) | Topramezone (min 96%) — khớp | khớp (tr.320, #309) | (ngô, cỏ) khớp | ✅ Khớp |
| 12 | Cherray 700WG (1942) | Imidacloprid 200g/kg+Pymetrozine 500g/kg — khớp | khớp (tr.112, #727) | (lúa, rầy nâu) khớp | ✅ Khớp |
| 13 | Danrat 0.005RB (5848) | **Barium sulfate 20%+Difennuozhi 0.02%** | **Brodifacoum (min 91%)** (tr.321, mục "4.Thuốc trừ chuột" #2) | (đồng ruộng, chuột) khớp | ❌ **LỖI MỚI** |
| 14 | Pylacol 700WP (4371) | **Propiconazole 10.7%+Tricyclazole 34.2%** | **Propineb (min 80%)** (tr.245-246, #741) | (cần tây,đốm lá)/(lúa,đạo ôn+đốm nâu)/(xoài+ớt,thán thư) khớp | ❌ **LỖI MỚI** |
| 15 | Bayluscide 70WP (6281) | **Metaldehyde 140g/kg+Pyridaben 10g/kg** | **Niclosamide (min 96%)** (tr.343, #20) | (lúa, ốc bươu vàng) khớp | ❌ **LỖI MỚI** |
| 16 | Nomefit 300EC (4828) | Acetochlor 15g/l+Pretilachlor 285g/l+Fenclorim 100g/l — khớp | khớp (tr.270, #15) | (lúa gieo thẳng, cỏ) khớp | ✅ Khớp |
| 17 | Dizorin 35EC (1112) | Cypermethrin 50g/l+Dimethoate 300g/l — khớp | khớp (tr.67, #486) | 6 cặp lúa/đậu tương khớp (có ";" nên tách sạch) | ✅ Khớp |
| 18 | Chat 20WP (1282) | Dimethoate 20%+Phenthoate 20% — khớp | khớp (tr.76, #539) | pest dính "/lúa","/xoài",... (garble) | ⚠️ Known |
| 19 | Ratgone 0.005DR (5889) | **Barium sulfate 20%+Difennuozhi 0.02%** | **Bromadiolone (min 97%)** (tr.322-323, mục "4." #3) | (đồng ruộng, chuột) khớp | ❌ **LỖI MỚI** |
| 20 | Biclofen Plus 400SC (629) | Bifenazate 300g/l+Spirodiclofen 100g/l — khớp | khớp (tr.41, #266) | (cam,hoa hồng / nhện đỏ) khớp | ✅ Khớp |
| 21 | Hoanganhvil 50SC (3630) | Gentamicin sulfate+Streptomycin sulfate — khớp | khớp (tr.207) | (cà phê, rỉ sắt) khớp | ✅ Khớp |
| 22 | Clatinusa 500EC (2201) | **Oxymatrine (min 98%)** | sai (tr.125-126, đầu nhóm bị mất — chưa dò được mã đúng, xem mục 3) | (lúa, sâu keo) khớp | ❌ **LỖI MỚI** |
| 23 | Yanibin 75WG (4550) | **Conabin 750WG** (= TÊN THƯƠNG PHẨM khác, không phải hoạt chất!) | **Tebuconazole 500g/kg(50%)+Trifloxystrobin 250g/kg(25%)** (tr.256-257, #801) | (cà phê, rỉ sắt) khớp | ❌ **LỖI MỚI** (cơ chế khác — mục 3.2) |
| 24 | Filia® 525SE (6783) | Propiconazole 125g/l+Tricyclazole 400g/l — khớp | khớp (tr.245, #734 lân cận) | (lúa, đạo ôn cổ bông) khớp | ✅ Khớp |
| 25 | Anfaza 350SC (2499) | **Thiacloprid (min 95%)** | **Thiamethoxam (min 95%)** (tr.142, #892) | (lúa,bọ trĩ)/(cà phê,rệp sáp) khớp | ❌ **LỖI MỚI** |
| 26 | Sinsmart SC (2825) | Bacillus amyloliquefaciens — khớp | khớp (tr.160) | 3 cặp khớp | ✅ Khớp |
| 27 | Tora 1.1SL (6194) | 1-Triacontanol (min 90%) — khớp | khớp (tr.339, #66) | 6 cây kích thích sinh trưởng khớp | ✅ Khớp |
| 28 | Windy 200SL (5491) | **Fomesafen 12%+Quizalofop-P-ethyl 3%** | **Glufosinate ammonium (min 95%)** (tr.296-297, #203) | (cao su, cỏ) khớp | ❌ **LỖI MỚI** (nhóm lớn nhất tìm được: 147 sản phẩm) |
| 29 | Multigreen SC (518) | Bacillus thuringiensis — khớp | khớp (tr.34, #224 lân cận) | (cải bắp, sâu tơ) khớp | ✅ Khớp |
| 30 | Emacarb 75EC (1543) | Emamectin benzoate 50g/l+Indoxacarb 25g/l — khớp | khớp (tr.91, #575) | (lúa, sâu cuốn lá) khớp | ✅ Khớp |
| 31 | Ang.clean 250SC (1756) | Fluacrypyrim (min 95%) — khớp | khớp (tr.103, #685) | (lúa, nhện gié) khớp | ✅ Khớp |
| 32 | No-ocbuuvang 750WP (6304) | **Metaldehyde 140g/kg+Pyridaben 10g/kg** | **Niclosamide (min 96%)** (tr.343-344, #20, cùng nhóm với #15) | (lúa, ốc bươu vàng) khớp | ❌ **LỖI MỚI** |
| 33 | Robot 15SC (652) | Bifenthrin 5%+Flonicamid 10% — khớp | khớp (tr.42, #277) | (sắn, bọ phấn trắng) khớp | ✅ Khớp |
| 34 | Spiromax 300SC (2435) | **Spinetoram 120g/kg+Triflumezopyrim 100g/kg** | sai (tr.137-139, đầu nhóm mất — chưa dò mã đúng) | (cam, nhện đỏ) khớp | ❌ **LỖI MỚI** |
| 35 | Baragren 480SL (4956) | **Bensulfuron-methyl 40g/kg+Quinclorac 560g/kg** | **Bentazone (min 96%)** (tr.276, #75) | (đậu tương, cỏ) khớp | ❌ **LỖI MỚI** |

### 2.1 Tổng kết mẫu 35 dòng

| Loại | Số dòng | Tỉ lệ |
|---|---|---|
| ✅ Khớp hoàn toàn | 19 | 54.3% |
| ⚠️ Known-issue (garble pest/crop nhiều dấu "/", Task 4 report, ~10%) | 3 | 8.6% |
| ❌ **Lỗi MỚI** (active_ingredient sai — mục 3) | 13 | **37.1%** |

**Tỉ lệ lỗi MỚI = 13/35 = 37.1% ≫ ngưỡng 2% → BLOCKED.** `crop`/`pest`/
`trade_name`/`formulation`/`registrant`/`status` của cả 35 dòng đều khớp PDF
(kể cả 13 dòng lỗi AI) — lỗi chỉ nằm ở cột `active_ingredient`/`ai_id`.

## 3. PHÁT HIỆN CHÍNH: lỗi hệ thống ở `products.ai_id` — MỚI, quy mô lớn

### 3.1 Cơ chế lỗi #1 (13/13 dòng lỗi ở mục 2 trừ Yanibin): mất "hàng tiêu đề
nhóm hoạt chất" khi trang không có header bảng riêng

Phụ lục I dùng ô "hoạt chất" GỘP theo rowspan (1 hoạt chất áp dụng cho nhiều
sản phẩm liên tiếp). `ingest/parse_annex._recover_missing_leading_cells` khôi
phục ô bị mất (cell=None) bằng cách crop lại theo x-range của cột "hoạt chất"
lấy từ **hàng tiêu đề bảng của CHÍNH TRANG ĐÓ** — nhưng hàng tiêu đề
("TT | Hoạt chất | ...") chỉ xuất hiện ở **trang 0** của toàn bộ Phụ lục I.
Với >99% số trang còn lại (`_header_col_bounds` trả `None`), hàm khôi phục bị
tắt hoàn toàn (`col_bounds is None` → return nguyên trạng) — kể cả khi trang
đó THỰC SỰ có 1 nhóm hoạt chất MỚI bắt đầu (dòng "NNN Tên hoạt chất" bị
pdfplumber dò nhầm thành ô gộp, `cells[0]/[1]` = `None` dù nội dung vẫn đọc
được bằng `extract_text()`). Khi đó `ingest.normalize.to_entries` (dòng
"if r['ai']: ... elif cur_group is not None: ai = cur_group[0]['ai']") coi
sản phẩm mở đầu nhóm mới này như đang KẾ THỪA hoạt chất của nhóm TRƯỚC —
gán sai toàn bộ chuỗi sản phẩm cho tới khi gặp 1 nhóm được dò đúng tiếp theo.

**Xác nhận bằng chứng cụ thể** (trích PDF trực tiếp, không suy đoán):
- `Makozeb-RBC 80WP` (id 4020): entry #626 "Laminarin (min 86%)" chỉ áp dụng
  cho **1** sản phẩm (Vacciplant 45SL). Entry #627 "Mancozeb (min 85%)" mất
  (Aikosen 80WP trở đi) → **50 sản phẩm** (id 3990–4040, Aikosen→ZebindiaX)
  bị gán sai "Laminarin" thay vì "Mancozeb".
- `TVG28 650SP`: entry #799 "Nitenpyram (min 95%)" mất → toàn bộ nhóm
  (Acnipyram, AT-Army, Benusa,... TVG28) bị gán sai "Natural rubber" (hoạt
  chất thật của #798, chỉ áp dụng 1 sản phẩm Map Laba 10EC).
- `Danrat`/`Ratgone` (mục "4. Thuốc trừ chuột"): **2 entry liên tiếp** mất
  (#2 Brodifacoum VÀ #3 Bromadiolone) → toàn bộ ~35 sản phẩm từ AMC-Kirate
  đến VT-Madi (gồm cả Danrat, Ratgone) bị gán sai "Barium sulfate 20%+
  Difennuozhi 0.02%" (hoạt chất thật của entry #1, chỉ 1 sản phẩm Rat-ba).
- `Windy 200SL`: entry #203 "Glufosinate ammonium (min 95%)" mất → **147
  sản phẩm** (Ace gluffit→...) gán sai "Fomesafen 12%+Quizalofop-P-ethyl 3%"
  (hoạt chất thật của #202, chỉ áp dụng Grasskill 15EC).
- `Bayluscide`/`No-ocbuuvang`: entry #20 "Niclosamide (min 96%)" mất → nhóm
  lớn (Ac-snailkill→...) gán sai "Metaldehyde 140g/kg+Pyridaben 10g/kg" (hoạt
  chất thật của #19, chỉ 1 sản phẩm Octhailane 150GR).
- `Anfaza`, `Pylacol`, `Clatinusa`, `Spiromax`, `Baragren`: cùng cơ chế,
  entry #892/#741/khoảng #635/khoảng #875/#75 tương ứng bị mất.

**Định lượng quy mô** (script chẩn đoán độc lập, xem `.superpowers/sdd/` scratch
— tái tạo bằng cách chạy `parse_pdf`/`to_entries` với x-bounds cột lấy TOÀN CỤC
từ trang 0 thay vì per-page, rồi so khớp entry sinh ra với DB thật): tìm được
**144 điểm mất "hàng tiêu đề nhóm"** riêng biệt trong Phụ lục I (ngoài trang 0,
nơi lỗi này ĐÃ được Task 5b fix đúng). Khớp tự động 93/144 điểm → tối thiểu
**1706 sản phẩm** bị gán sai `ai_id` chỉ riêng từ 93 điểm này (chưa tính 51
điểm còn lại chưa khớp tự động, trong đó ít nhất Danrat/Ratgone — 2 điểm — đã
xác nhận tay là lỗi thật, cộng thêm nhiều sản phẩm khác). **Ước tính thận
trọng: 1700–2500+ / 6489 sản phẩm Phụ lục I "allowed" (~26–38%)** bị gán sai
hoạt chất.

### 3.2 Cơ chế lỗi #2 (1/13, Yanibin): dịch cột do ô cắt dấu tiếng Việt tạo
cột thừa

`Yanibin 75WG`: `pdfplumber.find_tables()` phát hiện SAI 1 đường kẻ cột dọc
đúng giữa 1 ký tự có dấu ("rỉ sắt/cà phê" bị tách "r" | "ỉ sắt/cà phê" ở dòng
sản phẩm `Conabin 750WG` cùng nhóm) → hàng đó có 4 ô có nội dung thay vì 3
(trade/target/registrant chuẩn). `_row_to_fields` (nhánh `len(cells) <= n`)
coi đây là "thiếu cột ĐẦU" và đệm rỗng từ trái → tên thương phẩm `Conabin
750WG` bị dồn nhầm vào Ô HOẠT CHẤT thay vì ô trade. Giá trị rác này
(`ai = "Conabin 750WG"`) sau đó LAN TRUYỀN cho mọi sản phẩm kế tiếp trong
cùng nhóm merge (Natrobin, Navigator, Subway, Tanimax, Triflo-top, Twinstar,
**Yanibin**...) cho tới khi gặp nhóm mới — nhóm thật là "Tebuconazole
500g/kg(50%)+Trifloxystrobin 250g/kg(25%)" (#801). Đây là 1 lớp lỗi KHÁC cơ
chế lỗi #1 (không phải mất hàng tiêu đề — mà là dịch cột do ô bị vỡ vì dấu
tiếng Việt), phát hiện ngẫu nhiên qua đúng 1 dòng mẫu (Yanibin) — khả năng còn
tái diễn ở nơi khác trong tài liệu, chưa định lượng.

### 3.3 Vì sao không sửa parser ở đây

Theo yêu cầu Task 7 ("đừng tự sửa parser") — đây là phát hiện QA, không phải
fix. Cả 2 cơ chế lỗi cần thiết kế fix riêng ở tầng `ingest/parse_annex.py`
(cơ chế #1: dùng x-bounds cột TOÀN CỤC thay vì per-page cho
`_recover_missing_leading_cells`, hoặc dò lại theo `extract_text()` khi
`find_tables()` không chắc chắn; cơ chế #2: xử lý ô bị vỡ do ký tự dấu tràn
cột trước khi đếm số ô) + re-test toàn bộ Phụ lục I — nên quay lại Task 3/4,
KHÔNG vá tại chỗ trong Task 7.

### 3.4 Phạm vi ảnh hưởng / KHÔNG ảnh hưởng

- **Ảnh hưởng:** `products.ai_id` / `active_ingredients.name_common` —
  không tin cậy cho ~26–38% sản phẩm Phụ lục I "allowed". Bất kỳ tính năng
  P1 nào hiển thị/tra cứu theo TÊN HOẠT CHẤT (vd "sản phẩm nào chứa
  Mancozeb", cảnh báo theo nhóm hoạt chất, đối chiếu MRL/an toàn theo hoạt
  chất) đều SAI cho các sản phẩm bị ảnh hưởng.
- **KHÔNG ảnh hưởng** (xác nhận qua toàn bộ 35 dòng mẫu, kể cả 13 dòng lỗi):
  `trade_name`, `formulation`, `registrant`, `status`, `effective_from/to`,
  `uses.crop`/`uses.pest` — các cột này lấy từ vị trí ô KHÁC trong cùng
  hàng, không phụ thuộc cơ chế lỗi trên. `app.backend.db.lookup_products
  (crop, pest, on_date)` (truy vấn chính của P1 — "sản phẩm nào được dùng
  cho cây X, dịch hại Y") vẫn trả đúng DANH SÁCH SẢN PHẨM; chỉ trường
  `active_ingredient` trong kết quả `ProductHit` có thể sai với các sản
  phẩm bị ảnh hưởng. `scripts/scope_pests.py`/`docs/scope-pests.md` (Task 7
  Step 3) đếm hoàn toàn theo `uses.crop`/`uses.pest`, KHÔNG dùng `ai_id` —
  không bị ảnh hưởng, đã hoàn thành bình thường (mục 6 dưới).

## 4. Known-issues đã xác nhận (không tính lỗi mới)

- **3 dòng rác nhãn (Exin×2, Jiabat×1):** không rơi vào mẫu 35 dòng chọn để
  đối chiếu sâu; đã xác nhận là known-issue từ trước theo brief, không tự
  tìm lại trong phạm vi QA này.
- **4 SP crop-dính-hậu-tố (Fucarb, Finlet, "chuột/ đồng ruộng", Rat K):**
  gặp `Finlet 2.5DP` trong mẫu 343 dòng lớn hơn (`Finlet 2.5DP | Warfarin |
  pages=[324] | [('đồng ruộng (min 95%)', 'chuột')]`) — xác nhận đúng
  known-issue (hậu tố "(min 95%)" của hoạt chất dính vào cột crop). AI
  ("Warfarin") của Finlet CHÍNH XÁC (entry #9 tr.324) — không liên quan cơ
  chế lỗi mục 3.
- **3 SP cụt đuôi registrant (Kasugacin, Mexyl MZ, Saicoba):** log
  `to_entries` xác nhận 3 SP này (+ Oshin, Ramsing, Jiathi, Kara-one) đi qua
  nhánh gộp mảnh trade ngắt trang khi chạy `qa_registry.py` — đúng known-issue,
  không phải lỗi mới.
- **Multi-slash pest/crop garble (~10.4% theo Task 4 report, KHÔNG có trong
  danh sách known-issue coordinator liệt kê nhưng đã tài liệu hoá từ Task 4):**
  gặp 3/35 dòng mẫu sâu (Afudan, Zenlovo, Chat 20WP) = 8.6%, khớp đúng ước
  tính cũ. Cơ chế: `split_targets` cố tình `rsplit("/", 1)` chỉ 1 lần khi ô
  target không có ";" phân cách — an toàn nhưng để lại dấu "/" thừa trong
  pest khi ô gộp nhiều cặp pest/crop mà PDF không có dấu ";". Ảnh hưởng: 1
  trong N cặp (crop,pest) của các sản phẩm này bị gán sai crop + pest lẫn
  dấu "/" — P1 cần biết khi tra cứu chính xác theo crop có thể bỏ sót các
  sản phẩm này.

## 5. Số đếm cuối theo status (từ machine_checks)

| status | Số sản phẩm |
|---|---|
| allowed | 6841 |
| banned | 31 |
| removed | 6 |
| **Tổng** | **6878** |

| doc_id | Thông tư | Số sản phẩm |
|---|---|---|
| 1 | 75/2025/TT-BNNMT | 6520 |
| 2 | 28/2026/TT-BNNMT | 358 |

2243 active_ingredients (tên distinct — con số này KHÔNG phản ánh đúng do lỗi
mục 3: nhiều tên hoạt chất "biến mất" khỏi danh sách vì bị nhóm sản phẩm kế
tiếp che khuất, một số tên khác bị lặp/kế thừa sai). 16026 uses.

## 6. Bước 3 — `scripts/scope_pests.py` / `docs/scope-pests.md`

Chạy bình thường, không phụ thuộc `ai_id` (xem mục 3.4) — xem
`docs/scope-pests.md` cho bảng dịch hại/cây scope. Đã đối chiếu cross-check:
2 cột `crop`/`pest` dùng để đếm KHÔNG nằm trong các dòng bị garble theo mục 4
ở mức ảnh hưởng đáng kể tới thứ hạng top-15 mỗi cây (garble ~10% rải rác,
không tập trung vào 1 cặp cây/dịch hại cụ thể).

## 7. Kết luận & khuyến nghị

**BLOCKED** cho việc P1 dùng `products.ai_id`/`active_ingredients` cho tới khi
Task 3/4 được làm lại với fix cho 2 cơ chế lỗi ở mục 3 (khuyến nghị: dùng
x-bounds cột toàn cục thay vì per-page cho bước khôi phục ô mất trong
`ingest/parse_annex.py`, cộng QA lại toàn bộ ~2243 nhóm hoạt chất bằng đối
chiếu tự động số trang/label thay vì mẫu tay). Registry vẫn AN TOÀN dùng cho
truy vấn theo `(crop, pest)` → danh sách `trade_name` hợp lệ (đường dùng
chính của P1 theo spec §5.1 "Structured path") — chỉ trường hiển thị "hoạt
chất" đi kèm cần được coi là KHÔNG ĐÁNG TIN cho tới khi fix.

### Concerns

1. **Mức độ nghiêm trọng cao hơn dự kiến ban đầu của Task 7** — brief chỉ kỳ
   vọng ~2% lỗi biên; phát hiện thực tế là lỗi hệ thống ảnh hưởng ước tính
   26–38% Phụ lục I. Cần ưu tiên fix trước khi làm Task 8/9 nếu các task đó
   phụ thuộc tên hoạt chất hiển thị cho người dùng (labels.db ở Task 9 tra
   theo `product_id`, không theo `ai_id`, nên KHÔNG bị chặn bởi lỗi này —
   nhưng nếu labels.db hoặc UI có hiển thị "hoạt chất: X" lấy từ registry.db
   thì sẽ hiển thị sai cho các sản phẩm bị ảnh hưởng).
2. Chưa định lượng đầy đủ cơ chế lỗi #2 (dịch cột do ký tự dấu) — chỉ xác
   nhận 1 trường hợp cụ thể (Yanibin), có thể còn nơi khác.
3. `active_ingredients` bảng hiện có nhiều tên "hoạt chất" thực chất là
   entry bị mất → dùng nhầm cho các nhóm sau — số 2243 tên distinct hiện tại
   không phải con số tin cậy để báo cáo "tổng số hoạt chất trong danh mục".
4. Trùng lặp 34 sản phẩm (mục 1.1) — không chặn nhưng cần P1 khử trùng khi
   đếm "tổng số sản phẩm khác nhau" (dùng DISTINCT trade_name+formulation
   thay vì COUNT(*) nếu cần con số tổng).

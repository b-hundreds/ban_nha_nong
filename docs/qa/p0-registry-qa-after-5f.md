# P0 Registry QA — sau Task 5f (fix x-bounds toàn tài liệu)

Nguồn: `data/registry.db` rebuild sau Task 5f (HEAD trước khi commit fix này:
`5549150`). Registry sau fix: **6883 products / 16045 uses / 2327
active_ingredients** (trước fix: 6878/16026/2243). Đối chiếu tay bằng
`pdfplumber` trực tiếp trên `data/raw/tt75_2025_page_1.pdf` (Phụ lục I).

## 1. Fix đã áp dụng (tóm tắt — chi tiết ở `.superpowers/sdd/task-5f-fix-report.md`)

`ingest/parse_annex.py`:
1. **x-bounds cột toàn tài liệu**: `parse_pdf` tính x-bounds 1 lần từ hàng
   tiêu đề bảng thật (trang 0 Phụ lục I) rồi cache, truyền cho
   `_recover_missing_leading_cells` ở MỌI trang sau — thay vì chỉ dò cục bộ
   từng trang (chỉ trang 0 có header → khôi phục tắt ở >99% số trang).
2. **Hàng "thiếu hẳn cột"**: mở rộng khôi phục cho trường hợp
   `len(row.cells) < 5` toàn trang (không chỉ `cells[0] is None`) — kèm
   guard bắt buộc "phủ trọn phần đuôi bảng" để loại các ô phụ do
   `find_tables()` dò lặp (ca giả `Oncol` tr.38).
3. **`_merge_split_columns`** (mới): gộp lại ô bị tách do lưới cột lỗi bằng
   ánh xạ theo x-bounds tài liệu (không theo chỉ số vị trí thô) — sửa cơ
   chế lỗi #2 (Yanibin/Conabin) + loại ô LỒNG NHAU (artefact dò-lặp gây
   nối trùng, ca giả `Rasger 20DP` tr.324).
4. **Guard cột-0 bắt buộc**: chỉ chấp nhận khôi phục khi CẢ số mục (tt) VÀ
   hoạt chất (ai) cùng đọc được — chặn trường hợp ô hoạt chất 2 dòng tràn
   sang đúng y-range của hàng tiếp diễn kế tiếp (ca giả `Asiamycin super
   100SL` tr.264, chỉ dòng 2 của ô hoạt chất "835" tràn xuống).

## 2. Xác nhận 13 dòng lỗi của Task 7 (`docs/qa/p0-registry-qa.md` mục 2)

| # | Sản phẩm | AI SAI (trước fix) | AI ĐÚNG (sau fix) | Đối chiếu PDF |
|---|---|---|---|---|
| 3 | Makozeb-RBC 80WP | Laminarin (min 86%) | **Mancozeb (min 85%)** | tr.227 #627 ✅ |
| 5 | TVG28 650SP | Natural rubber | **Nitenpyram (min 95%)** | tr.123 #799 ✅ |
| 13 | Danrat 0.005RB | Barium sulfate 20%+Difennuozhi 0.02% | **Brodifacoum (min 91%)** | tr.321 mục "4." #2 ✅ |
| 14 | Pylacol 700WP | Propiconazole 10.7%+Tricyclazole 34.2% | **Propineb (min 80%)** | tr.245-246 #741 ✅ |
| 15 | Bayluscide 70WP | Metaldehyde 140g/kg+Pyridaben 10g/kg | **Niclosamide (min 96%)** | tr.343 #20 ✅ |
| 19 | Ratgone 0.005DR | Barium sulfate 20%+Difennuozhi 0.02% | **Bromadiolone (min 97%)** | tr.322-323 mục "4." #3 ✅ |
| 22 | Clatinusa 500EC | Oxymatrine (min 98%) | **Permethrin (min 92%)** (mới dò được — Task 7 chưa dò ra) | tr.125 #815 ✅ |
| 23 | Yanibin 75WG | Conabin 750WG (= tên thương phẩm khác) | **Tebuconazole 500g/kg(50%)+Trifloxystrobin 250g/kg(25%)** | tr.256-257 #801 ✅ (cơ chế 2) |
| 25 | Anfaza 350SC | Thiacloprid (min 95%) | **Thiamethoxam (min 95%)** | tr.142 #892 ✅ |
| 28 | Windy 200SL | Fomesafen 12%+Quizalofop-P-ethyl 3% | **Glufosinate ammonium (min 95%)** | tr.296-303 #203 ✅ (147 SP) |
| 32 | No-ocbuuvang 750WP | Metaldehyde 140g/kg+Pyridaben 10g/kg | **Niclosamide (min 96%)** | tr.343-344 #20 ✅ |
| 34 | Spiromax 300SC | Spinetoram 120g/kg+Triflumezopyrim 100g/kg | **Spirodiclofen (min 98%)** (mới dò được — Task 7 chưa dò ra) | tr.137-138 #872 ✅ |
| 35 | Baragren 480SL | Bensulfuron-methyl 40g/kg+Quinclorac 560g/kg | **Bentazone (min 96%)** | tr.276 #75 ✅ |

**13/13 khớp đúng PDF sau fix** (kể cả 2 dòng Task 7 chưa dò ra được mã đúng:
Clatinusa, Spiromax). Windy = "Glufosinate ammonium (min 95%)", nhóm **147
sản phẩm** (Ace gluffit → Zippi, tr.296-303) — khớp ước tính Task 7.

## 3. Re-sample QA MỚI — 30 dòng, seed=29 (khác seed=17 của Task 7)

`sample(conn, 30/6883, seed=29)` → 30 dòng. 18/30 là hàng ĐẦY ĐỦ (tt/ai đọc
trực tiếp từ PDF, không qua khôi phục — tin cậy tuyệt đối). 11/30 là hàng
tiếp diễn (cần đối chiếu nhóm hoạt chất bằng crop x-bounds trực tiếp trên
PDF, độc lập với parser đang review). 1/30 nguồn TT28 (CSV, không phải PDF
TT75 — ngoài phạm vi cơ chế lỗi đang fix).

| # | Sản phẩm (id) | AI trong DB | Loại hàng | Đối chiếu PDF | Kết luận |
|---|---|---|---|---|---|
| 1 | Dino-top 300WP (714) | Buprofezin 180g/kg+Dinotefuran 120g/kg | Đầy đủ | tr.45 #296 | ✅ |
| 2 | Mancobaca 80WP (4022) | Mancozeb (min 85%) | Đầy đủ | tr.227 | ✅ |
| 3 | Visumit 50EC (1669) | Fenitrothion (min 95%) | Tiếp diễn | tr.98 #645 (Factor→…→Visumit) | ✅ |
| 4 | Ni-tin 300EC (3248) | Difenoconazole 150g/l+Propiconazole 150g/l | Đầy đủ | tr.185 | ✅ |
| 5 | Starsuper 21SL (3938) | Kasugamycin 9g/l…+Polyoxin 1g/l… | Đầy đủ | tr.222 #588 | ✅ |
| 6 | Xeletsupe 24EC (5116) | Clethodim (min 91.2%) | Tiếp diễn | tr.284 #122 (Cetoxim→…→Xeletsupe) | ✅ |
| 7 | SV Hebula 66.5SL (4314) | Propamocarb.HCl (min 92%) | Tiếp diễn | tr.243 #724 (Hussa→…→SV Hebula) | ✅ |
| 8 | Eifelgold 415SC (3824) | Isoprothiolane 10.5g/l…+Propineb…+Tricyclazole… | Đầy đủ | tr.216 #551 | ✅ |
| 9 | Latimo super 500WP (3312) | Difenoconazole 50g/kg…+Tebuconazole…+Tricyclazole… | Đầy đủ | tr.188 #359 | ✅ |
| 10 | Daiwanper 300EC (3236) | Difenoconazole 150g/l+Propiconazole 150g/l | Tiếp diễn | tr.184 #328 (Acsupertil→…→Daiwanper — entry #328, KHÔNG phải #327 liền kề; xác nhận bằng crop x-bounds, không phải suy đoán từ dump thô) | ✅ |
| 11 | TCT Sieu 240SC (2132) | Methoxyfenozide (min 95%) | Tiếp diễn | tr.122 #791 (Gold Wing→TCT Sieu) | ✅ |
| 12 | Super soil 345WP (5162) | Cyhalofop-butyl 315g/kg+Ethoxysulfuron 30g/kg | Đầy đủ | tr.286 #133 | ✅ |
| 13 | Hacydo 20SC (1119) | Cypermethrin 10%+Indoxacarb 10% | Đầy đủ | tr.67 #489 | ✅ |
| 14 | Sirius 70WG (5737) | Pyrazosulfuron-ethyl (min 97%) | Tiếp diễn | tr.315 #281 (Aicerus→Sirius) | ✅ |
| 15 | Mifum 0.6SL (2935) | Chitosan tan 0.5%+Nano Ag 0.1% | Đầy đủ | tr.166 #180 | ✅ |
| 16 | Nofami 10SC (5007) | Bispyribac-sodium (min 93%) | Tiếp diễn | tr.279 #85 (Danphos→…→Nofami, nhóm lớn) | ✅ |
| 17 | Lục diệp tố 1SL (6106) | Gibberellic acid 1g/l+NPK 9g/l+Vi lượng | Đầy đủ | tr.333 #34 | ✅ |
| 18 | Mectinstar 20EC (1582) | Emamectin benzoate 19g/l…+Matrine 1g/l… | Đầy đủ | tr.93 #601 | ✅ |
| 19 | Oxdie 702WP (6347) | Niclosamide 680g/kg+Carbaryl 22g/kg | Đầy đủ | tr.346 #26 | ✅ |
| 20 | Rosazone 60EC (5075) | Butachlor 50%+Oxadiazon 10% | Đầy đủ | tr.282 #104 | ✅ |
| 21 | Oxili 320SC (3497) | Fluopicolide 80g/l+Oxine Copper 240g/l | Đầy đủ | tr.199 #446 | ✅ |
| 22 | Abatin 5.4EC (16) | Abamectin (min 90%) | Đầy đủ | tr.1 | ✅ |
| 23 | Pyan-Plus 5.8EC (5313) | Fenoxaprop-P-Ethyl 8g/l+Pyribenzoxim 50g/l | Đầy đủ | tr.294 #180 | ✅ |
| 24 | Osago 80WG (2176) | Nitenpyram 20%(200g/kg)+Pymetrozine 60%(600g/kg) | Tiếp diễn | tr.124 #801 (ADU-Matty→Osago) | ✅ |
| 25 | NP Pheta 3.6EC (92) | Abamectin (min 90%) | Đầy đủ | tr.6 | ✅ |
| 26 | Emagold 6.5WG (1409) | Emamectin benzoate (Avermectin B1a 90%+B1b 10%) (min 70%) | Đầy đủ | tr.83 | ✅ |
| 27 | Ngonta 250SC (2758) | Azoxystrobin 200g/l+Kasugamycin 50g/l | Tiếp diễn | tr.156 #86 (Hottawa→Ngonta) | ✅ |
| 28 | Slimgold 510SC (4849) | Ametryn (min 96%) | Tiếp diễn (bắc cầu trang 270→271) | tr.270-271 #19 (Amesip→Phu Quy Do→Slimgold) | ✅ |
| 29 | Abvertin 3.6EC (22) | Abamectin (min 90%) | Đầy đủ | tr.1 | ✅ |
| 30 | Arobate MD 69WP (6727) | Dimethomorph 9%+Mancozeb 60% | Nguồn TT28 (CSV) | TT28 PL.II mục 2 tr.11 | ✅ (ngoài phạm vi cơ chế PDF) |

**Tỉ lệ lỗi mới = 0/30 = 0% ≤ ngưỡng 2% → PASS.** Lưu ý dòng #10 (Daiwanper)
là trường hợp cần crop x-bounds thật mới xác định đúng nhóm (#328, không
phải #327 liền kề nhìn thấy trên dump chữ thô) — đúng loại lỗi mà fix này
nhắm tới, chứng minh fix hoạt động đúng ở 1 ca KHÔNG nằm trong 13 ca đã biết
trước.

## 4. Cơ chế lỗi #2 (dịch cột do dấu tiếng Việt / ô lồng nhau) — định lượng

So sánh `active_ingredients.name_common` giữa registry TRƯỚC và SAU fix,
lọc các tên trùng với 1 `trade_name` có sẵn hoặc tận cùng bằng mã quy cách
(dấu hiệu chắc chắn là tên thương phẩm bị lọt vào ô hoạt chất):

| | Trước fix | Sau fix |
|---|---|---|
| Tên hoạt chất trùng ĐÚNG 1 trade_name có sẵn | 0 | 0 |
| Tên hoạt chất tận cùng bằng mã quy cách (regex `_FORM_RE`) | **3** (`Oncol 5GR, 20EC, 25WP`; `Conabin 750WG`; `Rasger 20DP`) | **0** |
| Số sản phẩm bị ảnh hưởng bởi 3 tên trên | **31** (Oncol nhóm 20 SP + Conabin/Yanibin nhóm 8 SP + Rasger nhóm 3 SP) | 0 |

Toàn văn bản Phụ lục I + II: quét lại bằng script chẩn đoán tách-nửa-chuỗi
(kiểm mọi trường `trade`/`target`/`registrant` sau merge có bị nối trùng
X+X không) → **0 điểm** còn sót sau fix (trước khi thêm guard ô-lồng-nhau,
phát hiện 2 điểm bổ sung ngoài Yanibin: `Sunbishi 10SC` trang 279 và
`Rasger 20DP` trang 324 — cả 2 đã fix bằng cơ chế loại-bbox-lồng-nhau, xem
báo cáo task-5f-fix-report.md mục cơ chế 2b).

**Kết luận cơ chế 2:** không còn 1/13 (Yanibin) mà là **3 điểm xác nhận
độc lập** (Yanibin/Conabin, Oncol, Rasger) — cả 3 đều đã sửa bằng chính
`_merge_split_columns` (ánh xạ theo x-bounds + loại bbox lồng nhau), không
cần cơ chế riêng biệt.

## 5. Kết luận

**KHÔNG CÒN BLOCKED.** `products.ai_id`/`active_ingredient` tin cậy để dùng
ở P1 — 13/13 lỗi Task 7 đã sửa đúng theo PDF, re-sample 30 dòng mới (seed
khác) tỉ lệ lỗi 0% (≤ ngưỡng 2%), 3 điểm cơ chế 2 đã định lượng và sửa hết,
quét toàn văn bản không còn nối trùng chuỗi hay tên thương phẩm lọt vào ô
hoạt chất.

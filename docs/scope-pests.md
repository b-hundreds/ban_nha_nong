# Scope dịch hại — Task 7

Chốt danh sách (cây, dịch hại) chính thức cho demo (spec §3: lúa — An Giang;
cà phê + sầu riêng — Đắk Lắk). Căn cứ: `scripts/scope_pests.py` (đếm số sản
phẩm `allowed` đăng ký theo `uses.crop`/`uses.pest` trong `data/registry.db`)
+ hiểu biết nông học cho các dịch hại quan trọng nhưng ít sản phẩm đăng ký
riêng lẻ trong danh mục. **Không phụ thuộc cột `active_ingredient`/`ai_id`**
— xem `docs/qa/p0-registry-qa.md` mục 3 về lỗi hệ thống ở cột đó (không ảnh
hưởng dữ liệu `crop`/`pest` dùng ở đây).

Đã lọc bỏ khỏi bảng dưới: (a) mục "kích thích sinh trưởng"/"điều hoà sinh
trưởng" — đây là công dụng (chất điều hoà sinh trưởng), không phải dịch hại;
(b) các dòng dính garble rõ ràng (pest hoặc crop còn sót dấu "/", vd "rầy
nâu/ lúa" lẫn trong danh sách cà phê, hay "chết nhanh/ hồ tiêu" lẫn trong sầu
riêng — hệ quả known-issue mục 4 QA report, thuộc về cặp cây/dịch hại KHÁC bị
gộp nhầm crop, không phải dịch hại thật của cây đang xét).

Cột **"Curate label" (Task 9)** đánh dấu mức ưu tiên đưa vào `labels.db`
(curate liều lượng tay, spec §5.2, mục tiêu ~150–200 SP toàn scope, tối thiểu
~80 SP nếu cắt giảm theo kế hoạch P0 — ưu tiên lúa + cà phê nếu thiếu thời
gian): **Có** = ưu tiên curate ngay (nhóm định lượng của eval v0); **Dự
phòng** = curate nếu còn thời gian/người sau khi xong nhóm ưu tiên.

## Lúa (An Giang)

`scripts/scope_pests.py` — top sản phẩm đăng ký theo dịch hại (status=allowed):

```
 637  sâu cuốn lá
 621  rầy nâu
 541  đạo ôn
 448  lem lép hạt
 257  bọ trĩ
 235  khô vằn
 223  nhện gié
 213  sâu đục thân
 203  bạc lá
 180  ốc bươu vàng
  35  cỏ
```

| # | Dịch hại (canonical) | SP đăng ký | Curate label |
|---|---|---:|---|
| 1 | Sâu cuốn lá (*Cnaphalocrocis medinalis*) | 637 | Có |
| 2 | Rầy nâu (*Nilaparvata lugens*) | 621 | Có |
| 3 | Đạo ôn (*Pyricularia oryzae*, gồm đạo ôn lá + cổ bông) | 541 | Có |
| 4 | Lem lép hạt | 448 | Có |
| 5 | Bọ trĩ | 257 | Có |
| 6 | Khô vằn (*Rhizoctonia solani*) | 235 | Có |
| 7 | Nhện gié | 223 | Có |
| 8 | Sâu đục thân | 213 | Có |
| 9 | Bạc lá (*Xanthomonas oryzae*) | 203 | Dự phòng |
| 10 | Ốc bươu vàng | 180 | Dự phòng |
| 11 | Cỏ (nhóm thuốc trừ cỏ tiền/hậu nảy mầm) | 35 (riêng "cỏ"; nhóm trừ cỏ thực tế lớn hơn nhiều, phân theo "lúa gieo thẳng"/"lúa cấy" là chủ yếu) | Dự phòng |

## Cà phê (Đắk Lắk)

```
 235  rỉ sắt
 215  rệp sáp
 178  cỏ
 123  thán thư
  50  tuyến trùng
  38  nấm hồng
  14  nhện đỏ
  12  rệp vảy
   9  mọt đục cành
   9  sâu đục quả
   8  rầy xanh
   7  rệp vảy xanh
```
(đã bỏ 2 dòng garble "rầy nâu/ lúa" (15) và "lem lép hạt/ lúa" (10) — thực
chất là cặp (rầy nâu, lúa)/(lem lép hạt, lúa) bị gộp nhầm crop="cà phê" do
lỗi split_targets khi ô target không có ";", xem QA mục 4.)

| # | Dịch hại (canonical) | SP đăng ký | Curate label |
|---|---|---:|---|
| 1 | Rỉ sắt (*Hemileia vastatrix*) | 235 | Có |
| 2 | Rệp sáp (rễ + quả) | 215 | Có |
| 3 | Cỏ dại | 178 | Có |
| 4 | Thán thư (*Colletotrichum*) | 123 | Có |
| 5 | Tuyến trùng rễ | 50 | Có |
| 6 | Nấm hồng (*Corticium salmonicolor*) | 38 | Có |
| 7 | Nhện đỏ | 14 | Dự phòng |
| 8 | Rệp vảy (xanh + nâu, gộp) | 12 + 7 = 19 | Dự phòng |
| 9 | Mọt đục cành (*Xylosandrus*) | 9 | Dự phòng |
| 10 | Sâu đục quả | 9 | Dự phòng |
| 11 | Rầy xanh | 8 | Dự phòng |

## Sầu riêng (Đắk Lắk)

```
  19  xì mủ
  16  thán thư
   6  thối quả
   5  rệp sáp
   4  nứt thân xì mủ
   3  thối rễ
   2  ghẻ loét
   2  nhện đỏ
   2  phấn trắng
   2  rầy nhảy
   2  rầy xanh
   2  sâu ăn lá
   2  thối thân xì mủ
   2  thối trái
   2  xì mủ thân
   1  sâu đục quả
```
(đã bỏ ~15 dòng count=1 rõ ràng garble — pest/crop của cây KHÁC bị gộp nhầm
crop="sầu riêng", vd "rỉ sắt/cà phê", "loét sọc mặt cạo/cao su",
"mốc sương/dưa hấu"... — cùng known-issue mục 4 QA report. Gộp các biến thể
"xì mủ"/"nứt thân xì mủ"/"thối thân xì mủ"/"xì mủ thân"/"chảy gôm"/"chảy
mủ"/"nứt thân chảy nhựa"/"bệnh do nấm phythophthora" thành 1 dịch hại canonical
— cùng tác nhân *Phytophthora palmivora*, tổng 31 lượt đăng ký.)

Danh mục đăng ký cho sầu riêng trong TT75/TT28 còn mỏng (sầu riêng là cây bổ
sung gần đây so với lúa/cà phê) — bảng dưới bổ sung 1 dịch hại quan trọng theo
nông học dù số đăng ký thấp (đã có trong dữ liệu, count=1: "sâu đục quả",
đúng như sâu đục trái *Conogethes punctiferalis* mà nông dân hay hỏi).

| # | Dịch hại (canonical) | SP đăng ký | Curate label |
|---|---|---:|---|
| 1 | Xì mủ / chảy nhựa thân, xì mủ trái (*Phytophthora palmivora*, gộp biến thể) | 31 | Có |
| 2 | Thán thư (*Colletotrichum*) | 16 | Có |
| 3 | Thối quả/thối trái (gộp) | 6 + 2 = 8 | Có |
| 4 | Rệp sáp | 5 | Có |
| 5 | Thối rễ | 3 | Dự phòng |
| 6 | Ghẻ loét | 2 | Dự phòng |
| 7 | Nhện đỏ | 2 | Dự phòng |
| 8 | Phấn trắng | 2 | Dự phòng |
| 9 | Rầy nhảy | 2 | Dự phòng |
| 10 | Rầy xanh | 2 | Dự phòng |
| 11 | Sâu ăn lá | 2 | Dự phòng |
| 12 | Sâu đục quả/trái (*Conogethes punctiferalis*) | 1 (đăng ký thưa — cần đối chiếu thêm nguồn khuyến nông Đắk Lắk khi curate) | Dự phòng |

## Ghi chú ưu tiên curate (Task 9)

Theo kế hoạch cắt giảm P0 ("nếu thiếu người/thời gian: ... 1 tỉnh/vùng thay vì
2 ... labels.db còn 80 SP phủ lúa + cà phê"), **sầu riêng là nhóm bị cắt đầu
tiên** nếu nguồn lực hạn chế — vì vậy cột Curate label ở sầu riêng thiên về
"Dự phòng" hơn 2 cây kia; 4 dịch hại đầu (xì mủ, thán thư, thối quả, rệp sáp)
vẫn nên ưu tiên vì đây là các bệnh/dịch hại kinh tế quan trọng nhất của sầu
riêng theo thực tế canh tác Đắk Lắk, không chỉ theo số đếm đăng ký.

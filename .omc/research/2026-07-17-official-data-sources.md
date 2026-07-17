# Research: Catalog nguồn chính thống VN cho grounding trợ lý nông nghiệp

> Nguồn: agent data-sources-research, 17/07/2026. Phục vụ design doc trợ lý nông nghiệp voice-first VNAI.

**Bối cảnh cơ quan (đã xác minh):** Từ 3/2025, Bộ NN&PTNT + Bộ TN&MT hợp nhất thành **Bộ Nông nghiệp và Môi trường** (mae.gov.vn); Cục Trồng trọt + Cục BVTV hợp nhất thành **Cục Trồng trọt và Bảo vệ thực vật** (ppd.gov.vn). Văn bản mới ký hiệu `TT-BNNMT`; văn bản cũ `BNNPTNT`/`QĐ-BNN-*` vẫn hiệu lực nếu chưa bị thay thế.

## Nhóm 1 — Danh mục thuốc BVTV (lõi pháp lý)

**Hiệu lực hiện hành (17/07/2026): Thông tư 75/2025/TT-BNNMT** ngày 26/12/2025, hiệu lực **10/02/2026**. Chuỗi thay thế: TT 09/2023 → TT 25/2024/TT-BNNPTNT (16/12/2024) → TT 03/2025/TT-BNNMT (16/5/2025) → **TT 75/2025**. Sắp tới: **TT 28/2026/TT-BNNMT** (30/6/2026, hiệu lực **15/08/2026**) sửa đổi TT 75/2025: đổi đăng ký ~20 sản phẩm, 5 rút tự nguyện, thêm 3 hoạt chất + ~30 thuốc sinh học, 6 thuốc được phun drone. → Pipeline phải ingest cả văn bản sửa đổi + **versioning theo ngày hiệu lực**.

- **Tải (đã kiểm tra):** ppd.gov.vn có 3 PDF (thông tư + Phụ lục I được phép + Phụ lục II cấm): https://ppd.gov.vn/tin-moi-nhat-289/thong-tu-so-752025tt-bnnmt-ban-hanh-danh-muc-thuoc-bao-ve-thuc-vat-duoc-phep-su-dung-tai-viet-nam-va-danh-muc-thuoc-bao-ve-thuc-vat-cam-su-dung-tai-viet-nam.html ; bản Cổng Chính phủ (không chặn bot): https://vanban.chinhphu.vn/?docid=216337&pageid=27160 ; TT 28/2026: https://luatvietnam.vn/nong-nghiep/thong-tu-28-2026-tt-bnnmt-danh-muc-thuoc-bao-ve-thuc-vat-tai-viet-nam-439351-d1.html ; phụ lục PDF text: https://datafiles.chinhphu.vn/cpp/files/duthaovbpl/2026/Thang4/2.1.-phu-luc-kem-theo-thong-tu.pdf
- **Cấu trúc cột (xác minh trực tiếp):** `TT | Hoạt chất (common name) | Tên thương phẩm | Đối tượng phòng trừ (dịch hại/cây trồng) | Tổ chức đăng ký`. Một thương phẩm có nhiều dạng chế phẩm (50WP, 450EC…). Phụ lục I chia mục (trừ sâu/bệnh/cỏ/chuột, ĐHST, dẫn dụ, trừ ốc, hỗ trợ; trừ mối; bảo quản lâm sản; khử trùng kho; sân golf; xử lý hạt giống; bảo quản nông sản). **PDF text-based** → pdfplumber/Camelot parse được, cần xử lý ô gộp + QA tay; không có Excel chính thức công khai.
- **LIỀU LƯỢNG: Danh mục KHÔNG chứa liều.** Liều, nồng độ, PHI nằm trên **nhãn thuốc được duyệt theo GCN đăng ký** (khung: TT 21/2015/TT-BNNPTNT, sửa đổi nhiều lần — bản hợp nhất trên vbpl.vn; toàn văn: https://vanban.chinhphu.vn/default.aspx?pageid=27160&docid=180383 ). Nguồn chính thống duy nhất tổng hợp liều: **CSDL tra cứu thuốc BVTV quốc gia** (Cục BVTV + IDH) — app "Thuốc BVTV" (iOS/Android) + cổng https://sansangxuatkhau.ppd.gov.vn/thuoc-va-phan-bon/phan-mem-tra-cuu-thuoc-bao-ve-thuc-vat-quoc-gia.html — tra theo cây/dịch hại, trả thuốc kèm liều + PHI. **Không có API/bulk download công khai.**

## Nhóm 2 — Quy trình kỹ thuật canh tác (PDF/DOC text, tải tự do)

- **Lúa:** QĐ 145/QĐ-TT-CLT 27/3/2024 — lúa chất lượng cao phát thải thấp ĐBSCL (Cục TT + IRRI): https://thuvienphapluat.vn/van-ban/Linh-vuc-khac/Quyet-dinh-145-QD-TT-CLT-2024-huong-dan-Quy-trinh-ky-thuat-san-xuat-lua-chat-luong-cao-613332.aspx ; sổ tay: https://khuyennongvn.gov.vn/thu-vien-khuyen-nong/thu-vien-sach-kn/so-tay-huong-dan-quy-trinh-ky-thuat-san-xuat-lua-chat-luong-cao-va-phat-thai-thap-vung-dong-bang-song-cuu-long-24341.html . Nền tảng "1 phải 5 giảm", "3 giảm 3 tăng".
- **Sầu riêng:** QĐ 1899 ngày 30/6/2025 của Cục TT&BVTV: http://khuyennongtphcm.vn/wp-content/uploads/2025/07/30.6.2025-Quy-tr%C3%ACnh-s%E1%BA%A7u-ri%C3%AAng-Final-IN.pdf
- **Cà phê:** QĐ 2085/QĐ-BNN-TT 2016 (tái canh): https://thuvienphapluat.vn/van-ban/Linh-vuc-khac/Quyet-dinh-2085-QD-BNN-TT-Quy-trinh-tai-canh-ca-phe-voi-2016-331013.aspx ; QĐ 3702/QĐ-BNN-TT 2018 (trồng xen); QĐ 318/QĐ-TT-CCN 2023 (tiết kiệm vật tư); WASI 2020: http://wasi.org.vn/wp-content/uploads/2021/11/QUYET-DINH-BAN-HANH-QUY-TRINH-TAI-CANH-CA-PHE-VOI-2020.pdf
- **Hồ tiêu:** QĐ 730/QĐ-BNN-TT 2015: https://hethongphapluat.com/quyet-dinh-730-qd-bnn-tt-nam-2015-ve-quy-trinh-ky-thuat-trong-cham-soc-va-thu-hoach-ho-tieu-do-bo-nong-nghiep-va-phat-trien-nong-thon-ban-hanh.html/
- **IPM/IPHM:** QĐ 3592/QĐ-BNN-BVTV 2022 + QĐ 5416/QĐ-BNN-BVTV (Đề án IPHM 2030): https://ppd.gov.vn/tin-moi-nhat-289/quyet-dinh-so-5416qd-bnn-bvtv-phe-duyet-de-an-phat-trien-quan-ly-suc-khoe-cay-trong-tong-hop-iphm-den-nam-2030.html
- **TCVN 13268:2021** (điều tra sinh vật gây hại), DOC: https://sansangxuatkhau.ppd.gov.vn/FileUpload/Documents/tcvn_1326842021__nhom_cay_an_qua__final_3032021doc.doc

## Nhóm 3 — Khuyến nông

**khuyennongvn.gov.vn** (TT Khuyến nông QG, thuộc Bộ NN&MT): Kỹ thuật thực hành, Thư viện số, HTML sạch + PDF, cập nhật hằng ngày, dễ crawl. Cấp tỉnh: khuyennong.lamdong.gov.vn, khuyennongtphcm.vn… **Mức chính thống:** kênh nhà nước, đủ trích *khuyến cáo kỹ thuật*; KHÔNG phải VBQPPL — nội dung thuốc/liều phải đối chiếu về Danh mục + nhãn.

## Nhóm 4 — Dữ liệu theo vùng, theo thời gian

- **Bản tin sinh vật gây hại 7 ngày** (Cục TT&BVTV): https://www.ppd.gov.vn/thong-bao-tinh-hinh-svgh-7-ngay.html — hằng tuần, DOC/PDF dạng tự do (trích text + metadata tuần/vùng). Chi cục tỉnh có bản tin riêng (vd ccttbvtvdaklak.gov.vn).
- **Lịch thời vụ: KHÔNG có cổng tập trung.** Cục công bố khung vùng (vd ĐBSCL ĐX 2025–26 xuống giống sớm 10–30/10: https://baocantho.com.vn/dam-bao-an-toan-san-xuat-lua-dong-xuan-2025-2026-a191568.html ); mỗi Sở NN&MT tỉnh ra công văn mỗi vụ, PDF rải rác trên cổng tỉnh — đã xác minh: Huế https://snnmt.hue.gov.vn/trong-trot-bao-ve-thuc-vat/huong-dan-lich-thoi-vu-gieo-trong-vu-dong-xuan-2025-2026.html , Hải Phòng, Quảng Ngãi, Tuyên Quang. Một phần scan → OCR + nhập tay thành bảng (tỉnh/vụ/cây/mốc ngày).
- **Xâm nhập mặn ĐBSCL:** Viện KH Thủy lợi miền Nam bản tin tuần: http://www.siwrr.org.vn/?gid=93 (*site lỗi SSL — crawler phải bỏ verify*); kênh song song đã mở được: https://vawr.org.vn/du-bao-xam-nhap-man-mua-kho-vung-ven-bien-dong-bang-song-cuu-long ; nchmf.gov.vn (chưa xác minh chuyên mục).

## Nhóm 5 — CSDL văn bản pháp luật

- **vanban.chinhphu.vn** — PDF gốc kèm phụ lục, không chặn bot → **nguồn tải chuẩn khuyến nghị**.
- **vbpl.vn** — tra trạng thái hiệu lực + bản hợp nhất; khó deep-link.
- thuvienphapluat.vn / luatvietnam.vn — chặn bot (403), file trả phí → chỉ đối chiếu.
- datafiles.chinhphu.vn (phụ lục), spsvietnam.gov.vn.

## Kết luận pháp lý cho LIỀU LƯỢNG + khoảng trống

1. **Đủ pháp lý trích:** "thuốc X (hoạt chất Y) được phép/cấm cho dịch hại Z trên cây T" — căn cứ TT 75/2025 (+ TT 28/2026 từ 15/8/2026), PDF gốc ppd.gov.vn / vanban.chinhphu.vn. Ingest thành **bảng cấu trúc** (hoạt chất, thương phẩm, dạng chế phẩm, dịch hại, cây, nhà đăng ký, văn bản nguồn + ngày hiệu lực), có versioning.
2. **Liều KHÔNG nằm trong Thông tư** — chuẩn pháp lý là nhãn được duyệt (khung TT 21/2015). Chỉ phát ngôn liều khi có dữ liệu nhãn/CSDL quốc gia; nếu không → "theo liều trên nhãn" + khuyến cáo quy trình. **Khoảng trống #1: CSDL quốc gia không có API/bulk** → thu thập nhãn từng sản phẩm cho scope demo + rà soát tay.
3. Khoảng trống khác: danh mục chỉ PDF (trích bảng + QA tay); lịch thời vụ phân tán tỉnh, một phần scan; bản tin SVGH dạng DOC tự do; siwrr.org.vn hỏng SSL.

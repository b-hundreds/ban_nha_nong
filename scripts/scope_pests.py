"""In top dịch hại theo số sản phẩm đăng ký cho 3 cây scope (lúa, cà phê, sầu
riêng) → làm căn cứ chốt docs/scope-pests.md.

Lưu ý (Task 7 QA, xem docs/qa/p0-registry-qa.md): registry.db có lỗi hệ
thống ở cột active_ingredient (ai_id) cho một phần lớn sản phẩm Phụ lục I
(TT75) — KHÔNG ảnh hưởng script này, vì đếm ở đây dựa hoàn toàn vào
`uses.crop`/`uses.pest` (đã xác nhận đúng qua toàn bộ mẫu QA), không đụng
tới `products.ai_id`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.backend.db import connect  # noqa: E402

conn = connect()
for crop in ("lúa", "cà phê", "sầu riêng"):
    print(f"\n== {crop} ==")
    for pest, n in conn.execute(
        """SELECT u.pest, COUNT(DISTINCT u.product_id) n FROM uses u
           JOIN products p ON p.id=u.product_id AND p.status='allowed'
           WHERE u.crop=? GROUP BY u.pest ORDER BY n DESC LIMIT 15""", (crop,)):
        print(f"{n:4d}  {pest}")

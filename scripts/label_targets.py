"""In danh sách (cây, dịch hại, sản phẩm) cần tra liều, ưu tiên theo scope-pests.

SCOPE chép đúng từ docs/scope-pests.md (Task 7) — chỉ các dòng cột
"Curate label" = "Có" (nhóm ưu tiên curate ngay, spec §5.2):
  - Lúa: 8 dịch hại đầu (sâu cuốn lá, rầy nâu, đạo ôn, lem lép hạt, bọ trĩ,
    khô vằn, nhện gié, sâu đục thân)
  - Cà phê: 6 dịch hại đầu (rỉ sắt, rệp sáp, cỏ dại, thán thư, tuyến trùng
    rễ, nấm hồng)
  - Sầu riêng: 4 dịch hại đầu (xì mủ + biến thể, thán thư, thối quả/thối
    trái, rệp sáp) — các biến thể "xì mủ" (nứt thân xì mủ/thối thân xì
    mủ/xì mủ thân/bệnh do nấm phythophthora) và "thối quả"/"thối trái" được
    gộp vì cùng 1 dịch hại canonical (xem docs/scope-pests.md).

Mỗi mục SCOPE là (crop, [danh sách pest string thực tế trong uses.pest]).
"""
from app.backend.db import connect, lookup_products

SCOPE = [
    ("lúa", ["sâu cuốn lá"]),
    ("lúa", ["rầy nâu"]),
    ("lúa", ["đạo ôn"]),
    ("lúa", ["lem lép hạt"]),
    ("lúa", ["bọ trĩ"]),
    ("lúa", ["khô vằn"]),
    ("lúa", ["nhện gié"]),
    ("lúa", ["sâu đục thân"]),
    ("cà phê", ["rỉ sắt"]),
    ("cà phê", ["rệp sáp"]),
    ("cà phê", ["cỏ"]),
    ("cà phê", ["thán thư"]),
    ("cà phê", ["tuyến trùng"]),
    ("cà phê", ["nấm hồng"]),
    ("sầu riêng", ["xì mủ", "nứt thân xì mủ", "thối thân xì mủ", "xì mủ thân",
                   "bệnh do nấm phythophthora"]),
    ("sầu riêng", ["thán thư"]),
    ("sầu riêng", ["thối quả", "thối trái"]),
    ("sầu riêng", ["rệp sáp"]),
]

if __name__ == "__main__":
    conn = connect()
    for crop, pests in SCOPE:
        hits = []
        for pest in pests:
            hits.extend(lookup_products(conn, crop, pest, "2026-07-17"))
        # dedup theo (trade_name, formulation)
        seen = set()
        uniq = []
        for h in hits:
            k = (h.trade_name, h.formulation)
            if k not in seen:
                seen.add(k)
                uniq.append(h)
        label = "/".join(pests)
        print(f"\n== {crop} / {label}: {len(uniq)} sản phẩm (trước khi cắt top 12)")
        for h in uniq[:12]:
            print(f"  {h.trade_name} {h.formulation or ''} | {h.active_ingredient} | ĐK: {h.registrant}")

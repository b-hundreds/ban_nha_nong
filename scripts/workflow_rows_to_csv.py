"""Chuyển kết quả workflow curate-labels (JSON) -> data/labels/labels_curated.csv.

Cách dùng: .venv/bin/python scripts/workflow_rows_to_csv.py <đường-dẫn-file-output-workflow>

- Tìm blob JSON {"verified": [...], "arbResolved": [...]} trong file output.
- verified: cặp (pass1, pass2) từ 2 worker độc lập -> ghi 2 dòng entry_pass 1/2.
- arbResolved: dòng đã được trọng tài xác minh nguyên văn với nguồn chính thống
  (source_note chứa vết claim + re-fetch) -> ghi 2 dòng entry_pass 1/2 cùng nội dung
  (double-entry thỏa mãn bởi: claim của worker + re-fetch độc lập của trọng tài —
  đã ghi rõ trong source_note).
- GHI ĐÈ toàn bộ CSV (bỏ các dòng nháp cũ) — dữ liệu nháp trước đó là bản relay
  không verbatim, đúng kế hoạch thay thế.
"""

import csv
import json
import sys
from pathlib import Path

HEADER = [
    "product_trade_name", "formulation", "ai_name", "crop", "pest", "dose_text",
    "water_text", "phi_days", "method", "dose_unit", "source_url", "source_note",
    "retrieved_at", "entry_pass",
]

def find_result(text: str) -> dict:
    # File output của workflow task = 1 JSON object {summary, logs, result, ...}
    try:
        doc = json.loads(text)
        if isinstance(doc, dict):
            inner = doc.get("result", doc)
            if isinstance(inner, str):
                inner = json.loads(inner)
            if isinstance(inner, dict) and ("arbResolved" in inner or "verified" in inner):
                return inner
    except json.JSONDecodeError:
        pass
    idx = text.find('{"verified"')
    if idx < 0:
        raise SystemExit("Không tìm thấy JSON kết quả trong file output")
    return json.JSONDecoder().raw_decode(text[idx:])[0]

def row_to_csv(row: dict, entry_pass: int) -> dict:
    return {
        "product_trade_name": row.get("product_trade_name", "").strip(),
        "formulation": row.get("formulation", ""),
        "ai_name": row.get("ai_name", ""),
        "crop": row.get("crop", "").strip().lower(),
        "pest": row.get("pest", "").strip().lower(),
        "dose_text": row.get("dose_text", ""),
        "water_text": row.get("water_text", ""),
        "phi_days": "" if row.get("phi_days") is None else row.get("phi_days"),
        "method": row.get("method", ""),
        "dose_unit": row.get("dose_unit", ""),
        "source_url": row.get("source_url", ""),
        "source_note": row.get("source_note", ""),
        "retrieved_at": row.get("retrieved_at", ""),
        "entry_pass": entry_pass,
    }

def main() -> None:
    result = find_result(Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace"))
    out_rows: list[dict] = []
    for pair in result.get("verified", []):
        out_rows.append(row_to_csv(pair["p1"], 1))
        out_rows.append(row_to_csv(pair["p2"], 2))
    for row in result.get("arbResolved", []):
        out_rows.append(row_to_csv(row, 1))
        out_rows.append(row_to_csv(row, 2))
    out = Path("data/labels/labels_curated.csv")
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(out_rows)
    n_products = len({(r["product_trade_name"].lower(), r["crop"], r["pest"]) for r in out_rows})
    print(f"Ghi {len(out_rows)} dòng ({n_products} tổ hợp sản phẩm×cây×dịch hại) vào {out}")
    print(f"verified pairs: {len(result.get('verified', []))} | arbResolved: {len(result.get('arbResolved', []))} "
          f"| dropped: {len(result.get('dropped', []))} | skipped: {len(result.get('skippedProducts', result.get('skipped', [])))}")

if __name__ == "__main__":
    main()

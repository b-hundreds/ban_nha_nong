#!/usr/bin/env bash
# Đóng gói DỮ LIỆU PRIVATE thành zip gửi nội bộ team (KHÔNG kèm code — code lấy từ GitHub).
# Kèm: toàn bộ data/ (DB đã build, CSV liều curate, KB markdown, FAQ, config nguồn).
# Loại: data/raw/ (PDF nguồn công khai, tải lại được bằng `python -m ingest.download`),
#       DB runtime của người dùng (history.db, handoff.db).
set -euo pipefail
cd "$(dirname "$0")/.."

STAMP=$(date +%Y%m%d-%H%M)
OUT="${1:-$HOME/ban-nha-nong-DATA-${STAMP}.zip}"

zip -r "$OUT" data \
  -x "data/raw/*" \
  -x "data/history.db" -x "data/handoff.db"

# Chốt chặn: tuyệt đối không có secrets trong zip
if unzip -l "$OUT" | grep -E "\s\.env" >/dev/null; then
  echo "LỖI: phát hiện .env trong zip — đã xoá để tránh lộ key." >&2
  rm -f "$OUT"; exit 1
fi
echo "OK: $OUT"
unzip -l "$OUT" | tail -3

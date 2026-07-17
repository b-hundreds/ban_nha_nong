"""Tải nguồn chính thống vào data/raw/ kèm manifest sha256."""
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

RAW_DIR = Path("data/raw")
HEADERS = {"User-Agent": "Mozilla/5.0 (research; VNAI hackathon)"}

# data/sources.yaml là nguồn sự thật (JSON-in-YAML tối giản, khỏi thêm dependency yaml).
# kind=direct: tải thẳng. kind=page: mở trang, quét link PDF theo pattern.
SOURCES_PATH = Path("data/sources.yaml")


def load_sources(path: Path = SOURCES_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_pdf_links(html: str, base: str, pattern: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".pdf") and pattern.lower() in href.lower():
            out.append(urljoin(base, href))
        elif pattern != ".pdf" and pattern.lower() in href.lower() and ".pdf" in href.lower():
            out.append(urljoin(base, href))
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def fetch_one(name: str, url: str, raw_dir: Path, manifest: dict) -> None:
    r = httpx.get(url, headers=HEADERS, timeout=60, follow_redirects=True, verify=True)
    r.raise_for_status()
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / name
    path.write_bytes(r.content)
    manifest[name] = {
        "url": url,
        "sha256": hashlib.sha256(r.content).hexdigest(),
        "bytes": len(r.content),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def main() -> None:
    manifest_path = RAW_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    failures = []
    sources = load_sources()
    for src in sources:
        try:
            if src["kind"] == "direct":
                fetch_one(src["name"], src["url"], RAW_DIR, manifest)
            else:
                r = httpx.get(src["url"], headers=HEADERS, timeout=60, follow_redirects=True)
                r.raise_for_status()
                links = extract_pdf_links(r.text, src["url"], src["pattern"])
                if not links:
                    failures.append((src["name"], "no pdf links found"))
                for i, link in enumerate(links):
                    # lỗi 1 link không được làm rớt cả batch — bắt riêng từng link
                    try:
                        fetch_one(f'{src["name"]}_{i}.pdf', link, RAW_DIR, manifest)
                    except Exception as e:
                        failures.append((f'{src["name"]}_{i}', repr(e)))
        except Exception as e:  # ghi nhận và đi tiếp — nguồn gov hay chập chờn
            failures.append((src["name"], repr(e)))
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"OK: {len(manifest)} file(s). Failures: {failures or 'none'}")


if __name__ == "__main__":
    main()

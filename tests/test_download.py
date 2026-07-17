import json
from pathlib import Path
from ingest.download import fetch_one, extract_pdf_links, load_sources

def test_fetch_one_writes_file_and_manifest(tmp_path, monkeypatch):
    import ingest.download as dl

    def fake_get(url, **kw):
        class R:
            status_code = 200
            content = b"%PDF-fake"
            def raise_for_status(self): pass
        return R()

    monkeypatch.setattr(dl.httpx, "get", fake_get)
    manifest = {}
    fetch_one("a.pdf", "https://example.com/a.pdf", tmp_path, manifest)
    assert (tmp_path / "a.pdf").read_bytes() == b"%PDF-fake"
    assert manifest["a.pdf"]["sha256"]

def test_extract_pdf_links():
    html = '<a href="/FileUpload/Documents/x/phu-luc-1.pdf">PL1</a><a href="/y.docx">d</a>'
    links = extract_pdf_links(html, base="https://ppd.gov.vn", pattern="FileUpload")
    assert links == ["https://ppd.gov.vn/FileUpload/Documents/x/phu-luc-1.pdf"]

def test_load_sources_from_yaml():
    sources = load_sources()
    assert len(sources) >= 5
    for src in sources:
        assert "name" in src
        assert "kind" in src
        assert "url" in src
        if src["kind"] == "page":
            assert "pattern" in src

def test_page_link_failure_does_not_abort_batch(monkeypatch, tmp_path, capsys):
    import ingest.download as dl

    monkeypatch.setattr(dl, "RAW_DIR", tmp_path)

    html = (
        '<a href="/FileUpload/x/bad.pdf">bad</a>'
        '<a href="/FileUpload/x/good.pdf">good</a>'
    )

    def fake_get(url, **kw):
        class Page:
            status_code = 200
            text = html
            def raise_for_status(self): pass
        class Good:
            status_code = 200
            content = b"%PDF-good"
            def raise_for_status(self): pass
        if url.endswith("bad.pdf"):
            raise RuntimeError("boom")
        if url.endswith("good.pdf"):
            return Good()
        return Page()

    monkeypatch.setattr(dl.httpx, "get", fake_get)
    monkeypatch.setattr(dl, "load_sources", lambda path=dl.SOURCES_PATH: [
        {"name": "src", "kind": "page", "pattern": "FileUpload",
         "url": "https://example.com/page.html"},
    ])

    dl.main()

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert "src_1.pdf" in manifest
    assert "src_0.pdf" not in manifest

    out = capsys.readouterr().out
    assert "OK: 1 file(s)." in out
    assert "src_0" in out  # 1 failure entry, referencing the failed link

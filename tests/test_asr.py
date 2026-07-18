"""Tests for Google STT transport configuration without making network calls."""
from __future__ import annotations

from app.backend import asr


def _clear_proxy_env(monkeypatch) -> None:
    for key in (*asr._PROXY_ENV_KEYS, "NO_PROXY", "no_proxy", "GOOGLE_STT_BYPASS_PROXY"):
        monkeypatch.delenv(key, raising=False)


def test_google_stt_auto_bypasses_local_discard_proxy(monkeypatch):
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")

    assert asr._configure_google_proxy_bypass() is True
    assert ".googleapis.com" in asr.os.environ["NO_PROXY"].split(",")
    assert asr.os.environ["no_proxy"] == asr.os.environ["NO_PROXY"]


def test_google_stt_auto_keeps_legitimate_proxy(monkeypatch):
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.corp.example:8080")

    assert asr._configure_google_proxy_bypass() is False
    assert "NO_PROXY" not in asr.os.environ
    assert "no_proxy" not in asr.os.environ


def test_google_stt_proxy_bypass_can_be_forced_or_disabled(monkeypatch):
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("GOOGLE_STT_BYPASS_PROXY", "false")
    assert asr._configure_google_proxy_bypass() is False

    monkeypatch.setenv("GOOGLE_STT_BYPASS_PROXY", "true")
    assert asr._configure_google_proxy_bypass() is True
    assert ".googleapis.com" in asr.os.environ["NO_PROXY"].split(",")

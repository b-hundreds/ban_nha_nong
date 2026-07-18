"""Browserless regression tests for answer playback with Web Speech API."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


APP_JS = Path(__file__).resolve().parents[1] / "app" / "web" / "app.js"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js is required for frontend behavior tests")
def test_answer_speech_reads_vietnamese_in_chunks_and_can_stop() -> None:
    harness = r"""
const fs = require("fs");
const vm = require("vm");

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(name) { this.values.add(name); }
  remove(name) { this.values.delete(name); }
  toggle(name, force) {
    const enabled = force === undefined ? !this.values.has(name) : Boolean(force);
    if (enabled) this.values.add(name); else this.values.delete(name);
    return enabled;
  }
  contains(name) { return this.values.has(name); }
}

class FakeElement {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.listeners = new Map();
    this.attributes = new Map();
    this.classList = new FakeClassList();
    this.textContent = "";
  }
  appendChild(child) { this.children.push(child); return child; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, handler) { this.listeners.set(name, handler); }
  dispatch(name) { const handler = this.listeners.get(name); if (handler) handler({}); }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
}

const document = {
  addEventListener() {},
  createElement(tag) { return new FakeElement(tag); },
  createElementNS(_namespace, tag) { return new FakeElement(tag); },
  createTextNode(text) { return { textContent: String(text) }; },
};

const utterances = [];
const metrics = { cancelCalls: 0 };
class FakeUtterance {
  constructor(text) { this.text = text; this.lang = ""; this.rate = 1; this.voice = null; }
}
const vietnameseVoice = { lang: "vi-VN", name: "Vietnamese" };
const voiceState = { voices: [{ lang: "en-US", name: "English" }, vietnameseVoice] };
const speechSynthesis = {
  voiceHandler: null,
  getVoices() { return voiceState.voices; },
  speak(utterance) { utterances.push(utterance); },
  cancel() { metrics.cancelCalls += 1; },
  addEventListener(name, handler) { if (name === "voiceschanged") this.voiceHandler = handler; },
  removeEventListener(name, handler) {
    if (name === "voiceschanged" && this.voiceHandler === handler) this.voiceHandler = null;
  },
};

const window = { speechSynthesis, SpeechSynthesisUtterance: FakeUtterance, crypto: {} };
window.window = window;
const sandbox = {
  console,
  document,
  window,
  localStorage: { getItem() { return null; }, setItem() {} },
  crypto: {},
  setTimeout,
  clearTimeout,
  requestAnimationFrame(callback) { callback(); },
  fetch: async () => { throw new Error("network must not be used for browser speech"); },
  utterances,
  vietnameseVoice,
  metrics,
  voiceState,
  statusLine: new FakeElement("p"),
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox, { filename: process.argv[1] });
vm.runInContext("els.statusLine = statusLine", sandbox);
vm.runInContext(`
  const answer = {
    answer_segments: [
      { type: "text", content: "Sầu riêng bị thán thư cần kiểm tra nhãn thuốc." },
      { type: "dose_block", product: "Biocare WP", ai: "Bacillus subtilis", note: "Dùng theo liều trên nhãn" },
      { type: "citation", source: "Nguồn", url: "https://example.com/not-spoken" }
    ]
  };
  const readable = answerSpeechText(answer);
  if (!readable.includes("Biocare WP") || readable.includes("example.com") || readable.includes("Nguồn")) {
    throw new Error("answerSpeechText included the wrong answer fields: " + readable);
  }

  const longChunks = splitSpeechText(("Đây là một câu trả lời khá dài để kiểm tra chia đoạn. ").repeat(20));
  if (longChunks.length < 2 || longChunks.some((chunk) => chunk.length > 240)) {
    throw new Error("long speech was not divided into safe chunks");
  }

  const actions = renderSpeechButton(readable);
  const button = actions.children[0];
  button.dispatch("click");
  if (utterances.length !== 1 || utterances[0].lang !== "vi-VN" || utterances[0].voice !== vietnameseVoice) {
    throw new Error("Vietnamese voice was not selected");
  }
  if (button.attributes.get("aria-pressed") !== "true") throw new Error("button did not enter speaking state");
  while (speechState.speaking) utterances[utterances.length - 1].onend();
  if (button.attributes.get("aria-pressed") !== "false") throw new Error("button stayed active after playback");

  button.dispatch("click");
  button.dispatch("click");
  if (speechState.speaking || button.attributes.get("aria-pressed") !== "false") {
    throw new Error("second click did not stop playback");
  }
  if (metrics.cancelCalls < 2) throw new Error("speech synthesis cancel was not called");
`, sandbox);

async function testDelayedAndMissingVietnameseVoices() {
  voiceState.voices = [{ lang: "en-US", name: "English" }];
  const delayed = vm.runInContext("waitForVietnameseVoice(100)", sandbox);
  setTimeout(() => {
    voiceState.voices = [vietnameseVoice];
    speechSynthesis.voiceHandler?.();
  }, 0);
  if (await delayed !== vietnameseVoice) throw new Error("delayed Vietnamese voice was not selected");

  voiceState.voices = [{ lang: "en-US", name: "English" }];
  const missing = await vm.runInContext("waitForVietnameseVoice(5)", sandbox);
  if (missing !== null) throw new Error("English voice was accepted as Vietnamese fallback");

  metrics.ttsCalls = 0;
  metrics.audioPlayCalls = 0;
  sandbox.fetch = async (url, options) => {
    if (url !== "/api/tts" || JSON.parse(options.body).text !== "Câu trả lời tiếng Việt.") {
      throw new Error("Google TTS fallback request is malformed");
    }
    metrics.ttsCalls += 1;
    return { ok: true, blob: async () => ({ size: 8 }) };
  };
  window.URL = {
    createObjectURL() { return "blob:google-tts"; },
    revokeObjectURL() { metrics.revoked = true; },
  };
  window.Audio = class {
    constructor(url) { this.url = url; metrics.lastAudio = this; }
    play() { metrics.audioPlayCalls += 1; return Promise.resolve(); }
    pause() {}
  };
  vm.runInContext("waitForVietnameseVoice = () => Promise.resolve(null)", sandbox);
  await vm.runInContext(`(async () => {
    const fallback = renderSpeechButton("Câu trả lời tiếng Việt.").children[0];
    fallback.dispatch("click");
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
    if (metrics.ttsCalls !== 1 || metrics.audioPlayCalls !== 1) {
      throw new Error("missing vi-VN voice did not play Google TTS audio");
    }
    metrics.lastAudio.onended();
    if (fallback.attributes.get("aria-pressed") !== "false" || !metrics.revoked) {
      throw new Error("Google TTS playback did not clean up after ending");
    }
  })()`, sandbox);
}

testDelayedAndMissingVietnameseVoices().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
"""

    completed = subprocess.run(
        [NODE, "-e", harness, str(APP_JS)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout

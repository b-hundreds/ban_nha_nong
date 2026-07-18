"""Browserless regression tests for the microphone interaction in app.js.

The backend ASR tests only exercise ``/api/transcribe``.  This file executes the
real ``setupMic`` function with small DOM/MediaRecorder fakes so an event-ordering
regression in the browser cannot hide behind a healthy transcription endpoint.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


APP_JS = Path(__file__).resolve().parents[1] / "app" / "web" / "app.js"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js is required for frontend behavior tests")
def test_mic_uses_click_to_start_then_click_to_stop() -> None:
    """A normal tap starts recording; only a second tap may stop it."""
    harness = r"""
const fs = require("fs");
const vm = require("vm");

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(name) { this.values.add(name); }
  remove(name) { this.values.delete(name); }
  contains(name) { return this.values.has(name); }
}

class FakeElement {
  constructor() {
    this.listeners = new Map();
    this.classList = new FakeClassList();
    this.attributes = new Map();
    this.value = "";
    this.disabled = false;
    this.textContent = "";
  }
  addEventListener(name, handler) {
    const handlers = this.listeners.get(name) || [];
    handlers.push(handler);
    this.listeners.set(name, handlers);
  }
  dispatch(name, event = {}) {
    for (const handler of this.listeners.get(name) || []) handler(event);
  }
  setAttribute(name, value) { this.attributes.set(name, value); }
  setPointerCapture() {}
  focus() {}
}

const documentListeners = new Map();
const document = {
  hidden: false,
  addEventListener(name, handler) {
    const handlers = documentListeners.get(name) || [];
    handlers.push(handler);
    documentListeners.set(name, handlers);
  },
};

const recorderInstances = [];
class FakeMediaRecorder {
  static isTypeSupported() { return true; }
  constructor(stream, options = {}) {
    this.stream = stream;
    this.mimeType = options.mimeType || "audio/webm";
    this.state = "inactive";
    this.listeners = new Map();
    this.startCalls = 0;
    this.stopCalls = 0;
    recorderInstances.push(this);
  }
  addEventListener(name, handler) { this.listeners.set(name, handler); }
  start() { this.startCalls += 1; this.state = "recording"; }
  stop() { this.stopCalls += 1; this.state = "inactive"; }
}

const stream = {
  getTracks() { return [{ stop() {} }]; },
};
const micBtn = new FakeElement();
const textInput = new FakeElement();
const statusLine = new FakeElement();
const sendTextBtn = new FakeElement();

const sandbox = {
  console,
  document,
  navigator: { mediaDevices: { getUserMedia: async () => stream } },
  window: { MediaRecorder: FakeMediaRecorder, crypto: {} },
  MediaRecorder: FakeMediaRecorder,
  localStorage: { getItem() { return null; }, setItem() {} },
  crypto: {},
  setTimeout() { return 1; },
  clearTimeout() {},
  requestAnimationFrame(callback) { callback(); },
  Blob,
  FormData,
  fetch: async () => { throw new Error("transcription must not run during this test"); },
  micBtn,
  textInput,
  statusLine,
  sendTextBtn,
};
sandbox.window.window = sandbox.window;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox, { filename: process.argv[1] });
vm.runInContext(
  "els.micBtn = micBtn; els.textInput = textInput; els.statusLine = statusLine; " +
  "els.sendTextBtn = sendTextBtn; setupMic();",
  sandbox,
);

async function main() {
  const pointerEvent = { pointerId: 1, preventDefault() {} };
  micBtn.dispatch("pointerdown", pointerEvent);
  await new Promise((resolve) => setImmediate(resolve));
  micBtn.dispatch("pointerup", pointerEvent);
  micBtn.dispatch("click", pointerEvent);
  await new Promise((resolve) => setImmediate(resolve));

  if (recorderInstances.length !== 1 || recorderInstances[0].startCalls !== 1) {
    throw new Error(`expected one recording to start, got ${recorderInstances.length}`);
  }
  if (recorderInstances[0].stopCalls !== 0) {
    throw new Error("a short tap stopped the recording immediately");
  }

  micBtn.dispatch("click", pointerEvent);
  if (recorderInstances[0].stopCalls !== 1) {
    throw new Error("the second tap did not stop the active recording");
  }

  const oggName = vm.runInContext('audioFileName("audio/ogg;codecs=opus")', sandbox);
  const mp4Name = vm.runInContext('audioFileName("audio/mp4")', sandbox);
  if (oggName !== "clip.ogg" || mp4Name !== "clip.m4a") {
    throw new Error(`audio filename does not match MIME type: ${oggName}, ${mp4Name}`);
  }
}

main().catch((error) => {
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

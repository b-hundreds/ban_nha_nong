"""Browserless regressions for the officer alert history component."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest


OFFICER_JS = Path(__file__).resolve().parents[1] / "app" / "web" / "officer" / "officer.js"
OFFICER_CSS = Path(__file__).resolve().parents[1] / "app" / "web" / "officer" / "officer.css"
OFFICER_HTML = Path(__file__).resolve().parents[1] / "app" / "web" / "officer" / "index.html"
SERVICE_WORKER = Path(__file__).resolve().parents[1] / "app" / "web" / "sw.js"
NODE = shutil.which("node")


def test_hidden_components_cannot_keep_taking_layout_space() -> None:
    """The empty prompt must disappear instead of pushing selected-ticket detail down."""
    css = OFFICER_CSS.read_text(encoding="utf-8")
    hidden_rule = re.search(r"\[hidden\]\s*\{(?P<body>[^}]+)\}", css)
    assert hidden_rule is not None
    normalized = re.sub(r"\s+", "", hidden_rule.group("body"))
    assert "display:none!important" in normalized


def test_officer_assets_bypass_stale_service_worker_cache() -> None:
    """Officer HTML updates its SW and version-busts assets; SW uses network-first."""
    html = OFFICER_HTML.read_text(encoding="utf-8")
    sw = SERVICE_WORKER.read_text(encoding="utf-8")

    assert 'officer.css?v=' in html
    assert 'officer.js?v=' in html
    assert "serviceWorker.register('/sw.js')" in html
    assert 'url.pathname.startsWith("/officer")' in sw


@pytest.mark.skipif(NODE is None, reason="Node.js is required for frontend behavior tests")
def test_alert_history_is_paginated_and_switches_without_rendering_every_row() -> None:
    """A long history stays bounded and tab state remains accessible."""
    harness = r"""
const fs = require("fs");
const vm = require("vm");

class FakeClassList {
  constructor(owner) { this.owner = owner; this.values = new Set(); }
  add(name) { this.values.add(name); }
  remove(name) { this.values.delete(name); }
  toggle(name, force) {
    const enabled = force === undefined ? !this.contains(name) : Boolean(force);
    if (enabled) this.values.add(name); else this.values.delete(name);
    return enabled;
  }
  contains(name) {
    return this.values.has(name) || this.owner.className.split(/\s+/).includes(name);
  }
}

class FakeElement {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.parentNode = null;
    this.listeners = new Map();
    this.attributes = new Map();
    this.className = "";
    this.classList = new FakeClassList(this);
    this.dataset = {};
    this.hidden = false;
    this.disabled = false;
    this.tabIndex = 0;
    this.id = "";
    this.textContent = "";
    this.title = "";
    this.style = {};
  }
  get firstChild() { return this.children[0] || null; }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  removeChild(child) {
    this.children = this.children.filter((item) => item !== child);
    child.parentNode = null;
    return child;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  addEventListener(name, handler) {
    const handlers = this.listeners.get(name) || [];
    handlers.push(handler);
    this.listeners.set(name, handlers);
  }
  click() { for (const handler of this.listeners.get("click") || []) handler({}); }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  querySelectorAll(selector) {
    const className = selector.startsWith(".") ? selector.slice(1) : null;
    const found = [];
    function visit(node) {
      for (const child of node.children) {
        if (className && child.classList.contains(className)) found.push(child);
        visit(child);
      }
    }
    visit(this);
    return found;
  }
}

const alertStrip = new FakeElement("section");
alertStrip.id = "alert-strip";
alertStrip.className = "alert-strip";

const document = {
  addEventListener() {},
  createElement(tag) { return new FakeElement(tag); },
  createTextNode(text) { const node = new FakeElement("#text"); node.textContent = String(text); return node; },
  getElementById(id) { return id === "alert-strip" ? alertStrip : null; },
};

const sandbox = {
  console,
  document,
  localStorage: { getItem() { return null; }, setItem() {} },
  fetch: async () => { throw new Error("network is not used by this component test"); },
  setInterval() { return 1; },
  setTimeout() { return 1; },
  requestAnimationFrame(callback) { callback(); },
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox, { filename: process.argv[1] });

const history = Array.from({ length: 13 }, (_, index) => ({
  region: "an_giang",
  region_name: "An Giang",
  topic: "dịch hại " + index,
  first_ts: "2026-07-01T00:00:00Z",
  last_ts: "2026-07-18T00:00:00Z",
  peak_count: index + 3,
  active: index === 0,
}));

sandbox.input = {
  alerts: [],
  history,
  overview: {
    year: 2026,
    available_years: [2026, 2025],
    total_questions: 20,
    located_questions: 20,
    disease_report_count: 8,
    disease_reports_by_region: [
      { region: "an_giang", region_name: "An Giang", disease_report_count: 5, outbreak_count: 2 },
      { region: "dak_lak", region_name: "Đắk Lắk", disease_report_count: 3, outbreak_count: 1 },
    ],
    questions_by_region: [
      { region: "dak_lak", region_name: "Đắk Lắk", question_count: 12 },
      { region: "an_giang", region_name: "An Giang", question_count: 8 },
    ],
    note: "Số liệu từ câu hỏi.",
  },
};
vm.runInContext("renderAlerts(input)", sandbox);

const tabs = alertStrip.querySelectorAll(".alert-tab-btn");
if (tabs.length !== 3) throw new Error("expected overview, active, and history tabs");
if (alertStrip.querySelectorAll(".overview-rank-row").length !== 4) {
  throw new Error("year overview did not render both region rankings");
}
tabs[2].click();

if (!alertStrip.classList.contains("alert-strip--history")) {
  throw new Error("history tab did not enable the bounded history layout");
}
if (tabs[2].attributes.get("aria-selected") !== "true" || tabs[0].attributes.get("aria-selected") !== "false") {
  throw new Error("alert tab accessibility state is stale after switching");
}

let rows = alertStrip.querySelectorAll(".history-row");
if (rows.length !== 5) throw new Error(`expected 5 history rows on page 1, got ${rows.length}`);

let nextButton = alertStrip.querySelectorAll(".history-page-btn")[1];
nextButton.click();
rows = alertStrip.querySelectorAll(".history-row");
if (rows.length !== 5) throw new Error(`expected 5 history rows on page 2, got ${rows.length}`);

nextButton = alertStrip.querySelectorAll(".history-page-btn")[1];
nextButton.click();
rows = alertStrip.querySelectorAll(".history-row");
if (rows.length !== 3) throw new Error(`expected 3 history rows on final page, got ${rows.length}`);

const finalButtons = alertStrip.querySelectorAll(".history-page-btn");
if (!finalButtons[1].disabled || finalButtons[0].disabled) {
  throw new Error("history pagination controls have the wrong disabled state");
}
"""

    completed = subprocess.run(
        [NODE, "-e", harness, str(OFFICER_JS)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout

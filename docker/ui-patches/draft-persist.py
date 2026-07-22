#!/usr/bin/env python3
"""Persist generate-form drafts (lyrics/style/prompt) to localStorage.

Mobile browsers often discard or remount the SPA when switching tabs; React
state is lost. This injects a small script that:
  - saves textarea/input values matching lyrics/style/prompt on input
  - restores them on load and on pageshow / visibilitychange
"""
from pathlib import Path

js = r'''(function () {
  var KEY = "ace-step-ui-draft-v1";
  var SELECTORS = [
    'textarea[name*="lyric" i]',
    'textarea[id*="lyric" i]',
    'textarea[placeholder*="lyric" i]',
    'textarea[name*="style" i]',
    'textarea[id*="style" i]',
    'textarea[placeholder*="style" i]',
    'textarea[name*="prompt" i]',
    'textarea[id*="prompt" i]',
    'textarea[placeholder*="prompt" i]',
    'textarea[placeholder*="caption" i]',
    'input[name*="style" i]',
    'input[id*="style" i]',
    'input[placeholder*="style" i]',
    'textarea'
  ];

  function load() {
    try {
      return JSON.parse(localStorage.getItem(KEY) || "{}") || {};
    } catch (e) {
      return {};
    }
  }

  function save(map) {
    try {
      localStorage.setItem(KEY, JSON.stringify(map));
    } catch (e) {}
  }

  function fieldKey(el) {
    return [
      el.tagName,
      el.name || "",
      el.id || "",
      (el.getAttribute("placeholder") || "").slice(0, 40),
      el.getAttribute("aria-label") || ""
    ].join("|");
  }

  function relevant(el) {
    if (!el || el.disabled || el.readOnly) return false;
    if (el.tagName !== "TEXTAREA" && !(el.tagName === "INPUT" && (!el.type || el.type === "text"))) {
      return false;
    }
    var blob = (
      (el.name || "") +
      " " +
      (el.id || "") +
      " " +
      (el.getAttribute("placeholder") || "") +
      " " +
      (el.getAttribute("aria-label") || "")
    ).toLowerCase();
    if (/lyric|style|prompt|caption|description|genre/.test(blob)) return true;
    // large free-text areas on generate page
    if (el.tagName === "TEXTAREA" && (el.rows >= 3 || (el.offsetHeight || 0) > 80)) return true;
    return false;
  }

  function collectTargets() {
    var seen = new Set();
    var out = [];
    SELECTORS.forEach(function (sel) {
      try {
        document.querySelectorAll(sel).forEach(function (el) {
          if (seen.has(el)) return;
          if (!relevant(el)) return;
          seen.add(el);
          out.push(el);
        });
      } catch (e) {}
    });
    return out;
  }

  function restore() {
    var map = load();
    collectTargets().forEach(function (el) {
      var k = fieldKey(el);
      if (map[k] != null && map[k] !== "" && (!el.value || el.value === "")) {
        el.value = map[k];
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
  }

  function persistOne(el) {
    if (!relevant(el)) return;
    var map = load();
    map[fieldKey(el)] = el.value;
    map._ts = Date.now();
    save(map);
  }

  document.addEventListener(
    "input",
    function (e) {
      var t = e.target;
      if (t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT")) persistOne(t);
    },
    true
  );

  document.addEventListener(
    "change",
    function (e) {
      var t = e.target;
      if (t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT")) persistOne(t);
    },
    true
  );

  window.addEventListener("pagehide", function () {
    collectTargets().forEach(persistOne);
  });
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") {
      collectTargets().forEach(persistOne);
    } else {
      setTimeout(restore, 50);
      setTimeout(restore, 400);
    }
  });
  window.addEventListener("pageshow", function () {
    setTimeout(restore, 50);
    setTimeout(restore, 500);
  });

  // React may mount fields late
  setTimeout(restore, 300);
  setTimeout(restore, 1200);
  setTimeout(restore, 3000);
  var obs = new MutationObserver(function () {
    setTimeout(restore, 100);
  });
  if (document.body) {
    obs.observe(document.body, { childList: true, subtree: true });
  } else {
    document.addEventListener("DOMContentLoaded", function () {
      obs.observe(document.body, { childList: true, subtree: true });
      restore();
    });
  }
})();
'''

Path("public").mkdir(exist_ok=True)
Path("public/ace-xpu-draft.js").write_text(js)

for hp in ["index.html", "public/index.html"]:
    p = Path(hp)
    if not p.exists():
        continue
    h = p.read_text()
    if "ace-xpu-draft" in h:
        print(f"{hp} already has draft script")
        continue
    if "</body>" in h:
        h = h.replace("</body>", '<script src="/ace-xpu-draft.js"></script></body>')
    else:
        h = h + '\n<script src="/ace-xpu-draft.js"></script>\n'
    p.write_text(h)
    print(f"injected draft script into {hp}")

print("draft-persist OK")

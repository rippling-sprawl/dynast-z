/*
 * DynastZ Odds Recorder — discovery + capture bookmarklet (source)
 *
 * Runs in YOUR logged-in sportsbook tab. It monkeypatches fetch + XHR so that
 * every JSON API response the page loads is recorded (URL, method, status,
 * body). A small floating panel lets you Copy the captured bundle to the
 * clipboard, which you then paste into DynastZ's /odds/import box.
 *
 * Why a bookmarklet (not an extension / not server-side replay):
 *   - It is a real, logged-in browser session, so it inherits live cookies and
 *     PerimeterX / Cloudflare / Akamai tokens — there is no bot to detect.
 *   - It only reads same-page responses and writes to YOUR clipboard, so the
 *     sportsbook's CSP (which blocks cross-origin POSTs) never gets in the way.
 *
 * Usage:
 *   1. Open the book (FanDuel / DraftKings / theScore), log in, go to the NFL
 *      futures / player-props pages you want.
 *   2. Click this bookmarklet — a panel appears, hooks are installed.
 *   3. Navigate/click the pages whose data you want (each page load is captured).
 *   4. Click "Copy bundle" → paste into DynastZ.
 *
 * This file is the readable source. The draggable one-liner is generated from it
 * into scripts/odds-recorder.bookmarklet.txt (see the build command in the PR).
 */
(function () {
  "use strict";

  /* Re-clicking the bookmarklet just re-opens the panel instead of double-patching. */
  if (window.__dzRec) { window.__dzRec.show(); return; }

  /* url -> { url, method, status, contentType, body }. Keyed by URL so a
     re-fetch of the same endpoint overwrites with the freshest response. */
  var store = new Map();

  /* Domains whose requests are never recorded (analytics / telemetry / RUM).
     Matched by hostname (exact or subdomain). Keep this list in sync with the
     server-side import parser, which applies the same blocklist when parsing a
     pasted bundle so blocked hosts are dropped at both ends. */
  var BLOCK = ["datadoghq.com", "launchdarkly.com"];

  function blocked(url) {
    try {
      var h = new URL(url, location.href).hostname.toLowerCase();
      return BLOCK.some(function (d) {
        /* exact, dot-subdomain (rum.datadoghq.com), or hyphen sibling that
           vendors use for ingest hosts (browser-intake-datadoghq.com). */
        return h === d || h.endsWith("." + d) || h.endsWith("-" + d);
      });
    } catch (e) {
      return BLOCK.some(function (d) { return url.indexOf(d) !== -1; });
    }
  }

  function isJson(ct) { return !!ct && ct.indexOf("json") !== -1; }

  function record(url, method, status, contentType, text) {
    if (!url || blocked(url) || !isJson(contentType)) { return; }
    var body;
    try { body = JSON.parse(text); } catch (e) { body = text; }
    store.set(url, {
      url: url,
      method: method || "GET",
      status: status,
      contentType: contentType,
      body: body
    });
    render();
  }

  /* ---- fetch hook ---- */
  var origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function () {
      var args = arguments;
      var req = args[0];
      var method = (args[1] && args[1].method) || (req && req.method) || "GET";
      return origFetch.apply(this, args).then(function (res) {
        try {
          var ct = res.headers.get("content-type") || "";
          if (isJson(ct)) {
            var url = res.url || (req && req.url) || String(req);
            res.clone().text().then(function (t) {
              record(url, method, res.status, ct, t);
            }).catch(function () {});
          }
        } catch (e) {}
        return res;
      });
    };
  }

  /* ---- XHR hook ---- */
  var XO = XMLHttpRequest.prototype.open;
  var XS = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) {
    this.__dz = { m: m, u: u };
    return XO.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    var self = this;
    this.addEventListener("load", function () {
      try {
        var ct = self.getResponseHeader("content-type") || "";
        if (self.__dz && isJson(ct)) {
          record(self.__dz.u, self.__dz.m, self.status, ct, self.responseText);
        }
      } catch (e) {}
    });
    return XS.apply(this, arguments);
  };

  /* ---- bundle + clipboard ---- */
  function bundle() {
    return JSON.stringify({
      capturedAt: Date.now(),
      page: location.href,
      host: location.host,
      captures: Array.from(store.values())
    });
  }

  function flash(msg) {
    var s = document.getElementById("dz-rec-status");
    if (s) { s.textContent = msg; }
  }

  function copyBundle() {
    var text = bundle();
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () { flash("Copied " + store.size + " endpoints (" + Math.round(text.length / 1024) + " KB)"); },
        function () { fallbackCopy(text); }
      );
    } else {
      fallbackCopy(text);
    }
  }

  /* Permissions-Policy on some books can block the async clipboard API — fall
     back to a selectable textarea + execCommand. */
  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;left:0;top:0;width:1px;height:1px;opacity:0;";
    document.body.appendChild(ta);
    ta.focus(); ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(ta);
    flash(ok ? "Copied (fallback) " + store.size + " endpoints" : "Copy blocked — use Download");
  }

  function downloadBundle() {
    var blob = new Blob([bundle()], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "dz-odds-" + location.host.replace(/\W+/g, "-") + ".json";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    flash("Downloaded " + store.size + " endpoints");
  }

  /* ---- floating panel ---- */
  var panel;
  function render() {
    if (!panel) { return; }
    var count = document.getElementById("dz-rec-count");
    if (count) { count.textContent = String(store.size); }
    var list = document.getElementById("dz-rec-list");
    if (list) {
      list.innerHTML = "";
      Array.from(store.values()).slice(-12).forEach(function (c) {
        var li = document.createElement("div");
        li.style.cssText = "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;opacity:.8;";
        var path = c.url.replace(/^https?:\/\/[^/]+/, "");
        li.textContent = c.status + "  " + path;
        list.appendChild(li);
      });
    }
  }

  function build() {
    panel = document.createElement("div");
    panel.id = "dz-rec-panel";
    panel.style.cssText =
      "position:fixed;top:12px;right:12px;z-index:2147483647;width:340px;" +
      "font:12px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;color:#eaeaea;" +
      "background:#16181d;border:1px solid #3a3f4b;border-radius:10px;" +
      "box-shadow:0 8px 30px rgba(0,0,0,.5);padding:10px 12px;";
    panel.innerHTML =
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">' +
        '<strong style="font-size:13px;">DynastZ Recorder</strong>' +
        '<span><b id="dz-rec-count">0</b> endpoints</span>' +
      '</div>' +
      '<div id="dz-rec-list" style="max-height:140px;overflow:auto;font-size:11px;margin-bottom:8px;border-top:1px solid #2a2e37;border-bottom:1px solid #2a2e37;padding:6px 0;"></div>' +
      '<div style="display:flex;gap:6px;flex-wrap:wrap;">' +
        '<button id="dz-rec-copy" style="flex:1;cursor:pointer;background:#2563eb;color:#fff;border:0;border-radius:6px;padding:7px 8px;font-weight:600;">Copy bundle</button>' +
        '<button id="dz-rec-dl" style="cursor:pointer;background:#374151;color:#fff;border:0;border-radius:6px;padding:7px 8px;">Download</button>' +
        '<button id="dz-rec-clear" style="cursor:pointer;background:#374151;color:#fff;border:0;border-radius:6px;padding:7px 8px;">Clear</button>' +
        '<button id="dz-rec-close" style="cursor:pointer;background:transparent;color:#9aa0aa;border:0;padding:7px 4px;">✕</button>' +
      '</div>' +
      '<div id="dz-rec-status" style="margin-top:7px;min-height:14px;color:#7dd3fc;font-size:11px;">Recording… load the pages you want.</div>';
    document.body.appendChild(panel);
    document.getElementById("dz-rec-copy").onclick = copyBundle;
    document.getElementById("dz-rec-dl").onclick = downloadBundle;
    document.getElementById("dz-rec-clear").onclick = function () { store.clear(); render(); flash("Cleared."); };
    document.getElementById("dz-rec-close").onclick = function () { panel.style.display = "none"; };
    render();
  }

  window.__dzRec = {
    show: function () { if (panel) { panel.style.display = "block"; } },
    store: store,
    bundle: bundle
  };

  build();
})();

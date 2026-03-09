(function () {
  "use strict";

  var ws, currentSid, sessions = [], requests = [], pendingImgs = [];

  var $ = function (s) { return document.querySelector(s); };
  var $list      = $("#session-list"),
      $count     = $("#session-count"),
      $empty     = $("#empty-state"),
      $detail    = $("#session-detail"),
      $title     = $("#detail-title"),
      $status    = $("#detail-status"),
      $summary   = $("#summary-content"),
      $sumImgs   = $("#summary-images"),
      $respSec   = $("#response-section"),
      $doneSec   = $("#responded-section"),
      $doneText  = $("#responded-content"),
      $doneImgs  = $("#responded-images"),
      $input     = $("#response-input"),
      $preview   = $("#image-preview"),
      $file      = $("#file-input"),
      $send      = $("#btn-submit"),
      $cont      = $("#btn-continue"),
      $done      = $("#btn-done"),
      $history   = $("#history-list"),
      $wsInd     = $("#ws-status"),
      $wsLbl     = $("#ws-label"),
      $drop      = $("#drop-overlay");

  // ── API ──
  function api(url, o) {
    return fetch(url, Object.assign({ headers: { "Content-Type": "application/json" } }, o))
      .then(function (r) { return r.json(); });
  }
  function load() {
    return api("/api/sessions").then(function (d) { sessions = d; renderList(); });
  }
  function loadDetail(sid) {
    return api("/api/sessions/" + sid + "/feedback").then(function (d) { requests = d; renderDetail(); });
  }

  // ── Render list ──
  function renderList() {
    $count.textContent = sessions.length;
    $list.innerHTML = "";
    if (!sessions.length) { $empty.classList.remove("hidden"); $detail.classList.add("hidden"); return; }
    sessions.forEach(function (s) {
      var li = document.createElement("li");
      if (s.id === currentSid) li.classList.add("active");
      li.innerHTML = '<div class="s-title">' + esc(s.title || "Session " + s.id) + '</div>' +
        '<div class="s-meta"><span class="s-dot ' + s.status + '"></span>' +
        label(s.status) + " · " + ago(s.last_activity) + '</div>';
      li.onclick = function () { pick(s.id); };
      $list.appendChild(li);
    });
  }

  // ── Render detail ──
  function renderDetail() {
    var s = sessions.find(function (x) { return x.id === currentSid; });
    if (!s) return;
    $empty.classList.add("hidden");
    $detail.classList.remove("hidden");
    $title.textContent = s.title || "Session " + s.id;
    $status.textContent = label(s.status);
    $status.className = "tag " + s.status;

    var pending = requests.find(function (r) { return r.status === "pending"; });
    var done = requests.filter(function (r) { return r.status !== "pending"; });

    if (pending && s.status !== "disconnected") {
      showSummary(pending.summary, pending.summary_images);
      $respSec.classList.remove("hidden");
      $doneSec.classList.add("hidden");
      $input.value = "";
      clearImgs();
      $input.focus();
    } else if (s.status === "disconnected" && pending) {
      showSummary(pending.summary, pending.summary_images);
      $respSec.classList.add("hidden");
      $doneSec.classList.remove("hidden");
      $doneText.textContent = "Cursor 已断开连接，此请求已取消";
      fillGallery($doneImgs, []);
    } else if (done.length) {
      var last = done[done.length - 1];
      showSummary(last.summary, last.summary_images);
      $respSec.classList.add("hidden");
      $doneSec.classList.remove("hidden");
      $doneText.innerHTML = md(last.response || "");
      fillGallery($doneImgs, last.response_images);
    } else {
      $summary.innerHTML = '<span class="text-dim">暂无请求</span>';
      $sumImgs.innerHTML = ""; $sumImgs.classList.add("hidden");
      $respSec.classList.add("hidden");
      $doneSec.classList.add("hidden");
    }
    renderHistory(done);
    scrollToBottom();
  }

  function showSummary(text, imgs) {
    $summary.innerHTML = md(text || "");
    initCodeBlocks($summary);
    $sumImgs.innerHTML = "";
    if (imgs && imgs.length) {
      $sumImgs.classList.remove("hidden");
      imgs.forEach(function (src) {
        var w = document.createElement("div"); w.className = "gallery-item";
        w.appendChild(mkImg(src, "AI 图片", true));
        $sumImgs.appendChild(w);
      });
    } else { $sumImgs.classList.add("hidden"); }
  }

  function fillGallery(el, imgs) {
    el.innerHTML = "";
    if (!imgs || !imgs.length) return;
    imgs.forEach(function (src) { el.appendChild(mkImg(src, "", true)); });
  }

  function renderHistory(items) {
    $history.innerHTML = "";
    if (!items.length) {
      $history.innerHTML = '<div class="history-empty">暂无历史记录</div>';
      return;
    }
    items.forEach(function (r) {
      var d = document.createElement("div"); d.className = "chat-pair";

      var aiMsg = document.createElement("div"); aiMsg.className = "chat-msg ai";
      var aiLabel = document.createElement("div"); aiLabel.className = "chat-role";
      aiLabel.innerHTML = '<span class="role-dot ai"></span> AI';
      var aiBody = document.createElement("div"); aiBody.className = "chat-body prose";
      aiBody.innerHTML = md(r.summary || "");
      initCodeBlocks(aiBody);
      aiMsg.appendChild(aiLabel);
      aiMsg.appendChild(aiBody);

      if (r.summary_images && r.summary_images.length) {
        var aiImgs = document.createElement("div"); aiImgs.className = "chat-imgs";
        r.summary_images.forEach(function (src) { aiImgs.appendChild(mkImg(src, "", true)); });
        aiMsg.appendChild(aiImgs);
      }

      var userMsg = document.createElement("div"); userMsg.className = "chat-msg user";
      var userLabel = document.createElement("div"); userLabel.className = "chat-role";
      userLabel.innerHTML = '<span class="role-dot user"></span> User';
      var userBody = document.createElement("div"); userBody.className = "chat-body";
      var statusText = r.status === "cancelled" ? "已取消" : (r.response || "\u2014");
      userBody.textContent = statusText;
      userMsg.appendChild(userLabel);
      userMsg.appendChild(userBody);

      if (r.response_images && r.response_images.length) {
        var userImgs = document.createElement("div"); userImgs.className = "chat-imgs";
        r.response_images.forEach(function (src) { userImgs.appendChild(mkImg(src, "", true)); });
        userMsg.appendChild(userImgs);
      }

      var time = document.createElement("div"); time.className = "chat-time";
      time.textContent = fmtTime(r.responded_at || r.created_at);

      d.appendChild(aiMsg);
      d.appendChild(userMsg);
      d.appendChild(time);
      $history.appendChild(d);
    });
  }

  function scrollToBottom() {
    var el = document.getElementById("messages-scroll");
    if (el) setTimeout(function () { el.scrollTop = el.scrollHeight; }, 50);
  }

  // ── Code block enhancements ──
  function initCodeBlocks(container) {
    var blocks = container.querySelectorAll("pre");
    blocks.forEach(function (pre) {
      if (pre.querySelector(".code-header")) return;
      var code = pre.querySelector("code");
      var lang = "";
      if (code) {
        var cls = code.className || "";
        var m = cls.match(/language-(\w+)/);
        if (m) lang = m[1];
      }

      var header = document.createElement("div");
      header.className = "code-header";

      var langSpan = document.createElement("span");
      langSpan.className = "code-lang";
      langSpan.textContent = lang || "code";

      var actions = document.createElement("div");
      actions.className = "code-actions";

      var copyBtn = document.createElement("button");
      copyBtn.className = "code-btn";
      copyBtn.textContent = "复制";
      copyBtn.onclick = function () {
        var text = code ? code.textContent : pre.textContent;
        navigator.clipboard.writeText(text).then(function () {
          copyBtn.textContent = "已复制";
          setTimeout(function () { copyBtn.textContent = "复制"; }, 1500);
        });
      };

      var lines = (code ? code.textContent : pre.textContent).split("\n");
      if (lines.length > 5) {
        var foldBtn = document.createElement("button");
        foldBtn.className = "code-btn";
        pre.classList.add("collapsed");
        foldBtn.textContent = "展开";
        var collapsed = true;
        foldBtn.onclick = function () {
          collapsed = !collapsed;
          pre.classList.toggle("collapsed", collapsed);
          foldBtn.textContent = collapsed ? "展开" : "折叠";
        };
        actions.appendChild(foldBtn);
      }

      actions.appendChild(copyBtn);
      header.appendChild(langSpan);
      header.appendChild(actions);
      pre.insertBefore(header, pre.firstChild);
    });
  }

  // ── Actions ──
  function pick(sid) { currentSid = sid; renderList(); loadDetail(sid); }

  function submit(text) {
    var p = requests.find(function (r) { return r.status === "pending"; });
    if (!p) return;
    $send.disabled = $cont.disabled = $done.disabled = true;
    api("/api/feedback/" + p.id + "/respond", {
      method: "POST",
      body: JSON.stringify({ response: text, images: pendingImgs.slice() })
    }).then(function () {
      $send.disabled = $cont.disabled = $done.disabled = false;
      clearImgs();
      refresh();
    });
  }

  function refresh() {
    return load().then(function () { if (currentSid) loadDetail(currentSid); });
  }

  // ── Images ──
  function addFile(f) {
    if (!f.type.startsWith("image/")) return;
    var r = new FileReader();
    r.onload = function (e) { pendingImgs.push(e.target.result); renderPreview(); };
    r.readAsDataURL(f);
  }

  function handlePaste(e) {
    var items = (e.clipboardData || (e.originalEvent && e.originalEvent.clipboardData));
    if (!items) return;
    items = items.items || [];
    for (var i = 0; i < items.length; i++) {
      if (items[i].type.startsWith("image/")) {
        e.preventDefault();
        addFile(items[i].getAsFile());
        return;
      }
    }
  }

  function clearImgs() { pendingImgs = []; renderPreview(); }

  function renderPreview() {
    if (!pendingImgs.length) { $preview.classList.add("hidden"); $preview.innerHTML = ""; return; }
    $preview.classList.remove("hidden");
    $preview.innerHTML = "";
    pendingImgs.forEach(function (src, i) {
      var t = document.createElement("div"); t.className = "thumb";
      t.innerHTML = '<img src="' + src + '"><button class="x" data-i="' + i + '">&times;</button>';
      $preview.appendChild(t);
    });
  }

  // ── Events ──
  $send.onclick = function () { var t = $input.value.trim(); if (t || pendingImgs.length) submit(t); };
  $cont.onclick = function () { submit("继续"); };
  $done.onclick = function () { submit("结束"); };
  $input.onkeydown = function (e) {
    if (e.ctrlKey && e.key === "Enter") { e.preventDefault(); var t = $input.value.trim(); if (t || pendingImgs.length) submit(t); }
  };
  $file.onchange = function () { Array.from($file.files).forEach(addFile); $file.value = ""; };

  document.addEventListener("paste", handlePaste);

  $preview.onclick = function (e) {
    var b = e.target.closest(".x"); if (b) { pendingImgs.splice(+b.dataset.i, 1); renderPreview(); }
  };

  var dc = 0;
  document.addEventListener("dragenter", function (e) { e.preventDefault(); dc++; $drop.classList.remove("hidden"); });
  document.addEventListener("dragleave", function (e) { e.preventDefault(); dc--; if (dc <= 0) { dc = 0; $drop.classList.add("hidden"); } });
  document.addEventListener("dragover", function (e) { e.preventDefault(); });
  document.addEventListener("drop", function (e) {
    e.preventDefault(); dc = 0; $drop.classList.add("hidden");
    if (e.dataTransfer && e.dataTransfer.files) Array.from(e.dataTransfer.files).forEach(addFile);
  });

  document.addEventListener("img-zoom", function (e) { modal(e.detail); });

  // ── WebSocket ──
  function connect() {
    var p = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(p + "//" + location.host + "/ws");
    ws.onopen = function () { $wsInd.classList.add("connected"); $wsLbl.textContent = "已连接"; };
    ws.onclose = function () { $wsInd.classList.remove("connected"); $wsLbl.textContent = "已断开"; setTimeout(connect, 2000); };
    ws.onmessage = function (e) {
      try {
        var m = JSON.parse(e.data);
        if (m.type === "update") {
          refresh().then(function () {
            if (!currentSid) { var w = sessions.find(function (s) { return s.status === "waiting"; }); if (w) pick(w.id); }
          });
          toast("收到新的更新");
        }
      } catch (_) {}
    };
  }

  // ── Helpers ──
  function mkImg(src, alt, zoom) {
    var img = document.createElement("img");
    img.src = src; img.alt = alt || "";
    img.onerror = function () { this.classList.add("img-broken"); };
    if (zoom) { img.style.cursor = "pointer"; img.onclick = function () { modal(src); }; }
    return img;
  }

  function modal(src) {
    var bg = document.createElement("div"); bg.className = "modal-bg";
    var im = document.createElement("img"); im.src = src;
    bg.appendChild(im); bg.onclick = function () { bg.remove(); };
    document.body.appendChild(bg);
  }

  function esc(s) { var d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
  function escA(s) { return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

  function md(text) {
    if (!text) return "";
    var tok = [], out = text;

    // Extract fenced code blocks FIRST
    out = out.replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, code) {
      var i = tok.length;
      var escapedCode = esc(code.replace(/\n$/, ""));
      var cls = lang ? ' class="language-' + escA(lang) + '"' : '';
      tok.push('<pre><code' + cls + '>' + escapedCode + '</code></pre>');
      return "\n%%T" + i + "%%\n";
    });

    // Extract inline code
    out = out.replace(/`([^`]+)`/g, function (_, code) {
      var i = tok.length;
      tok.push('<code>' + esc(code) + '</code>');
      return "%%T" + i + "%%";
    });

    // Extract images
    out = out.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, function (_, a, u) {
      var i = tok.length;
      tok.push('<img class="md-image" src="' + escA(u) + '" alt="' + escA(a) + '" onclick="this.dispatchEvent(new CustomEvent(\'img-zoom\',{bubbles:true,detail:this.src}))" onerror="this.classList.add(\'md-image-broken\')">');
      return "%%T" + i + "%%";
    });

    // Extract links
    out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (_, l, u) {
      var i = tok.length;
      tok.push('<a href="' + escA(u) + '" target="_blank">' + esc(l) + '</a>');
      return "%%T" + i + "%%";
    });

    var h = esc(out);
    h = h.replace(/%%T(\d+)%%/g, function (_, i) { return tok[+i]; });

    // Headings
    h = h.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    h = h.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    h = h.replace(/^# (.+)$/gm, '<h2>$1</h2>');

    // Bold & italic
    h = h.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    h = h.replace(/\*(.+?)\*/g, "<em>$1</em>");

    // Lists
    h = h.replace(/^\* (.+)$/gm, "<li>$1</li>");
    h = h.replace(/^- (.+)$/gm, "<li>$1</li>");
    h = h.replace(/^(\d+)\. (.+)$/gm, "<li>$2</li>");
    h = h.replace(/((?:<li>[\s\S]*?<\/li>\s*)+)/g, "<ul>$1</ul>");

    // Horizontal rule
    h = h.replace(/^---$/gm, '<hr>');

    // Line breaks (but not around block elements)
    h = h.replace(/\n/g, "<br>");
    h = h.replace(/<br>(<\/?(?:pre|ul|ol|li|h[1-4]|hr|div))/g, "$1");
    h = h.replace(/(<\/(?:pre|ul|ol|li|h[1-4]|hr|div)>)<br>/g, "$1");

    return h;
  }

  function trunc(s, n) { return s && s.length > n ? s.slice(0, n) + "\u2026" : s || ""; }
  function label(st) { return { active: "活跃", waiting: "等待反馈", closed: "已关闭", disconnected: "已断开" }[st] || st; }
  function ago(iso) {
    if (!iso) return "";
    var d = (Date.now() - new Date(iso).getTime()) / 1000;
    if (d < 60) return "刚刚"; if (d < 3600) return ~~(d / 60) + "分钟前";
    if (d < 86400) return ~~(d / 3600) + "小时前"; return ~~(d / 86400) + "天前";
  }
  function fmtTime(iso) { return iso ? new Date(iso).toLocaleString("zh-CN") : ""; }
  function toast(msg) {
    var el = document.createElement("div"); el.className = "toast"; el.textContent = msg;
    document.getElementById("toast-container").appendChild(el);
    setTimeout(function () { el.remove(); }, 2500);
  }

  // ── Init ──
  load().then(function () {
    var w = sessions.find(function (s) { return s.status === "waiting"; });
    if (w) pick(w.id);
  });
  connect();
})();

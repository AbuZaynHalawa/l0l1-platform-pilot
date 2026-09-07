/* ==========================================================================
   MOBILE APP v2 -- Project Readiness (L0/L1) Platform
   ==========================================================================
   A separate, mobile-native presentation of the same product app.js drives
   on desktop -- same REST endpoints, same statuses/formulas/scoring (all of
   that lives server-side, untouched), completely different screens/nav/IA.
   Deliberately does NOT reuse app.js's desktop-DOM-coupled render functions
   (they're built for table rows and desktop modals); it reuses only the
   pure constants/formatters app.js exports via window.__app (see app.js's
   own IIFE tail) and otherwise talks to the backend directly.

   Structure: mode detection -> tiny api()/state helpers -> bottom-sheet
   primitive -> nav controller -> one render function per screen -> GAHIZ
   sheet -> bootstrap.
   ========================================================================== */
(function () {
  "use strict";

  var _mq = window.matchMedia("(max-width: 780px)");
  function isMobileMode() { return _mq.matches; }

  function applyShellClass() {
    document.body.classList.toggle("mobile-shell", isMobileMode());
  }

  // ---------------------------------------------------------------- state --
  var STATE = {
    tab: "home",
    stack: [], // screen-history for the mobile back button (project/deliverable detail)
    role: localStorage.getItem("mobileRole") || "Owner",
    email: localStorage.getItem("mobileActingEmail") || "",
    portfolioStage: "L0",
    actionsBucket: "due",
    gahizHistory: [],
  };
  function setRole(r) { STATE.role = r; localStorage.setItem("mobileRole", r); }
  function setEmail(e) { STATE.email = (e || "").trim(); localStorage.setItem("mobileActingEmail", STATE.email); }

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html !== undefined) e.innerHTML = html;
    return e;
  }

  async function api(path, opts) {
    opts = Object.assign({ cache: "no-store" }, opts || {});
    var r = await fetch(path, opts);
    if (!r.ok) {
      var t = await r.text();
      var msg = t;
      try { msg = JSON.parse(t).detail || t; } catch (e) {}
      throw new Error(msg || (r.status + ""));
    }
    var ct = r.headers.get("content-type") || "";
    return ct.indexOf("application/json") !== -1 ? r.json() : r.text();
  }

  function qs(obj) {
    var parts = [];
    Object.keys(obj).forEach(function (k) {
      if (obj[k] !== undefined && obj[k] !== null && obj[k] !== "") parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(obj[k]));
    });
    return parts.length ? "?" + parts.join("&") : "";
  }

  function relDate(iso) {
    if (!iso) return null;
    var d = new Date(iso + "T00:00:00");
    var today = new Date(); today.setHours(0, 0, 0, 0);
    var days = Math.round((d - today) / 86400000);
    if (days === 0) return { txt: "Today", tone: "warn" };
    if (days === 1) return { txt: "Tomorrow", tone: "warn" };
    if (days > 1) return { txt: "In " + days + " day" + (days === 1 ? "" : "s"), tone: days <= 3 ? "warn" : "neutral" };
    return { txt: Math.abs(days) + " day" + (Math.abs(days) === 1 ? "" : "s") + " past due", tone: "crit" };
  }

  var DL = window.__app ? window.__app.DEADLINE_META : {};
  var SM = window.__app ? window.__app.STATUS_META : {};
  var MSTONES = window.__app ? window.__app.L1_MILESTONE_LABELS : {};
  var fmtDate = window.__app ? window.__app.fmtDate : function (s) { return s || ""; };

  function toneOf(deadlineKey) { return (DL[deadlineKey] || ["neutral"])[0]; }
  function labelOf(deadlineKey) { return (DL[deadlineKey] || [, deadlineKey])[1] || deadlineKey; }
  function statusLabel(statusKey) { return (SM[statusKey] || [, statusKey])[1] || statusKey; }
  function statusTone(statusKey) { return (SM[statusKey] || ["neutral"])[0]; }

  // ---------------------------------------------------- readiness (matrix) --
  // Same technique the matrix/readiness math already uses server-side
  // (rules.deadline_bucket -> not_due/due/completed) -- computed here from
  // the real /api/dashboard/matrix response, never invented client data.
  var _matrixCache = {};
  async function getMatrix(stage) {
    if (_matrixCache[stage]) return _matrixCache[stage];
    var m = await api("/api/dashboard/matrix" + qs({ stage: stage }));
    _matrixCache[stage] = m;
    return m;
  }
  function readinessByProject(matrix) {
    var out = {};
    matrix.projects.forEach(function (p) { out[p.id] = { done: 0, total: 0 }; });
    matrix.rows.forEach(function (row) {
      Object.keys(row.cells).forEach(function (pid) {
        pid = parseInt(pid, 10);
        if (!out[pid]) return;
        out[pid].total++;
        if (row.cells[pid].bucket === "completed") out[pid].done++;
      });
    });
    var pct = {};
    Object.keys(out).forEach(function (pid) {
      var o = out[pid];
      pct[pid] = o.total ? Math.round((o.done / o.total) * 100) : 0;
    });
    return pct;
  }

  function ringSvg(pct, size, strokeW, colorVar) {
    var r = (size - strokeW) / 2, c = 2 * Math.PI * r;
    var off = c * (1 - Math.max(0, Math.min(100, pct)) / 100);
    var color = pct >= 80 ? "var(--good)" : pct >= 50 ? "var(--warn)" : "var(--crit)";
    return '<svg viewBox="0 0 ' + size + " " + size + '" width="' + size + '" height="' + size + '">' +
      '<circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r + '" fill="none" stroke="var(--surface-sunken)" stroke-width="' + strokeW + '"/>' +
      '<circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r + '" fill="none" stroke="' + (colorVar || color) + '" stroke-width="' + strokeW +
      '" stroke-linecap="round" stroke-dasharray="' + c + '" stroke-dashoffset="' + off + '" transform="rotate(-90 ' + size / 2 + " " + size / 2 + ')"/>' +
      "</svg>";
  }

  // ---------------------------------------------------------- bottom sheet --
  var _sheetOverlay, _sheetPanel;
  function ensureSheetDom() {
    if (_sheetOverlay) return;
    _sheetOverlay = el("div", "m-sheet-overlay");
    _sheetPanel = el("div", "m-sheet-panel");
    _sheetOverlay.appendChild(_sheetPanel);
    document.body.appendChild(_sheetOverlay);
    _sheetOverlay.addEventListener("click", function (e) { if (e.target === _sheetOverlay) closeSheet(); });
  }
  function openSheet(buildFn, opts) {
    ensureSheetDom();
    opts = opts || {};
    _sheetPanel.className = "m-sheet-panel" + (opts.full ? " full" : "");
    _sheetPanel.innerHTML = "";
    _sheetPanel.appendChild(el("div", "m-sheet-grabber"));
    var body = el("div", "m-sheet-body");
    _sheetPanel.appendChild(body);
    buildFn(body, closeSheet);
    requestAnimationFrame(function () { _sheetOverlay.classList.add("open"); });
  }
  function closeSheet() {
    if (!_sheetOverlay) return;
    _sheetOverlay.classList.remove("open");
  }

  // ------------------------------------------------------------- toast/msg --
  function toast(msg) {
    var t = el("div", "m-card", msg);
    t.style.cssText = "position:fixed;left:16px;right:16px;bottom:calc(var(--m-nav-h) + var(--m-safe-b) + 14px);z-index:80;text-align:center;font-size:13px;font-weight:600;box-shadow:0 6px 20px rgba(16,36,62,.25);";
    document.body.appendChild(t);
    setTimeout(function () { t.style.transition = "opacity .3s"; t.style.opacity = "0"; setTimeout(function () { t.remove(); }, 300); }, 2200);
  }

  // ------------------------------------------------------------ navigation --
  var SCREENS = ["home", "portfolio", "project-detail", "actions", "alerts", "more"];
  var NAV_TABS = [
    { key: "home", label: "Home", icon: "&#127968;" },
    { key: "portfolio", label: "Portfolio", icon: "&#128193;" },
    { key: "actions", label: "Actions", icon: "&#9989;" },
    { key: "alerts", label: "Alerts", icon: "&#128276;" },
    { key: "more", label: "More", icon: "&#8942;" },
  ];

  var _shell, _navEl, _fabEl;
  var _screenEls = {};
  var _renderers = {};

  function showScreen(name, pushToStack) {
    SCREENS.forEach(function (s) { if (_screenEls[s]) _screenEls[s].hidden = s !== name; });
    if (pushToStack !== false) {
      if (name === "project-detail") STATE.stack.push(name);
      else STATE.stack = [];
    }
    var isTab = NAV_TABS.some(function (t) { return t.key === name; });
    if (isTab) { STATE.tab = name; renderNav(); }
    if (_renderers[name]) _renderers[name]();
    if (_screenEls[name]) _screenEls[name].scrollTop = 0;
  }
  window.__mobileShowScreen = showScreen; // used by cross-screen "view all" links

  function renderNav() {
    _navEl.innerHTML = "";
    NAV_TABS.forEach(function (t) {
      var btn = el("button", "m-nav-btn" + (STATE.tab === t.key ? " active" : ""));
      btn.innerHTML = '<span class="m-nav-ic">' + t.icon + "</span><span class=\"m-nav-lbl\">" + t.label + "</span>";
      btn.addEventListener("click", function () { showScreen(t.key); });
      _navEl.appendChild(btn);
    });
  }

  // =========================================================== HOME ======
  async function renderHome() {
    var root = _screenEls.home.querySelector(".m-screen-inner");
    root.innerHTML = '<div class="m-skel m-skel-card"></div><div class="m-skel m-skel-card"></div><div class="m-skel m-skel-card"></div>';
    try {
      var hour = new Date().getHours();
      var greet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
      var firstName = STATE.email ? STATE.email.split("@")[0].split(".")[0] : "";
      firstName = firstName ? firstName.charAt(0).toUpperCase() + firstName.slice(1) : "";

      var dash = await api("/api/dashboard" + qs({ focus_email: STATE.email || undefined }));
      var mine = STATE.email
        ? await api("/api/deliverables" + qs({ actor_email: STATE.email, actor_role: STATE.role }))
        : [];
      var dueMine = mine.filter(function (d) { return d.deadline_status === "due"; });
      var todayMine = mine.filter(function (d) { var r = relDate(d.due_date); return r && (r.txt === "Today" || r.txt === "Tomorrow"); });
      var rejectedMine = mine.filter(function (d) { return d.status === "rejected"; });

      var atRiskProjects = [];
      try {
        var m0 = await getMatrix("L0"), m1 = await getMatrix("L1");
        var r0 = readinessByProject(m0), r1 = readinessByProject(m1);
        m0.projects.forEach(function (p) { if (r0[p.id] < 70) atRiskProjects.push({ est_no: p.est_no, name: p.name, pct: r0[p.id], stage: "L0" }); });
        m1.projects.forEach(function (p) { if (r1[p.id] < 70) atRiskProjects.push({ est_no: p.est_no, name: p.name, pct: r1[p.id], stage: "L1" }); });
        atRiskProjects.sort(function (a, b) { return a.pct - b.pct; });
      } catch (e) {}

      root.innerHTML = "";

      var greetEl = el("div", "m-greeting");
      greetEl.innerHTML = '<div class="m-hi">' + greet + (firstName ? ", " + firstName : "") + '</div><h1>Here’s what needs you</h1>' +
        '<div class="m-sub">' + (dueMine.length || atRiskProjects.length
          ? (dueMine.length ? dueMine.length + " item" + (dueMine.length === 1 ? "" : "s") + " past due" : "") +
            (dueMine.length && atRiskProjects.length ? " · " : "") +
            (atRiskProjects.length ? atRiskProjects.length + " project" + (atRiskProjects.length === 1 ? "" : "s") + " at risk" : "")
          : "You’re all caught up.") + "</div>";
      root.appendChild(greetEl);

      // Requires Attention
      var attnSection = el("div", "m-section");
      attnSection.appendChild(el("div", "m-section-head", "<h2>&#128308; Requires Attention</h2>" +
        '<span class="m-count">' + (dueMine.length + rejectedMine.length + atRiskProjects.length) + "</span>"));
      var attnCards = [];
      dueMine.slice(0, 3).forEach(function (d) {
        attnCards.push({ ic: "&#9203;", title: d.item_no + " · " + d.short_name, sub: d.est_no + " — past due", onTap: function () { openDeliverableSheet(d); } });
      });
      rejectedMine.slice(0, 2).forEach(function (d) {
        attnCards.push({ ic: "&#10060;", title: d.item_no + " · " + d.short_name, sub: d.est_no + " — rejected, needs rework", onTap: function () { openDeliverableSheet(d); } });
      });
      atRiskProjects.slice(0, 2).forEach(function (p) {
        attnCards.push({ ic: "&#128201;", title: p.name, sub: p.est_no + " — readiness " + p.pct + "%", onTap: function () { openProjectByEstNo(p.est_no, p.stage); } });
      });
      if (!attnCards.length) {
        attnSection.appendChild(el("div", "m-attn-empty", '<span class="m-attn-empty-ic">&#9989;</span>Nothing urgent right now.'));
      } else {
        attnCards.slice(0, 4).forEach(function (c) {
          var card = el("div", "m-card m-tap m-attn-card");
          card.innerHTML = '<span class="m-attn-ic">' + c.ic + '</span><div class="m-attn-body"><div class="m-attn-title">' + c.title +
            '</div><div class="m-attn-sub">' + c.sub + '</div></div><span class="m-attn-arrow">&#8250;</span>';
          card.addEventListener("click", c.onTap);
          attnSection.appendChild(card);
        });
      }
      root.appendChild(attnSection);

      // Today
      var todaySection = el("div", "m-section");
      var todayCard = el("div", "m-card m-tap m-today-strip");
      todayCard.innerHTML = '<div class="m-today-num">' + todayMine.length + '</div>' +
        '<div class="m-today-txt">due today or tomorrow' + (STATE.email ? "" : " — set your email in Profile") + '</div><span class="m-today-arrow">&#8250;</span>';
      todayCard.addEventListener("click", function () { STATE.actionsBucket = "due-today"; showScreen("actions"); });
      todaySection.appendChild(todayCard);
      root.appendChild(todaySection);

      // Portfolio snapshot
      var snapSection = el("div", "m-section");
      snapSection.appendChild(el("div", "m-section-head", "<h2>Portfolio Snapshot</h2>"));
      var allPct = atRiskProjects.length || dash.active_l0 || dash.active_l1
        ? Object.assign({}, readinessByProject(await getMatrix("L0")), {}) : {};
      var m0b = await getMatrix("L0"), m1b = await getMatrix("L1");
      var r0b = readinessByProject(m0b), r1b = readinessByProject(m1b);
      var allVals = Object.values(r0b).concat(Object.values(r1b));
      var avgReadiness = allVals.length ? Math.round(allVals.reduce(function (a, b) { return a + b; }, 0) / allVals.length) : 0;
      var snapGrid = el("div", "m-card");
      var grid = el("div", "m-snapshot-grid");
      grid.innerHTML =
        '<div class="m-snap-tile"><div class="m-snap-num">' + dash.active_l0 + '</div><div class="m-snap-lbl">Active L0</div></div>' +
        '<div class="m-snap-tile"><div class="m-snap-num">' + dash.active_l1 + '</div><div class="m-snap-lbl">Active L1</div></div>' +
        '<div class="m-snap-tile readiness"><div class="m-snap-num">' + avgReadiness + '%</div><div class="m-snap-lbl">Readiness</div></div>';
      snapGrid.appendChild(grid);
      snapGrid.classList.add("m-tap");
      snapGrid.addEventListener("click", function () { showScreen("portfolio"); });
      snapSection.appendChild(snapGrid);
      root.appendChild(snapSection);

      // Recent activity
      var recent = (dash.recent_l0 || []).concat(dash.recent_l1 || []).concat(dash.recent_milestones_l0 || []).concat(dash.recent_milestones_l1 || []);
      if (recent.length) {
        var actSection = el("div", "m-section");
        actSection.appendChild(el("div", "m-section-head", "<h2>Recent Activity</h2>"));
        var actCard = el("div", "m-card");
        recent.slice(0, 5).forEach(function (r) {
          var row = el("div", "m-activity-row");
          var txt = r.name ? ("<b>" + r.est_no + "</b> — " + r.name) : ("<b>" + (r.est_no || "") + "</b> — " + (r.milestone_code || ""));
          row.innerHTML = '<span class="m-act-ic">&#128276;</span><span class="m-act-txt">' + txt + '</span>';
          actCard.appendChild(row);
        });
        actSection.appendChild(actCard);
        root.appendChild(actSection);
      }
    } catch (e) {
      root.innerHTML = '<div class="m-empty-state">Couldn’t load your home screen. Pull to refresh or try again.</div>';
      console.error(e);
    }
  }

  // ======================================================= PORTFOLIO ======
  var _portfolioAll = { L0: null, L1: null };
  var _portfolioQuery = "";
  async function renderPortfolio() {
    var root = _screenEls.portfolio.querySelector(".m-screen-inner");
    if (!root.dataset.built) {
      root.dataset.built = "1";
      root.innerHTML =
        '<div class="m-search"><span class="m-search-ic">&#128269;</span><input type="text" placeholder="Search Est-No or name" id="mPortfolioSearch"></div>' +
        '<div class="m-segmented" id="mPortfolioSeg" style="margin-bottom:12px;">' +
        '<button data-stage="L0">Tenders</button><button data-stage="L1">Projects</button></div>' +
        '<div id="mPortfolioList"></div>';
      root.querySelector("#mPortfolioSearch").addEventListener("input", function (e) { _portfolioQuery = e.target.value.toLowerCase(); drawPortfolioList(); });
      root.querySelectorAll("#mPortfolioSeg button").forEach(function (b) {
        b.addEventListener("click", function () { STATE.portfolioStage = b.dataset.stage; drawPortfolioList(); });
      });
    }
    root.querySelectorAll("#mPortfolioSeg button").forEach(function (b) { b.classList.toggle("active", b.dataset.stage === STATE.portfolioStage); });
    await drawPortfolioList();
  }
  async function drawPortfolioList() {
    var listEl = document.getElementById("mPortfolioList");
    if (!listEl) return;
    var stage = STATE.portfolioStage;
    listEl.innerHTML = '<div class="m-skel m-skel-card"></div><div class="m-skel m-skel-card"></div>';
    try {
      var projects = _portfolioAll[stage] || await api("/api/projects" + qs({ stage: stage }));
      _portfolioAll[stage] = projects;
      var matrix = await getMatrix(stage);
      var pct = readinessByProject(matrix);
      var filtered = projects.filter(function (p) {
        if (!_portfolioQuery) return true;
        return (p.est_no + " " + p.name).toLowerCase().indexOf(_portfolioQuery) !== -1;
      });
      listEl.innerHTML = "";
      if (!filtered.length) { listEl.innerHTML = '<div class="m-empty-state">No matching ' + (stage === "L0" ? "tenders" : "projects") + ".</div>"; return; }
      filtered.forEach(function (p) {
        var readiness = pct[p.id] !== undefined ? pct[p.id] : null;
        var nextMs = stage === "L1" && p.current_milestone
          ? nextMilestoneAfter(p.current_milestone) : (stage === "L1" ? "M1" : null);
        var card = el("div", "m-card m-tap m-proj-card");
        var statusTone2 = p.status === "In Progress" ? "warn" : p.status === "Completed" || p.status === "Submitted" ? "good" : "neutral";
        card.innerHTML =
          '<div class="m-proj-top"><div><div class="m-proj-name">' + escapeHtml(p.name) + '</div><div class="m-proj-est">' + p.est_no + '</div></div>' +
          '<span class="m-pill tone-' + statusTone2 + '">' + p.status + '</span></div>' +
          '<div class="m-proj-mid"><span class="m-ring">' + (readiness !== null ? ringSvg(readiness, 40, 5) : "") + '</span>' +
          '<div class="m-proj-next">' + (readiness !== null ? '<div class="m-lbl">Readiness</div><div class="m-val">' + readiness + '%</div>' : '<div class="m-val">No active items</div>') + '</div>' +
          (nextMs ? '<div class="m-proj-next" style="text-align:right;"><div class="m-lbl">Next</div><div class="m-val">' + nextMs + " · " + (MSTONES[nextMs] || "") + '</div></div>' : "") +
          "</div>";
        card.addEventListener("click", function () { openProjectByEstNo(p.est_no, stage, p); });
        listEl.appendChild(card);
      });
    } catch (e) {
      listEl.innerHTML = '<div class="m-empty-state">Couldn’t load the list.</div>';
      console.error(e);
    }
  }
  function nextMilestoneAfter(code) {
    var order = ["M1", "M2", "M3", "M4", "M5", "M6"];
    var i = order.indexOf(code);
    return i >= 0 && i < order.length - 1 ? order[i + 1] : null;
  }
  function escapeHtml(s) { var d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }

  // =================================================== PROJECT DETAIL ======
  var _currentProject = null;
  async function openProjectByEstNo(estNo, stage, projectObj) {
    showScreen("project-detail");
    var root = _screenEls["project-detail"].querySelector(".m-screen-inner");
    root.innerHTML = '<div class="m-skel m-skel-card" style="height:180px;"></div><div class="m-skel m-skel-card"></div>';
    try {
      var p = projectObj || (await api("/api/projects" + qs({ stage: stage }))).find(function (x) { return x.est_no === estNo; });
      _currentProject = p;
      var deliverables = await api("/api/deliverables" + qs({}));
      var mine = deliverables.filter(function (d) { return d.est_no === estNo; });
      var matrix = await getMatrix(stage);
      var pct = readinessByProject(matrix)[p.id];
      var due = mine.filter(function (d) { return d.deadline_status === "due"; });
      var upcoming = mine.filter(function (d) { return d.deadline_status === "not_due"; })
        .sort(function (a, b) { return (a.due_date || "").localeCompare(b.due_date || ""); });
      var critical = due.concat(upcoming).slice(0, 5);

      root.innerHTML = "";
      var head = el("div", "m-pd-header");
      var statusTone2 = p.status === "In Progress" ? "warn" : "good";
      head.innerHTML = '<div class="m-pd-name">' + escapeHtml(p.name) + '</div><div class="m-pd-est">' + p.est_no + '</div>' +
        '<div class="m-pd-pills"><span class="m-pill tone-' + statusTone2 + '">' + p.status + '</span>' +
        (p.contract_status ? '<span class="m-pill tone-' + (p.contract_status === "Signed" ? "good" : "neutral") + '">' + p.contract_status + '</span>' : "") +
        (p.is_international ? '<span class="m-pill tone-accent">International</span>' : "") + "</div>";
      root.appendChild(head);

      var ringWrap = el("div", "m-ring-big-wrap");
      ringWrap.innerHTML = '<div style="position:relative;">' + ringSvg(pct === undefined ? 0 : pct, 108, 9) +
        '<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;">' +
        '<span class="m-ring-big-num">' + (pct === undefined ? "—" : pct + "%") + '</span><span class="m-ring-big-lbl">Ready</span></div></div>';
      if (due.length) {
        var nextAction = el("div", "m-next-action", "&#9888;&#65039; " + due.length + " item" + (due.length === 1 ? "" : "s") + " past due");
        ringWrap.appendChild(nextAction);
      } else if (upcoming.length) {
        ringWrap.appendChild(el("div", "m-next-action", "Next: " + upcoming[0].item_no + " · " + upcoming[0].short_name));
      }
      root.appendChild(ringWrap);

      if (stage === "L1") {
        var msSection = el("div", "m-section");
        msSection.appendChild(el("div", "m-section-head", "<h2>Milestones</h2>"));
        var strip = el("div", "m-mstone-strip");
        Object.keys(MSTONES).forEach(function (code) {
          var state = p.current_milestone && code <= p.current_milestone ? "done" : (nextMilestoneAfter(p.current_milestone || "") === code ? "current" : "upcoming");
          if (p.current_milestone === code) state = "done";
          if (!p.current_milestone && code === "M1") state = "current";
          var m = el("div", "m-mstone " + state);
          m.innerHTML = '<div class="m-mstone-dot">' + (state === "done" ? "&#10003;" : code.replace("M", "")) + '</div>' +
            '<div class="m-mstone-code">' + code + '</div><div class="m-mstone-name">' + MSTONES[code] + "</div>";
          strip.appendChild(m);
        });
        msSection.appendChild(strip);
        root.appendChild(msSection);
      }

      var critSection = el("div", "m-section");
      critSection.appendChild(el("div", "m-section-head", "<h2>Critical Deliverables</h2>" +
        (mine.length > 5 ? '<button class="m-section-link" id="mPdViewAll">View all ' + mine.length + "</button>" : "")));
      var critCard = el("div", "m-card");
      if (!critical.length) critCard.appendChild(el("div", "m-empty-state", "Nothing due or upcoming."));
      critical.forEach(function (d) { critCard.appendChild(deliverableMiniRow(d)); });
      critSection.appendChild(critCard);
      root.appendChild(critSection);
      if (mine.length > 5) {
        document.getElementById("mPdViewAll").addEventListener("click", function () {
          _actionsProjectFilter = estNo; STATE.actionsBucket = "all"; showScreen("actions");
        });
      }

      var actRow = el("div", "m-actions-row");
      var followBtn = el("button", "m-btn", "Follow");
      followBtn.addEventListener("click", function () { toast("Following isn’t wired to a single project yet — follow individual deliverables from Actions."); });
      var askBtn = el("button", "m-btn primary", "Ask GAHIZ");
      askBtn.addEventListener("click", function () { openGahizSheet("What's the status of " + estNo + "?"); });
      actRow.appendChild(followBtn); actRow.appendChild(askBtn);
      root.appendChild(actRow);
    } catch (e) {
      root.innerHTML = '<div class="m-empty-state">Couldn’t load this project.</div>';
      console.error(e);
    }
  }
  function deliverableMiniRow(d) {
    var row = el("div", "m-deliv-row m-tap");
    var tone = toneOf(d.deadline_status);
    var rd = relDate(d.due_date);
    row.innerHTML = '<span class="m-deliv-dot tone-' + tone + '"></span>' +
      '<div class="m-deliv-main"><div class="m-deliv-name">' + d.item_no + " · " + escapeHtml(d.short_name) + '</div>' +
      '<div class="m-deliv-sub">' + (rd ? rd.txt : "No due date") + "</div></div>" +
      '<span class="m-deliv-chev">&#8250;</span>';
    row.addEventListener("click", function () { openDeliverableSheet(d); });
    return row;
  }

  // ========================================================= ACTIONS ======
  var _actionsProjectFilter = null;
  var ACTION_BUCKETS = [
    { key: "due-today", label: "Due Today" }, { key: "due", label: "Overdue" },
    { key: "upcoming", label: "Upcoming" }, { key: "completed", label: "Completed" },
  ];
  async function renderActions() {
    var root = _screenEls.actions.querySelector(".m-screen-inner");
    if (!root.dataset.built) {
      root.dataset.built = "1";
      var seg = el("div", "m-segmented", "");
      ACTION_BUCKETS.forEach(function (b) {
        var btn = el("button", "", b.label); btn.dataset.key = b.key;
        btn.addEventListener("click", function () { STATE.actionsBucket = b.key; drawActionsList(); });
        seg.appendChild(btn);
      });
      root.appendChild(seg);
      var filterRow = el("div", "", "");
      filterRow.style.cssText = "margin:10px 0 4px;";
      filterRow.id = "mActionsFilterNote";
      root.appendChild(filterRow);
      root.appendChild(el("div", "", '<div id="mActionsList" style="margin-top:6px;"></div>'));
    }
    root.querySelectorAll(".m-segmented button").forEach(function (b) { b.classList.toggle("active", b.dataset.key === STATE.actionsBucket); });
    await drawActionsList();
  }
  async function drawActionsList() {
    var listEl = document.getElementById("mActionsList");
    var noteEl = document.getElementById("mActionsFilterNote");
    if (!listEl) return;
    if (!STATE.email) {
      listEl.innerHTML = '<div class="m-empty-state">Set your email in More &rarr; Profile to see your assigned deliverables.</div>';
      return;
    }
    noteEl.innerHTML = _actionsProjectFilter
      ? '<span class="m-chip active" id="mActionsClearFilter">' + _actionsProjectFilter + " &#10005;</span>" : "";
    if (_actionsProjectFilter) document.getElementById("mActionsClearFilter").addEventListener("click", function () { _actionsProjectFilter = null; drawActionsList(); });
    listEl.innerHTML = '<div class="m-skel m-skel-card"></div><div class="m-skel m-skel-card"></div>';
    try {
      var all = await api("/api/deliverables" + qs({ actor_email: STATE.email, actor_role: STATE.role }));
      if (_actionsProjectFilter) all = all.filter(function (d) { return d.est_no === _actionsProjectFilter; });
      var bucket = STATE.actionsBucket;
      var filtered = all.filter(function (d) {
        if (bucket === "completed") return d.status === "approved";
        if (bucket === "due") return d.deadline_status === "due";
        if (bucket === "due-today") { var r = relDate(d.due_date); return d.deadline_status !== "on_time" && d.deadline_status !== "early" && r && (r.txt === "Today" || r.txt === "Tomorrow"); }
        if (bucket === "upcoming") return d.deadline_status === "not_due";
        return true;
      }).sort(function (a, b) { return (a.due_date || "").localeCompare(b.due_date || ""); });
      listEl.innerHTML = "";
      if (!filtered.length) { listEl.innerHTML = '<div class="m-empty-state">Nothing here.</div>'; return; }
      filtered.forEach(function (d) {
        var rd = relDate(d.due_date);
        var card = el("div", "m-card m-tap m-action-card");
        card.innerHTML = '<div class="m-ac-main"><div class="m-ac-item">' + d.item_no + '</div><div class="m-ac-name">' + escapeHtml(d.short_name) + '</div>' +
          '<div class="m-ac-meta"><span>' + d.est_no + '</span><span class="sep">&middot;</span>' +
          '<span class="m-pill tone-' + statusTone(d.status) + '">' + statusLabel(d.status) + '</span>' +
          (rd ? '<span class="sep">&middot;</span><span>' + rd.txt + '</span>' : "") + '</div></div>' +
          '<span class="m-ac-chev">&#8250;</span>';
        card.addEventListener("click", function () { openDeliverableSheet(d); });
        listEl.appendChild(card);
      });
    } catch (e) {
      listEl.innerHTML = '<div class="m-empty-state">Couldn’t load your actions.</div>';
      console.error(e);
    }
  }

  // deliverable action sheet -------------------------------------------------
  function openDeliverableSheet(d) {
    openSheet(function (body, close) {
      var rd = relDate(d.due_date);
      body.innerHTML =
        '<div class="m-sheet-title">' + d.item_no + " · " + escapeHtml(d.short_name) + '</div>' +
        '<div class="m-sheet-sub">' + d.est_no + " · " + escapeHtml(d.project_name || "") + '</div>' +
        '<div class="m-kv-grid">' +
        '<div class="m-kv"><div class="m-kv-lbl">Status</div><div class="m-kv-val"><span class="m-pill tone-' + statusTone(d.status) + '">' + statusLabel(d.status) + '</span></div></div>' +
        '<div class="m-kv"><div class="m-kv-lbl">Deadline</div><div class="m-kv-val"><span class="m-pill tone-' + toneOf(d.deadline_status) + '">' + labelOf(d.deadline_status) + '</span></div></div>' +
        '<div class="m-kv"><div class="m-kv-lbl">Due Date</div><div class="m-kv-val">' + (fmtDate(d.due_date) || "—") + (rd ? " (" + rd.txt + ")" : "") + '</div></div>' +
        '<div class="m-kv"><div class="m-kv-lbl">Department</div><div class="m-kv-val">' + escapeHtml(d.department || "—") + '</div></div>' +
        '<div class="m-kv"><div class="m-kv-lbl">Owner</div><div class="m-kv-val">' + escapeHtml(d.owner || "Unassigned") + '</div></div>' +
        '<div class="m-kv"><div class="m-kv-lbl">SME</div><div class="m-kv-val">' + escapeHtml((d.sme_emails || []).join(", ") || "—") + '</div></div>' +
        "</div>";
      if (d.review_comment) body.appendChild(el("div", "m-formula-box", "<b>Last note:</b> " + escapeHtml(d.review_comment)));

      var myEmail = STATE.email.toLowerCase();
      var isOwner = (d.owner_emails || []).map(function (e) { return e.toLowerCase(); }).indexOf(myEmail) !== -1;
      var isSme = (d.sme_emails || []).map(function (e) { return e.toLowerCase(); }).indexOf(myEmail) !== -1;
      var canAct = STATE.role === "Admin" || isOwner || isSme;

      if (canAct && d.status !== "approved" && (STATE.role === "Owner" || STATE.role === "Admin") && (isOwner || STATE.role === "Admin") && d.status !== "pending_review") {
        var comment = el("textarea", "m-comment-box");
        comment.placeholder = "What did you do? (required to mark complete)";
        body.appendChild(comment);
        var row = el("div", "m-actions-row");
        var completeBtn = el("button", "m-btn primary", "Mark Complete");
        completeBtn.addEventListener("click", function () { submitMarkComplete(d, comment.value, close); });
        row.appendChild(completeBtn);
        body.appendChild(row);
      }
      if (canAct && (STATE.role === "SME" || STATE.role === "Admin") && d.status === "pending_review") {
        var rcomment = el("textarea", "m-comment-box");
        rcomment.placeholder = "Review comment (required if rejecting)";
        body.appendChild(rcomment);
        var row2 = el("div", "m-actions-row");
        var rejectBtn = el("button", "m-btn", "Reject");
        rejectBtn.addEventListener("click", function () { submitReview(d, false, rcomment.value, close); });
        var approveBtn = el("button", "m-btn primary", "Approve");
        approveBtn.addEventListener("click", function () { submitReview(d, true, rcomment.value, close); });
        row2.appendChild(rejectBtn); row2.appendChild(approveBtn);
        body.appendChild(row2);
      }
      var followRow = el("div", "m-actions-row");
      var followBtn = el("button", "m-btn" + (d.following ? " primary" : ""), d.following ? "Following" : "Follow");
      followBtn.addEventListener("click", function () { toggleFollow(d, followBtn); });
      var closeBtn = el("button", "m-btn ghost", "Close");
      closeBtn.addEventListener("click", close);
      followRow.appendChild(followBtn); followRow.appendChild(closeBtn);
      body.appendChild(followRow);
    });
  }
  async function submitMarkComplete(d, comment, close) {
    if (!comment || !comment.trim()) { toast("A comment is required."); return; }
    try {
      await api("/api/deliverables/" + d.id + "/mark-complete", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor_name: STATE.role, actor_role: STATE.role, actor_email: STATE.email, comment: comment.trim() }),
      });
      toast("Submitted.");
      close(); drawActionsList();
    } catch (e) { toast("Couldn’t submit: " + e.message); }
  }
  async function submitReview(d, approved, comment, close) {
    if (!approved && !(comment || "").trim()) { toast("A comment is required to reject."); return; }
    try {
      var fd = new FormData();
      fd.append("approved", approved ? "true" : "false");
      fd.append("comment", comment || "");
      fd.append("reviewer_name", STATE.role);
      fd.append("actor_role", STATE.role);
      fd.append("actor_email", STATE.email);
      await api("/api/deliverables/" + d.id + "/review", { method: "POST", body: fd });
      toast(approved ? "Approved." : "Rejected.");
      close(); drawActionsList();
    } catch (e) { toast("Couldn’t submit: " + e.message); }
  }
  async function toggleFollow(d, btn) {
    try {
      var r = await api("/api/deliverables/" + d.id + "/follow", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: STATE.email || "anonymous" }),
      });
      d.following = r.following;
      btn.textContent = r.following ? "Following" : "Follow";
      btn.classList.toggle("primary", r.following);
    } catch (e) { toast("Couldn’t update: " + e.message); }
  }

  // ========================================================== ALERTS ======
  async function renderAlerts() {
    var root = _screenEls.alerts.querySelector(".m-screen-inner");
    root.innerHTML = '<div class="m-skel m-skel-card"></div><div class="m-skel m-skel-card"></div>';
    try {
      var news = await api("/api/announcements" + qs({ limit: 40, category: "news" }));
      var reminders = await api("/api/announcements" + qs({ limit: 40, category: "reminders" }));
      var all = news.concat(reminders).sort(function (a, b) { return (b.created_at || "").localeCompare(a.created_at || ""); });
      var todayStr = new Date().toISOString().slice(0, 10);
      var urgent = [], today = [], earlier = [];
      all.forEach(function (a) {
        var isReminder = reminders.indexOf(a) !== -1;
        var d = (a.created_at || "").slice(0, 10);
        if (isReminder && (a.type === "deadline")) urgent.push(a);
        else if (d === todayStr) today.push(a);
        else earlier.push(a);
      });
      root.innerHTML = "";
      function group(label, items, urgentGroup) {
        if (!items.length) return;
        root.appendChild(el("div", "m-alert-group-lbl", label));
        var card = el("div", "m-card");
        items.slice(0, 20).forEach(function (a) {
          var row = el("div", "m-alert-row" + (urgentGroup ? " urgent" : ""));
          var icon = (window.__app && window.__app.ANN_ICON && window.__app.ANN_ICON[a.type]) ? window.__app.ANN_ICON[a.type][0] : "&#128276;";
          var bodyText = (a.body || "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
          row.innerHTML = '<span class="m-alert-ic">' + icon + '</span><div class="m-alert-main"><div class="m-alert-txt"><b>' + escapeHtml(a.title || "") + "</b>" +
            (bodyText ? " — " + escapeHtml(bodyText.length > 110 ? bodyText.slice(0, 110) + "…" : bodyText) : "") +
            '</div><div class="m-alert-time">' + timeAgo(a.created_at) + "</div></div>";
          card.appendChild(row);
        });
        root.appendChild(card);
      }
      group("Urgent", urgent, true);
      group("Today", today, false);
      group("Earlier", earlier, false);
      if (!all.length) root.innerHTML = '<div class="m-empty-state">No announcements yet.</div>';
    } catch (e) {
      root.innerHTML = '<div class="m-empty-state">Couldn’t load alerts.</div>';
      console.error(e);
    }
  }
  function timeAgo(iso) {
    if (!iso) return "";
    var diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 3600) return Math.max(1, Math.round(diff / 60)) + "m ago";
    if (diff < 86400) return Math.round(diff / 3600) + "h ago";
    return Math.round(diff / 86400) + "d ago";
  }

  // ============================================================ MORE ======
  function renderMore() {
    var root = _screenEls.more.querySelector(".m-screen-inner");
    root.innerHTML = "";
    var profileCard = el("div", "m-card m-tap m-profile-card");
    var initial = (STATE.email || STATE.role || "?").trim().charAt(0).toUpperCase();
    profileCard.innerHTML = '<div class="m-profile-avatar">' + initial + '</div><div class="m-profile-main">' +
      '<div class="m-profile-name">' + (STATE.email || "Set your email") + '</div>' +
      '<div class="m-profile-role">Acting as ' + STATE.role + '</div></div><span class="m-deliv-chev">&#8250;</span>';
    profileCard.addEventListener("click", openProfileSheet);
    root.appendChild(profileCard);

    function group(label, items) {
      root.appendChild(el("div", "m-more-group-lbl", label));
      var list = el("div", "m-more-list");
      items.forEach(function (it) {
        var row = el("div", "m-more-item");
        row.innerHTML = '<span class="m-more-ic">' + it.ic + '</span><span class="m-more-txt">' + it.label + '</span><span class="m-deliv-chev">&#8250;</span>';
        row.addEventListener("click", it.onTap);
        list.appendChild(row);
      });
      root.appendChild(list);
    }
    group("Insights", [
      { ic: "&#127942;", label: "Performance & Top Achievers", onTap: function () { openDesktopView("performance"); } },
      { ic: "&#128218;", label: "Deliverables Catalog", onTap: function () { openDesktopView("deliverableformulas"); } },
      { ic: "&#128203;", label: "BM Triage Status", onTap: function () { openDesktopView("bmtriage"); } },
    ]);
    group("Requests", [
      { ic: "&#128231;", label: "My Requests", onTap: function () { openDesktopView("myrequests"); } },
      { ic: "&#128172;", label: "Ask the Team", onTap: function () { openDesktopView("support"); } },
    ]);
    if (STATE.role === "Admin") {
      group("Admin", [
        { ic: "&#128202;", label: "Reports", onTap: function () { openDesktopView("reports"); } },
        { ic: "&#128100;", label: "Focal Points", onTap: function () { openDesktopView("focalpoints"); } },
        { ic: "&#9881;&#65039;", label: "Deliverables Configuration", onTap: function () { openDesktopView("deliverableconfig"); } },
      ]);
    }
    group("About", [
      { ic: "&#129302;", label: "L0/L1 Walkthrough", onTap: function () { if (window.__app && window.__app.openTour) window.__app.openTour(); } },
    ]);
  }
  function openDesktopView(viewName) {
    // Deliberately honest scope call: a handful of dense power-admin/editor
    // screens (Reports builder, Deliverables Configuration's full editor)
    // aren't worth redesigning for a phone -- forcing that onto mobile
    // would itself be bad UX. These drop back to the real desktop view
    // (same page, same data) instead of a half-built mobile knockoff.
    document.body.classList.add("mobile-desktop-peek");
    document.body.classList.remove("mobile-shell");
    if (window.__app && window.__app.switchView) window.__app.switchView(viewName);
    if (!document.getElementById("mMobileReturnBar")) {
      var bar = el("div", "", "&#8592; Back to mobile app");
      bar.id = "mMobileReturnBar";
      bar.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:999;background:var(--algihaz-red);color:#fff;text-align:center;padding:10px;font-size:13px;font-weight:700;cursor:pointer;";
      bar.addEventListener("click", function () {
        document.body.classList.remove("mobile-desktop-peek");
        applyShellClass();
        bar.remove();
      });
      document.body.appendChild(bar);
    }
  }
  function openProfileSheet() {
    openSheet(function (body, close) {
      body.innerHTML = '<div class="m-sheet-title">Profile</div><div class="m-sheet-sub">Who you’re acting as — same identity the rest of the app uses.</div>';
      var roleLbl = el("div", "m-kv-lbl", "Role");
      body.appendChild(roleLbl);
      var seg = el("div", "m-segmented", "");
      seg.style.marginBottom = "16px";
      ["Admin", "Owner", "SME", "Viewer"].forEach(function (r) {
        var b = el("button", r === STATE.role ? "active" : "", r);
        b.addEventListener("click", function () { setRole(r); openProfileSheet(); });
        seg.appendChild(b);
      });
      body.appendChild(seg);
      var emailLbl = el("div", "m-kv-lbl", "Email");
      body.appendChild(emailLbl);
      var input = el("input");
      input.type = "email"; input.value = STATE.email; input.placeholder = "name@algihaz.com";
      input.className = "m-comment-box"; input.style.minHeight = "auto"; input.style.marginTop = "6px";
      body.appendChild(input);
      var row = el("div", "m-actions-row"); row.style.marginTop = "16px";
      var save = el("button", "m-btn primary", "Save");
      save.addEventListener("click", function () { setEmail(input.value); toast("Saved."); close(); renderMore(); if (STATE.tab === "home") renderHome(); });
      row.appendChild(save);
      body.appendChild(row);
    });
  }

  // ============================================================ GAHIZ ======
  var GAHIZ_SUGGESTIONS = ["Show my due deliverables", "Which projects are at risk?", "What's due this week?", "Show L0 readiness", "Show L1 readiness"];
  function openGahizSheet(prefill) {
    openSheet(function (body, close) {
      var head = el("div", "m-gahiz-head");
      head.innerHTML = '<img src="/static/img/gahiz-icon.png" alt="GAHIZ"><div><h2>GAHIZ</h2><div class="m-gahiz-sub">How can I help?</div></div>';
      var closeBtn = el("button", "m-gahiz-close", "&#10005;");
      closeBtn.addEventListener("click", close);
      head.appendChild(closeBtn);
      body.appendChild(head);

      var suggestWrap = el("div", "m-gahiz-suggest");
      GAHIZ_SUGGESTIONS.forEach(function (s) {
        var b = el("button", "", s);
        b.addEventListener("click", function () { send(s); });
        suggestWrap.appendChild(b);
      });
      body.appendChild(suggestWrap);

      var msgsEl = el("div", "m-gahiz-msgs");
      body.appendChild(msgsEl);
      var usageEl = el("div", "m-gahiz-usage", "");
      body.appendChild(usageEl);

      var inputRow = el("div", "m-gahiz-input-row");
      var input = el("input"); input.type = "text"; input.placeholder = "Ask GAHIZ anything…";
      var sendBtn = el("button", "m-gahiz-send", "&#10148;");
      inputRow.appendChild(input); inputRow.appendChild(sendBtn);
      body.appendChild(inputRow);

      function renderMsgs() {
        msgsEl.innerHTML = "";
        suggestWrap.style.display = STATE.gahizHistory.length ? "none" : "flex";
        STATE.gahizHistory.forEach(function (m) {
          msgsEl.appendChild(el("div", "m-gahiz-bubble " + (m.role === "user" ? "user" : "ai"), escapeHtml(m.content)));
        });
        msgsEl.scrollTop = msgsEl.scrollHeight;
      }
      renderMsgs();

      async function send(text) {
        text = (text || input.value).trim();
        if (!text) return;
        input.value = "";
        STATE.gahizHistory.push({ role: "user", content: text });
        renderMsgs();
        sendBtn.disabled = true;
        try {
          var r = await api("/api/ai-support/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text, history: STATE.gahizHistory.slice(0, -1), actor_email: STATE.email, actor_role: STATE.role }),
          });
          STATE.gahizHistory.push({ role: "assistant", content: r.reply });
          usageEl.textContent = r.remaining + " of " + r.limit + " messages left today";
          renderMsgs();
        } catch (e) {
          STATE.gahizHistory.push({ role: "assistant", content: "Sorry, I couldn’t reach the server. Try again, or use Ask the Team." });
          renderMsgs();
        }
        sendBtn.disabled = false;
      }
      sendBtn.addEventListener("click", function () { send(); });
      input.addEventListener("keydown", function (e) { if (e.key === "Enter") send(); });
      if (prefill) send(prefill);
    }, { full: true });
  }

  // ============================================================ INIT =======
  function buildShell() {
    if (document.getElementById("mobileShell")) return;
    _shell = el("div"); _shell.id = "mobileShell";
    SCREENS.forEach(function (name) {
      var screen = el("div", "m-screen"); screen.id = "mScreen-" + name; screen.hidden = name !== "home";
      var needsBack = name === "project-detail";
      var titleMap = { home: "", portfolio: "Portfolio", "project-detail": "", actions: "My Actions", alerts: "Alerts", more: "More" };
      if (titleMap[name] || needsBack) {
        var top = el("div", "m-topbar");
        if (needsBack) {
          var back = el("button", "m-back-btn", "&#8592;");
          back.addEventListener("click", function () { showScreen("portfolio"); });
          top.appendChild(back);
        }
        if (titleMap[name]) top.appendChild(el("h1", "", titleMap[name]));
        screen.appendChild(top);
      }
      screen.appendChild(el("div", "m-screen-inner"));
      _screenEls[name] = screen;
      _shell.appendChild(screen);
    });
    _navEl = el("div", "m-nav");
    _shell.appendChild(_navEl);
    _fabEl = el("button", "m-fab");
    _fabEl.innerHTML = '<img src="/static/img/gahiz-icon.png" alt="GAHIZ">';
    _fabEl.addEventListener("click", function () { openGahizSheet(); });
    _shell.appendChild(_fabEl);
    document.body.appendChild(_shell);

    _renderers = { home: renderHome, portfolio: renderPortfolio, actions: renderActions, alerts: renderAlerts, more: renderMore };
    renderNav();
  }

  function boot() {
    buildShell();
    applyShellClass();
    if (isMobileMode()) showScreen(STATE.tab, false);
  }

  // matchMedia's own change listener (not a generic "resize" handler) is
  // the robust way to catch this: it fires exactly when the 780px
  // boundary is actually crossed -- including on a programmatic viewport
  // change (devtools device toolbar, automated resize) that doesn't
  // always dispatch a real window "resize" event -- rather than on every
  // pixel of an ordinary window drag. "resize" kept too as a fallback for
  // engines without addEventListener on a MediaQueryList.
  if (_mq.addEventListener) _mq.addEventListener("change", applyShellClass);
  else if (_mq.addListener) _mq.addListener(applyShellClass); // Safari <14
  window.addEventListener("resize", applyShellClass);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  // PWA installability -- shell-only caching, /api/* always passthrough
  // (see sw.js's own header comment). No version query string on this
  // URL: that would register a brand-new worker on every deploy instead
  // of letting the browser's normal byte-diff update check do its job.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function (e) { console.warn("SW registration failed", e); });
    });
  }
})();

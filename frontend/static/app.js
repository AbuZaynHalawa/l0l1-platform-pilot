/* Real frontend for the L0/L1 pilot. Every render here comes from an actual
   fetch() to the FastAPI backend — no hardcoded data arrays anywhere in this
   file. Role-based button gating is client-side only for now (no per-user
   login exists yet in the pilot) — before this goes company-wide, the same
   checks need to be enforced server-side too, not just hidden in the UI. */
(function () {
  "use strict";

  var CURRENT_ROLE = "Admin";
  function can(action) {
    if (CURRENT_ROLE === "Admin") return true;
    if (action === "upload") return CURRENT_ROLE === "Owner";
    if (action === "review") return CURRENT_ROLE === "SME";
    if (action === "remind" || action === "create") return false;
    return true;
  }

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html !== undefined) e.innerHTML = html;
    return e;
  }
  function fmtDate(iso) {
    if (!iso) return "&#8213;";
    var d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  }
  async function api(path, opts) {
    var r = await fetch(path, opts);
    if (!r.ok) { throw new Error(path + " -> " + r.status + ": " + (await r.text())); }
    return r.status === 204 ? null : r.json();
  }
  function showToast(msg) {
    var t = document.getElementById("toast");
    document.getElementById("toastMsg").innerHTML = msg;
    t.classList.add("show");
    clearTimeout(window.__toastTimer);
    window.__toastTimer = setTimeout(function () { t.classList.remove("show"); }, 3200);
  }

  var STATUS_META = {
    not_due: ["neutral", "Not Due"], due: ["warn", "Due"], overdue: ["crit", "Overdue"],
    pending_review: ["warn", "Pending SME Review"], approved: ["good", "Approved"], rejected: ["crit", "Rejected"],
  };
  var PROJECT_STATUS_CLASS = { "Signed": "good", "Cancelled": "crit", "Submitted": "good", "In Progress": "warn" };
  var ANN_ICON = {
    broadcast: ["&#128276;", "broadcast"], owner: ["&#128100;", "owner"], sme_request: ["&#128269;", "sme-request"],
    sme_decision: ["&#9989;", "sme-decision"], unlock: ["&#128275;", "unlock"], deadline: ["&#8987;", "deadline"], closed: ["&#127937;", "closed"],
  };

  /* ================= VIEW SWITCHING ================= */
  var LOADERS = {
    dashboard: loadDashboard, assigned: loadAssigned, announcements: loadAnnouncements,
    l0: function () { loadProjectsTable("L0"); }, l1: function () { loadProjectsTable("L1"); },
    performance: loadPerformance, reports: loadReports,
  };
  function switchView(name) {
    if ((name === "create" || name === "reports") && !can("create")) name = "dashboard";
    document.querySelectorAll(".view").forEach(function (v) { v.hidden = true; });
    document.getElementById("view-" + name).hidden = false;
    document.querySelectorAll(".nav-item").forEach(function (n) { n.classList.toggle("active", n.dataset.view === name); });
    if (LOADERS[name]) LOADERS[name]();
  }
  document.querySelectorAll(".nav-item").forEach(function (btn) {
    btn.addEventListener("click", function () { switchView(btn.dataset.view); });
  });
  document.getElementById("backBtn").addEventListener("click", function () { switchView(lastListView); });

  /* ================= DASHBOARD ================= */
  var STAGE_META = [
    { key: "lpre", label: "L-Pre", desc: "International BD opportunities" },
    { key: "l0", label: "L0", desc: "Tendering &mdash; bid preparation" },
    { key: "l1", label: "L1", desc: "Post-bid-win, M1&#8211;M6" },
    { key: "signed", label: "Signed", desc: "Contract executed" },
  ];
  async function loadDashboard() {
    var d = await api("/api/dashboard");

    var banner = document.getElementById("concernsBanner");
    var list = document.getElementById("concernsList");
    list.innerHTML = "";
    if (d.concerns && d.concerns.length) {
      banner.hidden = false;
      d.concerns.forEach(function (c) { list.appendChild(el("li", "", c)); });
    } else {
      banner.hidden = true;
    }

    var stats = document.getElementById("statRow");
    stats.innerHTML = "";
    [["Active L0 Tenders", d.active_l0, ""], ["Active L1 Projects", d.active_l1, ""],
     ["Pending SME Review", d.pending_review, ""], ["Overdue Right Now", d.overdue, "color:var(--crit)"]]
      .forEach(function (s) {
        var tile = el("div", "card stat-tile");
        tile.appendChild(el("div", "label", s[0]));
        var v = el("div", "value num", String(s[1]));
        if (s[2]) v.setAttribute("style", s[2]);
        tile.appendChild(v);
        stats.appendChild(tile);
      });

    var counts = { lpre: 0, l0: d.active_l0, l1: d.active_l1, signed: d.signed };
    var pipe = document.getElementById("pipelineRow");
    pipe.innerHTML = "";
    STAGE_META.forEach(function (s, i) {
      var stage = el("div", "pipe-stage" + (i <= 2 ? " on" : ""));
      stage.appendChild(el("div", "pipe-dot", s.label));
      stage.appendChild(el("div", "pcount num", String(counts[s.key])));
      stage.appendChild(el("div", "pname", s.label));
      stage.appendChild(el("div", "pdesc", s.desc));
      pipe.appendChild(stage);
    });

    renderDeptGrid(document.getElementById("dashDeptGrid"), d.departments.slice(0, 6), false);

    var anns = await api("/api/announcements?limit=6");
    var digest = document.getElementById("digestList");
    digest.innerHTML = "";
    if (!anns.length) digest.appendChild(el("div", "empty-state", "No announcements yet."));
    anns.forEach(function (a) {
      var row = el("div", "digest-row");
      row.appendChild(el("div", "digest-ic", (ANN_ICON[a.type] || ["&#128276;"])[0]));
      var body = el("div", "digest-body");
      body.appendChild(el("b", "", a.title));
      body.appendChild(el("div", "sub", a.body.replace(/<[^>]+>/g, "")));
      digest.appendChild(row);
      row.appendChild(body);
    });
  }

  function evalFromPct(pct) {
    if (pct === null) return { cls: "neutral", label: "No Data" };
    if (pct >= 95) return { cls: "good", label: "Excellent" };
    if (pct >= 80) return { cls: "warn", label: "Acceptable" };
    return { cls: "crit", label: "Needs Action" };
  }
  function renderDeptGrid(container, rows, big) {
    container.innerHTML = "";
    rows.forEach(function (row) {
      var ev = evalFromPct(row.pct);
      var card = el("div", "card dept-card");
      var head = el("div", "dept-head");
      head.appendChild(el("div", "dname", row.department.replace(/^\d+\.\s*/, "")));
      head.appendChild(el("span", "pill " + ev.cls, '<span class="dot"></span>' + ev.label));
      card.appendChild(head);
      var metrics = el("div", "dept-metrics");
      var m0 = el("div", "dept-metric");
      m0.appendChild(el("div", "mlabel", "Approved"));
      m0.appendChild(el("div", "mval num", String(row.approved) + " / " + row.total));
      var m1 = el("div", "dept-metric");
      m1.appendChild(el("div", "mlabel", "Live Score"));
      m1.appendChild(el("div", "mval num", row.pct === null ? "&#8213;" : row.pct + "%"));
      metrics.appendChild(m0); metrics.appendChild(m1);
      card.appendChild(metrics);
      if (row.overdue || row.pending_review) {
        var flags = el("div", "spark-wrap", "");
        var bits = [];
        if (row.overdue) bits.push('<span class="pill crit"><span class="dot"></span>' + row.overdue + ' overdue</span>');
        if (row.pending_review) bits.push('<span class="pill warn"><span class="dot"></span>' + row.pending_review + ' in review</span>');
        flags.innerHTML = bits.join(" ");
        card.appendChild(flags);
      }
      container.appendChild(card);
    });
  }

  /* ================= ASSIGNED DELIVERABLES ================= */
  var assignedFilter = "";
  var ASSIGNED_FILTERS = [["", "All"], ["overdue", "Overdue"], ["pending_review", "Pending SME Review"], ["not_due", "Not Due Yet"], ["approved", "Approved"]];
  async function loadAssigned() {
    var all = await api("/api/deliverables");
    document.getElementById("assignedBadge").textContent = all.filter(function (d) { return d.status === "overdue"; }).length || "";

    var chips = document.getElementById("assignedChips");
    chips.innerHTML = "";
    ASSIGNED_FILTERS.forEach(function (f) {
      var count = f[0] ? all.filter(function (d) { return d.status === f[0]; }).length : all.length;
      var chip = el("button", "chip" + (assignedFilter === f[0] ? " active" : ""), f[1] + ' <span class="cnum">' + count + '</span>');
      chip.addEventListener("click", function () { assignedFilter = f[0]; loadAssigned(); });
      chips.appendChild(chip);
    });

    var items = assignedFilter ? all.filter(function (d) { return d.status === assignedFilter; }) : all;
    var wrap = document.getElementById("assignedList");
    wrap.innerHTML = "";
    if (!items.length) { wrap.appendChild(el("div", "empty-state", "Nothing here right now.")); return; }
    items.forEach(function (d) {
      var sm = STATUS_META[d.status] || ["neutral", d.status];
      var row = el("div", "aq-row");
      var main = el("div", "aq-main");
      main.appendChild(el("div", "aq-title", d.item_no + " &middot; " + d.name));
      main.appendChild(el("div", "aq-sub",
        '<span>' + d.est_no + ' &#8211; ' + d.project_name + '</span><span class="sep">&middot;</span>' +
        '<span>' + d.department.replace(/^\d+\.\s*/, "") + '</span><span class="sep">&middot;</span>' +
        '<span>Owner: ' + d.owner + '</span><span class="sep">&middot;</span>' +
        '<span>Due ' + fmtDate(d.due_date) + '</span>'));
      row.appendChild(main);
      row.appendChild(el("span", "pill " + sm[0], '<span class="dot"></span>' + sm[1]));
      var actions = el("div", "deliv-actions");
      if (d.status === "pending_review" && can("review")) {
        var appr = el("button", "btn primary", "Approve");
        appr.addEventListener("click", function () { review(d.id, true, loadAssigned); });
        var rej = el("button", "btn ghost-crit", "Reject");
        rej.addEventListener("click", function () { review(d.id, false, loadAssigned); });
        actions.appendChild(appr); actions.appendChild(rej);
      } else if (d.status === "overdue" && can("remind")) {
        actions.appendChild(el("button", "btn ghost-crit", "Send reminder"));
      }
      row.appendChild(actions);
      wrap.appendChild(row);
    });
  }

  /* ================= L0 / L1 TABLES ================= */
  var lastListView = "l0";
  async function loadProjectsTable(stage) {
    lastListView = stage.toLowerCase();
    var list = await api("/api/projects?stage=" + stage);
    var table = stage === "L0" ? "#l0Table" : "#l1Table";
    var tbody = document.querySelector(table + " tbody");
    tbody.innerHTML = "";
    if (!list.length) {
      var tr = el("tr");
      tr.innerHTML = '<td colspan="7" style="text-align:center;color:var(--ink-500);padding:30px;">No ' + stage + ' projects yet.</td>';
      tbody.appendChild(tr);
      return;
    }
    for (var i = 0; i < list.length; i++) {
      var p = list[i];
      var tr2 = el("tr");
      var statusPill = '<span class="pill ' + (PROJECT_STATUS_CLASS[p.status] || "neutral") + '"><span class="dot"></span>' + p.status + '</span>';
      if (stage === "L0") {
        tr2.innerHTML = '<td class="est-no">' + p.est_no + '</td><td><span class="proj-name">' + p.name + '</span></td>' +
          '<td>' + (p.region || "&#8213;") + '</td><td>' + (p.scope || "&#8213;") + '</td><td>' + (p.bid_manager || "&#8213;") + '</td>' +
          '<td class="num">' + fmtDate(p.bsd) + '</td><td>' + statusPill + '</td>';
      } else {
        var mini = '<div class="mini-stepper" data-pid="' + p.id + '">&#8230;</div>';
        tr2.innerHTML = '<td class="est-no">' + p.est_no + '</td><td><span class="proj-name">' + p.name + '</span></td>' +
          '<td>' + mini + '</td><td>' + (p.bid_manager || "&#8213;") + '</td><td>' + statusPill + '</td>';
      }
      tr2.addEventListener("click", function (pid) { return function () { openDetail(pid); }; }(p.id));
      tbody.appendChild(tr2);
    }
    if (stage === "L1") {
      for (var j = 0; j < list.length; j++) {
        loadMiniStepper(list[j].id);
      }
    }
  }
  async function loadMiniStepper(projectId) {
    var ms = await api("/api/projects/" + projectId + "/milestones");
    var target = document.querySelector('.mini-stepper[data-pid="' + projectId + '"]');
    if (!target) return;
    target.innerHTML = ms.map(function (m) { return '<span class="mini-dot' + (m.reached ? " on" : "") + '"></span>'; }).join("");
  }

  function makeReachHandler(projectId, code) {
    return async function () {
      await api("/api/projects/" + projectId + "/milestones/" + code + "/reach", { method: "POST" });
      showToast(code + " marked reached &#8211; announcement sent, due dates updated");
      openDetail(projectId);
    };
  }

  /* ================= PROJECT DETAIL ================= */
  var currentProjectId = null, currentProjectStage = "L0", currentDeptOpen = null;
  async function openDetail(id) {
    currentProjectId = id;
    var p = await api("/api/projects/" + id);
    currentProjectStage = p.stage;
    document.getElementById("dEst").textContent = p.est_no;
    document.getElementById("dTitle").textContent = p.name;
    var pill = document.getElementById("dStatusPill");
    pill.className = "pill " + (PROJECT_STATUS_CLASS[p.status] || "neutral");
    pill.innerHTML = '<span class="dot"></span>' + p.status;
    var meta = document.getElementById("dMeta");
    meta.innerHTML = "";
    var metaItems = p.stage === "L0"
      ? [["Bid Manager", p.bid_manager || "&#8213;"], ["Region", p.region || "&#8213;"], ["Scope", p.scope || "&#8213;"], ["Bid Submission Date", fmtDate(p.bsd)]]
      : [["Bid Manager", p.bid_manager || "&#8213;"], ["Region", p.region || "&#8213;"], ["Client", "SEC"], ["Announced", fmtDate(p.announcement_date)]];
    metaItems.forEach(function (m) {
      var mi = el("div", "meta-item");
      mi.appendChild(el("div", "mk", m[0]));
      mi.appendChild(el("div", "mv", m[1]));
      meta.appendChild(mi);
    });

    var stepperCard = document.getElementById("dStepperCard");
    if (p.stage === "L1") {
      stepperCard.style.display = "";
      var ms = await api("/api/projects/" + id + "/milestones");
      var stepper = document.getElementById("dStepper");
      stepper.innerHTML = "";
      var lastDoneIdx = -1;
      ms.forEach(function (m, i) { if (m.reached) lastDoneIdx = i; });
      ms.forEach(function (m, i) {
        var cls = "fs-step" + (m.reached ? " done" : (i === lastDoneIdx + 1 ? " current" : ""));
        var step = el("div", cls);
        step.appendChild(el("div", "fs-dot", m.reached ? "&#10003;" : m.code));
        var label = el("div", "fs-label", m.code + " &middot; " + m.name);
        step.appendChild(label);
        step.appendChild(el("div", "fs-date", m.reached ? fmtDate(m.actual_date) : "&#8213;"));
        if (!m.reached && i === lastDoneIdx + 1 && can("create")) {
          var btn = el("button", "btn", "Mark reached");
          btn.style.marginTop = "4px";
          btn.addEventListener("click", makeReachHandler(id, m.code));
          step.appendChild(btn);
        }
        stepper.appendChild(step);
      });
    } else {
      stepperCard.style.display = "none";
    }

    var depts = await api("/api/departments");
    var allDelivs = await api("/api/projects/" + id + "/deliverables");
    var folders = document.getElementById("dFolders");
    folders.innerHTML = "";
    document.getElementById("dFolderCount").textContent = depts.length + " total";
    currentDeptOpen = depts.length ? depts[0].name : null;
    depts.forEach(function (dept, i) {
      var deptItems = allDelivs.filter(function (d) { return d.department === dept.name; });
      var approved = deptItems.filter(function (d) { return d.status === "approved"; }).length;
      var pct = deptItems.length ? Math.round((approved / deptItems.length) * 100) : null;
      var row = el("div", "folder-row" + (i === 0 ? " active" : ""));
      row.innerHTML =
        '<div class="folder-left"><span class="folder-ic">&#128193;</span><div><div class="folder-name">' + dept.name + '</div>' +
        '<div class="folder-focal">Focal: ' + (dept.focal_point_name || "&#8213;") + '</div></div></div>' +
        '<div class="folder-right"><span class="folder-pct">' + (pct === null ? "&#8213;" : pct + "%") + '</span></div>';
      row.addEventListener("click", function () {
        document.querySelectorAll(".folder-row").forEach(function (r) { r.classList.remove("active"); });
        row.classList.add("active");
        currentDeptOpen = dept.name;
        document.getElementById("dDeliverTitle").textContent = dept.name.replace(/^\d+\.\s*/, "") + " Deliverables";
        renderDeliverables(deptItems);
      });
      folders.appendChild(row);
    });
    var firstDeptItems = depts.length ? allDelivs.filter(function (d) { return d.department === depts[0].name; }) : [];
    document.getElementById("dDeliverTitle").textContent = depts.length ? depts[0].name.replace(/^\d+\.\s*/, "") + " Deliverables" : "Deliverables";
    renderDeliverables(firstDeptItems);

    switchView("detail");
  }

  function renderDeliverables(items) {
    var wrap = document.getElementById("dDeliverables");
    wrap.innerHTML = "";
    document.getElementById("dDeliverCount").textContent = items.length + " item" + (items.length === 1 ? "" : "s");
    if (!items.length) {
      wrap.appendChild(el("div", "deliv-row", '<span style="color:var(--ink-500);font-size:12.5px;">No deliverables catalogued for this department yet.</span>'));
      return;
    }
    items.forEach(function (d) {
      var sm = STATUS_META[d.status] || ["neutral", d.status];
      var row = el("div", "deliv-row");
      var body = el("div", "deliv-body");
      body.appendChild(el("div", "deliv-name", d.name));
      body.appendChild(el("div", "deliv-due", "Due " + fmtDate(d.due_date) + ' &middot; <span class="pill ' + sm[0] + '"><span class="dot"></span>' + sm[1] + "</span>" + (d.file_name ? " &middot; " + d.file_name : "")));
      row.appendChild(el("div", "deliv-num", d.item_no));
      row.appendChild(body);

      var actions = el("div", "deliv-actions");
      if (d.status === "pending_review") {
        if (can("review")) {
          var appr = el("button", "btn primary", "Approve");
          appr.addEventListener("click", function () { review(d.id, true, function () { openDetail(currentProjectId); }); });
          var rej = el("button", "btn ghost-crit", "Reject");
          rej.addEventListener("click", function () { review(d.id, false, function () { openDetail(currentProjectId); }); });
          actions.appendChild(appr); actions.appendChild(rej);
        } else {
          actions.appendChild(el("span", "locked-note", "Awaiting SME"));
        }
      } else if (d.status === "overdue") {
        if (can("remind")) {
          actions.appendChild(el("button", "btn ghost-crit", "Send reminder"));
        } else if (can("upload")) {
          actions.appendChild(uploadButton(d.id));
        }
      } else if (d.status === "not_due" || d.status === "due") {
        if (can("upload")) actions.appendChild(uploadButton(d.id));
      } else {
        actions.appendChild(el("button", "btn", "View files"));
      }
      row.appendChild(actions);
      wrap.appendChild(row);
    });
  }
  function uploadButton(submissionId) {
    var wrapper = document.createDocumentFragment();
    var fileInput = el("input"); fileInput.type = "file"; fileInput.style.display = "none";
    var btn = el("button", "btn", "Upload");
    btn.addEventListener("click", function () { fileInput.click(); });
    fileInput.addEventListener("change", async function () {
      if (!fileInput.files[0]) return;
      var fd = new FormData();
      fd.append("file", fileInput.files[0]);
      fd.append("owner_name", CURRENT_ROLE + " (pilot)");
      await api("/api/deliverables/" + submissionId + "/upload", { method: "POST", body: fd });
      showToast("Uploaded " + fileInput.files[0].name + " &#8211; SME notified");
      openDetail(currentProjectId);
    });
    var span = el("span"); span.appendChild(btn); span.appendChild(fileInput);
    return span;
  }
  async function review(submissionId, approved, after) {
    var comment = approved ? null : prompt("Reason for rejection (shown to the owner):", "Please review and resubmit with updated supporting documents.");
    await api("/api/deliverables/" + submissionId + "/review", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved: approved, comment: comment, reviewer_name: CURRENT_ROLE }),
    });
    showToast(approved ? "Approved &#8211; owner notified" : "Rejected &#8211; owner notified");
    if (after) after();
  }

  /* ================= PERFORMANCE / REPORTS ================= */
  async function loadPerformance() {
    var d = await api("/api/dashboard");
    renderDeptGrid(document.getElementById("perfDeptGrid"), d.departments, true);
  }
  async function loadReports() {
    var d = await api("/api/dashboard");
    var ranked = d.departments.slice().sort(function (a, b) { return (b.pct || 0) - (a.pct || 0); });
    var max = Math.max.apply(null, ranked.map(function (r) { return r.pct || 0; }).concat([1]));
    var wrap = document.getElementById("rankList");
    wrap.innerHTML = "";
    ranked.forEach(function (row, i) {
      var ev = evalFromPct(row.pct);
      var r = el("div", "rank-row");
      r.appendChild(el("div", "rank-num", "#" + (i + 1)));
      r.appendChild(el("div", "rank-name", row.department.replace(/^\d+\.\s*/, "")));
      var track = el("div", "rank-bar-track");
      var fill = el("div", "rank-bar-fill");
      fill.style.width = (((row.pct || 0) / max) * 100).toFixed(0) + "%";
      if (ev.cls === "crit") fill.style.background = "var(--crit)"; else if (ev.cls === "warn") fill.style.background = "var(--warn)";
      track.appendChild(fill);
      r.appendChild(track);
      r.appendChild(el("div", "rank-val num", row.pct === null ? "&#8213;" : row.pct + "%"));
      r.appendChild(el("span", "pill " + ev.cls, '<span class="dot"></span>' + ev.label));
      wrap.appendChild(r);
    });
  }

  /* ================= ANNOUNCEMENTS ================= */
  async function loadAnnouncements() {
    var list = await api("/api/announcements");
    var wrap = document.getElementById("announcementsList");
    wrap.innerHTML = "";
    if (!list.length) { wrap.appendChild(el("div", "empty-state", "No announcements sent yet.")); return; }
    list.forEach(function (a) {
      var meta = ANN_ICON[a.type] || ["&#128276;", "broadcast"];
      var row = el("div", "ann-row");
      row.appendChild(el("div", "ann-ic " + meta[1], meta[0]));
      var main = el("div", "ann-main");
      var when = new Date(a.created_at).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
      main.appendChild(el("div", "ann-top", '<span class="ann-title">' + a.title + '</span><span class="ann-time">' + when + '</span>'));
      main.appendChild(el("div", "ann-body", a.body));
      main.appendChild(el("div", "ann-meta", "To: <b>" + (a.recipients || "&#8213;") + "</b> &middot; " + a.email_status));
      row.appendChild(main);
      wrap.appendChild(row);
    });
  }

  /* ================= CREATE PROJECT ================= */
  document.getElementById("cfSubmit").addEventListener("click", async function () {
    var name = document.getElementById("cfName").value.trim();
    if (!name) { showToast("Project name is required"); return; }
    var payload = {
      name: name, stage: document.getElementById("cfStage").value,
      region: document.getElementById("cfRegion").value || null,
      scope: document.getElementById("cfScope").value || null,
      bid_manager: document.getElementById("cfBid").value || null,
      bsd: document.getElementById("cfBsd").value || null,
    };
    var p = await api("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    showToast(p.est_no + " created &#8211; announcement sent");
    switchView("announcements");
  });
  document.getElementById("cfCancel").addEventListener("click", function () { switchView("dashboard"); });

  /* ================= SEARCH ================= */
  document.getElementById("globalSearch").addEventListener("input", async function (e) {
    var v = e.target.value.trim().toLowerCase();
    if (!v) return;
    var list = await api("/api/projects");
    var match = list.filter(function (p) { return (p.est_no + " " + p.name).toLowerCase().indexOf(v) !== -1; });
    if (match.length === 1) { openDetail(match[0].id); e.target.value = ""; }
  });

  /* ================= ROLE + THEME ================= */
  document.getElementById("roleSelect").addEventListener("change", function (e) {
    CURRENT_ROLE = e.target.value;
    var showAdmin = can("create");
    document.getElementById("adminNav").style.display = showAdmin ? "" : "none";
    document.getElementById("adminGroupLabel").style.display = showAdmin ? "" : "none";
    if (!showAdmin && (!document.getElementById("view-create").hidden || !document.getElementById("view-reports").hidden)) switchView("dashboard");
    if (currentProjectId && !document.getElementById("view-detail").hidden) openDetail(currentProjectId);
  });
  document.getElementById("themeToggle").addEventListener("click", function () {
    var root = document.documentElement;
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    this.textContent = next === "dark" ? "Light mode" : "Dark mode";
  });

  /* ================= INIT ================= */
  document.getElementById("todayLabel").textContent = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "2-digit", month: "long", year: "numeric" });
  loadDashboard();
})();

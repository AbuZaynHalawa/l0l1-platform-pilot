/* Real frontend for the L0/L1 pilot. Every render here comes from an actual
   fetch() to the FastAPI backend — no hardcoded data arrays anywhere in this
   file. Role-based button gating is client-side only for now (no per-user
   login exists yet in the pilot) — before this goes company-wide, the same
   checks need to be enforced server-side too, not just hidden in the UI. */
(function () {
  "use strict";

  var CURRENT_ROLE = "Admin";
  function actingEmail() {
    var f = document.getElementById("actingEmail");
    return f ? f.value.trim() : "";
  }
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
    if (!r.ok) {
      var bodyText = await r.text();
      var err = new Error(path + " -> " + r.status + ": " + bodyText);
      try { err.detail = JSON.parse(bodyText).detail; } catch (e) { err.detail = bodyText; }
      throw err;
    }
    return r.status === 204 ? null : r.json();
  }
  function apiErrorDetail(err) { return err.detail || err.message; }
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
  var PROJECT_STATUS_CLASS = { "Completed": "good", "Cancelled": "crit", "Submitted": "good", "In Progress": "warn" };
  var L1_MILESTONE_LABELS = {
    M1: "Announcement", M2: "Early Plan", M3: "Handing Over",
    M4: "Post Bid Clarifications", M5: "LOA", M6: "Contract",
  };
  function joinList(v) { return (v && v.length) ? v.join(", ") : "&#8213;"; }
  var ANN_ICON = {
    broadcast: ["&#128276;", "broadcast"], owner: ["&#128100;", "owner"], sme_request: ["&#128269;", "sme-request"],
    sme_decision: ["&#9989;", "sme-decision"], unlock: ["&#128275;", "unlock"], deadline: ["&#8987;", "deadline"], closed: ["&#127937;", "closed"],
  };

  /* ================= VIEW SWITCHING ================= */
  var LOADERS = {
    dashboard: loadDashboard, assigned: loadAssigned, announcements: loadAnnouncements,
    l0: function () { loadProjectsTable("L0"); }, l1: function () { loadProjectsTable("L1"); },
    performance: loadPerformance, reports: loadReports, create: loadCreateOptions, gantt: loadGantt,
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
  document.getElementById("dGanttBtn").addEventListener("click", function () { openProjectGantt(currentProjectId); });

  /* ================= DASHBOARD ================= */
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

    await loadMatrix();
  }

  /* ================= DELIVERABLES MATRIX ================= */
  var matrixStage = "L0";
  document.querySelectorAll(".matrix-toggle .chip").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".matrix-toggle .chip").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      matrixStage = btn.dataset.stage;
      loadMatrix();
    });
  });
  async function loadMatrix() {
    var data = await api("/api/dashboard/matrix?stage=" + matrixStage);
    var wrap = document.getElementById("matrixWrap");
    if (!data.projects.length) {
      wrap.innerHTML = '<div class="empty-state">No active ' + matrixStage + ' projects right now.</div>';
      return;
    }
    var html = '<table class="matrix-table"><thead><tr><th>Deliverable</th>';
    data.projects.forEach(function (p) {
      html += '<th title="' + p.name.replace(/"/g, "&quot;") + '">' + p.est_no + "</th>";
    });
    html += "</tr></thead><tbody>";
    var lastDept = null;
    data.rows.forEach(function (row) {
      if (row.department !== lastDept) {
        html += '<tr><td class="matrix-dept-row" colspan="' + (data.projects.length + 1) + '">' +
          row.department.replace(/^\d+\.\s*/, "") + "</td></tr>";
        lastDept = row.department;
      }
      html += '<tr><td class="matrix-row-label" title="' + row.name.replace(/"/g, "&quot;") + '">' + row.item_no + " &middot; " + row.short_name +
        (row.is_milestone ? ' <span class="matrix-milestone-tag">' + row.milestone_code + "</span>" : "") + "</td>";
      data.projects.forEach(function (p) {
        var cell = row.cells[p.id];
        if (!cell) { html += '<td class="matrix-empty-cell">&#8213;</td>'; return; }
        var meta = STATUS_META[cell.status] || ["neutral", cell.status];
        var tip = meta[1] + (cell.due_date ? " &middot; due " + fmtDate(cell.due_date) : "");
        html += '<td><span class="matrix-dot ' + meta[0] + '" title="' + tip.replace(/"/g, "&quot;") +
          '" data-sid="' + cell.submission_id + '" data-pid="' + p.id + '"></span></td>';
      });
      html += "</tr>";
    });
    html += "</tbody></table>";
    wrap.innerHTML = html;
    wrap.querySelectorAll(".matrix-dot").forEach(function (dot) {
      dot.addEventListener("click", function () { openDetail(Number(dot.dataset.pid)); });
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
      tr.innerHTML = '<td colspan="8" style="text-align:center;color:var(--ink-500);padding:30px;">No ' + stage + ' projects yet.</td>';
      tbody.appendChild(tr);
      return;
    }
    for (var i = 0; i < list.length; i++) {
      var p = list[i];
      var tr2 = el("tr");
      var statusPill = '<span class="pill ' + (PROJECT_STATUS_CLASS[p.status] || "neutral") + '"><span class="dot"></span>' + p.status + '</span>';
      if (stage === "L0") {
        tr2.innerHTML = '<td class="est-no">' + p.est_no + '</td><td><span class="proj-name">' + p.name + '</span></td>' +
          '<td>' + (p.rfx_number || "&#8213;") + '</td><td>' + joinList(p.region) + '</td><td>' + joinList(p.scope) + '</td><td>' + (p.bid_manager || "&#8213;") + '</td>' +
          '<td class="num">' + fmtDate(p.bsd) + '</td><td>' + statusPill + '</td>';
      } else {
        var mini = '<div class="mini-stepper" data-pid="' + p.id + '">&#8230;</div>';
        tr2.innerHTML = '<td class="est-no">' + p.est_no + '</td><td><span class="proj-name">' + p.name + '</span></td>' +
          '<td>' + mini + '</td><td>' + (p.bid_manager || "&#8213;") + '</td><td>' + (p.project_manager || "&#8213;") + '</td><td>' + statusPill + '</td>';
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
      ? [["Bid Manager", p.bid_manager || "&#8213;"], ["RFX", p.rfx_number || "&#8213;"], ["Region", joinList(p.region)], ["Scope", joinList(p.scope)],
         ["Announced", fmtDate(p.announcement_date)], ["Site Visit", fmtDate(p.site_visit_date)], ["Pre-Bid Deadline", fmtDate(p.pre_bid_deadline)], ["Bid Submission Date", fmtDate(p.bsd)]]
      : [["Bid Manager", p.bid_manager || "&#8213;"], ["Project Manager", p.project_manager || "&#8213;", "pm"],
         ["Region", joinList(p.region)], ["Scope", joinList(p.scope)],
         ["Announced", fmtDate(p.announcement_date)],
         ["Contract Status", p.contract_status === "Signed"
           ? '<span class="pill good"><span class="dot"></span>Signed</span>'
           : (p.contract_status || "&#8213;")]];
    metaItems.forEach(function (m) {
      var mi = el("div", "meta-item");
      mi.appendChild(el("div", "mk", m[0]));
      var mv = el("div", "mv", m[1]);
      if (m[2] === "pm" && can("create")) {
        var editLink = el("a", "meta-edit-link", "Edit");
        editLink.href = "#";
        editLink.addEventListener("click", function (e) {
          e.preventDefault();
          var next = prompt("Project Manager name:", p.project_manager || "");
          if (next === null) return;
          api("/api/projects/" + id + "/project-manager", {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_manager: next.trim() || null }),
          }).then(function () { showToast("Project Manager updated"); openDetail(id); })
            .catch(function (err) { showToast("Could not update &#8211; " + apiErrorDetail(err)); });
        });
        mv.appendChild(document.createTextNode(" "));
        mv.appendChild(editLink);
      }
      mi.appendChild(mv);
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
        var label = el("div", "fs-label", m.code + " &middot; " + (L1_MILESTONE_LABELS[m.code] || m.name));
        step.appendChild(label);
        step.appendChild(el("div", "fs-date", m.reached ? fmtDate(m.actual_date) : "&#8213;"));
        stepper.appendChild(step);
      });
    } else {
      stepperCard.style.display = "none";
    }

    var allDeptsMeta = await api("/api/departments");
    var deptFocal = {};
    allDeptsMeta.forEach(function (d) { deptFocal[d.name] = d.focal_point_name; });
    var allDelivs = await api("/api/projects/" + id + "/deliverables");
    var deptNames = [];
    allDelivs.forEach(function (d) { if (deptNames.indexOf(d.department) === -1) deptNames.push(d.department); });
    var folders = document.getElementById("dFolders");
    folders.innerHTML = "";
    document.getElementById("dFolderCount").textContent = deptNames.length + " total";
    currentDeptOpen = deptNames.length ? deptNames[0] : null;
    deptNames.forEach(function (deptName, i) {
      var deptItems = allDelivs.filter(function (d) { return d.department === deptName; });
      var approved = deptItems.filter(function (d) { return d.status === "approved"; }).length;
      var pct = deptItems.length ? Math.round((approved / deptItems.length) * 100) : null;
      var row = el("div", "folder-row" + (i === 0 ? " active" : ""));
      row.innerHTML =
        '<div class="folder-left"><span class="folder-ic">&#128193;</span><div><div class="folder-name">' + deptName + '</div>' +
        '<div class="folder-focal">Focal: ' + (deptFocal[deptName] || "&#8213;") + '</div></div></div>' +
        '<div class="folder-right"><span class="folder-pct">' + (pct === null ? "&#8213;" : pct + "%") + '</span></div>';
      row.addEventListener("click", function () {
        document.querySelectorAll(".folder-row").forEach(function (r) { r.classList.remove("active"); });
        row.classList.add("active");
        currentDeptOpen = deptName;
        document.getElementById("dDeliverTitle").textContent = deptName.replace(/^\d+\.\s*/, "") + " Deliverables";
        renderDeliverables(deptItems);
      });
      folders.appendChild(row);
    });
    var firstDeptItems = deptNames.length ? allDelivs.filter(function (d) { return d.department === deptNames[0]; }) : [];
    document.getElementById("dDeliverTitle").textContent = deptNames.length ? deptNames[0].replace(/^\d+\.\s*/, "") + " Deliverables" : "Deliverables";
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
      fd.append("actor_name", CURRENT_ROLE + " (pilot)");
      fd.append("actor_role", CURRENT_ROLE);
      fd.append("actor_email", actingEmail());
      try {
        await api("/api/deliverables/" + submissionId + "/upload", { method: "POST", body: fd });
      } catch (err) {
        showToast("Upload blocked &#8211; " + apiErrorDetail(err));
        return;
      }
      showToast("Uploaded " + fileInput.files[0].name + " &#8211; SME notified");
      openDetail(currentProjectId);
    });
    var span = el("span"); span.appendChild(btn); span.appendChild(fileInput);
    return span;
  }
  async function review(submissionId, approved, after) {
    var comment = approved ? null : prompt("Reason for rejection (shown to the owner):", "Please review and resubmit with updated supporting documents.");
    try {
      await api("/api/deliverables/" + submissionId + "/review", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          approved: approved, comment: comment, reviewer_name: CURRENT_ROLE,
          actor_role: CURRENT_ROLE, actor_email: actingEmail(),
        }),
      });
    } catch (err) {
      showToast("Review blocked &#8211; " + apiErrorDetail(err));
      return;
    }
    showToast(approved ? "Approved &#8211; owner notified" : "Rejected &#8211; owner notified");
    if (after) after();
  }

  /* ================= TIMELINE / GANTT ================= */
  var ganttOptionsLoaded = false;
  async function loadGantt() {
    var scopeSel = document.getElementById("ganttScope");
    if (!ganttOptionsLoaded) {
      var projects = await api("/api/projects?status=" + encodeURIComponent("In Progress"));
      projects.forEach(function (p) {
        var o = el("option", "", p.est_no + " &#8211; " + p.name); o.value = p.id;
        scopeSel.appendChild(o);
      });
      ganttOptionsLoaded = true;
      // Default to a specific project's deliverable-level timeline (the useful
      // view) rather than the whole-project-as-one-bar overview.
      if (projects.length) scopeSel.value = String(projects[0].id);
    }
    await renderGanttFor(scopeSel.value);
  }
  document.getElementById("ganttScope").addEventListener("change", function () { renderGanttFor(this.value); });
  async function openProjectGantt(projectId) {
    switchView("gantt");
    var scopeSel = document.getElementById("ganttScope");
    if (!ganttOptionsLoaded) await loadGantt();
    scopeSel.value = String(projectId);
    await renderGanttFor(scopeSel.value);
  }
  async function renderGanttFor(projectId) {
    var isOverview = !projectId;
    var rows = isOverview ? await api("/api/gantt/overview") : await api("/api/gantt/projects/" + projectId);
    var axis = document.getElementById("ganttAxis");
    var wrap = document.getElementById("ganttRows");
    axis.innerHTML = "";
    wrap.innerHTML = "";
    if (!rows.length) {
      wrap.appendChild(el("div", "empty-state", "Nothing scheduled yet."));
      return;
    }
    var min = Math.min.apply(null, rows.map(function (r) { return new Date(r.start + "T00:00:00").getTime(); }));
    var max = Math.max.apply(null, rows.map(function (r) { return new Date(r.end + "T00:00:00").getTime(); }));
    var span = Math.max(1, max - min);
    axis.appendChild(el("span", "", fmtDate(new Date(min).toISOString().slice(0, 10))));
    axis.appendChild(el("span", "", fmtDate(new Date(max).toISOString().slice(0, 10))));
    rows.forEach(function (r) {
      var s = new Date(r.start + "T00:00:00").getTime();
      var e = new Date(r.end + "T00:00:00").getTime();
      var leftPct = ((s - min) / span) * 100;
      var widthPct = Math.max(0.8, ((e - s) / span) * 100);
      var row = el("div", "gantt-row");
      var labelHtml = isOverview
        ? "<b>" + r.est_no + "</b> &middot; " + r.name
        : "<b>" + r.item_no + "</b> &middot; " + r.short_name;
      var label = el("div", "gantt-label", labelHtml);
      if (!isOverview) label.title = r.name;
      row.appendChild(label);
      var track = el("div", "gantt-track");
      var cls = isOverview ? (PROJECT_STATUS_CLASS[r.status] || "neutral") : ((STATUS_META[r.status] || ["neutral"])[0]);
      var bar = el("div", "gantt-bar " + cls + (r.is_milestone ? " milestone" : ""));
      bar.style.left = leftPct.toFixed(2) + "%";
      bar.style.width = widthPct.toFixed(2) + "%";
      bar.title = fmtDate(r.start) + " " + String.fromCharCode(8594) + " " + fmtDate(r.end);
      track.appendChild(bar);
      row.appendChild(track);
      if (isOverview) {
        row.style.cursor = "pointer";
        row.addEventListener("click", function () { openDetail(r.id); });
      }
      wrap.appendChild(row);
    });
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
  var createOptionsLoaded = false;
  function renderCheckGroup(containerId, otherInputId, options) {
    var grid = document.getElementById(containerId);
    grid.innerHTML = "";
    options.forEach(function (opt) {
      var label = el("label", "scope-opt");
      var cb = el("input"); cb.type = "checkbox"; cb.value = opt;
      label.appendChild(cb);
      label.appendChild(document.createTextNode(opt));
      grid.appendChild(label);
      if (opt === "Other") {
        cb.addEventListener("change", function () {
          document.getElementById(otherInputId).style.display = cb.checked ? "" : "none";
        });
      }
    });
  }
  function checkedValues(containerId) {
    return Array.prototype.slice.call(document.querySelectorAll("#" + containerId + " input:checked")).map(function (c) { return c.value; });
  }
  async function loadCreateOptions() {
    if (!createOptionsLoaded) {
      var opts = await api("/api/departments/options");
      var bidSel = document.getElementById("cfBid");
      opts.bid_managers.forEach(function (m) { bidSel.appendChild(el("option", "", m)).value = m; });
      renderCheckGroup("cfRegionGrid", "cfRegionOther", opts.regions);
      renderCheckGroup("cfScopeGrid", "cfScopeOther", opts.scopes);
      createOptionsLoaded = true;
    }
    var l0List = await api("/api/projects?stage=L0&status=" + encodeURIComponent("In Progress"));
    var sourceSel = document.getElementById("cfL0Source");
    sourceSel.innerHTML = '<option value="">Select an in-progress L0&#8230;</option>';
    l0List.forEach(function (p) {
      var o = el("option", "", p.est_no + " &#8211; " + p.name); o.value = p.id;
      sourceSel.appendChild(o);
    });
    applyStageToggle();
  }
  function applyStageToggle() {
    var stage = document.getElementById("cfStage").value;
    document.getElementById("cfL0Form").hidden = stage !== "L0";
    document.getElementById("cfL1Form").hidden = stage !== "L1";
  }
  document.getElementById("cfStage").addEventListener("change", applyStageToggle);

  document.getElementById("cfSubmit").addEventListener("click", async function () {
    var stage = document.getElementById("cfStage").value;
    var submitBtn = document.getElementById("cfSubmit");
    var originalLabel = submitBtn.textContent;
    submitBtn.disabled = true;
    submitBtn.textContent = "Creating project…";
    submitBtn.classList.add("btn-loading");
    try {
      if (stage === "L0") {
        var name = document.getElementById("cfName").value.trim();
        var estNo = document.getElementById("cfEstNo").value.trim();
        var announce = document.getElementById("cfAnnounce").value;
        var bsd = document.getElementById("cfBsd").value;
        var bidManager = document.getElementById("cfBid").value;
        var region = checkedValues("cfRegionGrid");
        var scope = checkedValues("cfScopeGrid");
        if (!name) { showToast("Tender name is required"); return; }
        if (!estNo) { showToast("Est-Num is required"); return; }
        if (!bidManager) { showToast("Bid Manager is required"); return; }
        if (!announce) { showToast("Announcement Date is required"); return; }
        if (!bsd) { showToast("Bid Submission Date is required"); return; }
        if (!region.length) { showToast("Select at least one Region"); return; }
        if (!scope.length) { showToast("Select at least one Scope"); return; }
        var payload = {
          name: name, est_no: estNo,
          region: region, region_other: document.getElementById("cfRegionOther").value || null,
          scope: scope, scope_other: document.getElementById("cfScopeOther").value || null,
          rfx_number: document.getElementById("cfRfx").value || null,
          announcement_date: announce, site_visit_date: document.getElementById("cfSiteVisit").value || null,
          pre_bid_deadline: document.getElementById("cfPreBid").value || null,
          bid_manager: bidManager, bsd: bsd,
        };
        var p = await api("/api/projects/l0", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        showToast(p.est_no + " created &#8211; announcement sent");
      } else {
        var l0Id = document.getElementById("cfL0Source").value;
        var l1Announce = document.getElementById("cfL1Announce").value;
        if (!l0Id) { showToast("Select the L0 tender this L1 project comes from"); return; }
        if (!l1Announce) { showToast("L1 Announcement Date is required"); return; }
        var p1 = await api("/api/projects/l1", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            l0_source_id: Number(l0Id), announcement_date: l1Announce,
            project_manager: document.getElementById("cfL1PM").value.trim() || null,
          }),
        });
        showToast(p1.est_no + " created &#8211; announcement sent");
      }
    } catch (err) {
      showToast("Could not create project &#8211; " + apiErrorDetail(err));
      return;
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = originalLabel;
      submitBtn.classList.remove("btn-loading");
    }
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
    document.getElementById("actingEmail").style.display = (CURRENT_ROLE === "Owner" || CURRENT_ROLE === "SME") ? "" : "none";
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

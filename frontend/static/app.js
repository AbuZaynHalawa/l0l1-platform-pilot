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
  function annIcon(a) {
    var meta = ANN_ICON[a.type] || ["&#128276;", "broadcast"];
    if (a.type === "sme_decision" && a.title.indexOf("Rejected") !== -1) {
      return ["&#10060;", "sme-decision rejected"];
    }
    return meta;
  }

  /* ================= VIEW SWITCHING ================= */
  var LOADERS = {
    dashboard: loadDashboard, assigned: loadAssigned, announcements: loadAnnouncements,
    l0: function () { loadProjectsTable("L0"); }, l1: function () { loadProjectsTable("L1"); },
    performance: loadPerformance, reports: loadReports, create: loadCreateOptions, gantt: loadGantt,
    journey: loadJourney, scores: loadScores, focalpoints: loadFocalPoints, followup: loadFollowUp,
  };
  var ADMIN_ONLY_VIEWS = ["create", "reports", "scores", "focalpoints", "followup"];
  function switchView(name) {
    if (ADMIN_ONLY_VIEWS.indexOf(name) !== -1 && !can("create")) name = "dashboard";
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

    var achievers = await api("/api/dashboard/top-achievers");
    renderAchievers("topOwners", achievers.owners.slice(0, 3), "owner");
    renderAchievers("topSmes", achievers.smes.slice(0, 3), "sme");

    var anns = await api("/api/announcements?limit=6");
    var digest = document.getElementById("digestList");
    digest.innerHTML = "";
    if (!anns.length) digest.appendChild(el("div", "empty-state", "No announcements yet."));
    anns.forEach(function (a) {
      var meta = annIcon(a);
      var row = el("div", "digest-row");
      row.appendChild(el("div", "digest-ic", meta[0]));
      var body = el("div", "digest-body");
      body.appendChild(el("b", "", a.title));
      body.appendChild(el("div", "sub", a.body.replace(/<[^>]+>/g, "")));
      digest.appendChild(row);
      row.appendChild(body);
      if (a.project_id) {
        row.style.cursor = "pointer";
        row.addEventListener("click", function () { openDetail(a.project_id); });
      }
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
          deptLabel(row.department, row.department_number) + "</td></tr>";
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

  function renderAchievers(containerId, rows, kind) {
    var wrap = document.getElementById(containerId);
    wrap.innerHTML = "";
    if (!rows.length) { wrap.appendChild(el("div", "empty-state", "Not enough data yet.")); return; }
    var medals = ["&#129351;", "&#129352;", "&#129353;"];
    rows.forEach(function (r, i) {
      var row = el("div", "achiever-row");
      row.appendChild(el("div", "achiever-rank", medals[i] || String(i + 1)));
      var main = el("div", "achiever-main");
      main.appendChild(el("div", "achiever-email", r.email));
      if (kind === "sme") {
        main.appendChild(el("div", "achiever-sub", r.reviewed + " review" + (r.reviewed === 1 ? "" : "s")));
        row.appendChild(main);
        row.appendChild(el("div", "achiever-pct num", r.avg_label + " avg"));
      } else {
        main.appendChild(el("div", "achiever-sub", r.approved + " / " + r.total + " approved on time"));
        row.appendChild(main);
        row.appendChild(el("div", "achiever-pct num", r.pct + "%"));
      }
      wrap.appendChild(row);
    });
  }
  function deptLabel(name, number) {
    return (number ? number + ". " : "") + name;
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
      head.appendChild(el("div", "dname", deptLabel(row.department, row.department_number)));
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
  var ASSIGNED_FILTERS = [["", "All"], ["overdue", "Overdue"], ["pending_review", "Pending SME Review"], ["not_due", "Not Due Yet"], ["approved", "Approved"], ["rejected", "Rejected"]];
  async function loadAssigned() {
    var followQS = actingEmail() ? "?actor_email=" + encodeURIComponent(actingEmail()) : "";
    var all = await api("/api/deliverables" + followQS);
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
      row.dataset.sid = String(d.id);
      var main = el("div", "aq-main");
      main.appendChild(el("div", "aq-title", d.item_no + " &middot; " + d.name));
      main.appendChild(el("div", "aq-sub",
        '<span>' + d.est_no + ' &#8211; ' + d.project_name + '</span><span class="sep">&middot;</span>' +
        '<span>' + deptLabel(d.department, d.department_number) + '</span><span class="sep">&middot;</span>' +
        '<span>Owner: ' + d.owner + '</span><span class="sep">&middot;</span>' +
        '<span>Due ' + fmtDate(d.due_date) + '</span>'));
      if (d.completion_note) main.appendChild(el("div", "deliv-comment", "&#128172; " + d.completion_note));
      row.appendChild(main);
      row.appendChild(el("span", "pill " + sm[0], '<span class="dot"></span>' + sm[1]));
      var actions = el("div", "deliv-actions");
      if (d.file_url) actions.appendChild(fileLink(d));
      actions.appendChild(followButton(d));
      if (d.status === "pending_review" && can("review")) {
        var appr = el("button", "btn primary", "Approve");
        appr.addEventListener("click", function () { review(d.id, true, loadAssigned); });
        var rej = el("button", "btn ghost-crit", "Reject");
        rej.addEventListener("click", function () { review(d.id, false, loadAssigned); });
        actions.appendChild(appr); actions.appendChild(rej);
      }
      if (d.status === "overdue" && can("remind")) {
        var remindBtn = el("button", "btn ghost-crit", "Send reminder");
        remindBtn.addEventListener("click", async function () {
          try {
            var res = await api("/api/deliverables/bulk-remind", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ submission_ids: [d.id], actor_role: CURRENT_ROLE }),
            });
            showToast(res.sent ? "Reminder sent to " + d.owner : "No owner to remind");
          } catch (err) {
            showToast("Could not send reminder &#8211; " + apiErrorDetail(err));
          }
        });
        actions.appendChild(remindBtn);
      }
      if ((d.status === "not_due" || d.status === "due" || d.status === "overdue" || d.status === "rejected") && can("upload")) {
        actions.appendChild(uploadButton(d.id, loadAssigned));
        actions.appendChild(markCompleteButton(d.id, loadAssigned));
        var reassignBtn = el("button", "btn", "Reassign…");
        reassignBtn.addEventListener("click", async function () {
          var toEmail = prompt("Reassign " + d.item_no + " to (email):", "");
          if (!toEmail) return;
          toEmail = toEmail.trim();
          if (!toEmail) return;
          var reason = prompt("Reason (optional):", "") || null;
          try {
            await api("/api/deliverables/" + d.id + "/reassign-request", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ to_email: toEmail, reason: reason, from_email: d.owner }),
            });
          } catch (err) {
            showToast("Could not request reassignment &#8211; " + apiErrorDetail(err));
            return;
          }
          showToast("Reassignment requested — pending admin approval");
        });
        actions.appendChild(reassignBtn);
      }
      row.appendChild(actions);
      wrap.appendChild(row);
    });
  }
  function followButton(d) {
    var btn = el("button", "btn" + (d.following ? " primary" : ""), d.following ? "&#9733; Following" : "&#9734; Follow");
    btn.addEventListener("click", async function () {
      var email = actingEmail();
      if (!email) {
        email = prompt("Your email (to follow this item and get updates):", "");
        if (!email) return;
        email = email.trim();
        if (!email) return;
      }
      try {
        var res = await api("/api/deliverables/" + d.id + "/follow", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: email }),
        });
        d.following = res.following;
        btn.className = "btn" + (d.following ? " primary" : "");
        btn.innerHTML = d.following ? "&#9733; Following" : "&#9734; Follow";
        showToast(d.following ? "Following " + d.item_no : "Unfollowed " + d.item_no);
      } catch (err) {
        showToast("Could not update follow &#8211; " + apiErrorDetail(err));
      }
    });
    return btn;
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
  var currentProjectId = null, currentProjectStage = "L0", currentProjectTerminal = false, currentDeptOpen = null;
  async function openDetail(id) {
    currentProjectId = id;
    var p = await api("/api/projects/" + id);
    currentProjectStage = p.stage;
    currentProjectTerminal = (p.stage === "L0" && (p.status === "Submitted" || p.status === "Cancelled")) ||
      (p.stage === "L1" && p.status === "Completed");
    document.getElementById("dTerminalBanner").hidden = !currentProjectTerminal;
    var stageBadge = document.getElementById("dStageBadge");
    stageBadge.textContent = p.stage + " Stage";
    stageBadge.className = "stage-badge " + (p.stage === "L0" ? "l0" : "l1");
    document.getElementById("dEst").textContent = p.est_no;
    document.getElementById("dTitle").textContent = p.name;
    var pill = document.getElementById("dStatusPill");
    pill.className = "pill " + (PROJECT_STATUS_CLASS[p.status] || "neutral");
    pill.innerHTML = '<span class="dot"></span>' + p.status;

    var statusSel = document.getElementById("dStatusSelect");
    if (can("create")) {
      var statusOptions = ["In Progress"].concat(p.stage === "L0" ? ["Submitted", "Cancelled"] : ["Completed"]);
      statusSel.innerHTML = "";
      statusOptions.forEach(function (s) { var o = el("option", "", s); o.value = s; statusSel.appendChild(o); });
      statusSel.value = p.status;
      statusSel.style.display = "";
      statusSel.onchange = async function () {
        try {
          await api("/api/projects/" + id + "/status", {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: statusSel.value }),
          });
        } catch (err) {
          showToast("Could not update status &#8211; " + apiErrorDetail(err));
          statusSel.value = p.status;
          return;
        }
        showToast("Status updated to " + statusSel.value);
        openDetail(id);
      };
    } else {
      statusSel.style.display = "none";
    }

    var meta = document.getElementById("dMeta");
    meta.innerHTML = "";
    var buLabel = (p.business_units && p.business_units.length) ? p.business_units.join(" / ") : "&#8213;";
    var metaItems = p.stage === "L0"
      ? [["Bid Manager", p.bid_manager || "&#8213;"], ["RFX", p.rfx_number || "&#8213;"], ["Region", joinList(p.region)], ["Scope", joinList(p.scope)],
         ["Business Unit", buLabel],
         ["Announced", fmtDate(p.announcement_date)], ["Site Visit", fmtDate(p.site_visit_date)], ["Pre-Bid Deadline", fmtDate(p.pre_bid_deadline)], ["Bid Submission Date", fmtDate(p.bsd)]]
      : [["Bid Manager", p.bid_manager || "&#8213;"], ["Project Manager", p.project_manager || "&#8213;", "pm"],
         ["Region", joinList(p.region)], ["Scope", joinList(p.scope)], ["Business Unit", buLabel],
         ["Announced", fmtDate(p.announcement_date)],
         ["Contract Status", p.contract_status === "Signed"
           ? '<span class="pill good"><span class="dot"></span>Signed</span>'
           : (p.contract_status || "&#8213;")]];
    metaItems.forEach(function (m) {
      var mi = el("div", "meta-item");
      mi.appendChild(el("div", "mk", m[0]));
      var mv = el("div", "mv", m[1]);
      if (m[2] === "pm" && can("create") && !currentProjectTerminal) {
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
    var deptFocal = {}, deptNumber = {};
    allDeptsMeta.forEach(function (d) { deptFocal[d.name] = d.focal_point_name; deptNumber[d.name] = d.number; });
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
        '<div class="folder-left"><span class="folder-ic">&#128193;</span><div><div class="folder-name">' + deptLabel(deptName, deptNumber[deptName]) + '</div>' +
        '<div class="folder-focal">Focal: ' + (deptFocal[deptName] || "&#8213;") + '</div></div></div>' +
        '<div class="folder-right"><span class="folder-pct">' + (pct === null ? "&#8213;" : pct + "%") + '</span></div>';
      row.addEventListener("click", function () {
        document.querySelectorAll(".folder-row").forEach(function (r) { r.classList.remove("active"); });
        row.classList.add("active");
        currentDeptOpen = deptName;
        document.getElementById("dDeliverTitle").textContent = deptLabel(deptName, deptNumber[deptName]) + " Deliverables";
        renderDeliverables(deptItems);
      });
      folders.appendChild(row);
    });
    var firstDeptItems = deptNames.length ? allDelivs.filter(function (d) { return d.department === deptNames[0]; }) : [];
    document.getElementById("dDeliverTitle").textContent = deptNames.length ? deptLabel(deptNames[0], deptNumber[deptNames[0]]) + " Deliverables" : "Deliverables";
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
      body.appendChild(el("div", "deliv-due", "Due " + fmtDate(d.due_date) + ' &middot; <span class="pill ' + sm[0] + '"><span class="dot"></span>' + sm[1] + "</span>"));
      if (d.completion_note) {
        body.appendChild(el("div", "deliv-comment", "&#128172; " + d.completion_note));
      }
      row.appendChild(el("div", "deliv-num", d.item_no));
      row.appendChild(body);

      var actions = el("div", "deliv-actions");
      if (currentProjectTerminal) {
        if (d.file_url) actions.appendChild(fileLink(d));
      } else if (d.status === "pending_review") {
        if (d.file_url) actions.appendChild(fileLink(d));
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
        if (can("remind")) actions.appendChild(el("button", "btn ghost-crit", "Send reminder"));
        if (can("upload")) { actions.appendChild(uploadButton(d.id)); actions.appendChild(markCompleteButton(d.id)); }
      } else if (d.status === "not_due" || d.status === "due" || d.status === "rejected") {
        if (d.file_url) actions.appendChild(fileLink(d));
        if (can("upload")) { actions.appendChild(uploadButton(d.id)); actions.appendChild(markCompleteButton(d.id)); }
      } else if (d.file_url) {
        actions.appendChild(fileLink(d));
      }
      row.appendChild(actions);
      wrap.appendChild(row);
    });
  }
  function fileLink(d) {
    var a = el("a", "btn", "View / Download");
    a.href = d.file_url; a.target = "_blank"; a.rel = "noopener";
    return a;
  }
  function uploadButton(submissionId, after) {
    after = after || function () { openDetail(currentProjectId); };
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
      after();
    });
    var span = el("span"); span.appendChild(btn); span.appendChild(fileInput);
    return span;
  }
  function markCompleteButton(submissionId, after) {
    after = after || function () { openDetail(currentProjectId); };
    var btn = el("button", "btn", "Mark Completed");
    btn.addEventListener("click", async function () {
      var comment = prompt("Describe how this was completed (required — no file to attach):", "");
      if (comment === null) return;
      comment = comment.trim();
      if (!comment) { showToast("A comment is required to mark this complete"); return; }
      try {
        await api("/api/deliverables/" + submissionId + "/mark-complete", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ comment: comment, actor_name: CURRENT_ROLE + " (pilot)", actor_role: CURRENT_ROLE, actor_email: actingEmail() }),
        });
      } catch (err) {
        showToast("Could not mark complete &#8211; " + apiErrorDetail(err));
        return;
      }
      showToast("Marked complete &#8211; SME notified");
      after();
    });
    return btn;
  }
  async function review(submissionId, approved, after) {
    var comment;
    if (approved) {
      comment = prompt("Add a comment (optional):", "");
      if (comment === null) return;
      comment = comment.trim() || null;
    } else {
      comment = prompt("Reason for rejection (shown to the owner):", "Please review and resubmit with updated supporting documents.");
      if (comment === null) return;
    }
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
  var DEPT_COLORS = {
    1: "#e63946", 2: "#f3722c", 3: "#d4a017", 4: "#90be6d", 5: "#2a9d8f",
    6: "#219ebc", 7: "#3a86ff", 8: "#7209b7", 9: "#b5179e", 10: "#ef476f",
    11: "#6a4c93", 12: "#495057",
  };
  function deptColor(number) { return DEPT_COLORS[number] || "#94a3b8"; }
  var ganttStage = "L0";
  var ganttPooledRows = [];
  document.querySelectorAll("#ganttStageToggle .chip").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll("#ganttStageToggle .chip").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      ganttStage = btn.dataset.stage;
      loadGanttForStage();
    });
  });
  document.getElementById("ganttDeptFilter").addEventListener("change", applyGanttFilters);
  document.getElementById("ganttStatusFilter").addEventListener("change", applyGanttFilters);
  document.getElementById("ganttScope").addEventListener("change", function () { renderGanttFor(this.value); });

  async function loadGantt() { await loadGanttForStage(); }

  async function loadGanttForStage() {
    var list = await api("/api/projects?stage=" + ganttStage + "&status=" + encodeURIComponent("In Progress"));
    var scopeSel = document.getElementById("ganttScope");
    scopeSel.innerHTML = '<option value="">Pooled Timeline (all active ' + ganttStage + ' projects)</option>';
    list.forEach(function (p) {
      var o = el("option", "", p.est_no + " &#8211; " + p.name); o.value = p.id;
      scopeSel.appendChild(o);
    });
    document.getElementById("ganttStatusFilter").value = "";
    document.getElementById("ganttDeptFilter").innerHTML = '<option value="">All Departments</option>';
    await renderGanttFor(scopeSel.value);
  }

  async function openProjectGantt(projectId) {
    switchView("gantt");
    ganttStage = currentProjectStage;
    document.querySelectorAll("#ganttStageToggle .chip").forEach(function (b) {
      b.classList.toggle("active", b.dataset.stage === ganttStage);
    });
    await loadGanttForStage();
    var scopeSel = document.getElementById("ganttScope");
    scopeSel.value = String(projectId);
    await renderGanttFor(scopeSel.value);
  }

  async function renderGanttFor(projectId) {
    var isPooled = !projectId;
    document.querySelectorAll("#ganttDeptFilter,#ganttStatusFilter")
      .forEach(function (s) { s.style.display = isPooled ? "" : "none"; });
    var legend = document.getElementById("ganttDeptLegend");
    if (isPooled) {
      ganttPooledRows = await api("/api/gantt/timeline?stage=" + ganttStage);
      var deptSel = document.getElementById("ganttDeptFilter");
      var seenDepts = {};
      ganttPooledRows.forEach(function (r) { seenDepts[r.department] = r.department_number; });
      deptSel.innerHTML = '<option value="">All Departments</option>';
      Object.keys(seenDepts).sort(function (a, b) { return (seenDepts[a] || 0) - (seenDepts[b] || 0); }).forEach(function (name) {
        var o = el("option", "", deptLabel(name, seenDepts[name])); o.value = name;
        deptSel.appendChild(o);
      });
      legend.innerHTML = "";
      Object.keys(seenDepts).sort(function (a, b) { return (seenDepts[a] || 0) - (seenDepts[b] || 0); }).forEach(function (name) {
        var lg = el("span", "lg");
        lg.innerHTML = '<span class="sw" style="background:' + deptColor(seenDepts[name]) + '"></span>';
        lg.appendChild(document.createTextNode(deptLabel(name, seenDepts[name])));
        legend.appendChild(lg);
      });
      legend.className = "ann-type-key gantt-dept-legend";
      applyGanttFilters();
      return;
    }
    legend.innerHTML = "";
    var rows = await api("/api/gantt/projects/" + projectId);
    drawGanttRows(rows, false);
  }

  function applyGanttFilters() {
    var dept = document.getElementById("ganttDeptFilter").value;
    var status = document.getElementById("ganttStatusFilter").value;
    var rows = ganttPooledRows.filter(function (r) {
      return (!dept || r.department === dept) && (!status || r.status === status);
    });
    drawGanttRows(rows, true);
  }

  function drawGanttRows(rows, isPooled) {
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
    var DAY = 86400000;
    max += DAY; // include the last day's full width, not just its start instant
    var span = Math.max(1, max - min);
    function pct(t) { return ((t - min) / span) * 100; }

    // Month header, one flex segment per month proportional to its share of the range.
    var cur = new Date(min); cur.setHours(0, 0, 0, 0); cur.setDate(1);
    while (cur.getTime() <= max) {
      var segStart = Math.max(cur.getTime(), min);
      var next = new Date(cur.getFullYear(), cur.getMonth() + 1, 1).getTime();
      var segEnd = Math.min(next, max);
      if (segEnd > segStart) {
        var seg = el("span", "", cur.toLocaleDateString("en-GB", { month: "short", year: "numeric" }));
        seg.style.flex = "0 0 " + (((segEnd - segStart) / span) * 100).toFixed(3) + "%";
        axis.appendChild(seg);
      }
      cur = new Date(cur.getFullYear(), cur.getMonth() + 1, 1);
    }

    // Gridlines overlay (month boundaries + week ticks + today marker), aligned under the track area.
    var gridlines = el("div", "gantt-gridlines");
    var monthCur = new Date(min); monthCur.setHours(0, 0, 0, 0); monthCur.setDate(1);
    monthCur = new Date(monthCur.getFullYear(), monthCur.getMonth() + 1, 1);
    while (monthCur.getTime() < max) {
      var mLine = el("div", "gantt-gridline month");
      mLine.style.left = pct(monthCur.getTime()).toFixed(3) + "%";
      gridlines.appendChild(mLine);
      monthCur = new Date(monthCur.getFullYear(), monthCur.getMonth() + 1, 1);
    }
    for (var w = min + 7 * DAY; w < max; w += 7 * DAY) {
      var wLine = el("div", "gantt-gridline week");
      wLine.style.left = pct(w).toFixed(3) + "%";
      gridlines.appendChild(wLine);
    }
    var today = new Date(); today.setHours(0, 0, 0, 0);
    if (today.getTime() >= min && today.getTime() < max) {
      var tLine = el("div", "gantt-gridline today");
      tLine.style.left = pct(today.getTime()).toFixed(3) + "%";
      tLine.title = "Data Date: " + fmtDate(today.toISOString().slice(0, 10));
      var tLabel = el("div", "gantt-today-label", "Today");
      tLabel.style.left = pct(today.getTime()).toFixed(3) + "%";
      gridlines.appendChild(tLine);
      gridlines.appendChild(tLabel);
    }
    wrap.appendChild(gridlines);

    rows.forEach(function (r) {
      var s = new Date(r.start + "T00:00:00").getTime();
      var e = new Date(r.end + "T00:00:00").getTime() + DAY;
      var leftPct = pct(s);
      var widthPct = Math.max(0.8, ((e - s) / span) * 100);
      var row = el("div", "gantt-row");
      var labelHtml = isPooled
        ? "<b>" + r.item_no + "</b> &middot; " + r.short_name + '<span class="gantt-est-tag">' + r.est_no + "</span>"
        : "<b>" + r.item_no + "</b> &middot; " + r.short_name;
      var label = el("div", "gantt-label", labelHtml);
      label.title = r.name;
      row.appendChild(label);
      var track = el("div", "gantt-track");
      var bar;
      if (isPooled) {
        bar = el("div", "gantt-bar" + (r.is_milestone ? " milestone" : ""));
        bar.style.background = deptColor(r.department_number);
      } else {
        var cls = (STATUS_META[r.status] || ["neutral"])[0];
        bar = el("div", "gantt-bar " + cls + (r.is_milestone ? " milestone" : ""));
      }
      bar.style.left = leftPct.toFixed(2) + "%";
      bar.style.width = widthPct.toFixed(2) + "%";
      var statusLabel = (STATUS_META[r.status] || ["", r.status])[1];
      bar.title = (isPooled ? r.department + " &#8211; " + statusLabel + " &#8211; " : "") +
        fmtDate(r.start) + " " + String.fromCharCode(8594) + " " + fmtDate(r.end);
      track.appendChild(bar);
      row.appendChild(track);
      if (r.submission_id) {
        row.style.cursor = "pointer";
        row.addEventListener("click", function () { jumpToAssignedItem(r.submission_id); });
      }
      wrap.appendChild(row);
    });
    gridlines.style.height = wrap.scrollHeight + "px";
  }

  async function jumpToAssignedItem(submissionId) {
    if (!submissionId) return;
    assignedFilter = "";
    switchView("assigned");
    await loadAssigned();
    var target = document.querySelector('.aq-row[data-sid="' + submissionId + '"]');
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.classList.add("flash");
      setTimeout(function () { target.classList.remove("flash"); }, 1800);
    }
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
      r.appendChild(el("div", "rank-name", deptLabel(row.department, row.department_number)));
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

  /* ================= JOURNEY / HISTORY ================= */
  var journeyProjectsLoaded = false;
  var HISTORY_ACTION_ICON = {
    submitted: "&#128228;", assigned: "&#128100;", review_requested: "&#128269;",
    approved: "&#9989;", rejected: "&#10060;", unlocked: "&#128275;",
  };
  async function loadJourney() {
    var sel = document.getElementById("journeyProjectSel");
    if (!journeyProjectsLoaded) {
      var list = await api("/api/projects");
      list.forEach(function (p) {
        var o = el("option", "", p.stage + " &middot; " + p.est_no + " &#8211; " + p.name);
        o.value = p.id;
        sel.appendChild(o);
      });
      sel.addEventListener("change", function () { renderJourneyTimeline(sel.value); });
      journeyProjectsLoaded = true;
    }
    if (sel.value) renderJourneyTimeline(sel.value);
  }
  async function renderJourneyTimeline(projectId) {
    var wrap = document.getElementById("journeyTimeline");
    if (!projectId) { wrap.innerHTML = ""; return; }
    var events = await api("/api/projects/" + projectId + "/history");
    wrap.innerHTML = "";
    if (!events.length) { wrap.appendChild(el("div", "empty-state", "No activity recorded yet.")); return; }
    events.slice().reverse().forEach(function (ev) {
      var row = el("div", "journey-event");
      row.appendChild(el("div", "journey-event-ic", HISTORY_ACTION_ICON[ev.action] || "&#128276;"));
      var main = el("div", "journey-event-main");
      var when = new Date(ev.at).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
      main.appendChild(el("div", "journey-event-top",
        "<b>" + ev.item_no + "</b> &middot; " + ev.name + '<span class="journey-event-time">' + when + "</span>"));
      main.appendChild(el("div", "journey-event-sub",
        ev.action.replace(/_/g, " ") + " by <b>" + (ev.actor || "system") + "</b>" + (ev.note ? " &#8212; " + ev.note : "")));
      row.appendChild(main);
      wrap.appendChild(row);
    });
  }

  /* ================= SCORES (admin full leaderboard) ================= */
  async function loadScores() {
    var d = await api("/api/dashboard/top-achievers");
    renderAchievers("scoresOwners", d.owners, "owner");
    renderAchievers("scoresSmes", d.smes, "sme");
  }

  /* ================= FOCAL POINTS (admin) ================= */
  async function loadFocalPoints() {
    var depts = await api("/api/departments");
    var tbody = document.getElementById("focalPointsBody");
    tbody.innerHTML = "";
    depts.forEach(function (d) {
      var tr = el("tr");
      var nameInput = el("input"); nameInput.type = "text"; nameInput.value = d.focal_point_name || ""; nameInput.placeholder = "Name";
      var emailInput = el("input"); emailInput.type = "text"; emailInput.value = d.focal_point_email || ""; emailInput.placeholder = "email@algihaz.com";
      var saveBtn = el("button", "btn", "Save");
      saveBtn.addEventListener("click", async function () {
        try {
          await api("/api/departments/" + d.id + "/focal-point", {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ focal_point_name: nameInput.value.trim(), focal_point_email: emailInput.value.trim() }),
          });
        } catch (err) {
          showToast("Could not save &#8211; " + apiErrorDetail(err));
          return;
        }
        showToast("Focal point updated for " + d.name);
      });
      var tdNum = el("td", "", d.number == null ? "&#8213;" : String(d.number));
      var tdName = el("td", "", d.name);
      var tdNameInput = el("td"); tdNameInput.appendChild(nameInput);
      var tdEmailInput = el("td"); tdEmailInput.appendChild(emailInput);
      var tdSave = el("td"); tdSave.appendChild(saveBtn);
      tr.appendChild(tdNum); tr.appendChild(tdName); tr.appendChild(tdNameInput); tr.appendChild(tdEmailInput); tr.appendChild(tdSave);
      tbody.appendChild(tr);
    });
  }

  /* ================= FOLLOW UP (admin) ================= */
  async function loadFollowUp() {
    var reqs = await api("/api/deliverables/reassignment-requests?status=pending");
    var reassignWrap = document.getElementById("reassignList");
    document.getElementById("reassignCount").textContent = reqs.length || "";
    reassignWrap.innerHTML = "";
    if (!reqs.length) {
      reassignWrap.appendChild(el("div", "empty-state", "No pending reassignment requests."));
    } else {
      reqs.forEach(function (r) {
        var row = el("div", "aq-row");
        var main = el("div", "aq-main");
        main.appendChild(el("div", "aq-title", r.item_no + " &middot; " + r.name));
        main.appendChild(el("div", "aq-sub",
          '<span>' + r.est_no + '</span><span class="sep">&middot;</span>' +
          '<span>' + (r.from_email || "Unassigned") + ' &#8594; ' + r.to_email + '</span>' +
          (r.reason ? '<span class="sep">&middot;</span><span>' + r.reason + '</span>' : "")));
        row.appendChild(main);
        var actions = el("div", "deliv-actions");
        var appr = el("button", "btn primary", "Approve");
        appr.addEventListener("click", async function () {
          await api("/api/deliverables/reassignment-requests/" + r.id + "/decide", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approved: true, actor_role: CURRENT_ROLE }),
          });
          showToast("Reassigned to " + r.to_email);
          loadFollowUp();
        });
        var rej = el("button", "btn ghost-crit", "Reject");
        rej.addEventListener("click", async function () {
          await api("/api/deliverables/reassignment-requests/" + r.id + "/decide", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approved: false, actor_role: CURRENT_ROLE }),
          });
          showToast("Reassignment rejected");
          loadFollowUp();
        });
        actions.appendChild(appr); actions.appendChild(rej);
        row.appendChild(actions);
        reassignWrap.appendChild(row);
      });
    }

    var items = await api("/api/deliverables/follow-up");
    var deptSel = document.getElementById("fuDeptFilter");
    var estSel = document.getElementById("fuEstFilter");
    var seenDepts = {}, seenEsts = {};
    items.forEach(function (d) { seenDepts[d.department] = true; seenEsts[d.est_no] = true; });
    deptSel.innerHTML = '<option value="">All Departments</option>';
    Object.keys(seenDepts).sort().forEach(function (n) { var o = el("option", "", n); o.value = n; deptSel.appendChild(o); });
    estSel.innerHTML = '<option value="">All Est Numbers</option>';
    Object.keys(seenEsts).sort().forEach(function (n) { var o = el("option", "", n); o.value = n; estSel.appendChild(o); });

    function renderFollowUpList() {
      var dept = deptSel.value, estNo = estSel.value;
      var filtered = items.filter(function (d) {
        return (!dept || d.department === dept) && (!estNo || d.est_no === estNo);
      });
      var wrap = document.getElementById("followUpList");
      wrap.innerHTML = "";
      if (!filtered.length) { wrap.appendChild(el("div", "empty-state", "Nothing due or overdue right now.")); return; }
      filtered.forEach(function (d) {
        var sm = STATUS_META[d.status] || ["neutral", d.status];
        var row = el("div", "aq-row");
        var main = el("div", "aq-main");
        main.appendChild(el("div", "aq-title", d.item_no + " &middot; " + d.name));
        main.appendChild(el("div", "aq-sub",
          '<span>' + d.est_no + ' &#8211; ' + d.project_name + '</span><span class="sep">&middot;</span>' +
          '<span>' + deptLabel(d.department, null) + '</span><span class="sep">&middot;</span>' +
          '<span>Owner: ' + d.owner + '</span><span class="sep">&middot;</span>' +
          '<span>Due ' + fmtDate(d.due_date) + '</span>'));
        row.appendChild(main);
        row.appendChild(el("span", "pill " + sm[0], '<span class="dot"></span>' + sm[1]));
        wrap.appendChild(row);
      });
      document.getElementById("fuRemindAll").onclick = async function () {
        var ids = filtered.map(function (d) { return d.id; });
        if (!ids.length) return;
        var res = await api("/api/deliverables/bulk-remind", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ submission_ids: ids, actor_role: CURRENT_ROLE }),
        });
        showToast("Sent " + res.sent + " reminder(s)");
      };
    }
    deptSel.onchange = renderFollowUpList;
    estSel.onchange = renderFollowUpList;
    renderFollowUpList();
  }

  /* ================= ANNOUNCEMENTS ================= */
  async function loadAnnouncements() {
    var list = await api("/api/announcements");
    var wrap = document.getElementById("announcementsList");
    wrap.innerHTML = "";
    if (!list.length) { wrap.appendChild(el("div", "empty-state", "No announcements sent yet.")); return; }
    list.forEach(function (a) {
      var meta = annIcon(a);
      var row = el("div", "ann-row");
      row.appendChild(el("div", "ann-ic " + meta[1], meta[0]));
      var main = el("div", "ann-main");
      var when = new Date(a.created_at).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
      main.appendChild(el("div", "ann-top", '<span class="ann-title">' + a.title + '</span><span class="ann-time">' + when + '</span>'));
      main.appendChild(el("div", "ann-body", a.body));
      main.appendChild(el("div", "ann-meta", "To: <b>" + (a.recipients || "&#8213;") + "</b> &middot; " + a.email_status));
      row.appendChild(main);
      if (a.project_id) {
        row.style.cursor = "pointer";
        row.addEventListener("click", function () { openDetail(a.project_id); });
      }
      wrap.appendChild(row);
    });
  }

  /* ================= CREATE PROJECT ================= */
  var createOptionsLoaded = false;
  var buUncoveredScopes = [];
  function refreshBuFieldVisibility() {
    var scope = checkedValues("cfScopeGrid");
    var needed = scope.some(function (s) { return buUncoveredScopes.indexOf(s) !== -1; });
    document.getElementById("cfBuField").style.display = needed ? "" : "none";
  }
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
      renderCheckGroup("cfBuGrid", "", opts.business_units);
      buUncoveredScopes = opts.bu_uncovered_scopes || [];
      document.querySelectorAll("#cfScopeGrid input").forEach(function (cb) {
        cb.addEventListener("change", refreshBuFieldVisibility);
      });
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
  document.getElementById("cfEstNo").addEventListener("input", function () {
    this.value = this.value.replace(/\D/g, "");
  });

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
        var estNoDigits = document.getElementById("cfEstNo").value.trim();
        var announce = document.getElementById("cfAnnounce").value;
        var bsd = document.getElementById("cfBsd").value;
        var bidManager = document.getElementById("cfBid").value;
        var region = checkedValues("cfRegionGrid");
        var scope = checkedValues("cfScopeGrid");
        if (!name) { showToast("Tender name is required"); return; }
        if (!estNoDigits) { showToast("Est-Num is required"); return; }
        if (!/^\d+$/.test(estNoDigits)) { showToast("Est-Num must be a number only"); return; }
        var estNo = "Est-" + estNoDigits;
        if (!bidManager) { showToast("Bid Manager is required"); return; }
        if (!announce) { showToast("Announcement Date is required"); return; }
        if (!bsd) { showToast("Bid Submission Date is required"); return; }
        if (!region.length) { showToast("Select at least one Region"); return; }
        if (!scope.length) { showToast("Select at least one Scope"); return; }
        var regionOtherVal = document.getElementById("cfRegionOther").value.trim();
        var scopeOtherVal = document.getElementById("cfScopeOther").value.trim();
        if (region.indexOf("Other") !== -1 && !regionOtherVal) { showToast("Specify the Other region"); return; }
        if (scope.indexOf("Other") !== -1 && !scopeOtherVal) { showToast("Specify the Other scope"); return; }
        var needsManualBu = scope.some(function (s) { return buUncoveredScopes.indexOf(s) !== -1; });
        var businessUnits = checkedValues("cfBuGrid");
        if (needsManualBu && !businessUnits.length) { showToast("Business Unit is required for this scope"); return; }
        var payload = {
          name: name, est_no: estNo,
          region: region, region_other: regionOtherVal || null,
          scope: scope, scope_other: scopeOtherVal || null,
          rfx_number: document.getElementById("cfRfx").value || null,
          announcement_date: announce, site_visit_date: document.getElementById("cfSiteVisit").value || null,
          pre_bid_deadline: document.getElementById("cfPreBid").value || null,
          bid_manager: bidManager, bsd: bsd,
          business_units: needsManualBu ? businessUnits : null,
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
    if (!showAdmin && ADMIN_ONLY_VIEWS.some(function (v) { return !document.getElementById("view-" + v).hidden; })) switchView("dashboard");
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

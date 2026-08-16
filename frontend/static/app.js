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
  function isAssigned(d) {
    if (CURRENT_ROLE === "Admin") return true;
    var email = actingEmail().trim().toLowerCase();
    if (!email) return false;
    var owner = (d.owner_email || "").trim().toLowerCase();
    var sme = (d.sme_email || "").trim().toLowerCase();
    return (!!owner && email === owner) || (!!sme && email === sme);
  }

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html !== undefined) e.innerHTML = html;
    return e;
  }
  // Item 170: DD-MonthName-YYYY everywhere a date renders (e.g.
  // "15-November-2026") -- toLocaleDateString has no hyphen-separator,
  // full-month-name preset, so this is built by hand instead.
  function fmtDate(iso) {
    if (!iso) return "&#8213;";
    var d = new Date(iso + "T00:00:00");
    var day = String(d.getDate()).padStart(2, "0");
    var month = d.toLocaleDateString("en-GB", { month: "long" });
    return day + "-" + month + "-" + d.getFullYear();
  }
  // Item 143 (2nd revision): a deliverable now carries two independent
  // status pills -- Deadline (Not Due / Due / On Time / Early / Late, with
  // a day count) and Progress (No Progress Yet / In Progress / Pending SME
  // Review / Completed / Rejected). Not Required and Pending Triage sit
  // outside both axes, so they render as a single pill on their own.
  function deadlinePillHtml(d) {
    var meta = DEADLINE_META[d.deadline_status] || ["neutral", d.deadline_status];
    var text = meta[1];
    if (d.deadline_days !== null && d.deadline_days !== undefined) {
      text += " (" + (d.deadline_days > 0 ? "+" : "") + d.deadline_days + " days)";
    }
    return '<span class="pill ' + meta[0] + '"><span class="dot"></span>' + text + "</span>";
  }
  function progressPillHtml(d) {
    // Auto-completed items (1.1-1.5, milestones) get a distinct label
    // rather than folding into plain "Completed" -- they were never a real
    // SME sign-off, just data already known from the project's own form.
    if (d.status === "approved" && d.auto_completed) {
      return '<span class="pill good"><span class="dot"></span>Auto-Completed</span>';
    }
    var meta = STATUS_META[d.status] || ["neutral", d.status];
    return '<span class="pill ' + meta[0] + '"><span class="dot"></span>' + meta[1] + "</span>";
  }
  function statusPillsHtml(d) {
    if (d.status === "not_required" || d.status === "pending_triage") return progressPillHtml(d);
    return deadlinePillHtml(d) + progressPillHtml(d);
  }
  // Item 144: same two axes as the pills above, rendered as plain
  // dot+text for the Assigned Deliverables table (no pill background).
  function deadlineStatusCellHtml(d) {
    if (d.status === "not_required" || d.status === "pending_triage") {
      return '<span class="aqt-status neutral">&#8213;</span>';
    }
    var meta = DEADLINE_META[d.deadline_status] || ["neutral", d.deadline_status];
    var text = meta[1];
    if (d.deadline_days !== null && d.deadline_days !== undefined) {
      text += " (" + (d.deadline_days > 0 ? "+" : "") + d.deadline_days + " days)";
    }
    return '<span class="aqt-status ' + meta[0] + '"><span class="dot"></span>' + text + "</span>";
  }
  function progressStatusCellHtml(d) {
    if (d.status === "approved" && d.auto_completed) {
      return '<span class="aqt-status good"><span class="dot"></span>Auto-Completed</span>';
    }
    var meta = STATUS_META[d.status] || ["neutral", d.status];
    return '<span class="aqt-status ' + meta[0] + '"><span class="dot"></span>' + meta[1] + "</span>";
  }
  // Item 91: a centered loading popup for every in-flight API call, so a
  // slow reminder/creation/etc. reads as "working" instead of "stuck".
  // Delayed briefly so a normal fast request never even flickers it.
  var _loadingCount = 0, _loadingShowTimer = null;
  function _loadingStart() {
    _loadingCount++;
    if (_loadingCount === 1) {
      _loadingShowTimer = setTimeout(function () {
        document.getElementById("globalLoadingOverlay").hidden = false;
      }, 200);
    }
  }
  function _loadingEnd() {
    _loadingCount = Math.max(0, _loadingCount - 1);
    if (_loadingCount === 0) {
      clearTimeout(_loadingShowTimer);
      document.getElementById("globalLoadingOverlay").hidden = true;
    }
  }
  async function api(path, opts) {
    // Item 100: force a real network round-trip on every call — GET requests
    // otherwise had no explicit Cache-Control, letting the browser occasionally
    // serve a stale response (e.g. the deliverable popup opened right after
    // an upload from a different entry point, showing the pre-upload state
    // until something forced a genuinely fresh request).
    opts = Object.assign({ cache: "no-store" }, opts || {});
    _loadingStart();
    try {
      var r = await fetch(path, opts);
      if (!r.ok) {
        var bodyText = await r.text();
        var err = new Error(path + " -> " + r.status + ": " + bodyText);
        try { err.detail = JSON.parse(bodyText).detail; } catch (e) { err.detail = bodyText; }
        throw err;
      }
      return r.status === 204 ? null : r.json();
    } finally {
      _loadingEnd();
    }
  }
  function apiErrorDetail(err) { return err.detail || err.message; }
  function showToast(msg, isError) {
    var t = document.getElementById("toast");
    t.classList.toggle("error", !!isError);
    document.getElementById("toastIc").textContent = isError ? "❌" : "✅";
    document.getElementById("toastMsg").innerHTML = msg;
    t.classList.add("show");
    clearTimeout(window.__toastTimer);
    var duration = isError ? Math.max(3200, msg.split("<br>").length * 1600) : 3200;
    window.__toastTimer = setTimeout(function () { t.classList.remove("show"); }, duration);
  }

  // Item 143 (2nd revision): Progress status -- how far the work itself
  // has gotten. Independent of Deadline status (DEADLINE_META below).
  var STATUS_META = {
    no_progress: ["neutral", "No Progress Yet"],
    in_progress: ["warn", "In Progress"],
    pending_review: ["warn", "Pending SME Review"],
    approved: ["good", "Completed"], rejected: ["crit", "Rejected"],
    pending_triage: ["neutral", "Pending BM Triage"], not_required: ["neutral", "Not Required"],
  };
  // Deadline status -- where a deliverable stands against its due date,
  // live while open (Due's day count grows daily) and frozen the moment it
  // resolves (Early/On Time/Late read off the actual completion date).
  var DEADLINE_META = {
    not_due: ["neutral", "Not Due"], due: ["crit", "Due"],
    on_time: ["good", "On Time"], early: ["good", "Early"], late: ["crit", "Late"],
  };
  // Item 143 (2nd revision): the Dashboard matrix collapses everything down
  // to just these three buckets (rules.deadline_bucket() on the backend).
  var MATRIX_BUCKET_META = { not_due: ["neutral", "Not Due"], due: ["crit", "Due"], completed: ["good", "Completed"] };
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
    support: loadSupport, bmtriage: loadBmTriageStatus, tickets: loadTickets,
  };
  var ADMIN_ONLY_VIEWS = ["create", "reports", "scores", "focalpoints", "followup", "tickets"];
  // Item 110: BM Triage Status isn't strictly admin-only — a Bid Manager
  // acting as themselves (Owner role, since that's the role they'd pick to
  // represent themselves elsewhere in the app) can see it too, scoped
  // server-side to just their own tenders.
  // Item 160: BM Triage Status is the admin-facing overview of every
  // project's triage state -- it used to also show for "Owner" since
  // there's no distinct Bid Manager role in the switcher, but a real BM's
  // own forced triage flow (checkBmTriageDeadline's overlay, openTriage)
  // is email-matched and independent of this nav item, so restricting the
  // nav item itself to Admin doesn't block anyone's actual triage work.
  function canSeeBmTriage() { return can("create"); }
  // Item 158: Viewer has no upload/review/create actions at all, so a work
  // queue of assigned items has nothing for them to do with it.
  function canSeeAssigned() { return CURRENT_ROLE !== "Viewer"; }
  function switchView(name) {
    if (ADMIN_ONLY_VIEWS.indexOf(name) !== -1 && !can("create")) name = "dashboard";
    if (name === "bmtriage" && !canSeeBmTriage()) name = "dashboard";
    if (name === "assigned" && !canSeeAssigned()) name = "dashboard";
    document.querySelectorAll(".view").forEach(function (v) { v.hidden = true; });
    document.getElementById("view-" + name).hidden = false;
    document.querySelectorAll(".nav-item").forEach(function (n) { n.classList.toggle("active", n.dataset.view === name); });
    // Item 99: a plain nav view is remembered in the URL so a refresh comes
    // back here instead of bouncing to the Dashboard. "detail" and "triage"
    // aren't nav views — they get their own hash from openDetail/openTriage.
    if (name !== "detail" && name !== "triage") location.hash = "view=" + name;
    if (LOADERS[name]) LOADERS[name]();
    // Item 145: re-check on every navigation except into the triage flow
    // itself, so completing it doesn't get instantly re-blocked mid-flow.
    if (name !== "triage") checkBmTriageDeadline();
  }
  document.querySelectorAll(".nav-item").forEach(function (btn) {
    btn.addEventListener("click", function () { switchView(btn.dataset.view); });
  });
  document.getElementById("backBtn").addEventListener("click", function () { switchView(lastListView); });
  document.getElementById("dGanttBtn").addEventListener("click", function () { openProjectGantt(currentProjectId); });

  /* ================= DASHBOARD ================= */
  var dashFocus = "all";
  document.querySelectorAll("#dashFocusToggle .chip").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll("#dashFocusToggle .chip").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      dashFocus = btn.dataset.focus;
      document.getElementById("dashFocusEmail").style.display = dashFocus === "mine" ? "" : "none";
      loadDashboard();
    });
  });
  document.getElementById("dashFocusEmail").addEventListener("change", loadDashboard);

  async function loadDashboard() {
    var focusEmail = (dashFocus === "mine" ? document.getElementById("dashFocusEmail").value.trim() : "");
    var qs = focusEmail ? "?focus_email=" + encodeURIComponent(focusEmail) : "";
    var d = await api("/api/dashboard" + qs);

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
    var mine = !!focusEmail;
    // Item 121: the three deliverable-status cards jump straight to
    // Assigned Deliverables pre-filtered to match what was clicked,
    // instead of just being a number you then have to go re-find.
    [["Active L0 Tenders", d.active_l0, "", null, null], ["Active L1 Projects", d.active_l1, "", null, null],
     [mine ? "My Not Due" : "Not Due", d.not_due, "", "deadline", "not_due"],
     [mine ? "My Pending SME Review" : "Pending SME Review", d.pending_review, "", "progress", "pending_review"],
     [mine ? "My Due" : "Due Right Now", d.overdue, "color:var(--crit)", "deadline", "due"]]
      .forEach(function (s) {
        var tile = el("div", "card stat-tile");
        if (s[3]) {
          tile.style.cursor = "pointer";
          tile.addEventListener("click", function () { goToAssignedFilter(s[3], s[4]); });
        }
        tile.appendChild(el("div", "label", s[0]));
        var v = el("div", "value num", String(s[1]));
        if (s[2]) v.setAttribute("style", s[2]);
        tile.appendChild(v);
        stats.appendChild(tile);
      });

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
      if (a.submission_id || a.project_id) {
        row.style.cursor = "pointer";
        // Item 92: opens straight to the deliverable popup, like Assigned
        // Deliverables does — no more redirecting to project detail first.
        row.addEventListener("click", function () {
          if (a.submission_id) openDelivModal(a.submission_id);
          else openDetail(a.project_id);
        });
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
        // Item 143 (2nd revision): the matrix shows the 3-state Deadline
        // collapse (Not Due / Due / Completed), not the raw Progress status.
        var meta = MATRIX_BUCKET_META[cell.bucket] || ["neutral", cell.bucket];
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
      var label = (r.name ? r.name + " &middot; " : "") + r.email;
      var emailLine = label + (r.sample ? ' <span class="sample-tag">Sample</span>' : "");
      main.appendChild(el("div", "achiever-email", emailLine));
      if (kind === "sme") {
        var smeSub = r.reviewed + " review" + (r.reviewed === 1 ? "" : "s") + (r.department ? " &middot; " + r.department : "");
        main.appendChild(el("div", "achiever-sub", smeSub));
        row.appendChild(main);
        row.appendChild(el("div", "achiever-pct num", r.avg_label + " avg"));
      } else {
        var ownerSub = r.approved + " / " + r.total + " approved on time" + (r.department ? " &middot; " + r.department : "");
        main.appendChild(el("div", "achiever-sub", ownerSub));
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
  // Item 143 (2nd revision): Deadline and Progress are independent filters
  // now, each its own chip row, combined with AND logic.
  var assignedDeadlineFilter = "";
  var assignedProgressFilter = "";
  var assignedEstFilter = "";
  var assignedStage = "";
  var DEADLINE_FILTERS = [["", "All"], ["not_due", "Not Due"], ["due", "Due"]];
  var PROGRESS_FILTERS = [
    ["", "All"], ["no_progress", "No Progress Yet"], ["in_progress", "In Progress"],
    ["pending_review", "Pending SME Review"], ["approved", "Completed"], ["rejected", "Rejected"],
  ];
  function deliverableMatchesFilters(d) {
    if (assignedDeadlineFilter && d.deadline_status !== assignedDeadlineFilter) return false;
    if (assignedProgressFilter && d.status !== assignedProgressFilter) return false;
    if (assignedEstFilter && d.est_no !== assignedEstFilter) return false;
    return true;
  }
  // Item 121: jump to Assigned Deliverables pre-filtered, from a Dashboard
  // stat card. axis is "deadline" or "progress" -- resets the OTHER axis
  // and the L0/L1 stage toggle back to "All" since the card being clicked
  // is single-dimension and stage-agnostic.
  function goToAssignedFilter(axis, value) {
    assignedDeadlineFilter = axis === "deadline" ? value : "";
    assignedProgressFilter = axis === "progress" ? value : "";
    assignedEstFilter = "";
    assignedStage = "";
    document.querySelectorAll("#assignedStageToggle .chip").forEach(function (b) { b.classList.toggle("active", b.dataset.stage === ""); });
    switchView("assigned");
  }
  document.querySelectorAll("#assignedStageToggle .chip").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll("#assignedStageToggle .chip").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      assignedStage = btn.dataset.stage;
      loadAssigned();
    });
  });
  async function loadAssigned() {
    // Item 166: a non-admin only sees their own assigned deliverables
    // (owner or SME on that item) -- previously every role saw the
    // entire cross-project list.
    var qs = "?actor_role=" + encodeURIComponent(CURRENT_ROLE);
    if (passiveIdentity()) qs += "&actor_email=" + encodeURIComponent(passiveIdentity());
    var everything = await api("/api/deliverables" + qs);
    var all = assignedStage ? everything.filter(function (d) { return d.stage === assignedStage; }) : everything;
    document.getElementById("assignedBadge").textContent = everything.filter(function (d) { return d.deadline_status === "due"; }).length || "";

    var deadlineBase = assignedProgressFilter ? all.filter(function (d) { return d.status === assignedProgressFilter; }) : all;
    var dchips = document.getElementById("assignedDeadlineChips");
    dchips.innerHTML = "";
    DEADLINE_FILTERS.forEach(function (f) {
      var count = f[0] ? deadlineBase.filter(function (d) { return d.deadline_status === f[0]; }).length : deadlineBase.length;
      var chip = el("button", "chip" + (assignedDeadlineFilter === f[0] ? " active" : ""), f[1] + ' <span class="cnum">' + count + '</span>');
      chip.addEventListener("click", function () { assignedDeadlineFilter = f[0]; loadAssigned(); });
      dchips.appendChild(chip);
    });

    var progressBase = assignedDeadlineFilter ? all.filter(function (d) { return d.deadline_status === assignedDeadlineFilter; }) : all;
    var pchips = document.getElementById("assignedProgressChips");
    pchips.innerHTML = "";
    PROGRESS_FILTERS.forEach(function (f) {
      var count = f[0] ? progressBase.filter(function (d) { return d.status === f[0]; }).length : progressBase.length;
      var chip = el("button", "chip" + (assignedProgressFilter === f[0] ? " active" : ""), f[1] + ' <span class="cnum">' + count + '</span>');
      chip.addEventListener("click", function () { assignedProgressFilter = f[0]; loadAssigned(); });
      pchips.appendChild(chip);
    });

    var estSel = document.getElementById("assignedEstFilter");
    var seenEsts = {};
    all.forEach(function (d) { seenEsts[d.est_no] = true; });
    estSel.innerHTML = '<option value="">All</option>';
    Object.keys(seenEsts).sort().forEach(function (n) { var o = el("option", "", n); o.value = n; estSel.appendChild(o); });
    estSel.value = assignedEstFilter;
    estSel.onchange = function () { assignedEstFilter = estSel.value; loadAssigned(); };

    var items = all.filter(deliverableMatchesFilters);
    var wrap = document.getElementById("assignedList");
    wrap.innerHTML = "";
    if (!items.length) { wrap.appendChild(el("div", "empty-state", "Nothing here right now.")); return; }
    // Item 144: a real table -- one column per field, plain buttons off to
    // the side, no status pills. Grid-based (see .aqt-row in styles.css) so
    // it always fits the card width instead of ever needing horizontal
    // scroll -- text columns ellipsize under pressure rather than overflow.
    var table = el("div", "aqt");
    var head = el("div", "aqt-row aqt-head");
    ["Est No.", "Deliverable", "Department", "Focal Point", "Deadline", "Progress", "Due Date", "Actions"].forEach(function (label, i) {
      var cell = el("div", "aqt-cell", label);
      if (i === 3) cell.classList.add("aqt-focal");
      head.appendChild(cell);
    });
    table.appendChild(head);
    items.forEach(function (d) {
      var row = el("div", "aqt-row aqt-body-row");
      row.dataset.sid = String(d.id);
      row.addEventListener("click", function () { openDelivModal(d.id); });

      row.appendChild(el("div", "aqt-cell aqt-ellipsis aqt-est", d.est_no));

      var nameCell = el("div", "aqt-cell aqt-ellipsis aqt-name",
        d.item_no + " &middot; " + d.name + '<span class="aqt-proj"> &#8211; ' + d.project_name + "</span>");
      row.appendChild(nameCell);

      row.appendChild(el("div", "aqt-cell aqt-ellipsis aqt-dept", deptLabel(d.department, d.department_number)));
      row.appendChild(el("div", "aqt-cell aqt-ellipsis aqt-focal", d.owner));
      row.appendChild(el("div", "aqt-cell", deadlineStatusCellHtml(d)));
      row.appendChild(el("div", "aqt-cell", progressStatusCellHtml(d)));
      row.appendChild(el("div", "aqt-cell aqt-ellipsis aqt-due", fmtDate(d.due_date)));

      var authorized = isAssigned(d);
      var actions = el("div", "aqt-cell aqt-actions");
      // Stop the row's own click (which opens the modal) from also firing
      // when a button inside the actions cell is clicked.
      actions.addEventListener("click", function (ev) { ev.stopPropagation(); });
      if (authorized && d.file_url) actions.appendChild(fileLink(d));
      actions.appendChild(followButton(d));
      if (!authorized) {
        actions.appendChild(el("span", "aqt-locked", "Owner/SME only"));
      } else {
        // Item 143 (2nd revision): whole-deliverable Approve/Reject only
        // exists once Mark Completed has been clicked (Pending SME Review)
        // -- per-document review no longer exists.
        if (d.status === "pending_review" && can("review")) {
          var appr = el("button", "btn primary", "Approve");
          appr.addEventListener("click", function () { review(d.id, true, loadAssigned); });
          var rej = el("button", "btn ghost-crit", "Reject");
          rej.addEventListener("click", function () { review(d.id, false, loadAssigned); });
          actions.appendChild(appr); actions.appendChild(rej);
        }
        if (d.deadline_status === "due" && can("remind")) {
          var remindBtn = el("button", "btn ghost-crit", "Send reminder");
          remindBtn.addEventListener("click", async function () {
            try {
              var res = await api("/api/deliverables/bulk-remind", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ submission_ids: [d.id], actor_role: CURRENT_ROLE }),
              });
              showToast(res.sent ? "Reminder sent to " + d.owner : "No owner to remind");
            } catch (err) {
              showToast("Could not send reminder &#8211; " + apiErrorDetail(err), true);
            }
          });
          actions.appendChild(remindBtn);
        }
      }
      row.appendChild(actions);
      table.appendChild(row);
    });
    wrap.appendChild(table);
  }
  function followButton(d) {
    var btn = el("button", "btn" + (d.following ? " primary" : ""), d.following ? "&#9733; Following" : "&#9734; Follow");
    btn.addEventListener("click", async function () {
      // No separate prompt (item 87) — uses the same signed-in identity
      // Ask the Team relies on: acting-email field, else the cached/
      // one-time-prompted email, never asked twice for the same person.
      var email = myIdentity();
      if (!email) return;
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
        showToast("Could not update follow &#8211; " + apiErrorDetail(err), true);
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

  /* ================= BM TRIAGE ================= */
  async function openTriage(projectId) {
    var p = await api("/api/projects/" + projectId);
    document.getElementById("triageTitle").textContent = "Confirm Applicable Deliverables – " + p.est_no.toUpperCase();
    var items = await api("/api/projects/" + projectId + "/deliverables");
    var pending = items.filter(function (d) { return d.status === "pending_triage"; });
    var defaults = {};
    try { defaults = await api("/api/projects/" + projectId + "/triage-defaults"); } catch (e) { /* no BM history yet */ }
    var card = document.getElementById("triageCard");
    card.innerHTML = "";
    var state = {};
    var toggleButtons = []; // {id, appBtn, notBtn} — item 86's bulk action flips all of these
    // Item 171: these two default to Not Required unless the BM explicitly
    // flips them -- everything else still defaults to Applicable. A
    // remembered pick (item 79) from this BM's own past triages always
    // wins over either default.
    var NOT_REQUIRED_BY_DEFAULT = { "5.4": true, "8.4": true };
    if (!pending.length) {
      card.appendChild(el("div", "deliv-row", '<span style="color:var(--ink-500);font-size:12.5px;">Nothing left to triage.</span>'));
    } else {
      // Item 118: one header per Operation Units BU sub-department
      // (TBU/PBU/DBU/BBU), each listing its own 2.1-2.6 run — not one
      // header per row (the original bug, items interleave by item_no
      // since they share department number 2) and not one shared
      // "Operation Units" header for every BU either (item 97, superseded
      // here). Grouped explicitly by full department name so each BU's
      // items land together under their own header regardless of the
      // interleaved item_no order they arrive in.
      var groupLabel = function (dept) { return dept; };
      var groups = {}, groupOrder = [];
      pending.forEach(function (d) {
        var label = groupLabel(d.department);
        if (!groups[label]) { groups[label] = []; groupOrder.push(label); }
        groups[label].push(d);
      });
      groupOrder.forEach(function (label) {
        card.appendChild(el("div", "deliv-subheader", label));
        groups[label].forEach(function (d) { renderTriageRow(d); });
      });
    }
    function renderTriageRow(d) {
        // A remembered pick (item 79) from this BM's past triages pre-selects
        // the toggle — still just a default, they can override it below.
        var remembered = defaults.hasOwnProperty(d.item_no) ? defaults[d.item_no]
          : !NOT_REQUIRED_BY_DEFAULT.hasOwnProperty(d.item_no);
        state[d.id] = remembered;
        var row = el("div", "deliv-row");
        row.appendChild(el("div", "deliv-num", d.item_no));
        var body = el("div", "deliv-body");
        // Which BU this item belongs to is now conveyed by its group
        // header (item 118), so the row name itself doesn't need a
        // "— DBU" suffix tacked on anymore.
        var nameEl = el("div", "deliv-name", d.name);
        nameEl.title = d.name;
        body.appendChild(nameEl);
        row.appendChild(body);
        var toggle = el("div", "triage-toggle");
        var appBtn = el("button", "chip" + (remembered ? " active" : ""), "Applicable");
        var notBtn = el("button", "chip" + (remembered ? "" : " active"), "Not Required");
        appBtn.addEventListener("click", function () {
          state[d.id] = true;
          appBtn.classList.add("active"); notBtn.classList.remove("active");
        });
        notBtn.addEventListener("click", function () {
          state[d.id] = false;
          notBtn.classList.add("active"); appBtn.classList.remove("active");
        });
        toggle.appendChild(appBtn); toggle.appendChild(notBtn);
        row.appendChild(toggle);
        card.appendChild(row);
        toggleButtons.push({ id: d.id, appBtn: appBtn, notBtn: notBtn });
    }
    var markAllBtn = document.getElementById("triageMarkAllNotRequired");
    markAllBtn.hidden = !(can("create") && pending.length);
    markAllBtn.onclick = function () {
      if (!confirm("Mark all " + pending.length + " item(s) as Not Required?")) return;
      toggleButtons.forEach(function (t) {
        state[t.id] = false;
        t.notBtn.classList.add("active"); t.appBtn.classList.remove("active");
      });
    };
    document.getElementById("triageConfirm").onclick = async function () {
      var payloadItems = Object.keys(state).map(function (sid) {
        return { submission_id: Number(sid), applicable: state[sid] };
      });
      try {
        await api("/api/projects/" + projectId + "/triage", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ items: payloadItems, actor_role: CURRENT_ROLE, actor_email: actingEmail() }),
        });
      } catch (err) {
        showToast("Could not save triage &#8211; " + apiErrorDetail(err), true);
        return;
      }
      showToast("Triage confirmed");
      openDetail(projectId);
    };
    switchView("triage");
  }

  // Item 145: if triage on one of MY L0 tenders has sat unstarted for 24h+,
  // block the rest of the app with a non-dismissible modal until it's done.
  // Scoped to a real personal identity only -- never prompts for one just to
  // run this background check (a stale acting-email field or empty identity
  // simply means nothing to check yet, not "block everyone").
  async function checkBmTriageDeadline() {
    var email = passiveIdentity();
    var overlay = document.getElementById("bmTriageBlockOverlay");
    if (!email) { overlay.hidden = true; return; }
    var rows;
    try {
      // actor_role is deliberately never "Admin" here -- this check is about
      // a specific person's own tenders, regardless of which role they
      // currently have selected in the viewer.
      rows = await api("/api/projects/bm-triage-status?actor_role=Owner&actor_email=" + encodeURIComponent(email));
    } catch (e) { return; }
    var now = Date.now();
    var overdue = rows.filter(function (r) {
      return r.status !== "done" && r.created_at && (now - new Date(r.created_at).getTime()) >= 24 * 60 * 60 * 1000;
    });
    if (!overdue.length) { overlay.hidden = true; return; }
    var body = document.getElementById("bmTriageBlockBody");
    body.innerHTML = "";
    overdue.forEach(function (r) {
      var row = el("div", "bmtb-row");
      var main = el("div");
      main.appendChild(el("div", "bmtb-name", r.est_no + " &#8211; " + r.name));
      main.appendChild(el("div", "bmtb-sub", r.pending_count + " deliverable(s) still awaiting your call"));
      row.appendChild(main);
      var btn = el("button", "btn primary", "Complete Triage");
      btn.addEventListener("click", function () { overlay.hidden = true; openTriage(r.id); });
      row.appendChild(btn);
      body.appendChild(row);
    });
    overlay.hidden = false;
  }
  setInterval(checkBmTriageDeadline, 5 * 60 * 1000);

  /* ================= DELIVERABLE DETAIL MODAL ================= */
  document.getElementById("delivModalClose").addEventListener("click", closeDelivModal);
  document.getElementById("delivModalOverlay").addEventListener("click", function (e) {
    if (e.target.id === "delivModalOverlay") closeDelivModal();
  });
  function closeDelivModal() { document.getElementById("delivModalOverlay").hidden = true; }

  /* ================= ITEM 131: INTERACTIVE SYSTEM INTRODUCTION WALKTHROUGH =================
     Portal "screens" below are illustrative recreations built from the app's
     own CSS (pill/fs-step/folder-row/gantt-row look-alikes), not literal
     screenshots -- there's no reliable way to capture and keep real pixel
     screenshots current across redesigns, and these read as authentic since
     they reuse the same visual language as the live UI. */
  var TOUR_STEPS = [
    {
      eyebrow: "Welcome",
      title: "What L0/L1 Actually Is",
      body:
        '<p class="tour-step-text">L0/L1 is Algihaz\'s control system for tracking every department\'s ' +
        "deliverables through a tender (<b>L0</b>) and, once won, through project execution " +
        "(<b>L1</b>) &#8212; who owns what, when it's due, and whether it's been reviewed and approved. " +
        'This walkthrough covers where the system came from, how the two stages work, and ' +
        "how to actually use this portal day to day. Nine short steps &#8212; use Next/Back or the dots below.</p>",
    },
    {
      eyebrow: "The Story So Far",
      title: "Standard L0/L1 Development",
      body:
        '<p class="tour-step-text">Rolled out in stages over roughly a year and a half:</p>' +
        '<ul class="tour-list">' +
        "<li>Developed a new procedure along with a defined scheme</li>" +
        "<li>Engaged key departments for input and collaboration</li>" +
        "<li>Obtained management approvals</li>" +
        "<li>Conducted introduction meetings explaining the process and objectives</li>" +
        "<li>Received and evaluated the quality of early deliverables</li>" +
        "<li>Tracked departments' response against the proposed timeline</li>" +
        "<li><b>Ran a pilot</b> &#8211; NAJRAN BSP, L1 Stage</li>" +
        "<li><b>Launched official operation</b> (Dec 2024)</li>" +
        "</ul>",
    },
    {
      eyebrow: "The Story So Far",
      title: "Where It's Headed",
      body:
        '<p class="tour-step-text"><b>International L0/L1 Development</b> is running in parallel &#8212; ' +
        "analyzing departments' willingness to adapt the new system, market analysis, service " +
        "development, and business intelligence work, so the same control system extends beyond " +
        "the standard rollout. Meanwhile a <b>New L1 Model</b> has been in active development " +
        'since Sep 2025, feeding directly into what this portal runs today.</p>' +
        '<div class="tour-callout">&#128161; This portal is a direct product of that rollout &#8212; ' +
        "the department catalog, milestone structure and due-date rules all trace back to the " +
        "procedure developed during Standard L0/L1 Development.</div>",
    },
    {
      eyebrow: "How It Works · L0",
      title: "Tendering Stage",
      body:
        '<p class="tour-step-text">A tender opens at <b>Announcement (M1)</b>. Site visit, pre-bid meeting, ' +
        "and pre-bid clarification deadlines get announced, and every department (Operations, " +
        "Supply Chain, Engineering, Planning/Cost Control, Contract, HR, Finance, SHEQ, IT, Risk, " +
        "Fleet/FM) prepares its own risk register, execution plan and schedule in parallel. The " +
        "<b>Project Schedule (M3)</b> anchors most department due dates. Technical offers circulate " +
        "once RFQs return (<b>M4</b>), and the tender closes with the <b>Proposal Submitted to " +
        "client (M5)</b>, timed to the Bid Submission Date.</p>" +
        '<div class="mock-fs">' +
        milestoneMock([
          ["M1", "Announced", true], ["M2", "Site Visit", true], ["M3", "Schedule", true],
          ["M4", "Tech Offers", false, true], ["M5", "Proposal", false],
        ]) +
        "</div>",
    },
    {
      eyebrow: "How It Works · L1",
      title: "Execution Stage",
      body:
        '<p class="tour-step-text">Once a tender is awarded, an L1 project starts from the same scope: ' +
        "<b>L1 Announcement (M1)</b>, an <b>Early Mobilization Plan (M2)</b>, then full " +
        "<b>Commercial &amp; Technical Handover (M3)</b> from the tendering team to the project " +
        "team. <b>Post-Bid Clarification (M4)</b> runs until the <b>LOA is received (M5)</b>, and " +
        "the project formally begins execution at <b>Contract Signing (M6)</b> &#8212; the moment " +
        "the platform marks Contract Status as Signed. From there, Planning, Cost Control, Supply " +
        "Chain, Engineering, HSSE and the rest carry the project through execution.</p>" +
        '<div class="mock-fs">' +
        milestoneMock([
          ["M1", "Announced", true], ["M2", "Mobilize", true], ["M3", "Handover", false, true],
          ["M4", "Post-Bid", false], ["M5", "LOA", false], ["M6", "Signed", false],
        ]) +
        "</div>",
    },
    {
      eyebrow: "Around the Portal",
      title: "Dashboard",
      body:
        '<p class="tour-step-text">Your landing page &#8212; the org-wide snapshot of what needs attention ' +
        'right now. Toggle <b>All / My Items</b> at the top to scope everything to just what you ' +
        "own or review.</p>" +
        '<div class="mock-window"><div class="mock-titlebar"><div class="mock-dot-3"></div>' +
        '<div class="mock-dot-3"></div><div class="mock-dot-3"></div><span>Dashboard</span></div>' +
        '<div class="mock-body">' +
        '<div class="mock-stat-row">' +
        statMock("Not Due", "142") + statMock("Pending Review", "18") +
        statMock("Due", "7") + statMock("Active Projects", "24") +
        "</div>" +
        '<div class="tour-callout">&#128072; Click any of these tiles on the real Dashboard to jump ' +
        "straight to that filtered slice of Assigned Deliverables.</div>" +
        "</div></div>",
    },
    {
      eyebrow: "Around the Portal",
      title: "Project Detail — Folders & Deliverables",
      body:
        '<p class="tour-step-text">Open any tender or project and you get its department folders on the ' +
        "left (numbered, same order as the catalog) and that folder's deliverables on the right. " +
        "Click a deliverable row to open its full detail popup &#8212; owner, SME, due date, " +
        "documents, and a complete activity log.</p>" +
        '<div class="mock-window"><div class="mock-titlebar"><div class="mock-dot-3"></div>' +
        '<div class="mock-dot-3"></div><div class="mock-dot-3"></div><span>Est-1800 &middot; Project Detail</span></div>' +
        '<div class="mock-body" style="display:grid;grid-template-columns:1fr 1.4fr;gap:12px;">' +
        '<div class="mock-folder-list">' +
        '<div class="mock-folder-row active"><span>&#128193; 1. Tendering</span><span>60%</span></div>' +
        '<div class="mock-folder-row"><span>&#128193; 2. Operation Units</span><span>20%</span></div>' +
        '<div class="mock-folder-row"><span>&#128193; 5. Planning</span><span>0%</span></div>' +
        '<div class="mock-folder-row"><span>&#128193; 6. Cost Control</span><span>0%</span></div>' +
        "</div>" +
        '<div class="mock-deliv-list">' +
        deliverableMock("1.3", "Announce Pre-bid Meeting", "good", "Completed") +
        deliverableMock("1.7", "Develop Estimate Program", "crit", "Due") +
        deliverableMock("1.9", "Float Materials RFQ", "neutral", "Not Due") +
        deliverableMock("1.5", "Assign Bid Manager", "warn", "Pending Review") +
        "</div></div></div>",
    },
    {
      eyebrow: "Around the Portal",
      title: "Timeline / Gantt",
      body:
        '<p class="tour-step-text">A Gantt view across every active deliverable &#8212; pooled across all ' +
        "projects, or scoped to just one. Filter by department and status; click a bar to open " +
        "that deliverable directly. Milestones get a highlighted outline so they stand out from " +
        "regular deliverables.</p>" +
        '<div class="mock-window"><div class="mock-titlebar"><div class="mock-dot-3"></div>' +
        '<div class="mock-dot-3"></div><div class="mock-dot-3"></div><span>Timeline</span></div>' +
        '<div class="mock-body" style="padding:10px 14px;">' +
        ganttRowMock("1.1 Announcement", 4, 10, "neutral", true) +
        ganttRowMock("1.7 Estimate Program", 8, 34, "crit", false) +
        ganttRowMock("2.4 Risk Register", 22, 26, "warn", false) +
        ganttRowMock("5.3 Project Schedule", 30, 40, "good", true) +
        "</div></div>",
    },
    {
      eyebrow: "You're Ready",
      title: "Finding Your Way Around",
      body:
        '<p class="tour-step-text">Quick reference for the rest of the nav:</p>' +
        '<ul class="tour-list">' +
        "<li><b>Assigned Deliverables</b> &#8212; every deliverable assigned to you, filterable by L0/L1 and status</li>" +
        "<li><b>Announcements</b> &#8212; the full notification log, filterable by type and date</li>" +
        "<li><b>L0 Tenders / L1 Projects</b> &#8212; the full list, each with its own Activity Trail tab</li>" +
        "<li><b>Ask the Team</b> &#8212; a question about a tender, project or deliverable, straight to the admins</li>" +
        "<li><b>Performance / Top Achievers</b> &#8212; on-time-rate tracking by department and by person</li>" +
        "</ul>" +
        '<div class="tour-callout">&#127881; That\'s the full picture &#8212; close this and start ' +
        "exploring, or scroll down for the same content laid out as a reference page.</div>",
    },
  ];

  function statMock(label, value) {
    return '<div class="mock-stat"><div class="label">' + label + '</div><div class="value">' + value + "</div></div>";
  }
  function deliverableMock(itemNo, name, tone, statusLabel) {
    return '<div class="mock-deliv-row"><span><b>' + itemNo + "</b> &middot; " + name + '</span>' +
      '<span class="pill ' + tone + '"><span class="dot"></span>' + statusLabel + "</span></div>";
  }
  function ganttRowMock(label, start, len, tone, milestone) {
    return '<div class="mock-gantt-row"><div class="mock-gantt-label">' + label + '</div>' +
      '<div class="mock-gantt-track"><div class="mock-gantt-bar ' +
      (milestone ? "milestone " : "") + tone + '" style="left:' + start + '%;width:' + len + '%;"></div></div></div>';
  }
  function milestoneMock(steps) {
    return steps.map(function (s) {
      var code = s[0], label = s[1], done = s[2], current = s[3];
      var cls = "fs-step" + (done ? " done" : current ? " current" : "");
      return '<div class="' + cls + '" style="flex:1;"><div class="fs-dot" style="width:26px;height:26px;font-size:9px;">' +
        (done ? "&#10003;" : code) + '</div><div class="fs-label">' + label + "</div></div>";
    }).join("");
  }

  var tourStep = 0;
  function renderTourStep() {
    var s = TOUR_STEPS[tourStep];
    document.getElementById("tourEyebrow").textContent = s.eyebrow;
    document.getElementById("tourTitle").textContent = s.title;
    document.getElementById("tourBody").innerHTML = s.body;
    var dots = document.getElementById("tourDots");
    dots.innerHTML = "";
    TOUR_STEPS.forEach(function (_, i) {
      var d = el("span", "tour-dot" + (i === tourStep ? " active" : i < tourStep ? " done" : ""));
      d.addEventListener("click", function () { tourStep = i; renderTourStep(); });
      dots.appendChild(d);
    });
    document.getElementById("tourPrev").disabled = tourStep === 0;
    document.getElementById("tourNext").textContent = tourStep === TOUR_STEPS.length - 1 ? "Done" : "Next →";
    document.getElementById("tourBody").scrollTop = 0;
  }
  // Item 41: a brand-new user (no completed-walkthrough flag yet) gets this
  // forced open on their very first load and can't back out of it -- no
  // close button, no backdrop dismiss -- until they've actually clicked
  // through to the end. Anyone reopening it later (nav item, or a returning
  // user) gets the normal closable version.
  var tourLocked = false;
  function openTour(forced) {
    tourLocked = !!forced;
    document.getElementById("tourClose").hidden = tourLocked;
    tourStep = 0;
    renderTourStep();
    document.getElementById("tourOverlay").hidden = false;
  }
  function closeTour() { document.getElementById("tourOverlay").hidden = true; }
  document.getElementById("tourStartBtn").addEventListener("click", function () { openTour(false); });
  document.getElementById("tourClose").addEventListener("click", closeTour);
  document.getElementById("tourOverlay").addEventListener("click", function (e) {
    if (e.target.id === "tourOverlay" && !tourLocked) closeTour();
  });
  document.getElementById("tourPrev").addEventListener("click", function () {
    if (tourStep > 0) { tourStep--; renderTourStep(); }
  });
  document.getElementById("tourNext").addEventListener("click", function () {
    if (tourStep < TOUR_STEPS.length - 1) { tourStep++; renderTourStep(); return; }
    if (tourLocked) {
      localStorage.setItem("tourCompletedOnce", "1");
      tourLocked = false;
      document.getElementById("tourClose").hidden = false;
    }
    closeTour();
  });
  async function openDelivModal(submissionId) {
    var qs = passiveIdentity() ? "?actor_email=" + encodeURIComponent(passiveIdentity()) : "";
    var d = await api("/api/deliverables/" + submissionId + qs);
    document.getElementById("delivModalEyebrow").textContent = d.est_no + " – " + deptLabel(d.department, d.department_number);
    document.getElementById("delivModalTitle").textContent = d.item_no + " · " + d.name;
    var authorized = isAssigned({ owner_email: d.owner_email, sme_email: d.sme_email });
    var body = document.getElementById("delivModalBody");
    body.innerHTML = "";

    var meta = el("div", "modal-meta-grid");
    // Item 134 rework: SME is no longer editable from here -- it's set as
    // a catalog default in Focal Points instead, so every new project
    // picks it up automatically rather than being patched one project at
    // a time from this popup.
    [["Owner", d.owner_email || "&#8213;"], ["SME", d.sme_email || "&#8213;"],
     ["Due Date", fmtDate(d.due_date)],
     ["Status", statusPillsHtml(d)]]
      .forEach(function (m) {
        var mi = el("div");
        mi.appendChild(el("div", "mk", m[0]));
        mi.appendChild(el("div", "mv", m[1]));
        meta.appendChild(mi);
      });
    body.appendChild(meta);

    // Item 138: refreshing the modal alone left the deliverables list
    // behind it stale (still showing the pre-action status/buttons) until
    // a manual page reload -- also refresh that list every time.
    var refreshModal = function () { openDelivModal(submissionId); refreshCurrentFolder(); };
    var actionsRow = el("div", "modal-actions-row");
    var shareBtn = el("button", "btn", "Share");
    shareBtn.addEventListener("click", async function () {
      var url = location.origin + location.pathname + "#deliverable=" + d.id;
      if (navigator.share) {
        try { await navigator.share({ title: d.item_no + " - " + d.name, url: url }); return; }
        catch (e) { return; } // user cancelled the native share sheet — no error to show
      }
      try {
        await navigator.clipboard.writeText(url);
        showToast("Link copied to clipboard");
      } catch (e) {
        prompt("Copy this link:", url);
      }
    });
    actionsRow.appendChild(shareBtn);
    actionsRow.appendChild(followButton({ id: d.id, following: d.following }));

    // Item 143 (2nd revision): Upload/Add Document stays available right up
    // until Mark Completed is clicked -- once Pending SME Review, uploads
    // close entirely until the SME confirms or sends it back (no more
    // slipping in new evidence mid-review).
    var canUpload = d.status !== "approved" && d.status !== "pending_review";
    if (authorized && canUpload && can("upload")) {
      actionsRow.appendChild(uploadButton(d.id, refreshModal));
    }

    // Item 143 (2nd revision): Mark Completed -- Owner or SME, comment-only
    // or with any number of documents already uploaded, it makes no
    // difference since there's no more per-document gate to clear first.
    // The endpoint itself decides whether the caller's click finalizes it
    // (SME) or just flags it for the SME's confirmation (Owner).
    var canMarkComplete = d.status === "no_progress" || d.status === "in_progress" || d.status === "rejected";
    if (authorized && canMarkComplete && (can("upload") || can("review"))) {
      actionsRow.appendChild(markCompleteButton(d.id, refreshModal));
    }

    var eligibleStatus = d.status === "no_progress" || d.status === "rejected";
    if (authorized && eligibleStatus && can("upload")) {
      if (CURRENT_ROLE === "Admin") actionsRow.appendChild(markNotRequiredButton(d.id, refreshModal));
      var reassignBtn = el("button", "btn", "Reassign");
      reassignBtn.addEventListener("click", async function () {
        var toEmail = prompt("Reassign " + d.item_no + " to (email):", "");
        if (!toEmail) return;
        toEmail = toEmail.trim();
        if (!toEmail) return;
        var reason = prompt("Reason (optional):", "") || null;
        try {
          await api("/api/deliverables/" + d.id + "/reassign-request", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ to_email: toEmail, reason: reason, from_email: d.owner_email }),
          });
        } catch (err) {
          showToast("Could not request reassignment – " + apiErrorDetail(err), true);
          return;
        }
        showToast("Reassignment requested — pending admin approval");
      });
      actionsRow.appendChild(reassignBtn);
    }

    // Item 143 (2nd revision): the SME's confirm/reject on a completion
    // claim -- the only place a whole-deliverable Approve/Reject exists,
    // reached only via Mark Completed now.
    if (authorized && d.status === "pending_review" && can("review")) {
      var confirmBtn = el("button", "btn primary", "Confirm Completion");
      confirmBtn.addEventListener("click", function () { review(d.id, true, refreshModal); });
      var sendBackBtn = el("button", "btn ghost-crit", "Send Back");
      sendBackBtn.addEventListener("click", function () { review(d.id, false, refreshModal); });
      actionsRow.appendChild(confirmBtn); actionsRow.appendChild(sendBackBtn);
    }

    var isOwnerOrAdmin = CURRENT_ROLE === "Admin" ||
      (actingEmail() && actingEmail().trim().toLowerCase() === (d.owner_email || "").trim().toLowerCase());
    // Item 108: reopening a Not Required item undoes an admin's earlier
    // call, so it's admin-only — symmetric with markNotRequiredButton's
    // own gating, unlike the approved case which the owner can also do.
    var canReopen = (d.status === "approved" && isOwnerOrAdmin) || (d.status === "not_required" && CURRENT_ROLE === "Admin");
    if (canReopen) {
      var reopenBtn = el("button", "btn ghost-crit", "Reopen");
      reopenBtn.addEventListener("click", async function () {
        var confirmMsg = d.status === "not_required"
          ? "Reopen " + d.item_no + "? It'll go back into the normal workflow and need a submission again."
          : "Reopen " + d.item_no + "? It'll go back into the normal workflow for more work.";
        if (!confirm(confirmMsg)) return;
        try {
          await api("/api/deliverables/" + d.id + "/reopen?actor_role=" + encodeURIComponent(CURRENT_ROLE) +
            "&actor_email=" + encodeURIComponent(actingEmail()), { method: "POST" });
        } catch (err) {
          showToast("Could not reopen – " + apiErrorDetail(err), true);
          return;
        }
        showToast(d.item_no + " reopened");
        refreshModal();
      });
      actionsRow.appendChild(reopenBtn);
    }
    body.appendChild(actionsRow);

    // Item 143 (2nd revision): workflow nudges -- a reminder to close out
    // once documents are in, or while waiting on the SME's confirmation.
    if (authorized && d.status === "in_progress") {
      body.appendChild(el("div", "modal-hint", "Mark Completed if no more documents are needed."));
    } else if (authorized && d.status === "pending_review") {
      body.appendChild(el("div", "modal-hint", "Awaiting SME confirmation."));
    }

    // Item 107: the primary upload is already mirrored into the Documents
    // list below (same as any other upload) — a separate "Primary File"
    // link here just duplicated it.
    if (authorized && (d.review_comment || d.completion_note)) {
      body.appendChild(el("div", "deliv-comment", "&#128172; " + (d.review_comment || d.completion_note)));
    }

    body.appendChild(el("div", "modal-section-title", "Documents"));
    if (!authorized) {
      // Item 143 (2nd revision): per-document review no longer exists, so
      // there's no more partial mid-flight visibility -- documents are
      // visible to everyone only once the whole deliverable is Completed,
      // same as item 7's original rule.
      if (d.status === "approved" && d.documents.length) {
        d.documents.forEach(function (doc) {
          var row = el("div", "doc-row");
          var main = el("div", "doc-main");
          var link = el("a", "", doc.file_name);
          link.href = doc.file_url; link.target = "_blank"; link.rel = "noopener";
          main.appendChild(link);
          main.appendChild(el("div", "doc-sub", "Submitted by " + (doc.uploaded_by || "&#8213;")));
          row.appendChild(main);
          body.appendChild(row);
        });
      } else {
        body.appendChild(el("div", "empty-state",
          d.status === "approved" ? "No documents were attached." : "Documents are visible once this deliverable is Completed."));
      }
    } else {
      if (!d.documents.length) body.appendChild(el("div", "empty-state", "No documents yet."));
      d.documents.forEach(function (doc) {
        var row = el("div", "doc-row");
        var main = el("div", "doc-main");
        var link = el("a", "", doc.file_name);
        link.href = doc.file_url; link.target = "_blank"; link.rel = "noopener";
        main.appendChild(link);
        main.appendChild(el("div", "doc-sub", "Submitted by " + (doc.uploaded_by || "&#8213;")));
        row.appendChild(main);
        body.appendChild(row);
      });
      // Item 161: this used to have its own "Upload" button here too, a
      // second control doing the same thing as the actionsRow Upload above
      // (same canUpload gate) but through a different endpoint with a
      // different confirmation message -- confusing since both were
      // labeled identically. One Upload control is enough; the actionsRow
      // button already refreshes this whole modal (including this list)
      // after a successful upload.
    }

    body.appendChild(el("div", "modal-section-title", "Activity"));
    if (!authorized) {
      body.appendChild(el("div", "empty-state", "Owner/SME/Admin only."));
    } else if (!d.history.length) {
      body.appendChild(el("div", "empty-state", "No activity yet."));
    } else {
      d.history.slice().reverse().forEach(function (ev) {
        var row = el("div", "journey-event");
        row.appendChild(el("div", "journey-event-ic", HISTORY_ACTION_ICON[ev.action] || "&#128276;"));
        var main = el("div", "journey-event-main");
        var when = new Date(ev.at).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
        main.appendChild(el("div", "journey-event-top", '<span class="journey-event-time">' + when + "</span>"));
        main.appendChild(el("div", "journey-event-sub",
          ev.action.replace(/_/g, " ") + " by <b>" + (ev.actor || "system") + "</b>" + (ev.note ? " &#8212; " + ev.note : "")));
        row.appendChild(main);
        body.appendChild(row);
      });
    }

    document.getElementById("delivModalOverlay").hidden = false;
  }

  /* ================= PROJECT DETAIL ================= */
  var currentProjectId = null, currentProjectStage = "L0", currentProjectTerminal = false, currentDeptOpen = null;
  async function openDetail(id, highlightSubmissionId) {
    currentProjectId = id;
    // Always land back on Deliverables, not wherever the previously-viewed
    // project's Activity Trail tab happened to leave things (item 96).
    document.querySelectorAll("#dSubTabs .chip").forEach(function (b) { b.classList.toggle("active", b.dataset.tab === "deliverables"); });
    document.getElementById("dDeliverablesPane").style.display = "";
    document.getElementById("dTrailPane").style.display = "none";
    // Item 112: hide the triage banner/pill synchronously, before the
    // await below -- otherwise a just-completed triage's own re-render
    // (openDetail() called right after confirming) briefly shows the
    // previous "Complete Triage" state on screen until the fresh project
    // data comes back and says it's actually done.
    document.getElementById("dTriageBanner").hidden = true;
    document.getElementById("dTriagePill").hidden = true;
    // Item 157: this function makes several sequential API calls before
    // finally switching to the detail view -- previously, if any of them
    // failed (a transient network hiccup, cold-start timeout), the whole
    // thing silently aborted right there with no error shown, leaving the
    // click looking like it just didn't do anything. Now a failure at any
    // point surfaces as a toast instead of a dead end.
    try {
    var p = await api("/api/projects/" + id);
    currentProjectStage = p.stage;
    currentProjectTerminal = (p.stage === "L0" && (p.status === "Submitted" || p.status === "Cancelled")) ||
      (p.stage === "L1" && p.status === "Completed");
    document.getElementById("dTerminalBanner").hidden = !currentProjectTerminal;
    var triageBanner = document.getElementById("dTriageBanner");
    var triagePill = document.getElementById("dTriagePill");
    if (p.stage !== "L0") {
      triageBanner.hidden = true;
      triagePill.hidden = true;
    } else if (p.pending_triage_count > 0) {
      triageBanner.hidden = false;
      document.getElementById("dTriageBannerText").textContent =
        p.pending_triage_count + " deliverable(s) still need a Bid Manager applicable / not-required call.";
      document.getElementById("dTriageBannerBtn").onclick = function () { openTriage(id); };
      triagePill.hidden = false;
      triagePill.className = "pill crit";
      triagePill.innerHTML = '<span class="dot"></span>Triage Pending';
    } else {
      triageBanner.hidden = true;
      triagePill.hidden = false;
      triagePill.className = "pill good";
      triagePill.innerHTML = '<span class="dot"></span>Triage Completed';
    }
    var stageBadge = document.getElementById("dStageBadge");
    stageBadge.textContent = p.stage + " Stage";
    stageBadge.className = "stage-badge " + (p.stage === "L0" ? "l0" : "l1");
    document.getElementById("dTitle").textContent = p.est_no.toUpperCase() + " – " + p.name;
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
          showToast("Could not update status &#8211; " + apiErrorDetail(err), true);
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
      ? [["Bid Manager", p.bid_manager || "&#8213;", "bm"], ["RFX", p.rfx_number || "&#8213;", "rfx"], ["Region", joinList(p.region), "region"], ["Scope", joinList(p.scope), "scope"],
         ["Business Unit", buLabel, "bu"],
         ["Announced", fmtDate(p.announcement_date), "date:announcement_date:Announcement Date"],
         ["Site Visit", fmtDate(p.site_visit_date), "date:site_visit_date:Site Visit Date"],
         ["Pre-Bid Meeting", fmtDate(p.pre_bid_meeting_date), "date:pre_bid_meeting_date:Pre-Bid Meeting Date"],
         ["Pre-Bid Deadline", fmtDate(p.pre_bid_deadline), "date:pre_bid_deadline:Pre-Bid Deadline"],
         // Item 149: BSD is editable like every other anchor date -- extending
         // it recomputes every dependent deliverable's due date the same way
         // any other date-field edit already does (see the shared "date:"
         // handler above and update_project_details's date_changed loop).
         ["Bid Submission Date", fmtDate(p.bsd), "date:bsd:Bid Submission Date"]]
      : [["Bid Manager", p.bid_manager || "&#8213;", "bm"], ["Project Manager", p.project_manager || "&#8213;", "pm"],
         ["Region", joinList(p.region), "region"], ["Scope", joinList(p.scope)], ["Business Unit", buLabel],
         ["Announced", fmtDate(p.announcement_date), "date:announcement_date:Announcement Date"],
         ["Contract Status", p.contract_status === "Signed"
           ? '<span class="pill good"><span class="dot"></span>Signed</span>'
           : (p.contract_status || "&#8213;")]];
    metaItems.forEach(function (m) {
      var mi = el("div", "meta-item");
      mi.appendChild(el("div", "mk", m[0]));
      var mv = el("div", "mv", m[1]);
      var tag = m[2];
      if (tag && can("create") && !currentProjectTerminal) {
        var editLink = el("a", "meta-edit-link", "Edit");
        editLink.href = "#";
        editLink.addEventListener("click", async function (e) {
          e.preventDefault();
          if (tag === "pm") {
            var nextPm = prompt("Project Manager name:", p.project_manager || "");
            if (nextPm === null) return;
            api("/api/projects/" + id + "/project-manager", {
              method: "PATCH", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ project_manager: nextPm.trim() || null }),
            }).then(function () { showToast("Project Manager updated"); openDetail(id); })
              .catch(function (err) { showToast("Could not update &#8211; " + apiErrorDetail(err), true); });
          } else if (tag === "bm") {
            var opts = await getCreateOptions();
            openChecklistEditModal({
              type: "select",
              title: "Edit Bid Manager",
              options: opts.bid_managers,
              selected: p.bid_manager || "",
              onSave: function (nextBm) {
                if (!nextBm) return;
                api("/api/projects/" + id + "/details", {
                  method: "PATCH", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ bid_manager: nextBm, actor_role: CURRENT_ROLE }),
                }).then(function () { closeChecklistEditModal(); showToast("Bid Manager updated"); openDetail(id); })
                  .catch(function (err) { showToast("Could not update &#8211; " + apiErrorDetail(err), true); });
              },
            });
          } else if (tag === "rfx") {
            var nextRfx = prompt("RFX Number:", p.rfx_number || "");
            if (nextRfx === null) return;
            api("/api/projects/" + id + "/details", {
              method: "PATCH", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ rfx_number: nextRfx.trim() || null, actor_role: CURRENT_ROLE }),
            }).then(function () { showToast("RFX updated"); openDetail(id); })
              .catch(function (err) { showToast("Could not update &#8211; " + apiErrorDetail(err), true); });
          } else if (tag === "scope") {
            var sopts = await getCreateOptions();
            openChecklistEditModal({
              eyebrow: "Only allowed before this tender has any real progress — changing it regenerates the deliverable list to match.",
              title: "Edit Scope",
              options: sopts.scopes,
              selected: p.scope || [],
              hasOther: true,
              otherValue: p.scope_other || "",
              onSave: function (scopeArr, scopeOther) {
                if (!scopeArr.length) { showToast("Select at least one Scope", true); return; }
                api("/api/projects/" + id + "/details", {
                  method: "PATCH", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ scope: scopeArr, scope_other: scopeOther || null, actor_role: CURRENT_ROLE }),
                }).then(function () { closeChecklistEditModal(); showToast("Scope updated &#8211; deliverables regenerated"); openDetail(id); })
                  .catch(function (err) { showToast("Could not update &#8211; " + apiErrorDetail(err), true); });
              },
            });
          } else if (tag === "bu") {
            openChecklistEditModal({
              eyebrow: "Only allowed before this tender has any real progress — changing it regenerates the deliverable list to match.",
              title: "Edit Business Unit",
              options: ["TBU", "PBU", "DBU", "BBU", "TBA"],
              selected: p.business_units || [],
              hasOther: false,
              onSave: function (buArr) {
                if (!buArr.length) { showToast("Select at least one Business Unit", true); return; }
                api("/api/projects/" + id + "/details", {
                  method: "PATCH", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ business_units: buArr, actor_role: CURRENT_ROLE }),
                }).then(function () { closeChecklistEditModal(); showToast("Business Unit updated &#8211; deliverables regenerated"); openDetail(id); })
                  .catch(function (err) { showToast("Could not update &#8211; " + apiErrorDetail(err), true); });
              },
            });
          } else if (tag === "region") {
            var ropts = await getCreateOptions();
            var rlist = ropts.regions.map(function (o) { return "&#8226; " + o; }).join("\n");
            var nextRegion = prompt("Region(s) &#8211; comma-separated, choose from:\n\n" + rlist, (p.region || []).join(", "));
            if (nextRegion === null) return;
            var regionArr = nextRegion.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
            if (!regionArr.length) { showToast("Select at least one Region", true); return; }
            var regionOther = p.region_other || "";
            if (regionArr.indexOf("Other") !== -1) {
              var nextOther = prompt("Specify the Other region:", regionOther);
              if (nextOther === null) return;
              regionOther = nextOther.trim();
            }
            api("/api/projects/" + id + "/details", {
              method: "PATCH", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ region: regionArr, region_other: regionOther || null, actor_role: CURRENT_ROLE }),
            }).then(function () { showToast("Region updated"); openDetail(id); })
              .catch(function (err) { showToast("Could not update &#8211; " + apiErrorDetail(err), true); });
          } else if (tag.indexOf("date:") === 0) {
            var parts = tag.split(":");
            var fieldName = parts[1], fieldLabel = parts[2];
            var currentVal = p[fieldName] || "";
            openChecklistEditModal({
              type: "date",
              title: "Edit " + fieldLabel,
              selected: currentVal,
              onSave: function (nextDate) {
                if (!nextDate && fieldName === "announcement_date") { showToast("Announcement Date is required", true); return; }
                var body = { actor_role: CURRENT_ROLE };
                body[fieldName] = nextDate || null;
                api("/api/projects/" + id + "/details", {
                  method: "PATCH", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(body),
                }).then(function () { closeChecklistEditModal(); showToast(fieldLabel + " updated"); openDetail(id); })
                  .catch(function (err) { showToast("Could not update &#8211; " + apiErrorDetail(err), true); });
              },
            });
          }
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

    function makeFolderRow(deptName, isChild) {
      var deptItems = allDelivs.filter(function (d) { return d.department === deptName; });
      var approved = deptItems.filter(function (d) { return d.status === "approved"; }).length;
      var pct = deptItems.length ? Math.round((approved / deptItems.length) * 100) : null;
      var row = el("div", "folder-row" + (isChild ? " folder-row-child" : ""));
      row.dataset.dept = deptName;
      var label = isChild ? deptName.replace(/^.* \(([^)]+)\)$/, "$1") : deptLabel(deptName, deptNumber[deptName]);
      row.innerHTML =
        '<div class="folder-left"><span class="folder-ic">&#128193;</span><div><div class="folder-name">' + label + '</div>' +
        '<div class="folder-focal">Focal: ' + (deptFocal[deptName] || "&#8213;") + '</div></div></div>' +
        '<div class="folder-right"><span class="folder-pct">' + (pct === null ? "&#8213;" : pct + "%") + '</span></div>';
      row.addEventListener("click", function () {
        document.querySelectorAll(".folder-row").forEach(function (r) { r.classList.remove("active"); });
        row.classList.add("active");
        currentDeptOpen = deptName;
        document.getElementById("dDeliverTitle").textContent = deptLabel(deptName, deptNumber[deptName]) + " Deliverables";
        renderDeliverables(deptItems);
      });
      return row;
    }
    // Item 98: departments that share a common base name (e.g. Operation
    // Units' TBU/PBU/DBU/BBU split, all "Operation Units (X)") nest as a
    // group instead of appearing as separate same-numbered top-level rows.
    var groupOrder = [], groups = {};
    deptNames.forEach(function (deptName) {
      var key = (deptName.match(/^(.*) \([^)]+\)$/) || [null, deptName])[1];
      if (!groups[key]) { groups[key] = []; groupOrder.push(key); }
      groups[key].push(deptName);
    });
    var firstRow = true;
    groupOrder.forEach(function (key) {
      var members = groups[key];
      if (members.length === 1) {
        var row = makeFolderRow(members[0], false);
        if (firstRow) { row.classList.add("active"); firstRow = false; }
        folders.appendChild(row);
      } else {
        var groupHead = el("div", "folder-group-head", '<span class="folder-ic">&#128193;</span>' + deptLabel(key, deptNumber[members[0]]));
        folders.appendChild(groupHead);
        members.forEach(function (deptName) {
          var row = makeFolderRow(deptName, true);
          if (firstRow) { row.classList.add("active"); firstRow = false; }
          folders.appendChild(row);
        });
      }
    });
    var highlightItem = highlightSubmissionId
      ? allDelivs.find(function (d) { return d.id === Number(highlightSubmissionId); })
      : null;
    var initialDept = highlightItem ? highlightItem.department : deptNames[0];
    var initialDeptItems = deptNames.length ? allDelivs.filter(function (d) { return d.department === initialDept; }) : [];
    document.getElementById("dDeliverTitle").textContent = deptNames.length ? deptLabel(initialDept, deptNumber[initialDept]) + " Deliverables" : "Deliverables";
    currentDeptOpen = initialDept;
    document.querySelectorAll(".folder-row").forEach(function (r) { r.classList.toggle("active", r.dataset.dept === initialDept); });
    renderDeliverables(initialDeptItems);

    switchView("detail");
    location.hash = "project=" + id; // item 99 — survives a refresh
    if (highlightItem) {
      setTimeout(function () {
        var target = document.querySelector('.deliv-row[data-sid="' + highlightSubmissionId + '"]');
        if (target) {
          target.scrollIntoView({ behavior: "smooth", block: "center" });
          target.classList.add("flash");
          setTimeout(function () { target.classList.remove("flash"); }, 1800);
        }
      }, 50);
    }
    } catch (err) {
      showToast("Could not open this project &#8211; " + apiErrorDetail(err), true);
    }
  }

  // Item 46 (picker rework): a small reusable edit modal covering every
  // real-picker case this project detail page needs -- checkboxes
  // (Scope/Business Unit), a single dropdown (Bid Manager), or a native
  // date input (every anchor date) -- instead of a free-text prompt()
  // for any of them. cfg.type: "checklist" (default) | "select" | "date".
  var _checklistEditSave = null;
  function openChecklistEditModal(cfg) {
    document.getElementById("checklistEditEyebrow").textContent = cfg.eyebrow || "";
    document.getElementById("checklistEditTitle").textContent = cfg.title;
    var grid = document.getElementById("checklistEditGrid");
    var otherInput = document.getElementById("checklistEditOtherInput");
    var selectEl = document.getElementById("checklistEditSelect");
    var dateEl = document.getElementById("checklistEditDateInput");
    grid.style.display = "none";
    otherInput.style.display = "none";
    selectEl.style.display = "none";
    dateEl.style.display = "none";

    if (cfg.type === "select") {
      selectEl.innerHTML = "";
      cfg.options.forEach(function (opt) {
        var o = el("option", "", opt); o.value = opt; selectEl.appendChild(o);
      });
      selectEl.value = cfg.selected || "";
      selectEl.style.display = "";
      _checklistEditSave = function () { cfg.onSave(selectEl.value); };
    } else if (cfg.type === "date") {
      dateEl.value = cfg.selected || "";
      dateEl.style.display = "";
      _checklistEditSave = function () { cfg.onSave(dateEl.value); };
    } else {
      grid.style.display = "";
      grid.innerHTML = "";
      cfg.options.forEach(function (opt) {
        var label = el("label", "scope-opt");
        var cb = el("input"); cb.type = "checkbox"; cb.value = opt;
        cb.checked = cfg.selected.indexOf(opt) !== -1;
        label.appendChild(cb);
        label.appendChild(document.createTextNode(opt));
        grid.appendChild(label);
        if (cfg.hasOther && opt === "Other") {
          cb.addEventListener("change", function () { otherInput.style.display = cb.checked ? "" : "none"; });
        }
      });
      if (cfg.hasOther) {
        otherInput.style.display = cfg.selected.indexOf("Other") !== -1 ? "" : "none";
        otherInput.value = cfg.otherValue || "";
      }
      _checklistEditSave = function () {
        var picked = Array.prototype.slice.call(grid.querySelectorAll("input:checked")).map(function (c) { return c.value; });
        cfg.onSave(picked, otherInput.value.trim());
      };
    }
    document.getElementById("checklistEditOverlay").hidden = false;
  }
  function closeChecklistEditModal() {
    document.getElementById("checklistEditOverlay").hidden = true;
  }
  document.getElementById("checklistEditSave").addEventListener("click", function () { if (_checklistEditSave) _checklistEditSave(); });
  document.getElementById("checklistEditCancel").addEventListener("click", closeChecklistEditModal);
  document.getElementById("checklistEditClose").addEventListener("click", closeChecklistEditModal);

  function renderDeliverables(items) {
    var wrap = document.getElementById("dDeliverables");
    wrap.innerHTML = "";
    document.getElementById("dDeliverCount").textContent = items.length + " item" + (items.length === 1 ? "" : "s");
    if (!items.length) {
      wrap.appendChild(el("div", "deliv-row", '<span style="color:var(--ink-500);font-size:12.5px;">No deliverables catalogued for this department yet.</span>'));
      return;
    }
    var hasSplit = items.some(function (d) { return /\[PBU\]/.test(d.name); }) && items.some(function (d) { return !/\[PBU\]/.test(d.name); });
    var lastSubGroup = null;
    items.forEach(function (d, idx) {
      var subGroup = /\[PBU\]/.test(d.name) ? "PBU" : "Main";
      if (hasSplit && subGroup !== lastSubGroup) {
        wrap.appendChild(el("div", "deliv-subheader", subGroup === "PBU" ? "PBU-Specific Items" : "Main Business Unit"));
        lastSubGroup = subGroup;
      }
      var row = el("div", "deliv-row");
      row.dataset.sid = String(d.id);
      var body = el("div", "deliv-body");
      var nameEl = el("div", "deliv-name", d.name);
      nameEl.title = d.name;
      body.appendChild(nameEl);
      body.appendChild(el("div", "deliv-due", '<span class="deliv-due-date">Due ' + fmtDate(d.due_date) + '</span> ' + statusPillsHtml(d)));
      var authorized = isAssigned(d);
      if (authorized && d.completion_note) {
        body.appendChild(el("div", "deliv-comment", "&#128172; " + d.completion_note));
      }
      body.style.cursor = "pointer";
      body.addEventListener("click", function () { openDelivModal(d.id); });
      row.appendChild(el("div", "deliv-num", d.item_no));
      row.appendChild(body);

      var actions = el("div", "deliv-actions");
      if (!authorized) {
        actions.appendChild(el("span", "locked-note", "Owner/SME only"));
      } else if (currentProjectTerminal) {
        if (d.file_url) actions.appendChild(fileLink(d));
      } else if (d.status === "pending_review") {
        // Item 143 (2nd revision): Mark Completed was clicked -- awaiting
        // the SME's confirm/reject. Uploads close entirely until the SME
        // decides, so only a view link shows here, no Upload button.
        if (d.file_url) actions.appendChild(fileLink(d));
        if (can("review")) {
          var appr = el("button", "btn primary", "Confirm Completion");
          appr.addEventListener("click", function () { review(d.id, true, function () { openDetail(currentProjectId); }); });
          var rej = el("button", "btn ghost-crit", "Send Back");
          rej.addEventListener("click", function () { review(d.id, false, function () { openDetail(currentProjectId); }); });
          actions.appendChild(appr); actions.appendChild(rej);
        } else {
          actions.appendChild(el("span", "locked-note", "Awaiting SME confirmation"));
        }
      } else if (d.status === "no_progress" || d.status === "in_progress" || d.status === "rejected") {
        if (d.file_url) actions.appendChild(fileLink(d));
        if (d.deadline_status === "due" && can("remind")) actions.appendChild(el("button", "btn ghost-crit", "Send reminder"));
        if (can("upload")) { actions.appendChild(uploadButton(d.id)); actions.appendChild(markCompleteButton(d.id)); }
        if (CURRENT_ROLE === "Admin") actions.appendChild(markNotRequiredButton(d.id));
      } else if (d.file_url) {
        actions.appendChild(fileLink(d));
      }
      row.appendChild(actions);
      wrap.appendChild(row);
    });
  }
  // Item 138: a lighter refresh than openDetail() for the project detail
  // deliverables list -- re-fetches and re-renders just the currently-open
  // folder's items, without rebuilding the whole page (which resets
  // currentDeptOpen back to the first folder every time, jarring if the
  // user was looking at a different one). Used as the default post-action
  // refresh for the list's own inline buttons, and also fired alongside
  // the popup's own refresh so status/action changes made there show up
  // here immediately too, instead of needing a manual page reload.
  async function refreshCurrentFolder() {
    if (!currentProjectId || !currentDeptOpen) return;
    var allDelivs = await api("/api/projects/" + currentProjectId + "/deliverables");
    renderDeliverables(allDelivs.filter(function (d) { return d.department === currentDeptOpen; }));
  }
  function fileLink(d) {
    // Item 107: opens the deliverable popup to pick which document to
    // view/download, instead of jumping straight to just the primary file.
    var btn = el("button", "btn", "View Document");
    btn.addEventListener("click", function () { openDelivModal(d.id); });
    return btn;
  }
  function uploadButton(submissionId, after) {
    after = after || refreshCurrentFolder;
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
        showToast("Upload blocked &#8211; " + apiErrorDetail(err), true);
        return;
      }
      showToast("Submitted " + fileInput.files[0].name + " &#8211; SME notified");
      after();
    });
    var span = el("span"); span.appendChild(btn); span.appendChild(fileInput);
    return span;
  }
  function markCompleteButton(submissionId, after) {
    after = after || refreshCurrentFolder;
    var btn = el("button", "btn", "Mark Completed");
    btn.addEventListener("click", async function () {
      var comment = prompt("Describe how this was completed (required — no file to attach):", "");
      if (comment === null) return;
      comment = comment.trim();
      if (!comment) { showToast("A comment is required to mark this complete", true); return; }
      try {
        await api("/api/deliverables/" + submissionId + "/mark-complete", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ comment: comment, actor_name: CURRENT_ROLE + " (pilot)", actor_role: CURRENT_ROLE, actor_email: actingEmail() }),
        });
      } catch (err) {
        showToast("Could not mark complete &#8211; " + apiErrorDetail(err), true);
        return;
      }
      showToast("Marked complete &#8211; SME notified");
      after();
    });
    return btn;
  }
  function markNotRequiredButton(submissionId, after) {
    after = after || refreshCurrentFolder;
    var btn = el("button", "btn ghost-crit", "Mark Not Required");
    btn.addEventListener("click", async function () {
      if (!confirm("Mark this deliverable as Not Required? It won't need a due date or a submission.")) return;
      try {
        await api("/api/deliverables/" + submissionId + "/mark-not-required?actor_role=" + encodeURIComponent(CURRENT_ROLE) +
          "&actor_email=" + encodeURIComponent(actingEmail()), { method: "POST" });
      } catch (err) {
        showToast("Could not mark Not Required &#8211; " + apiErrorDetail(err), true);
        return;
      }
      showToast("Marked Not Required");
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
    // Item 152: optional attachment as part of the decision (e.g. a
    // marked-up file or reference doc) -- native confirm+file-picker,
    // matching this app's existing lightweight prompt()-based quick-action
    // pattern rather than a new custom modal just for this one step.
    var file = null;
    if (confirm("Attach a document to this decision? (optional)")) {
      file = await new Promise(function (resolve) {
        var input = document.createElement("input");
        input.type = "file";
        input.addEventListener("change", function () { resolve(input.files[0] || null); });
        input.click();
      });
    }
    var fd = new FormData();
    fd.append("approved", approved ? "true" : "false");
    fd.append("comment", comment || "");
    fd.append("reviewer_name", CURRENT_ROLE);
    fd.append("actor_role", CURRENT_ROLE);
    fd.append("actor_email", actingEmail());
    if (file) fd.append("file", file);
    try {
      await api("/api/deliverables/" + submissionId + "/review", { method: "POST", body: fd });
    } catch (err) {
      showToast("Review blocked &#8211; " + apiErrorDetail(err), true);
      return;
    }
    showToast(approved ? "Approved &#8211; owner notified" : "Rejected &#8211; owner notified");
    if (after) after();
  }

  /* ================= TIMELINE / GANTT ================= */
  var DEPT_COLORS = {
    1: "#b91c1c", 2: "#f3722c", 3: "#ca8a04", 4: "#65a30d", 5: "#0d9488",
    6: "#0284c7", 7: "#4f46e5", 8: "#7c3aed", 9: "#db2777", 10: "#f472b6",
    11: "#78716c", 12: "#44403c",
  };
  function deptColor(number) { return DEPT_COLORS[number] || "#94a3b8"; }
  var ganttStage = "L0";
  var ganttRowsUnfiltered = [];
  var ganttIsPooled = true;
  document.querySelectorAll("#ganttStageToggle .chip").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll("#ganttStageToggle .chip").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      ganttStage = btn.dataset.stage;
      loadGanttForStage();
    });
  });
  document.getElementById("ganttDeptFilter").addEventListener("change", applyGanttFilters);
  document.getElementById("ganttDeadlineFilter").addEventListener("change", applyGanttFilters);
  document.getElementById("ganttProgressFilter").addEventListener("change", applyGanttFilters);
  document.getElementById("ganttRows").addEventListener("scroll", function () {
    document.getElementById("ganttAxis").style.transform = "translateX(-" + this.scrollLeft + "px)";
  });
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
    document.getElementById("ganttDeadlineFilter").value = "";
    document.getElementById("ganttProgressFilter").value = "";
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

  var ganttCurrentProjectId = null;
  async function renderGanttFor(projectId) {
    ganttIsPooled = !projectId;
    ganttCurrentProjectId = projectId || null;
    ganttRowsUnfiltered = ganttIsPooled
      ? await api("/api/gantt/timeline?stage=" + ganttStage)
      : await api("/api/gantt/projects/" + projectId);

    var deptSel = document.getElementById("ganttDeptFilter");
    var legend = document.getElementById("ganttDeptLegend");
    var seenDepts = {};
    ganttRowsUnfiltered.forEach(function (r) { seenDepts[r.department] = r.department_number; });
    var sortedDeptNames = Object.keys(seenDepts).sort(function (a, b) { return (seenDepts[a] || 0) - (seenDepts[b] || 0); });
    deptSel.innerHTML = '<option value="">All Departments</option>';
    sortedDeptNames.forEach(function (name) {
      var o = el("option", "", deptLabel(name, seenDepts[name])); o.value = name;
      deptSel.appendChild(o);
    });
    legend.innerHTML = "";
    sortedDeptNames.forEach(function (name) {
      var lg = el("span", "lg");
      lg.innerHTML = '<span class="sw" style="background:' + deptColor(seenDepts[name]) + '"></span>';
      lg.appendChild(document.createTextNode(deptLabel(name, seenDepts[name])));
      legend.appendChild(lg);
    });
    legend.className = "ann-type-key gantt-dept-legend";
    legend.style.display = ganttIsPooled ? "" : "none";

    applyGanttFilters();
  }

  function applyGanttFilters() {
    var dept = document.getElementById("ganttDeptFilter").value;
    var deadline = document.getElementById("ganttDeadlineFilter").value;
    var progress = document.getElementById("ganttProgressFilter").value;
    var rows = ganttRowsUnfiltered.filter(function (r) {
      return (!dept || r.department === dept) && (!deadline || r.deadline_status === deadline) && (!progress || r.status === progress);
    });
    drawGanttRows(rows, ganttIsPooled);
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
    var totalDays = Math.max(1, Math.round((max - min) / DAY));
    var PX_PER_DAY = 30;
    var trackWidthPx = Math.max(500, totalDays * PX_PER_DAY);
    function px(t) { return ((t - min) / DAY) * PX_PER_DAY; }

    // Year row
    var yearRow = el("div", "gantt-axis-row year");
    var yc = new Date(min); yc.setHours(0, 0, 0, 0); yc.setMonth(0, 1);
    while (yc.getTime() <= max) {
      var ySegStart = Math.max(yc.getTime(), min);
      var yNext = new Date(yc.getFullYear() + 1, 0, 1).getTime();
      var ySegEnd = Math.min(yNext, max);
      if (ySegEnd > ySegStart) {
        var ySeg = el("span", "", String(yc.getFullYear()));
        ySeg.style.width = (px(ySegEnd) - px(ySegStart)) + "px";
        yearRow.appendChild(ySeg);
      }
      yc = new Date(yc.getFullYear() + 1, 0, 1);
    }
    yearRow.style.width = trackWidthPx + "px";
    axis.appendChild(yearRow);

    // Month row
    var monthRow = el("div", "gantt-axis-row month");
    var cur = new Date(min); cur.setHours(0, 0, 0, 0); cur.setDate(1);
    while (cur.getTime() <= max) {
      var segStart = Math.max(cur.getTime(), min);
      var next = new Date(cur.getFullYear(), cur.getMonth() + 1, 1).getTime();
      var segEnd = Math.min(next, max);
      if (segEnd > segStart) {
        var seg = el("span", "", cur.toLocaleDateString("en-GB", { month: "short" }));
        seg.style.width = (px(segEnd) - px(segStart)) + "px";
        monthRow.appendChild(seg);
      }
      cur = new Date(cur.getFullYear(), cur.getMonth() + 1, 1);
    }
    monthRow.style.width = trackWidthPx + "px";
    axis.appendChild(monthRow);

    // Day row
    var dayRow = el("div", "gantt-axis-row day");
    for (var d = min; d < max; d += DAY) {
      var dSeg = el("span", "", String(new Date(d).getDate()));
      dSeg.style.width = PX_PER_DAY + "px";
      dayRow.appendChild(dSeg);
    }
    dayRow.style.width = trackWidthPx + "px";
    axis.appendChild(dayRow);

    // Gridlines overlay (month boundaries + week ticks + today marker), aligned under the track area.
    var gridlines = el("div", "gantt-gridlines");
    gridlines.style.width = trackWidthPx + "px";
    var monthCur = new Date(min); monthCur.setHours(0, 0, 0, 0); monthCur.setDate(1);
    monthCur = new Date(monthCur.getFullYear(), monthCur.getMonth() + 1, 1);
    while (monthCur.getTime() < max) {
      var mLine = el("div", "gantt-gridline month");
      mLine.style.left = px(monthCur.getTime()) + "px";
      gridlines.appendChild(mLine);
      monthCur = new Date(monthCur.getFullYear(), monthCur.getMonth() + 1, 1);
    }
    for (var w = min + DAY; w < max; w += DAY) {
      var wLine = el("div", "gantt-gridline week");
      wLine.style.left = px(w) + "px";
      gridlines.appendChild(wLine);
    }
    var today = new Date(); today.setHours(0, 0, 0, 0);
    if (today.getTime() >= min && today.getTime() < max) {
      var tLine = el("div", "gantt-gridline today");
      tLine.style.left = px(today.getTime()) + "px";
      tLine.title = "Data Date: " + fmtDate(today.toISOString().slice(0, 10));
      var tLabel = el("div", "gantt-today-label", "Today");
      tLabel.style.left = px(today.getTime()) + "px";
      gridlines.appendChild(tLine);
      gridlines.appendChild(tLabel);
    }
    wrap.appendChild(gridlines);

    rows.forEach(function (r) {
      var s = new Date(r.start + "T00:00:00").getTime();
      var e = new Date(r.end + "T00:00:00").getTime() + DAY;
      var leftPx = px(s);
      var widthPx = Math.max(4, px(e) - px(s));
      var row = el("div", "gantt-row");
      var labelHtml = isPooled
        ? "<b>" + r.item_no + "</b> &middot; " + r.short_name + '<span class="gantt-est-tag">' + r.est_no + "</span>"
        : "<b>" + r.item_no + "</b> &middot; " + r.short_name;
      var label = el("div", "gantt-label", labelHtml);
      label.title = r.name;
      row.appendChild(label);
      var track = el("div", "gantt-track");
      track.style.width = trackWidthPx + "px";
      var bar;
      if (isPooled) {
        bar = el("div", "gantt-bar" + (r.is_milestone ? " milestone" : ""));
        bar.style.background = deptColor(r.department_number);
      } else {
        // Item 143 (2nd revision): rejected is its own worth-flagging red;
        // everything else colors by the live Deadline collapse (matches
        // the matrix) since that's what a schedule view is really about.
        var barCls = r.status === "rejected" ? "crit" : (MATRIX_BUCKET_META[r.status === "approved" ? "completed" : r.deadline_status] || ["neutral"])[0];
        bar = el("div", "gantt-bar " + barCls + (r.is_milestone ? " milestone" : ""));
      }
      bar.style.left = leftPx + "px";
      bar.style.width = widthPx + "px";
      var statusLabel = (STATUS_META[r.status] || ["", r.status])[1];
      bar.title = (isPooled ? r.department + " &#8211; " + statusLabel + " &#8211; " : "") +
        fmtDate(r.start) + " " + String.fromCharCode(8594) + " " + fmtDate(r.end);
      track.appendChild(bar);
      row.appendChild(track);
      if (r.submission_id) {
        row.style.cursor = "pointer";
        // Item 92: opens straight to the deliverable popup instead of
        // redirecting to project detail first.
        row.addEventListener("click", function () { openDelivModal(r.submission_id); });
      }
      wrap.appendChild(row);
    });
    gridlines.style.height = wrap.scrollHeight + "px";
  }

  /* ================= PERFORMANCE / REPORTS ================= */
  var perfTriageStage = "L0";
  async function loadPerformance() {
    var d = await api("/api/dashboard");
    renderDeptGrid(document.getElementById("perfDeptGrid"), d.departments, true);
    // Item 117: only admins get the "Manage Tracking" sub-tab; everyone
    // else just sees the Overview scores.
    document.getElementById("perfTriageTabBtn").hidden = !can("create");
    if (!can("create") && document.getElementById("perfTriagePane").hidden === false) {
      document.querySelectorAll("#perfSubTabs .chip").forEach(function (b) { b.classList.toggle("active", b.dataset.pane === "overview"); });
      document.getElementById("perfOverviewPane").hidden = false;
      document.getElementById("perfTriagePane").hidden = true;
    }
  }
  document.querySelectorAll("#perfSubTabs .chip").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll("#perfSubTabs .chip").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      var pane = btn.dataset.pane;
      document.getElementById("perfOverviewPane").hidden = pane !== "overview";
      document.getElementById("perfTriagePane").hidden = pane !== "triage";
      if (pane === "triage") loadPerfTriage();
    });
  });
  document.querySelectorAll("#perfTriageStageToggle .chip").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll("#perfTriageStageToggle .chip").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      perfTriageStage = btn.dataset.stage;
      loadPerfTriage();
    });
  });
  async function loadPerfTriage() {
    var rows = await api("/api/departments/performance-triage?stage=" + perfTriageStage);
    var tbody = document.getElementById("perfTriageBody");
    tbody.innerHTML = "";
    rows.forEach(function (r) {
      var tr = el("tr");
      tr.appendChild(el("td", "num", r.item_no));
      tr.appendChild(el("td", "", r.name + (r.is_milestone ? ' <span class="gantt-est-tag">Milestone</span>' : "")));
      tr.appendChild(el("td", "", r.department));
      var tdToggle = el("td");
      var toggleBtn = el("button", "chip" + (r.kpi_relevant ? " active" : ""), r.kpi_relevant ? "On" : "Off");
      if (r.is_milestone) {
        toggleBtn.disabled = true;
        toggleBtn.title = "Milestones always count — they anchor the due-date chain.";
      } else {
        toggleBtn.addEventListener("click", async function () {
          var next = !r.kpi_relevant;
          try {
            await api("/api/departments/performance-triage/" + r.id, {
              method: "PATCH", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ kpi_relevant: next }),
            });
          } catch (err) {
            showToast("Could not update &#8211; " + apiErrorDetail(err), true);
            return;
          }
          r.kpi_relevant = next;
          toggleBtn.textContent = next ? "On" : "Off";
          toggleBtn.classList.toggle("active", next);
        });
      }
      tdToggle.appendChild(toggleBtn);
      tr.appendChild(tdToggle);
      tbody.appendChild(tr);
    });
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
  async function loadJourney() {
    // Item 131 rework: the tab has no reference page of its own anymore --
    // opens straight into the walkthrough. Fallback content (just the
    // reopen button) stays underneath for when the modal is closed.
    openTour();
  }

  /* ================= ACTIVITY TRAIL (L0 Tenders / L1 Projects tab) ================= */
  var HISTORY_ACTION_ICON = {
    submitted: "&#128228;", assigned: "&#128100;", review_requested: "&#128269;",
    approved: "&#9989;", rejected: "&#10060;", unlocked: "&#128275;",
    document_added: "&#128206;", document_approved: "&#9989;", document_rejected: "&#10060;",
    reopened: "&#128257;", auto_done: "&#9989;",
  };
  async function renderActivityTimeline(projectId, timelineId) {
    var wrap = document.getElementById(timelineId);
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
  // Item 96: Activity Trail lives inside the project detail page itself now,
  // as a sub-tab next to Deliverables, instead of a picker on the L0/L1 list.
  document.querySelectorAll("#dSubTabs .chip").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll("#dSubTabs .chip").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      var isTrail = btn.dataset.tab === "trail";
      // The stepper only ever applies to L1 projects (see openDetail) — don't
      // let switching back from the trail tab resurrect it for an L0 tender.
      document.getElementById("dStepperCard").style.display = (isTrail || currentProjectStage !== "L1") ? "none" : "";
      document.getElementById("dDeliverablesPane").style.display = isTrail ? "none" : "";
      document.getElementById("dTrailPane").style.display = isTrail ? "" : "none";
      if (isTrail) renderActivityTimeline(currentProjectId, "dTrailTimeline");
    });
  });

  /* ================= SCORES (admin full leaderboard) ================= */
  var scoresData = { owners: [], smes: [] };
  async function loadScores() {
    scoresData = await api("/api/dashboard/top-achievers");
    var deptSel = document.getElementById("scoresDeptFilter");
    if (!deptSel.dataset.loaded) {
      var depts = await api("/api/departments");
      depts.forEach(function (dep) {
        var opt = document.createElement("option");
        opt.value = dep.name; opt.textContent = deptLabel(dep.name, dep.number);
        deptSel.appendChild(opt);
      });
      deptSel.dataset.loaded = "1";
    }
    renderScores();
  }
  function renderScores() {
    var q = document.getElementById("scoresSearch").value.trim().toLowerCase();
    var dept = document.getElementById("scoresDeptFilter").value;
    var sort = document.getElementById("scoresSort").value;
    function filterSort(rows, kind) {
      var filtered = rows.filter(function (r) {
        if (dept && r.department !== dept) return false;
        if (q && ((r.name || "") + " " + r.email).toLowerCase().indexOf(q) === -1) return false;
        return true;
      });
      filtered = filtered.slice();
      if (sort === "name") {
        filtered.sort(function (a, b) { return (a.name || a.email).localeCompare(b.name || b.email); });
      } else if (sort === "pct_desc") {
        filtered.sort(function (a, b) { return kind === "sme" ? a.avg_seconds - b.avg_seconds : b.pct - a.pct; });
      } else if (sort === "total_desc") {
        filtered.sort(function (a, b) {
          return (kind === "sme" ? b.reviewed - a.reviewed : b.total - a.total);
        });
      }
      return filtered;
    }
    renderAchievers("scoresOwners", filterSort(scoresData.owners || [], "owner"), "owner");
    renderAchievers("scoresSmes", filterSort(scoresData.smes || [], "sme"), "sme");
  }
  document.getElementById("scoresSearch").addEventListener("input", renderScores);
  document.getElementById("scoresDeptFilter").addEventListener("change", renderScores);
  document.getElementById("scoresSort").addEventListener("change", renderScores);

  /* ================= FOCAL POINTS (admin) ================= */
  var fpTab = "L0";
  document.querySelectorAll("#fpSubTabs .chip").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll("#fpSubTabs .chip").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      fpTab = btn.dataset.fp;
      loadFocalPoints();
    });
  });

  async function loadFocalPoints() {
    document.getElementById("fpDeliverablePanel").hidden = (fpTab !== "L0" && fpTab !== "L1");
    document.getElementById("fpBmPanel").hidden = fpTab !== "bm";
    document.getElementById("fpGroupPanel").hidden = fpTab !== "group";
    if (fpTab === "L0" || fpTab === "L1") return loadFocalDeliverables(fpTab);
    if (fpTab === "bm") return loadBidManagers();
    return loadSystemGroup();
  }

  async function loadFocalDeliverables(stage) {
    var rows = await api("/api/departments/deliverable-focal?stage=" + stage);
    var tbody = document.getElementById("focalPointsBody");
    tbody.innerHTML = "";
    var lastDept = null;
    rows.forEach(function (d) {
      if (d.department !== lastDept) {
        var hr = el("tr");
        var hc = el("td", "matrix-dept-row", deptLabel(d.department, d.department_number));
        hc.setAttribute("colspan", "6");
        hr.appendChild(hc);
        tbody.appendChild(hr);
        lastDept = d.department;
      }
      var tr = el("tr");
      tr.appendChild(el("td", "", d.item_no));
      var nameCell = el("td", "fp-deliv-name", d.name);
      nameCell.title = d.name; // item 135: column is narrowed with ellipsis, full text on hover
      tr.appendChild(nameCell);
      tr.appendChild(el("td", "", d.department));
      // Item 134 rework: SME is editable here for every row including
      // Tendering (unlike focal point name/email, which Tendering always
      // routes to that project's own Bid Manager instead) -- no per-project
      // popup edit anymore, this catalog default is the one place for it.
      var smeInput = el("input"); smeInput.type = "text";
      smeInput.value = d.default_sme_email || ""; smeInput.placeholder = "sme@algihaz.com";
      if (d.is_tendering_bm) {
        var noteCell = el("td", "muted", "Defaults to the project's Bid Manager");
        tr.appendChild(noteCell);
      } else {
        var emailInput = el("input"); emailInput.type = "text";
        emailInput.value = d.focal_point_email || ""; emailInput.placeholder = d.department_focal_email || "email@algihaz.com";
        var tdEmail = el("td"); tdEmail.appendChild(emailInput);
        tr.appendChild(tdEmail);
      }
      var tdSme = el("td"); tdSme.appendChild(smeInput);
      tr.appendChild(tdSme);
      var saveBtn = el("button", "btn", "Save");
      saveBtn.addEventListener("click", async function () {
        var body = { default_sme_email: smeInput.value.trim() };
        if (!d.is_tendering_bm) {
          body.focal_point_email = emailInput.value.trim();
        }
        try {
          await api("/api/departments/deliverable-focal/" + d.id, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
        } catch (err) {
          showToast("Could not save &#8211; " + apiErrorDetail(err), true);
          return;
        }
        showToast("Updated for " + d.item_no);
      });
      var tdSave = el("td"); tdSave.appendChild(saveBtn);
      tr.appendChild(tdSave);
      tbody.appendChild(tr);
    });
  }

  async function loadBidManagers() {
    var bms = await api("/api/departments/bid-managers");
    var tbody = document.getElementById("bmBody");
    tbody.innerHTML = "";
    bms.filter(function (b) { return b.active; }).forEach(function (b) {
      var tr = el("tr");
      var nameInput = el("input"); nameInput.setAttribute("type", "text"); nameInput.value = b.name || ""; nameInput.placeholder = "Name";
      var saveBtn = el("button", "btn", "Save");
      saveBtn.addEventListener("click", async function () {
        try {
          await api("/api/departments/bid-managers/" + b.id, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: nameInput.value.trim() }),
          });
        } catch (err) {
          showToast("Could not save &#8211; " + apiErrorDetail(err), true);
          return;
        }
        showToast("Updated " + b.email);
      });
      var tdName = el("td"); tdName.appendChild(nameInput);
      tr.appendChild(tdName);
      tr.appendChild(el("td", "", b.email));
      var removeBtn = el("button", "btn ghost-crit", "Remove");
      removeBtn.addEventListener("click", async function () {
        await api("/api/departments/bid-managers/" + b.id, { method: "DELETE" });
        showToast("Removed " + b.email + " from the Bid Manager roster");
        loadBidManagers();
      });
      var tdActions = el("td"); tdActions.appendChild(saveBtn); tdActions.appendChild(removeBtn);
      tr.appendChild(tdActions);
      tbody.appendChild(tr);
    });
    document.getElementById("bmAddBtn").onclick = async function () {
      var email = document.getElementById("bmNewEmail").value.trim();
      var name = document.getElementById("bmNewName").value.trim();
      if (!email) { showToast("Email is required", true); return; }
      try {
        await api("/api/departments/bid-managers", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: email, name: name || null }),
        });
      } catch (err) {
        showToast("Could not add &#8211; " + apiErrorDetail(err), true);
        return;
      }
      document.getElementById("bmNewEmail").value = "";
      document.getElementById("bmNewName").value = "";
      showToast("Bid Manager added");
      loadBidManagers();
    };
  }

  async function loadSystemGroup() {
    var users = await api("/api/departments/users");
    var tbody = document.getElementById("groupBody");
    tbody.innerHTML = "";
    users.forEach(function (u) {
      var tr = el("tr");
      tr.appendChild(el("td", "", u.name));
      tr.appendChild(el("td", "", u.email));
      tr.appendChild(el("td", "", u.role));
      tr.appendChild(el("td", "", u.manager_email || "&#8213;"));
      var removeBtn = el("button", "btn ghost-crit", "Remove");
      removeBtn.addEventListener("click", async function () {
        await api("/api/departments/users/" + u.id, { method: "DELETE" });
        showToast("Removed " + u.email + " from the group");
        loadSystemGroup();
      });
      var tdRemove = el("td"); tdRemove.appendChild(removeBtn);
      tr.appendChild(tdRemove);
      tbody.appendChild(tr);
    });
    document.getElementById("groupAddBtn").onclick = async function () {
      var name = document.getElementById("groupNewName").value.trim();
      var email = document.getElementById("groupNewEmail").value.trim();
      var role = document.getElementById("groupNewRole").value;
      var managerEmail = document.getElementById("groupNewManager").value.trim();
      if (!name || !email) { showToast("Name and email are required", true); return; }
      try {
        await api("/api/departments/users", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: name, email: email, role: role, manager_email: managerEmail || null }),
        });
      } catch (err) {
        showToast("Could not add &#8211; " + apiErrorDetail(err), true);
        return;
      }
      document.getElementById("groupNewName").value = "";
      document.getElementById("groupNewEmail").value = "";
      document.getElementById("groupNewManager").value = "";
      showToast("Added to the L0-L1 Group");
      loadSystemGroup();
    };
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
    var focalSel = document.getElementById("fuFocalFilter");
    var seenDepts = {}, seenEsts = {}, seenFocals = {};
    items.forEach(function (d) { seenDepts[d.department] = true; seenEsts[d.est_no] = true; if (d.focal) seenFocals[d.focal] = true; });
    deptSel.innerHTML = '<option value="">All Departments</option>';
    Object.keys(seenDepts).sort().forEach(function (n) { var o = el("option", "", n); o.value = n; deptSel.appendChild(o); });
    estSel.innerHTML = '<option value="">All Est Numbers</option>';
    Object.keys(seenEsts).sort().forEach(function (n) { var o = el("option", "", n); o.value = n; estSel.appendChild(o); });
    focalSel.innerHTML = '<option value="">All Focal Points</option>';
    Object.keys(seenFocals).sort().forEach(function (n) { var o = el("option", "", n); o.value = n; focalSel.appendChild(o); });

    function renderFollowUpList() {
      var dept = deptSel.value, estNo = estSel.value, focal = focalSel.value;
      var filtered = items.filter(function (d) {
        return (!dept || d.department === dept) && (!estNo || d.est_no === estNo) && (!focal || d.focal === focal);
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
          '<span>Focal: ' + d.focal + '</span><span class="sep">&middot;</span>' +
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
          body: JSON.stringify({
            submission_ids: ids, actor_role: CURRENT_ROLE,
            message: document.getElementById("fuMessage").value.trim() || null,
            cc_manager: document.getElementById("fuCcManager").checked,
          }),
        });
        showToast("Sent " + res.sent + " reminder(s)");
      };
    }
    deptSel.onchange = renderFollowUpList;
    estSel.onchange = renderFollowUpList;
    focalSel.onchange = renderFollowUpList;
    renderFollowUpList();
  }

  /* ================= BM TRIAGE STATUS (admin) ================= */
  var BM_TRIAGE_STATUS_META = {
    done: ["good", "Done"], reminded: ["warn", "Reminded"], pending: ["crit", "Pending"],
  };
  async function loadBmTriageStatus() {
    // Item 110: a Bid Manager (not just Admin) can load this, but the
    // backend scopes the rows to just their own tenders when non-admin.
    var rows = await api("/api/projects/bm-triage-status?actor_role=" + CURRENT_ROLE +
      "&actor_email=" + encodeURIComponent(actingEmail()));
    document.getElementById("bmTriageSub").textContent = can("create")
      ? "Every active L0 tender's Bid Manager triage progress — pending, reminded, or done."
      : "Your own active L0 tenders' triage progress — pending, reminded, or done.";
    var tbody = document.getElementById("bmTriageBody");
    tbody.innerHTML = "";
    if (!rows.length) {
      var tr = el("tr");
      var td = el("td", "", "No active L0 tenders right now.");
      td.setAttribute("colspan", "6");
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    rows.forEach(function (r) {
      var tr = el("tr");
      tr.appendChild(el("td", "", r.est_no));
      tr.appendChild(el("td", "", '<span class="proj-name">' + r.name + '</span>'));
      tr.appendChild(el("td", "", r.bid_manager || "&#8213;"));
      tr.appendChild(el("td", "", r.total_count ? (r.total_count - r.pending_count) + " / " + r.total_count : "&#8213;"));
      var sm = BM_TRIAGE_STATUS_META[r.status] || ["neutral", r.status];
      tr.appendChild(el("td", "", '<span class="pill ' + sm[0] + '"><span class="dot"></span>' + sm[1] + "</span>"));
      var tdAction = el("td");
      if (r.status !== "done" && can("create")) {
        var remindBtn = el("button", "btn", r.status === "reminded" ? "Remind Again" : "Remind BM");
        remindBtn.addEventListener("click", async function () {
          try {
            await api("/api/projects/" + r.id + "/triage-reminder?actor_role=" + CURRENT_ROLE, { method: "POST" });
          } catch (err) {
            showToast("Could not send reminder &#8211; " + apiErrorDetail(err), true);
            return;
          }
          showToast("Reminder sent to " + (r.bid_manager || "the Bid Manager"));
          loadBmTriageStatus();
        });
        tdAction.appendChild(remindBtn);
      }
      tr.appendChild(tdAction);
      tbody.appendChild(tr);
    });
  }

  /* ================= ASK THE TEAM ================= */
  // Item 146: read-only identity lookup -- acting-email field, else the
  // cached prompted email, never a fresh prompt. Anything that just needs
  // to know "who (if anyone) is already known" -- e.g. deciding whether a
  // deliverable should show as Followed -- must use this, not actingEmail()
  // alone, or it silently disagrees with myIdentity() (used by the actual
  // Follow toggle) any time someone follows via a cached identity with the
  // acting-email field left blank: the toggle records it under the cached
  // email, but a bare actingEmail() check for "am I following this" comes
  // back empty and always renders "Follow" again on the next open.
  function passiveIdentity() {
    return (actingEmail() || localStorage.getItem("myEmail") || "").trim();
  }
  /* Identity for "Ask the Team" (item 77): reuses the acting-email field
     that's already how this pilot tracks "who's doing this" everywhere else
     (no real login exists) — falls back to a one-time prompt cached in
     localStorage, so the asker is never made to type it twice.
  */
  function myIdentity() {
    var known = passiveIdentity();
    if (known) return known;
    var entered = (prompt("Your email, so the team knows who's asking:") || "").trim();
    if (entered) localStorage.setItem("myEmail", entered);
    return entered;
  }

  async function _populateSupEstNo() {
    var stage = document.getElementById("supStage").value;
    var projects = await api("/api/projects" + (stage ? "?stage=" + stage : ""));
    var sel = document.getElementById("supEstNo");
    sel.innerHTML = '<option value="">Not specific to a tender/project</option>';
    projects.forEach(function (p) {
      var opt = document.createElement("option");
      opt.value = p.id; opt.textContent = p.est_no + " — " + p.name;
      sel.appendChild(opt);
    });
    _populateSupDeliverable();
  }
  async function _populateSupDeliverable() {
    var sel = document.getElementById("supDeliverable");
    sel.innerHTML = '<option value="">Not specific to a deliverable</option>';
    var pid = document.getElementById("supEstNo").value;
    if (!pid) return;
    var delivs = await api("/api/projects/" + pid + "/deliverables");
    delivs.forEach(function (d) {
      var opt = document.createElement("option");
      opt.value = d.item_no + " " + d.name; opt.textContent = d.item_no + " · " + d.name;
      sel.appendChild(opt);
    });
  }
  document.getElementById("supStage").addEventListener("change", _populateSupEstNo);
  document.getElementById("supEstNo").addEventListener("change", _populateSupDeliverable);

  // Item 37: "Direct to" picker, populated with real SMEs from the roster
  // (item 75's role field) so the asker can address a specific person
  // instead of just Admins generally.
  async function _populateSupTarget() {
    var sel = document.getElementById("supTarget");
    if (sel.dataset.loaded) return;
    sel.dataset.loaded = "1";
    try {
      var users = await api("/api/departments/users");
      users.filter(function (u) { return u.role === "SME"; }).forEach(function (u) {
        var opt = el("option", "", (u.name ? u.name + " " : "") + "&#8211; " + u.email);
        opt.value = u.email;
        sel.appendChild(opt);
      });
    } catch (e) { /* roster lookup is a nice-to-have, not required to submit */ }
  }

  document.getElementById("supSubmit").addEventListener("click", async function () {
    var email = myIdentity();
    var message = document.getElementById("supMessage").value.trim();
    var errors = [];
    if (!email) errors.push("An email is required to send this");
    if (!message) errors.push("Message is required");
    if (errors.length) { showToast(errors.join("<br>"), true); return; }
    var estSel = document.getElementById("supEstNo");
    var payload = {
      name: null,
      email: email,
      stage: document.getElementById("supStage").value || null,
      est_no: estSel.value ? estSel.options[estSel.selectedIndex].textContent.split(" — ")[0] : null,
      deliverable: document.getElementById("supDeliverable").value || null,
      target_email: document.getElementById("supTarget").value || null,
      message: message,
    };
    try {
      var users = await api("/api/departments/users");
      var me = users.find(function (u) { return u.email.toLowerCase() === email.toLowerCase(); });
      if (me) payload.name = me.name;
    } catch (e) { /* roster lookup is a nice-to-have, not required to submit */ }
    try {
      await api("/api/support", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (err) {
      showToast("Could not send &#8211; " + apiErrorDetail(err), true);
      return;
    }
    showToast(payload.target_email ? "Sent, directed to " + payload.target_email : "Sent to the admins &#8211; they'll follow up by email");
    document.getElementById("supMessage").value = "";
    document.getElementById("supStage").value = "";
    document.getElementById("supTarget").value = "";
    _populateSupEstNo();
    loadSupport();
  });

  function _renderSupportThread(container, r, opts) {
    container.innerHTML = "";
    // Item 37: surface who this was really directed to (a specific SME, or
    // Admins generally) so whoever's handling it knows to loop them in.
    var context = ["To: " + (r.target_email || "Admins"), r.stage, r.est_no, r.deliverable].filter(Boolean).join(" &middot; ");
    var row = el("div", "aq-row");
    var main = el("div", "aq-main");
    main.appendChild(el("div", "aq-title", r.name || r.email));
    main.appendChild(el("div", "aq-sub",
      '<span>' + r.email + '</span>' + (context ? '<span class="sep">&middot;</span><span>' + context + "</span>" : "")));
    main.appendChild(el("div", "deliv-comment", r.message));
    (r.messages || []).forEach(function (m) {
      var mrow = el("div", "deliv-comment", "<b>" + (m.author === "admin" ? "Admin" : "You") + ":</b> " + m.body);
      main.appendChild(mrow);
    });
    row.appendChild(main);
    var side = el("div", "deliv-actions");
    if (r.status === "resolved") {
      side.appendChild(el("span", "pill good", '<span class="dot"></span>Resolved'));
    } else {
      side.appendChild(el("span", "pill warn", '<span class="dot"></span>Open'));
      if (opts.canReply) {
        var replyInput = el("input"); replyInput.setAttribute("type", "text"); replyInput.placeholder = opts.replyPlaceholder;
        var kbRefSelect = null;
        // Item 150: admin-only -- reuse an existing knowledge base answer
        // instead of writing a fresh one, so this question doesn't turn
        // into a duplicate entry (the reply still goes out to the asker;
        // only the "auto-add to the knowledge base" part is skipped).
        if (opts.kbEntries && opts.kbEntries.length) {
          kbRefSelect = el("select");
          kbRefSelect.appendChild(el("option", "", "Reference an existing answer&#8230;"));
          opts.kbEntries.forEach(function (e) {
            var o = el("option", "", "#" + e.id + " &middot; " + e.question.slice(0, 60));
            o.value = e.id;
            kbRefSelect.appendChild(o);
          });
          kbRefSelect.addEventListener("change", function () {
            var picked = opts.kbEntries.find(function (e) { return String(e.id) === kbRefSelect.value; });
            if (picked) replyInput.value = picked.answer;
          });
          side.appendChild(kbRefSelect);
        }
        var replyBtn = el("button", "btn", "Reply");
        replyBtn.addEventListener("click", async function () {
          var body = replyInput.value.trim();
          if (!body) return;
          var payload = { body: body, actor_role: CURRENT_ROLE, actor_email: myIdentity() };
          if (kbRefSelect && kbRefSelect.value) payload.kb_reference_id = Number(kbRefSelect.value);
          try {
            await api("/api/support/" + r.id + "/" + opts.replyEndpoint, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            });
          } catch (err) {
            showToast("Could not reply &#8211; " + apiErrorDetail(err), true);
            return;
          }
          opts.onReplied();
        });
        side.appendChild(replyInput);
        side.appendChild(replyBtn);
      }
      if (opts.canResolve) {
        var resolveBtn = el("button", "btn", "Mark Resolved");
        resolveBtn.addEventListener("click", async function () {
          await api("/api/support/" + r.id + "/resolve?actor_role=" + CURRENT_ROLE, { method: "PATCH" });
          showToast("Marked resolved");
          opts.onReplied();
        });
        side.appendChild(resolveBtn);
      }
    }
    row.appendChild(side);
    container.appendChild(row);
  }

  // Item 150: Ask a Question / Knowledge Base sub-tabs inside the same
  // "Q/A - Ask the Team" nav item.
  document.querySelectorAll("#supSubtabRow .chip").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll("#supSubtabRow .chip").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      var pane = btn.dataset.pane;
      document.getElementById("supAskPane").hidden = pane !== "ask";
      document.getElementById("supKbPane").hidden = pane !== "kb";
      if (pane === "kb") loadKb();
    });
  });
  var kbCache = [];
  function _kbMatches(entry, term, category) {
    if (category && entry.category !== category) return false;
    if (!term) return true;
    var haystack = (entry.question + " " + entry.answer).toLowerCase();
    return haystack.indexOf(term) !== -1;
  }
  function _renderKbList() {
    var term = document.getElementById("kbSearch").value.trim().toLowerCase();
    var category = document.getElementById("kbCategoryFilter").value;
    var wrap = document.getElementById("kbList");
    wrap.innerHTML = "";
    var filtered = kbCache.filter(function (e) { return _kbMatches(e, term, category); });
    if (!filtered.length) {
      wrap.appendChild(el("div", "empty-state", kbCache.length ? "No matching questions." : "No answered questions yet."));
      return;
    }
    var groups = {}, groupOrder = [];
    filtered.forEach(function (e) {
      if (!groups[e.category]) { groups[e.category] = []; groupOrder.push(e.category); }
      groups[e.category].push(e);
    });
    groupOrder.sort();
    var card = el("div", "card table-card");
    groupOrder.forEach(function (cat) {
      card.appendChild(el("div", "deliv-subheader", cat));
      groups[cat].forEach(function (e) {
        var row = el("div", "aq-row");
        var main = el("div", "aq-main");
        main.appendChild(el("div", "aq-title", "#" + e.id + " &middot; " + e.question));
        main.appendChild(el("div", "deliv-comment", e.answer));
        row.appendChild(main);
        card.appendChild(row);
      });
    });
    wrap.appendChild(card);
  }
  document.getElementById("kbSearch").addEventListener("input", _renderKbList);
  document.getElementById("kbCategoryFilter").addEventListener("change", _renderKbList);
  async function loadKb() {
    kbCache = await api("/api/support/kb");
    var catSel = document.getElementById("kbCategoryFilter");
    var current = catSel.value;
    var cats = Array.from(new Set(kbCache.map(function (e) { return e.category; }))).sort();
    catSel.innerHTML = '<option value="">All categories</option>';
    cats.forEach(function (c) { var o = el("option", "", c); o.value = c; catSel.appendChild(o); });
    catSel.value = cats.indexOf(current) !== -1 ? current : "";
    _renderKbList();
  }

  async function loadSupport() {
    document.getElementById("supAsEmail").textContent = actingEmail() || localStorage.getItem("myEmail") || "(not set yet)";
    if (!document.getElementById("supEstNo").dataset.loaded) {
      document.getElementById("supEstNo").dataset.loaded = "1";
      await _populateSupEstNo();
    }
    await _populateSupTarget();

    var mineWrap = document.getElementById("supMineList");
    var email = actingEmail() || localStorage.getItem("myEmail") || "";
    mineWrap.innerHTML = "";
    if (!email) {
      mineWrap.appendChild(el("div", "empty-state", "Send a request above, or set your acting email, to see your own requests here."));
    } else {
      var mine = await api("/api/support/mine?email=" + encodeURIComponent(email));
      if (!mine.length) {
        mineWrap.appendChild(el("div", "empty-state", "No requests from you yet."));
      } else {
        mine.forEach(function (r) {
          var holder = el("div");
          _renderSupportThread(holder, r, {
            canReply: true, canResolve: false, replyEndpoint: "respond", replyPlaceholder: "Reply to the admin&#8230;",
            onReplied: loadSupport,
          });
          mineWrap.appendChild(holder);
        });
      }
    }

  }

  // Item 151: every Ask the Team thread, admin-only, in its own dedicated
  // view -- same reply/resolve/reference-KB behavior that used to live
  // inline inside "Q/A - Ask the Team" as an "Inbox" card.
  async function loadTickets() {
    var reqs = await api("/api/support?actor_role=" + CURRENT_ROLE);
    // Item 150: admins get the option to reference an existing KB entry
    // instead of writing a fresh answer, so the picker needs the full list.
    var kbEntries = await api("/api/support/kb");
    var wrap = document.getElementById("ticketsList");
    wrap.innerHTML = "";
    if (!reqs.length) { wrap.appendChild(el("div", "empty-state", "No requests yet.")); return; }
    reqs.forEach(function (r) {
      var holder = el("div");
      _renderSupportThread(holder, r, {
        canReply: true, canResolve: true, replyEndpoint: "reply", replyPlaceholder: "Reply to the asker&#8230;",
        onReplied: loadTickets, kbEntries: kbEntries,
      });
      wrap.appendChild(holder);
    });
  }

  /* ================= ANNOUNCEMENTS ================= */
  var announcementsAll = [];
  document.getElementById("annTypeFilter").addEventListener("change", renderAnnouncements);
  document.getElementById("annFromDate").addEventListener("change", renderAnnouncements);
  document.getElementById("annToDate").addEventListener("change", renderAnnouncements);
  document.getElementById("annClearFilters").addEventListener("click", function () {
    document.getElementById("annTypeFilter").value = "";
    document.getElementById("annFromDate").value = "";
    document.getElementById("annToDate").value = "";
    renderAnnouncements();
  });
  async function loadAnnouncements() {
    var qs = "?limit=500";
    if (CURRENT_ROLE !== "Admin") {
      qs += "&actor_role=" + encodeURIComponent(CURRENT_ROLE) + "&actor_email=" + encodeURIComponent(passiveIdentity());
    }
    announcementsAll = await api("/api/announcements" + qs);
    renderAnnouncements();
  }
  function renderAnnouncements() {
    var type = document.getElementById("annTypeFilter").value;
    var from = document.getElementById("annFromDate").value;
    var to = document.getElementById("annToDate").value;
    var list = announcementsAll.filter(function (a) {
      if (type && a.type !== type) return false;
      var day = a.created_at.slice(0, 10);
      if (from && day < from) return false;
      if (to && day > to) return false;
      return true;
    });
    var wrap = document.getElementById("announcementsList");
    wrap.innerHTML = "";
    if (!list.length) { wrap.appendChild(el("div", "empty-state", "No announcements match this filter.")); return; }
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
      if (a.submission_id || a.project_id) {
        row.style.cursor = "pointer";
        row.addEventListener("click", function () {
          if (a.submission_id) openDelivModal(a.submission_id);
          else openDetail(a.project_id);
        });
      }
      wrap.appendChild(row);
    });
  }

  /* ================= CREATE PROJECT ================= */
  var createOptionsLoaded = false;
  var _createOptionsCache = null;
  async function getCreateOptions() {
    if (!_createOptionsCache) _createOptionsCache = await api("/api/departments/options");
    return _createOptionsCache;
  }
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
      var opts = await getCreateOptions();
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
    var createdL0Id = null;
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
        var regionOtherVal = document.getElementById("cfRegionOther").value.trim();
        var scopeOtherVal = document.getElementById("cfScopeOther").value.trim();
        var needsManualBu = scope.some(function (s) { return buUncoveredScopes.indexOf(s) !== -1; });
        var businessUnits = checkedValues("cfBuGrid");
        var errors = [];
        if (!name) errors.push("Tender name is required");
        if (!estNoDigits) errors.push("Est-Num is required");
        else if (!/^\d+$/.test(estNoDigits)) errors.push("Est-Num must be a number only");
        if (!bidManager) errors.push("Bid Manager is required");
        if (!announce) errors.push("Announcement Date is required");
        if (!bsd) errors.push("Bid Submission Date is required");
        if (!region.length) errors.push("Select at least one Region");
        if (!scope.length) errors.push("Select at least one Scope");
        if (region.indexOf("Other") !== -1 && !regionOtherVal) errors.push("Specify the Other region");
        if (scope.indexOf("Other") !== -1 && !scopeOtherVal) errors.push("Specify the Other scope");
        if (needsManualBu && !businessUnits.length) errors.push("Business Unit is required for this scope");
        if (errors.length) { showToast(errors.join("<br>"), true); return; }
        var estNo = "Est-" + estNoDigits;
        var payload = {
          name: name, est_no: estNo,
          region: region, region_other: regionOtherVal || null,
          scope: scope, scope_other: scopeOtherVal || null,
          rfx_number: document.getElementById("cfRfx").value || null,
          announcement_date: announce, site_visit_date: document.getElementById("cfSiteVisit").value || null,
          pre_bid_meeting_date: document.getElementById("cfPreBidMeeting").value || null,
          pre_bid_deadline: document.getElementById("cfPreBid").value || null,
          bid_manager: bidManager, bsd: bsd,
          business_units: needsManualBu ? businessUnits : null,
        };
        var p = await api("/api/projects/l0", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        showToast(p.est_no + " created &#8211; announcement sent");
        createdL0Id = p.id;
      } else {
        var l0Id = document.getElementById("cfL0Source").value;
        var l1Announce = document.getElementById("cfL1Announce").value;
        var l1Errors = [];
        if (!l0Id) l1Errors.push("Select the L0 tender this L1 project comes from");
        if (!l1Announce) l1Errors.push("L1 Announcement Date is required");
        if (l1Errors.length) { showToast(l1Errors.join("<br>"), true); return; }
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
      showToast("Could not create project &#8211; " + apiErrorDetail(err), true);
      return;
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = originalLabel;
      submitBtn.classList.remove("btn-loading");
    }
    if (createdL0Id) {
      await openTriage(createdL0Id);
    } else {
      switchView("announcements");
    }
  });
  document.getElementById("cfCancel").addEventListener("click", function () { switchView("dashboard"); });

  /* ================= SEARCH ================= */
  document.getElementById("globalSearch").addEventListener("input", async function (e) {
    var v = e.target.value.trim().toLowerCase();
    if (!v) return;
    var list = await api("/api/projects");
    var match = list.filter(function (p) { return (p.est_no + " " + p.name).toLowerCase().indexOf(v) !== -1; });
    if (match.length === 1) {
      openDetail(match[0].id); e.target.value = "";
      return;
    }
    // Item 119: an L0/L1 pair now shares one Est number, so a search that's
    // an exact Est-No match can hit two rows instead of one -- go to
    // whichever is still active (its L1, once the L0 auto-closes) rather
    // than silently doing nothing the way a length!==1 check used to.
    var exact = match.filter(function (p) { return p.est_no.toLowerCase() === v; });
    if (exact.length > 1) {
      var active = exact.filter(function (p) { return p.status === "In Progress"; });
      var pick = (active.length ? active : exact).sort(function (a, b) { return b.id - a.id; })[0];
      openDetail(pick.id); e.target.value = "";
    }
  });

  /* ================= ROLE + THEME ================= */
  // Item 162: lets a tester actually become a real Owner/SME with real
  // assigned work instead of guessing an email that matches nothing (the
  // real cause behind item 160's "why can't I upload" question -- the acting
  // email has to match a real owner_email/sme_email for isAssigned() to
  // pass). Built from the live /api/deliverables list, so it's always
  // pointing at real, current, testable rows -- SME options are labelled
  // with their pending-review count so "test Pending SME Review" is a
  // one-click pick instead of a hunt through the data.
  async function populateActingEmailQuickPick() {
    var quickPick = document.getElementById("actingEmailQuickPick");
    if (CURRENT_ROLE !== "Owner" && CURRENT_ROLE !== "SME") { quickPick.style.display = "none"; return; }
    var all = await api("/api/deliverables");
    var counts = {};
    all.forEach(function (d) {
      var email = CURRENT_ROLE === "Owner" ? d.owner_email : d.sme_email;
      if (!email) return;
      if (!counts[email]) counts[email] = { due: 0, pendingReview: 0 };
      if (d.deadline_status === "due") counts[email].due++;
      if (d.status === "pending_review") counts[email].pendingReview++;
    });
    var emails = Object.keys(counts).sort();
    quickPick.innerHTML = '<option value="">Quick pick&#8230;</option>';
    emails.forEach(function (email) {
      var c = counts[email];
      var label = CURRENT_ROLE === "SME"
        ? email + " (" + c.pendingReview + " pending review)"
        : email + " (" + c.due + " due)";
      var o = el("option", "", label); o.value = email; quickPick.appendChild(o);
    });
    quickPick.style.display = emails.length ? "" : "none";
  }
  document.getElementById("roleSelect").addEventListener("change", function (e) {
    CURRENT_ROLE = e.target.value;
    var showAdmin = can("create");
    document.getElementById("adminNav").style.display = showAdmin ? "" : "none";
    document.getElementById("adminGroupLabel").style.display = showAdmin ? "" : "none";
    var actingAsPerson = CURRENT_ROLE === "Owner" || CURRENT_ROLE === "SME";
    document.getElementById("actingEmail").style.display = actingAsPerson ? "" : "none";
    // A hidden field a user can no longer see or edit shouldn't keep
    // silently steering identity-dependent checks (announcement visibility,
    // isAssigned) after switching away from Owner/SME -- clear it so
    // Admin/Viewer never inherit whichever email was last typed in.
    if (!actingAsPerson) document.getElementById("actingEmail").value = "";
    document.getElementById("bmTriageNavItem").hidden = !canSeeBmTriage();
    document.getElementById("assignedNavItem").hidden = !canSeeAssigned();
    populateActingEmailQuickPick();
    if (!showAdmin && ADMIN_ONLY_VIEWS.some(function (v) { return !document.getElementById("view-" + v).hidden; })) switchView("dashboard");
    if (!canSeeBmTriage() && !document.getElementById("view-bmtriage").hidden) switchView("dashboard");
    if (!canSeeAssigned() && !document.getElementById("view-assigned").hidden) switchView("dashboard");
    if (currentProjectId && !document.getElementById("view-detail").hidden) openDetail(currentProjectId);
    if (!document.getElementById("view-announcements").hidden) loadAnnouncements();
    checkBmTriageDeadline();
  });
  document.getElementById("actingEmailQuickPick").addEventListener("change", function (e) {
    if (!e.target.value) return;
    document.getElementById("actingEmail").value = e.target.value;
    document.getElementById("actingEmail").dispatchEvent(new Event("change"));
  });
  document.getElementById("actingEmail").addEventListener("change", function () {
    if (!document.getElementById("view-announcements").hidden) loadAnnouncements();
    checkBmTriageDeadline();
  });
  document.getElementById("themeToggle").addEventListener("click", function () {
    var root = document.documentElement;
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    this.textContent = next === "dark" ? "Light mode" : "Dark mode";
  });

  /* ================= INIT ================= */
  document.getElementById("todayLabel").textContent = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "2-digit", month: "long", year: "numeric" });

  // Item 120: loadDashboard() used to always fire immediately, then a
  // project/view restore (below) would hide it again a moment later once
  // its own awaits resolved — the dashboard would actually finish loading
  // and render onscreen before being swapped out, a visible flash on every
  // refresh. Decide the real starting view FIRST, and only load the
  // dashboard when that's genuinely where we're landing.
  var sharedMatch = location.hash.match(/deliverable=(\d+)/);
  var projectMatch = location.hash.match(/project=(\d+)/);
  var viewMatch = location.hash.match(/view=(\w+)/);
  if (projectMatch) {
    // Item 99: refreshing while on a project detail page returns to it.
    // openDetail() makes several sequential api() calls before it finally
    // reveals #view-detail — wrapping the whole thing in one extra
    // start/end pair keeps the loading count above zero the entire time,
    // so the overlay shows (at most) once instead of flickering between
    // each individual fetch (item 120).
    document.getElementById("view-dashboard").hidden = true;
    _loadingStart();
    openDetail(parseInt(projectMatch[1], 10)).finally(_loadingEnd);
  } else if (viewMatch && document.getElementById("view-" + viewMatch[1])) {
    // Item 99: refreshing on any other nav view stays on that view.
    document.getElementById("view-dashboard").hidden = true;
    switchView(viewMatch[1]);
  } else {
    // Item 147: view-dashboard now starts `hidden` in the markup like every
    // other view (it used to be the one exception, so on a refresh landing
    // anywhere else the browser painted the raw dashboard HTML -- filter
    // chips, empty stat cards and all -- for the entire time it takes app.js
    // to download and run, before swapping to the real destination view).
    // That means the dashboard-landing case now has to unhide itself
    // explicitly instead of relying on already being visible by default.
    document.getElementById("view-dashboard").hidden = false;
    loadDashboard();
    // A shared deliverable link (item 76) opens straight to that item's
    // popup, on top of the dashboard it's actually landing on.
    if (sharedMatch) openDelivModal(parseInt(sharedMatch[1], 10));
  }
  checkBmTriageDeadline();
  // Item 41: a brand-new browser (no completed-walkthrough flag) gets the
  // System Introduction forced open, on top of whatever view they landed
  // on, before they can do anything else on the site.
  if (!localStorage.getItem("tourCompletedOnce")) openTour(true);
})();

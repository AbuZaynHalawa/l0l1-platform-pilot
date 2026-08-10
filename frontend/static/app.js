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

  var STATUS_META = {
    not_due: ["neutral", "Not Due"], due: ["warn", "Due"], overdue: ["crit", "Overdue"],
    pending_review: ["warn", "Pending SME Review"], approved: ["good", "Approved"], rejected: ["crit", "Rejected"],
    pending_triage: ["neutral", "Pending BM Triage"], not_required: ["neutral", "Not Required"],
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
    support: loadSupport, bmtriage: loadBmTriageStatus,
  };
  var ADMIN_ONLY_VIEWS = ["create", "reports", "scores", "focalpoints", "followup", "bmtriage"];
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
    [["Active L0 Tenders", d.active_l0, ""], ["Active L1 Projects", d.active_l1, ""],
     [mine ? "My Not Due" : "Not Due", d.not_due, ""],
     [mine ? "My Pending SME Review" : "Pending SME Review", d.pending_review, ""],
     [mine ? "My Overdue" : "Overdue Right Now", d.overdue, "color:var(--crit)"]]
      .forEach(function (s) {
        var tile = el("div", "card stat-tile");
        tile.appendChild(el("div", "label", s[0]));
        var v = el("div", "value num", String(s[1]));
        if (s[2]) v.setAttribute("style", s[2]);
        tile.appendChild(v);
        stats.appendChild(tile);
      });

    renderDeptGrid(document.getElementById("dashDeptGrid"), d.departments, false);

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
        row.addEventListener("click", function () { openDetail(a.project_id, a.submission_id); });
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
  var assignedFilter = "";
  var assignedStage = "";
  var ASSIGNED_FILTERS = [["", "All"], ["overdue", "Overdue"], ["pending_review", "Pending SME Review"], ["not_due", "Not Due Yet"], ["approved", "Approved"], ["rejected", "Rejected"]];
  document.querySelectorAll("#assignedStageToggle .chip").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll("#assignedStageToggle .chip").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      assignedStage = btn.dataset.stage;
      loadAssigned();
    });
  });
  async function loadAssigned() {
    var followQS = actingEmail() ? "?actor_email=" + encodeURIComponent(actingEmail()) : "";
    var everything = await api("/api/deliverables" + followQS);
    var all = assignedStage ? everything.filter(function (d) { return d.stage === assignedStage; }) : everything;
    document.getElementById("assignedBadge").textContent = everything.filter(function (d) { return d.status === "overdue"; }).length || "";

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
      var authorized = isAssigned(d);
      if (authorized && d.completion_note) main.appendChild(el("div", "deliv-comment", "&#128172; " + d.completion_note));
      main.style.cursor = "pointer";
      main.addEventListener("click", function () { openDelivModal(d.id); });
      row.appendChild(main);
      row.appendChild(el("span", "pill " + sm[0], '<span class="dot"></span>' + sm[1]));
      var actions = el("div", "deliv-actions");
      if (authorized && d.file_url) actions.appendChild(fileLink(d));
      actions.appendChild(followButton(d));
      if (!authorized) {
        actions.appendChild(el("span", "locked-note", "Owner/SME only"));
      } else {
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
              showToast("Could not send reminder &#8211; " + apiErrorDetail(err), true);
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
              showToast("Could not request reassignment &#8211; " + apiErrorDetail(err), true);
              return;
            }
            showToast("Reassignment requested — pending admin approval");
          });
          actions.appendChild(reassignBtn);
        }
      }
      row.appendChild(actions);
      wrap.appendChild(row);
    });
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
    if (!pending.length) {
      card.appendChild(el("div", "deliv-row", '<span style="color:var(--ink-500);font-size:12.5px;">Nothing left to triage.</span>'));
    } else {
      var lastDept = null;
      pending.forEach(function (d) {
        if (d.department !== lastDept) {
          card.appendChild(el("div", "deliv-subheader", d.department));
          lastDept = d.department;
        }
        // A remembered pick (item 79) from this BM's past triages pre-selects
        // the toggle — still just a default, they can override it below.
        var remembered = defaults.hasOwnProperty(d.item_no) ? defaults[d.item_no] : true;
        state[d.id] = remembered;
        var row = el("div", "deliv-row");
        row.appendChild(el("div", "deliv-num", d.item_no));
        var body = el("div", "deliv-body");
        body.appendChild(el("div", "deliv-name", d.name));
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
      });
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

  /* ================= DELIVERABLE DETAIL MODAL ================= */
  document.getElementById("delivModalClose").addEventListener("click", closeDelivModal);
  document.getElementById("delivModalOverlay").addEventListener("click", function (e) {
    if (e.target.id === "delivModalOverlay") closeDelivModal();
  });
  function closeDelivModal() { document.getElementById("delivModalOverlay").hidden = true; }
  async function openDelivModal(submissionId) {
    var qs = actingEmail() ? "?actor_email=" + encodeURIComponent(actingEmail()) : "";
    var d = await api("/api/deliverables/" + submissionId + qs);
    document.getElementById("delivModalEyebrow").textContent = d.est_no + " – " + deptLabel(d.department, d.department_number);
    document.getElementById("delivModalTitle").textContent = d.item_no + " · " + d.name;
    var authorized = isAssigned({ owner_email: d.owner_email, sme_email: d.sme_email });
    var body = document.getElementById("delivModalBody");
    body.innerHTML = "";

    var sm = STATUS_META[d.status] || ["neutral", d.status];
    var meta = el("div", "modal-meta-grid");
    [["Owner", d.owner_email || "&#8213;"], ["SME", d.sme_email || "&#8213;"],
     ["Due Date", fmtDate(d.due_date)], ["Status", '<span class="pill ' + sm[0] + '"><span class="dot"></span>' + sm[1] + "</span>"]]
      .forEach(function (m) {
        var mi = el("div");
        mi.appendChild(el("div", "mk", m[0]));
        mi.appendChild(el("div", "mv", m[1]));
        meta.appendChild(mi);
      });
    body.appendChild(meta);

    var refreshModal = function () { openDelivModal(submissionId); };
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
    var eligibleStatus = d.status === "not_due" || d.status === "due" || d.status === "overdue" || d.status === "rejected";
    if (authorized && eligibleStatus && can("upload")) {
      actionsRow.appendChild(uploadButton(d.id, refreshModal));
      actionsRow.appendChild(markCompleteButton(d.id, refreshModal));
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
    var isOwnerOrAdmin = CURRENT_ROLE === "Admin" ||
      (actingEmail() && actingEmail().trim().toLowerCase() === (d.owner_email || "").trim().toLowerCase());
    if (d.status === "approved" && isOwnerOrAdmin) {
      var reopenBtn = el("button", "btn ghost-crit", "Reopen");
      reopenBtn.addEventListener("click", async function () {
        if (!confirm("Reopen " + d.item_no + "? It'll go back into the normal workflow for more work.")) return;
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

    if (authorized && d.file_url) {
      var primaryLink = el("a", "btn", "View / Download Primary File");
      primaryLink.href = d.file_url; primaryLink.target = "_blank"; primaryLink.rel = "noopener";
      body.appendChild(primaryLink);
    }
    if (authorized && (d.review_comment || d.completion_note)) {
      body.appendChild(el("div", "deliv-comment", "&#128172; " + (d.review_comment || d.completion_note)));
    }

    body.appendChild(el("div", "modal-section-title", "Documents"));
    if (!authorized) {
      body.appendChild(el("div", "empty-state", "Owner/SME/Admin only."));
    } else {
      if (!d.documents.length) body.appendChild(el("div", "empty-state", "No supplementary documents yet."));
      d.documents.forEach(function (doc) {
        var row = el("div", "doc-row");
        var main = el("div", "doc-main");
        var link = el("a", "", doc.file_name);
        link.href = doc.file_url; link.target = "_blank"; link.rel = "noopener";
        main.appendChild(link);
        var docSm = { pending: ["warn", "Pending Review"], approved: ["good", "Approved"], rejected: ["crit", "Rejected"] }[doc.status] || ["neutral", doc.status];
        main.appendChild(el("div", "doc-sub", "Uploaded by " + (doc.uploaded_by || "&#8213;") +
          '<span class="pill ' + docSm[0] + '" style="margin-left:8px;"><span class="dot"></span>' + docSm[1] + "</span>"));
        row.appendChild(main);
        if (doc.status === "pending" && can("review")) {
          var appr = el("button", "btn primary", "Approve");
          appr.addEventListener("click", async function () {
            await api("/api/deliverables/documents/" + doc.id + "/review", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ approved: true, reviewer_name: CURRENT_ROLE, actor_role: CURRENT_ROLE, actor_email: actingEmail() }),
            });
            openDelivModal(submissionId);
          });
          var rej = el("button", "btn ghost-crit", "Reject");
          rej.addEventListener("click", async function () {
            var comment = prompt("Reason for rejecting " + doc.file_name + ":", "") || null;
            await api("/api/deliverables/documents/" + doc.id + "/review", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ approved: false, comment: comment, reviewer_name: CURRENT_ROLE, actor_role: CURRENT_ROLE, actor_email: actingEmail() }),
            });
            openDelivModal(submissionId);
          });
          row.appendChild(appr); row.appendChild(rej);
        }
        body.appendChild(row);
      });
      if (can("upload")) {
        var addBtn = el("button", "btn", "Add Document");
        var addInput = el("input"); addInput.type = "file"; addInput.style.display = "none";
        addInput.addEventListener("change", async function () {
          if (!addInput.files.length) return;
          var fd = new FormData();
          fd.append("file", addInput.files[0]);
          fd.append("actor_name", CURRENT_ROLE + " (pilot)");
          fd.append("actor_role", CURRENT_ROLE);
          fd.append("actor_email", actingEmail());
          try {
            await api("/api/deliverables/" + submissionId + "/documents", { method: "POST", body: fd });
          } catch (err) {
            showToast("Could not add document &#8211; " + apiErrorDetail(err), true);
            return;
          }
          showToast("Document added");
          openDelivModal(submissionId);
        });
        addBtn.addEventListener("click", function () { addInput.click(); });
        body.appendChild(addBtn); body.appendChild(addInput);
      }
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
      ? [["Bid Manager", p.bid_manager || "&#8213;", "bm"], ["RFX", p.rfx_number || "&#8213;"], ["Region", joinList(p.region), "region"], ["Scope", joinList(p.scope)],
         ["Business Unit", buLabel],
         ["Announced", fmtDate(p.announcement_date), "date:announcement_date:Announcement Date"],
         ["Site Visit", fmtDate(p.site_visit_date), "date:site_visit_date:Site Visit Date"],
         ["Pre-Bid Deadline", fmtDate(p.pre_bid_deadline), "date:pre_bid_deadline:Pre-Bid Deadline"],
         ["Bid Submission Date", fmtDate(p.bsd)]]
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
            var list = opts.bid_managers.map(function (o) { return "&#8226; " + o; }).join("\n");
            var nextBm = prompt("Bid Manager &#8211; enter the email exactly as listed:\n\n" + list, p.bid_manager || "");
            if (nextBm === null) return;
            nextBm = nextBm.trim();
            if (!nextBm) return;
            api("/api/projects/" + id + "/details", {
              method: "PATCH", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ bid_manager: nextBm, actor_role: CURRENT_ROLE }),
            }).then(function () { showToast("Bid Manager updated"); openDetail(id); })
              .catch(function (err) { showToast("Could not update &#8211; " + apiErrorDetail(err), true); });
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
            var nextDate = prompt(fieldLabel + " (YYYY-MM-DD):", currentVal);
            if (nextDate === null) return;
            nextDate = nextDate.trim();
            if (!nextDate && fieldName === "announcement_date") { showToast("Announcement Date is required", true); return; }
            var body = { actor_role: CURRENT_ROLE };
            body[fieldName] = nextDate || null;
            api("/api/projects/" + id + "/details", {
              method: "PATCH", headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            }).then(function () { showToast(fieldLabel + " updated"); openDetail(id); })
              .catch(function (err) { showToast("Could not update &#8211; " + apiErrorDetail(err), true); });
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
    var highlightItem = highlightSubmissionId
      ? allDelivs.find(function (d) { return d.id === Number(highlightSubmissionId); })
      : null;
    var initialDept = highlightItem ? highlightItem.department : deptNames[0];
    var initialDeptItems = deptNames.length ? allDelivs.filter(function (d) { return d.department === initialDept; }) : [];
    document.getElementById("dDeliverTitle").textContent = deptNames.length ? deptLabel(initialDept, deptNumber[initialDept]) + " Deliverables" : "Deliverables";
    currentDeptOpen = initialDept;
    document.querySelectorAll(".folder-row").forEach(function (r, i) { r.classList.toggle("active", deptNames[i] === initialDept); });
    renderDeliverables(initialDeptItems);

    switchView("detail");
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
  }

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
      var sm = STATUS_META[d.status] || ["neutral", d.status];
      var row = el("div", "deliv-row");
      row.dataset.sid = String(d.id);
      var body = el("div", "deliv-body");
      body.appendChild(el("div", "deliv-name", d.name));
      body.appendChild(el("div", "deliv-due", '<span class="deliv-due-date">Due ' + fmtDate(d.due_date) + '</span> <span class="pill ' + sm[0] + '"><span class="dot"></span>' + sm[1] + "</span>"));
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
        showToast("Upload blocked &#8211; " + apiErrorDetail(err), true);
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
  document.getElementById("ganttStatusFilter").addEventListener("change", applyGanttFilters);
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
    var status = document.getElementById("ganttStatusFilter").value;
    var rows = ganttRowsUnfiltered.filter(function (r) {
      return (!dept || r.department === dept) && (!status || r.status === status);
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
        var cls = (STATUS_META[r.status] || ["neutral"])[0];
        bar = el("div", "gantt-bar " + cls + (r.is_milestone ? " milestone" : ""));
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
        row.addEventListener("click", function () {
          var pid = isPooled ? r.project_id : ganttCurrentProjectId;
          if (pid) openDetail(pid, r.submission_id);
        });
      }
      wrap.appendChild(row);
    });
    gridlines.style.height = wrap.scrollHeight + "px";
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
  async function loadJourney() {}

  var HISTORY_DEPARTMENTS = [
    { name: "Tendering", items: [
      "Introduced BBU as a separate unit with their own deliverables during both L0 &amp; L1 stages",
    ]},
    { name: "Supply Chain", items: [
      "Refined L1 deliverables by relocating some items to other departments",
      "Introduced a deliverable to provide a list of expected LCs with their respective durations during L1 Stage",
    ]},
    { name: "Operation", items: [
      "S/C Strategy handed to Operation",
      "Project DCS handed to Engineering",
      "Provide cashflow input to the Financial Department",
      "Provide CANDY Data as part of Handing Over Files",
      "Provide Local Content plan prepared during L0 Stage",
      "Introduced Performing Site Studies during L0 Stage under specific criteria",
      "Provide Design Firm Information / Offers to Supply Chain",
      "Provide list of Project Permits",
      "Provide Subcontracting Strategy / Plan",
      "Provide Vendor / Subcontractor Performance Evaluation",
      "Provide Lessons Learned",
      "Converted some deliverables into &quot;Library&quot; during L0 Stage to reduce unnecessary workload, such as POs and Procurement Historical Data",
      "Currently studying preparation of Cashflow during L0 Stage",
    ]},
    { name: "Engineering, Contract &amp; Control", items: [
      "Accelerated the preparation of the Baseline Schedule to be ready before contract signing during L1 Stage",
      "Introduced Contract Department as a separate department in L1 Stage, focused on Contracts Risk Register, Contract Liabilities, feedback on Subcontract Agreements, and feedback on PO templates",
      "Emphasized Control deliverables by relocating contractual deliverables to the Contract Department",
      "Removed unnecessary involvement by merging Legal into the Contract Department",
      "Introduced a deliverable to Support Technical Proposals (if applicable) during L0 Stage",
      "Provide Engineering Risk Register including lessons learned",
      "Provide scope for other early site studies, such as ESIA &amp; Hydrology",
      "Provide Project Deliverable Register (DCS)",
      "Compile all design inputs and studies for the Design Firm",
      "Accelerated the Review of Design Firm Offers to be immediately after L1 announcement",
      "Converted some deliverables into &quot;Library&quot; during L0 Stage, such as Fleet Productivities",
      "Prepare an internal Working Schedule",
      "Create a Temporary Cost Breakdown Structure to facilitate early PR/PO issuance",
      "Converted some deliverables to be &quot;On-Request&quot; only during L0 Stage to reduce unnecessary workload",
    ]},
    { name: "Human Resources", items: [
      "Completely refined HR L1 deliverables to be more practical and focused on major aspects",
      "Introduced Cashflow Preparation during L1 Stage, immediately after L1 announcement, to secure Bank Facilities early on",
    ]},
    { name: "SHEQ", items: [
      "Refined preparation of HSE and QA/QC detailed plans during L1 Stage to be after receiving the LOA",
      "Following the HSE audit, agreed to start receiving more project-focused deliverables, such as the List of Safety Requirements &amp; PPE",
    ]},
    { name: "Financial", items: [
      "Providing Workforce Availability Plan",
      "Verifying Local Content Plan",
      "Providing Hiring Plan",
      "Providing Study to Enhance Skills' Gaps, after consulting with the Operation team",
      "Refined providing Insurance Requirements (cost &amp; provider selection) during L1 Stage to be after Technical / Commercial Handing Over",
      "Converted some deliverables into &quot;Library&quot; during L0 Stage, such as HR Cost Estimates &amp; Availability",
      "Converted Overheads (%) into a &quot;Library&quot; item to reduce estimate-preparation time",
    ]},
    { name: "IT, Fleet &amp; FM, and Risk", items: [
      "Converted IT Costs into &quot;Library&quot; during L0 Stage to reduce unnecessary workload",
      "Introduced Risk Department as a separate department in L1 Stage, focused on reviewing &amp; compiling all risk registers received from all departments",
      "Currently refining the Risk Register Template to be more concise, practical &amp; easy to use with the new Risk Department Management Team",
      "Introduced Fleet Department as a separate department, providing Equipment Cost Estimates, Consumptions and Maintenance, and Equipment availability, location and release date",
      "Introduced FM Department as a separate department to provide Camp Cost Estimates",
      "Converted Fleet &amp; FM deliverables into &quot;Library&quot; during L0 Stage to reduce unnecessary workload",
      "Introduced IRM (Internal Rental Module)",
    ]},
  ];
  (function renderHistoryDepartments() {
    var card = document.getElementById("historyDeptCard");
    if (!card) return;
    HISTORY_DEPARTMENTS.forEach(function (dept) {
      var details = el("details", "history-dept");
      var summary = el("summary", "", dept.name);
      details.appendChild(summary);
      var ul = el("ul");
      dept.items.forEach(function (item) { ul.appendChild(el("li", "", item)); });
      details.appendChild(ul);
      card.appendChild(details);
    });
  })();

  /* ================= ACTIVITY TRAIL (L0 Tenders / L1 Projects tab) ================= */
  var HISTORY_ACTION_ICON = {
    submitted: "&#128228;", assigned: "&#128100;", review_requested: "&#128269;",
    approved: "&#9989;", rejected: "&#10060;", unlocked: "&#128275;",
    document_added: "&#128206;", document_approved: "&#9989;", document_rejected: "&#10060;",
    reopened: "&#128257;",
  };
  var trailLoaded = { L0: false, L1: false };
  function setupActivityTrail(stage, selId, timelineId, listCardId, trailCardId, subTabsId) {
    var sel = document.getElementById(selId);
    document.querySelectorAll("#" + subTabsId + " .chip").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll("#" + subTabsId + " .chip").forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        var isTrail = btn.dataset.tab === "trail";
        document.getElementById(listCardId).style.display = isTrail ? "none" : "";
        document.getElementById(trailCardId).style.display = isTrail ? "" : "none";
        if (isTrail) loadActivityTrail(stage, selId, timelineId);
      });
    });
  }
  async function loadActivityTrail(stage, selId, timelineId) {
    var sel = document.getElementById(selId);
    if (!trailLoaded[stage]) {
      var list = await api("/api/projects?stage=" + stage);
      sel.innerHTML = '<option value="">Select a ' + (stage === "L0" ? "tender" : "project") + "&#8230;</option>";
      list.forEach(function (p) {
        var o = el("option", "", p.est_no + " &#8211; " + p.name);
        o.value = p.id;
        sel.appendChild(o);
      });
      sel.addEventListener("change", function () { renderActivityTimeline(sel.value, timelineId); });
      trailLoaded[stage] = true;
    }
    if (sel.value) renderActivityTimeline(sel.value, timelineId);
  }
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
  setupActivityTrail("L0", "l0TrailProjectSel", "l0TrailTimeline", "l0ListCard", "l0TrailCard", "l0SubTabs");
  setupActivityTrail("L1", "l1TrailProjectSel", "l1TrailTimeline", "l1ListCard", "l1TrailCard", "l1SubTabs");

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
      tr.appendChild(el("td", "", d.name));
      tr.appendChild(el("td", "", d.department));
      if (d.is_tendering_bm) {
        var noteCell = el("td", "muted", "Defaults to the project's Bid Manager");
        noteCell.setAttribute("colspan", "2");
        tr.appendChild(noteCell);
        tr.appendChild(el("td"));
      } else {
        var nameInput = el("input"); nameInput.type = "text";
        nameInput.value = d.focal_point_name || ""; nameInput.placeholder = d.department_focal_name || "Name";
        var emailInput = el("input"); emailInput.type = "text";
        emailInput.value = d.focal_point_email || ""; emailInput.placeholder = d.department_focal_email || "email@algihaz.com";
        var saveBtn = el("button", "btn", "Save");
        saveBtn.addEventListener("click", async function () {
          try {
            await api("/api/departments/deliverable-focal/" + d.id, {
              method: "PATCH", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ focal_point_name: nameInput.value.trim(), focal_point_email: emailInput.value.trim() }),
            });
          } catch (err) {
            showToast("Could not save &#8211; " + apiErrorDetail(err), true);
            return;
          }
          showToast("Focal point updated for " + d.item_no);
        });
        var tdName = el("td"); tdName.appendChild(nameInput);
        var tdEmail = el("td"); tdEmail.appendChild(emailInput);
        var tdSave = el("td"); tdSave.appendChild(saveBtn);
        tr.appendChild(tdName); tr.appendChild(tdEmail); tr.appendChild(tdSave);
      }
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
    var rows = await api("/api/projects/bm-triage-status?actor_role=" + CURRENT_ROLE);
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
      tr.appendChild(el("td", "", r.name));
      tr.appendChild(el("td", "", r.bid_manager || "&#8213;"));
      tr.appendChild(el("td", "", r.total_count ? (r.total_count - r.pending_count) + " / " + r.total_count : "&#8213;"));
      var sm = BM_TRIAGE_STATUS_META[r.status] || ["neutral", r.status];
      tr.appendChild(el("td", "", '<span class="pill ' + sm[0] + '"><span class="dot"></span>' + sm[1] + "</span>"));
      var tdAction = el("td");
      if (r.status !== "done") {
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
  /* Identity for "Ask the Team" (item 77): reuses the acting-email field
     that's already how this pilot tracks "who's doing this" everywhere else
     (no real login exists) — falls back to a one-time prompt cached in
     localStorage, so the asker is never made to type it twice.
  */
  function myIdentity() {
    var acting = actingEmail();
    if (acting) return acting;
    var cached = localStorage.getItem("myEmail");
    if (cached) return cached;
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
    showToast("Sent to the admins &#8211; they'll follow up by email");
    document.getElementById("supMessage").value = "";
    document.getElementById("supStage").value = "";
    _populateSupEstNo();
    loadSupport();
  });

  function _renderSupportThread(container, r, opts) {
    container.innerHTML = "";
    var context = [r.stage, r.est_no, r.deliverable].filter(Boolean).join(" &middot; ");
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
        var replyBtn = el("button", "btn", "Reply");
        replyBtn.addEventListener("click", async function () {
          var body = replyInput.value.trim();
          if (!body) return;
          try {
            await api("/api/support/" + r.id + "/" + opts.replyEndpoint, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ body: body, actor_role: CURRENT_ROLE, actor_email: myIdentity() }),
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

  async function loadSupport() {
    document.getElementById("supAsEmail").textContent = actingEmail() || localStorage.getItem("myEmail") || "(not set yet)";
    if (!document.getElementById("supEstNo").dataset.loaded) {
      document.getElementById("supEstNo").dataset.loaded = "1";
      await _populateSupEstNo();
    }

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

    var inboxCard = document.getElementById("supInboxCard");
    if (!can("create")) { inboxCard.style.display = "none"; return; }
    inboxCard.style.display = "";
    var reqs = await api("/api/support?actor_role=" + CURRENT_ROLE);
    var wrap = document.getElementById("supInboxList");
    wrap.innerHTML = "";
    if (!reqs.length) { wrap.appendChild(el("div", "empty-state", "No requests yet.")); return; }
    reqs.forEach(function (r) {
      var holder = el("div");
      _renderSupportThread(holder, r, {
        canReply: true, canResolve: true, replyEndpoint: "reply", replyPlaceholder: "Reply to the asker&#8230;",
        onReplied: loadSupport,
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
    announcementsAll = await api("/api/announcements?limit=500");
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
      if (a.project_id) {
        row.style.cursor = "pointer";
        row.addEventListener("click", function () { openDetail(a.project_id, a.submission_id); });
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

  // A shared deliverable link (item 76) opens straight to that item's popup.
  var sharedMatch = location.hash.match(/deliverable=(\d+)/);
  if (sharedMatch) openDelivModal(parseInt(sharedMatch[1], 10));
})();

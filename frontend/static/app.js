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
    var owners = (d.owner_emails || []).map(function (e) { return (e || "").trim().toLowerCase(); });
    var smes = (d.sme_emails || []).map(function (e) { return (e || "").trim().toLowerCase(); });
    return owners.indexOf(email) !== -1 || smes.indexOf(email) !== -1;
  }

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html !== undefined) e.innerHTML = html;
    return e;
  }
  // Item 170: DD-Mon-YYYY everywhere a date renders (e.g. "16-Sep-2026")
  // -- toLocaleDateString has no hyphen-separator preset, and en-GB's own
  // "short" month for September is the 4-letter "Sept", so this is a
  // fixed 3-letter table instead of relying on locale formatting.
  var MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function fmtDate(iso) {
    if (!iso) return "&#8213;";
    var d = new Date(iso + "T00:00:00");
    var day = String(d.getDate()).padStart(2, "0");
    return day + "-" + MONTH_ABBR[d.getMonth()] + "-" + d.getFullYear();
  }
  // Item 169: a predecessor-gated deliverable's due_date/awaiting_note pair
  // covers two cases -- no date at all yet (awaiting_note replaces the
  // date entirely) and a date that's already computed but still only
  // tentative (awaiting_note appends alongside it, in parens). Shared by
  // every place a deliverable's due date is rendered so the wording/shape
  // never drifts between them.
  function dueDateHtml(d) {
    if (!d.due_date) return d.awaiting_note || fmtDate(d.due_date);
    return fmtDate(d.due_date) + (d.awaiting_note ? ' <span class="pending-note">(' + d.awaiting_note + ")</span>" : "");
  }
  // Item [early bonus]: human label for a Completed deliverable's earned
  // point value, matching rules.kpi_points' exact tiers on the backend.
  function pointsEarnedLabel(pts) {
    var why = pts >= 1.1 ? "Early &#8211; 10% bonus"
      : pts === 1.0 ? "On Time"
      : pts === 0.9 ? "1&#8211;7 days late"
      : pts === 0.8 ? "8&#8211;14 days late"
      : pts === 0.7 ? "15&#8211;21 days late"
      : pts === 0.6 ? "22&#8211;28 days late"
      : "Not submitted in time";
    return pts.toFixed(1) + " pts <span class=\"pending-note\">(" + why + ")</span>";
  }
  // Item 143 (2nd revision): a deliverable now carries two independent
  // status pills -- Deadline (Not Due / Due / On Time / Early / Late, with
  // a day count) and Progress (No Progress Yet / In Progress / Pending SME
  // Review / Completed / Rejected). Not Required and Pending Triage sit
  // outside both axes, so they render as a single pill on their own.
  // Item [due-date pending pill]: an outstanding extension/hold request
  // takes over the Deadline pill (instead of showing the normal Due/Not Due
  // it would otherwise read) so it's visible while just browsing a list,
  // not only inside the deliverable's own modal. on_hold still wins if both
  // are somehow true, since deadline_status() already checks that first.
  function pendingDueDateRequestKind(d) {
    return d.pending_due_date_request_kind || (d.pending_due_date_request && d.pending_due_date_request.kind) || null;
  }
  function deadlinePillHtml(d) {
    var pendingKind = pendingDueDateRequestKind(d);
    if (pendingKind && d.deadline_status !== "on_hold") {
      var label = pendingKind === "extension" ? "Pending Extension Approval" : "Pending On Hold Approval";
      return '<span class="pill warn"><span class="dot"></span>' + label + "</span>";
    }
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
    var pendingKind = pendingDueDateRequestKind(d);
    if (pendingKind && d.deadline_status !== "on_hold") {
      var label = pendingKind === "extension" ? "Pending Extension Approval" : "Pending On Hold Approval";
      return '<span class="aqt-status warn"><span class="dot"></span>' + label + "</span>";
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
    on_hold: ["warn", "On Hold"],
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
    milestone: ["&#127919;", "milestone"], bsd_extended: ["&#128197;", "bsd-extended"],
    doc_added: ["&#128206;", "doc-added"], deliverable_approved: ["&#9989;", "deliverable-approved"],
    extension_request: ["&#8987;", "extension-request"], extension_decision: ["&#128197;", "extension-decision"],
    hold_request: ["&#9208;", "hold-request"], hold_decision: ["&#9208;", "hold-decision"],
  };
  // Item 165: single source of truth for the Announcements type filter and
  // its legend -- audience: "all" means every role sees it as a filter
  // choice (matches the types every role can actually receive, per the
  // backend's _ALWAYS_VISIBLE_TYPES); a role array restricts it to roles
  // that could ever actually see that type. Admin always gets every option
  // regardless, since Admin sees every announcement.
  var ANN_TYPE_META = [
    { value: "broadcast", label: "Broadcast", sw: "var(--purple-1)", audience: "all" },
    { value: "milestone", label: "Milestone Reached", sw: "var(--purple-2)", audience: "all" },
    { value: "bsd_extended", label: "BSD Extended", sw: "var(--warn)", audience: "all" },
    { value: "doc_added", label: "Document Added", sw: "var(--purple-1)", audience: "all" },
    { value: "deliverable_approved", label: "Deliverable Approved", sw: "var(--good)", audience: "all" },
    { value: "unlock", label: "Cross-department Unlock", sw: "var(--purple-2)", audience: "all" },
    { value: "closed", label: "Closed", sw: "var(--neutral-bg);border:1px solid var(--line)", audience: "all" },
    { value: "owner", label: "To Owner", sw: "var(--good)", audience: ["Owner"] },
    { value: "sme_request", label: "SME Review Request", sw: "var(--warn)", audience: ["Owner", "SME"] },
    { value: "sme_decision", label: "SME Decision &#8211; Rejected", sw: "var(--good)", audience: ["Owner"] },
    { value: "deadline", label: "Deadline / Reminder", sw: "var(--warn)", audience: ["Owner", "SME"] },
    { value: "extension_request", label: "Extension Requested", sw: "var(--warn)", audience: ["Owner", "SME"] },
    { value: "extension_decision", label: "Extension Decision", sw: "var(--good)", audience: ["Owner"] },
    { value: "hold_request", label: "Hold Requested", sw: "var(--warn)", audience: ["Owner", "SME"] },
    { value: "hold_decision", label: "Hold Decision", sw: "var(--good)", audience: ["Owner"] },
  ];
  // Item [announcement recipients]: the "To:" line used to list every
  // recipient email verbatim -- fine at a handful of test users, unreadable
  // once the roster is hundreds of real people. Show the audience group
  // instead of the literal address list.
  var _ROLE_PLURAL = { Owner: "Owners", SME: "SMEs", Admin: "Admins" };
  // Item [audience tag bug]: this used to read the per-*type* static list
  // in ANN_TYPE_META (e.g. "deadline" -> ["Owner", "SME"]) regardless of who
  // actually got the email -- accurate back when each type had one fixed
  // audience, but DEADLINE is now a shared bucket for several flows with
  // different real audiences (the due-soon/overdue batch is Owner-only, BM
  // Triage is the Bid Manager, reassignment-requested is Admin-only...), so
  // a single static per-type guess started mislabeling most of them (an
  // Owner-only overdue reminder showing "To: Owners & SMEs"). This now
  // derives the tag from the announcement's actual `recipients` emails via
  // a real email->role lookup, falling back to the static per-type label
  // only when recipients is empty/unresolvable.
  function annAudienceTag(a, roleMap) {
    var meta = ANN_TYPE_META.find(function (t) { return t.value === a.type; });
    if (meta && meta.audience === "all") return "All Users";
    var emails = (a.recipients || "").split(",").map(function (s) { return s.trim().toLowerCase(); }).filter(Boolean);
    if (emails.length && roleMap) {
      var roles = {};
      emails.forEach(function (e) { var r = roleMap[e]; if (r) roles[r] = true; });
      var roleNames = Object.keys(roles);
      if (roleNames.length) return roleNames.map(function (r) { return _ROLE_PLURAL[r] || r; }).join(" &amp; ");
    }
    if (emails.length) return emails.length + " recipient" + (emails.length === 1 ? "" : "s");
    if (!meta) return "&#8213;";
    return meta.audience.map(function (r) { return _ROLE_PLURAL[r] || r; }).join(" &amp; ");
  }
  var _emailRoleMap = null;
  async function _getEmailRoleMap() {
    if (_emailRoleMap) return _emailRoleMap;
    var users = await _getRoster();
    _emailRoleMap = {};
    users.forEach(function (u) { if (u.email) _emailRoleMap[u.email.trim().toLowerCase()] = u.role; });
    return _emailRoleMap;
  }
  function buildAnnouncementFilterUI() {
    var visible = ANN_TYPE_META.filter(function (t) {
      return CURRENT_ROLE === "Admin" || t.audience === "all" || t.audience.indexOf(CURRENT_ROLE) !== -1;
    });
    var key = document.getElementById("annTypeKey");
    key.innerHTML = "";
    visible.forEach(function (t) {
      key.appendChild(el("span", "lg", '<span class="sw" style="background:' + t.sw + '"></span> ' + t.label));
    });
    var select = document.getElementById("annTypeFilter");
    var current = select.value;
    select.innerHTML = '<option value="">All Types</option>';
    visible.forEach(function (t) {
      var o = el("option", "", t.label); o.value = t.value; select.appendChild(o);
    });
    if (visible.some(function (t) { return t.value === current; })) select.value = current;
  }
  function annIcon(a) {
    var meta = ANN_ICON[a.type] || ["&#128276;", "broadcast"];
    if (a.type === "sme_decision" && a.title.indexOf("Rejected") !== -1) {
      return ["&#10060;", "sme-decision rejected"];
    }
    return meta;
  }

  /* ================= VIEW SWITCHING ================= */
  var LOADERS = {
    dashboard: loadDashboard, assigned: loadAssigned, announcements: loadAnnouncements, reminders: loadReminders,
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
  // Item 164: back to showing it for Owner, but only when the acting email
  // is actually an active Bid Manager -- every other Owner, and SME/Viewer
  // entirely, have no use for it. The BM roster is fetched once and cached,
  // same pattern as _getRoster()/_rosterCache for the SME/Owner picker.
  var _bmEmailSet = null;
  async function _getBmEmailSet() {
    if (_bmEmailSet) return _bmEmailSet;
    try {
      var bms = await api("/api/departments/bid-managers");
      _bmEmailSet = new Set(bms.filter(function (b) { return b.active; })
        .map(function (b) { return b.email.trim().toLowerCase(); }));
    } catch (e) { _bmEmailSet = new Set(); }
    return _bmEmailSet;
  }
  var _canSeeBmTriageCached = true; // matches the default CURRENT_ROLE of "Admin"
  async function _refreshCanSeeBmTriage() {
    if (CURRENT_ROLE === "Admin") { _canSeeBmTriageCached = true; return true; }
    if (CURRENT_ROLE !== "Owner") { _canSeeBmTriageCached = false; return false; }
    var email = actingEmail().trim().toLowerCase();
    if (!email) { _canSeeBmTriageCached = false; return false; }
    var set = await _getBmEmailSet();
    _canSeeBmTriageCached = set.has(email);
    return _canSeeBmTriageCached;
  }
  // switchView needs a synchronous answer (no flash of content while an
  // async roster fetch resolves), so it reads this cache -- kept current by
  // _refreshCanSeeBmTriage() on every role/acting-email change below.
  function canSeeBmTriage() { return _canSeeBmTriageCached; }
  // Item 158: Viewer has no upload/review/create actions at all, so a work
  // queue of assigned items has nothing for them to do with it.
  function canSeeAssigned() { return CURRENT_ROLE !== "Viewer"; }
  // Item [reminders tab]: same reasoning as Assigned Deliverables -- a
  // Viewer has no deliverable of their own to be reminded about, so a due-
  // soon/overdue nudge queue is meaningless for that role.
  function canSeeReminders() { return CURRENT_ROLE !== "Viewer"; }
  function switchView(name) {
    if (ADMIN_ONLY_VIEWS.indexOf(name) !== -1 && !can("create")) name = "dashboard";
    if (name === "bmtriage" && !canSeeBmTriage()) name = "dashboard";
    if (name === "assigned" && !canSeeAssigned()) name = "dashboard";
    if (name === "reminders" && !canSeeReminders()) name = "dashboard";
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
    btn.addEventListener("click", function () { switchView(btn.dataset.view); closeMobileNav(); });
  });
  document.getElementById("backBtn").addEventListener("click", function () { switchView(lastListView); });
  // Item 154: hamburger nav -- the rail is an off-canvas drawer below the
  // tablet breakpoint (styles.css), opened/closed via these three triggers.
  function closeMobileNav() {
    document.getElementById("rail").classList.remove("open");
    document.getElementById("railBackdrop").classList.remove("open");
  }
  document.getElementById("railToggle").addEventListener("click", function () {
    document.getElementById("rail").classList.add("open");
    document.getElementById("railBackdrop").classList.add("open");
  });
  document.getElementById("railBackdrop").addEventListener("click", closeMobileNav);
  document.getElementById("dGanttBtn").addEventListener("click", function () { openProjectGantt(currentProjectId); });

  /* ================= DASHBOARD ================= */
  // Item 183: "My Items" reuses the acting-as-email identity that's already
  // how the rest of the app tracks "who's doing this" (topbar field /
  // myIdentity()'s cached prompt) -- no separate email box just for the
  // Dashboard. Concerns, the Deliverable Matrix, and the announcements feed
  // all scope down too now, not just the stat cards.
  var dashFocus = "all";
  document.querySelectorAll("#dashFocusToggle .chip").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll("#dashFocusToggle .chip").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      dashFocus = btn.dataset.focus;
      if (dashFocus === "mine") myIdentity();
      loadDashboard();
    });
  });

  async function loadDashboard() {
    var focusEmail = dashFocus === "mine" ? myIdentity() : "";
    var qs = focusEmail ? "?focus_email=" + encodeURIComponent(focusEmail) : "";
    var d = await api("/api/dashboard" + qs);

    // Item [dashboard stage split]: Concerns is now one card per stage,
    // living in that stage's own column further down. Item [empty concerns]:
    // the card always stays visible (title + "No concerns") instead of
    // disappearing entirely when there's nothing to flag -- a vanished card
    // on one side while the other stage still has one looked like a layout
    // bug, and broke the visual rhythm of the column below it.
    [["L0", d.concerns_l0], ["L1", d.concerns_l1]].forEach(function (s) {
      var list = document.getElementById("concerns" + s[0] + "List");
      list.innerHTML = "";
      if (s[1] && s[1].length) {
        s[1].forEach(function (c) { list.appendChild(el("li", "", c)); });
      } else {
        list.appendChild(el("div", "empty-state", "No concerns."));
      }
    });

    var stats = document.getElementById("statRow");
    stats.innerHTML = "";
    var mine = !!focusEmail;
    // Item [dashboard cards redesign]: project counts get their own more
    // prominent pair of cards (a real headline number, not just another
    // tile in a flat row), and every deadline/progress status becomes a
    // child stat inside one of two parent "Status" cards -- clicking a
    // child still jumps straight to Assigned Deliverables pre-filtered,
    // same as the old flat tiles did (item 121).
    // Item [dashboard redesign 2]: only the card's own header stays
    // colorful (tag + count) -- the body underneath lists the 3 newest
    // tenders/projects for that stage in the card's plain surface color,
    // with just the Est No taking the stage's identity color.
    var projectRow = el("div", "dash-project-row");
    [["L0", mine ? "My Active L0 Tenders" : "Active L0 Tenders", d.active_l0, d.recent_l0, "Latest L0 Tenders"],
     ["L1", mine ? "My Active L1 Projects" : "Active L1 Projects", d.active_l1, d.recent_l1, "Latest L1 Projects"]]
      .forEach(function (s) {
        var card = el("div", "card dash-project-card " + s[0].toLowerCase());
        var head = el("div", "dpc-head");
        head.innerHTML = '<div class="dpc-tag">' + s[0] + '</div><div><div class="dpc-value">' + s[2] +
          '</div><div class="dpc-label">' + s[1] + "</div></div>";
        card.appendChild(head);
        var body = el("div", "dpc-body");
        body.appendChild(el("div", "dpc-body-title", s[4]));
        var recent = s[3] || [];
        if (!recent.length) {
          body.appendChild(el("div", "dpc-empty", "No " + s[0] + " projects yet."));
        } else {
          recent.forEach(function (p) {
            var row = el("div", "dpc-recent-row");
            row.innerHTML = '<span class="dpc-recent-est">' + p.est_no + '</span>' +
              '<span class="dpc-recent-name">' + p.name + '</span>' +
              '<span class="dpc-recent-date">' + fmtDate(p.announcement_date) + "</span>";
            row.addEventListener("click", function () { openDetail(p.id); });
            body.appendChild(row);
          });
        }
        card.appendChild(body);
        projectRow.appendChild(card);
      });
    stats.appendChild(projectRow);

    function statusCard(title, children) {
      var card = el("div", "card dash-status-card");
      var head = el("div", "dsc-head", title);
      card.appendChild(head);
      var kids = el("div", "dsc-children");
      children.forEach(function (c) {
        var child = el("div", "dsc-child" + (c[3] ? " " + c[3] : ""));
        child.innerHTML = '<div class="dsc-child-val">' + c[1] + '</div><div class="dsc-child-label">' + c[0] + "</div>";
        if (c[2]) {
          child.style.cursor = "pointer";
          child.addEventListener("click", function () { goToAssignedFilter(c[2][0], c[2][1]); });
        }
        kids.appendChild(child);
      });
      card.appendChild(kids);
      return card;
    }
    var statusRow = el("div", "dash-status-row");
    statusRow.appendChild(statusCard("Deliverables Deadline Status", [
      [mine ? "My Not Due" : "Not Due", d.not_due, ["deadline", "not_due"], ""],
      [mine ? "My Due" : "Due", d.overdue, ["deadline", "due"], "crit"],
      ["Early", d.early, ["deadline", "early"], "good"],
      ["On Time", d.on_time, ["deadline", "on_time"], "good"],
      ["Late", d.late, ["deadline", "late"], "crit"],
    ]));
    statusRow.appendChild(statusCard("Deliverables Progress Status", [
      ["No Progress Yet", d.no_progress, ["progress", "no_progress"], ""],
      ["In Progress", d.in_progress, ["progress", "in_progress"], "warn"],
      [mine ? "My Pending SME Review" : "Pending SME Review", d.pending_review, ["progress", "pending_review"], "warn"],
      ["Completed", d.approved, ["progress", "approved"], "good"],
      ["Rejected", d.rejected, ["progress", "rejected"], "crit"],
    ]));
    stats.appendChild(statusRow);

    // Item [dashboard stage split]: Top Departments, Newest Milestones and
    // Latest Announcements each render twice now, once into L0's column
    // and once into L1's -- everything about one stage lives together
    // under that stage's own headline card.
    function renderStageMilestones(stage, milestones) {
      var wrap = document.getElementById("milestones" + stage);
      wrap.innerHTML = "";
      if (!milestones || !milestones.length) {
        wrap.appendChild(el("div", "empty-state", "No milestones reached yet."));
        return;
      }
      milestones.forEach(function (m) {
        var row = el("div", "milestone-row");
        row.innerHTML = '<span class="milestone-code-badge">' + (m.milestone_code || "M") + '</span>' +
          '<span class="milestone-body"><span class="milestone-name">' + m.name + '</span>' +
          '<div class="milestone-meta">' + m.est_no + " &#8211; " + m.project_name + "</div></span>" +
          '<span class="milestone-date">' + fmtDate(m.reviewed_at ? m.reviewed_at.slice(0, 10) : null) + "</span>";
        row.addEventListener("click", function () { openDetail(m.project_id); });
        wrap.appendChild(row);
      });
    }
    renderStageMilestones("L0", d.recent_milestones_l0);
    renderStageMilestones("L1", d.recent_milestones_l1);

    function renderStageDepts(stage, rows) {
      var wrap = document.getElementById("topDepts" + stage);
      wrap.innerHTML = "";
      if (!rows || !rows.length) {
        wrap.appendChild(el("div", "empty-state", "No data yet."));
        return;
      }
      rows.forEach(function (r, i) {
        var row = el("div", "top-dept-row");
        row.innerHTML = '<span class="top-dept-rank">#' + (i + 1) + '</span>' +
          '<span class="top-dept-name">' + deptLabel(r.department, r.department_number) + '</span>' +
          '<span class="top-dept-pct">' + r.pct.toFixed(1) + "%</span>";
        wrap.appendChild(row);
      });
    }
    renderStageDepts("L0", d.top_depts_l0);
    renderStageDepts("L1", d.top_depts_l1);

    var achievers = await api("/api/dashboard/top-achievers");
    renderAchievers("topOwners", achievers.owners.slice(0, 3), "owner");
    renderAchievers("topSmes", achievers.smes.slice(0, 3), "sme");

    // Item [dashboard announcements scoping]: this feed used to be called
    // with no actor_role/actor_email at all, which the backend treats as
    // "show everything" -- the same private SME/Owner-only announcements
    // the full Announcements page correctly hides from the wrong role were
    // leaking onto every Dashboard regardless of who's looking. Same
    // actor_role/actor_email pattern as loadAnnouncements(), now also
    // split per stage (item [dashboard stage split]).
    async function loadStageAnnouncements(stage) {
      var qs = "?limit=6&stage=" + stage;
      if (CURRENT_ROLE !== "Admin") {
        qs += "&actor_role=" + encodeURIComponent(CURRENT_ROLE) + "&actor_email=" + encodeURIComponent(passiveIdentity());
      }
      // Item 183: "My Items" narrows the feed to only announcements
      // actually addressed to the focus email, on top of whatever
      // role-visibility filtering already applied above -- an Admin
      // toggling My Items gets this for the first time too, since the
      // role branch above never runs for them.
      if (focusEmail) qs += "&mine=true&actor_email=" + encodeURIComponent(focusEmail);
      var anns = await api("/api/announcements" + qs);
      var digest = document.getElementById("digest" + stage + "List");
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
    }
    await Promise.all([loadStageAnnouncements("L0"), loadStageAnnouncements("L1")]);

    matrixFocusEmail = focusEmail;
    await loadMatrix();
  }

  /* ================= DELIVERABLES MATRIX ================= */
  var matrixStage = "L0";
  // Item 183: set by loadDashboard() to the current "My Items" focus email
  // (empty when "All" is selected) -- the L0/L1 toggle inside the matrix
  // widget re-fetches independently of a full dashboard reload, so it needs
  // its own remembered copy rather than reading dashFocus/focusEmail directly.
  var matrixFocusEmail = "";
  document.querySelectorAll(".matrix-toggle .chip").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".matrix-toggle .chip").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      matrixStage = btn.dataset.stage;
      loadMatrix();
    });
  });
  async function loadMatrix() {
    var qs = "?stage=" + matrixStage;
    if (matrixFocusEmail) qs += "&focus_email=" + encodeURIComponent(matrixFocusEmail);
    var data = await api("/api/dashboard/matrix" + qs);
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
  var _BU_ORDER = ["TBU", "PBU", "DBU", "BBU"];
  function sortBusinessUnits(bus) {
    return bus.slice().sort(function (a, b) {
      var ai = _BU_ORDER.indexOf(a), bi = _BU_ORDER.indexOf(b);
      return (ai === -1 ? _BU_ORDER.length : ai) - (bi === -1 ? _BU_ORDER.length : bi);
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
  var DEADLINE_FILTERS = [
    ["", "All"], ["not_due", "Not Due"], ["due", "Due"],
    ["early", "Early"], ["on_time", "On Time"], ["late", "Late"],
  ];
  var PROGRESS_FILTERS = [
    ["", "All"], ["no_progress", "No Progress Yet"], ["in_progress", "In Progress"],
    ["pending_review", "Pending SME Review"], ["approved", "Completed"], ["rejected", "Rejected"],
  ];
  // Item [SME scope]: an SME's Assigned cohort is now only pending_review
  // (his own) or rejected (his own) -- every other status is permanently
  // absent from his list, so those chips would always read 0 and are hidden.
  var SME_PROGRESS_FILTERS = [
    ["", "All"], ["pending_review", "Pending My Review"], ["rejected", "Rejected by Me"],
    ["approved", "Approved by Me"],
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
    var progressFilterSet = CURRENT_ROLE === "SME" ? SME_PROGRESS_FILTERS : PROGRESS_FILTERS;
    progressFilterSet.forEach(function (f) {
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
    // Newest action first: items with a real submit/review timestamp sort
    // by that descending; untouched items (no action yet) sink to the
    // bottom, in their existing relative order.
    items = items.slice().sort(function (a, b) {
      var at = a.last_action_at ? new Date(a.last_action_at).getTime() : -1;
      var bt = b.last_action_at ? new Date(b.last_action_at).getTime() : -1;
      return bt - at;
    });
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

      row.appendChild(el("div", "aqt-cell aqt-ellipsis aqt-est " + (d.stage || "").toLowerCase(), d.est_no));

      var nameCell = el("div", "aqt-cell aqt-ellipsis aqt-name",
        d.item_no + " &middot; " + d.name + '<span class="aqt-proj"> &#8211; ' + d.project_name + "</span>");
      row.appendChild(nameCell);

      row.appendChild(el("div", "aqt-cell aqt-ellipsis aqt-dept", deptLabel(d.department, d.department_number)));
      row.appendChild(el("div", "aqt-cell aqt-ellipsis aqt-focal", d.owner));
      row.appendChild(el("div", "aqt-cell", deadlineStatusCellHtml(d)));
      row.appendChild(el("div", "aqt-cell", progressStatusCellHtml(d)));
      // Item 169: same predecessor-wait note as the project detail list,
      // instead of a bare "—" for an item with no due date yet -- or,
      // alongside an already-computed date that's still only tentative.
      var aqtDueCell = el("div", "aqt-cell aqt-ellipsis aqt-due", dueDateHtml(d));
      if (d.awaiting_note) aqtDueCell.title = d.awaiting_note;
      row.appendChild(aqtDueCell);

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
      var estClass = "est-no " + stage.toLowerCase();
      if (stage === "L0") {
        tr2.innerHTML = '<td class="' + estClass + '">' + p.est_no + '</td><td><span class="proj-name">' + p.name + '</span></td>' +
          '<td>' + (p.rfx_number || "&#8213;") + '</td><td>' + joinList(p.region) + '</td><td>' + joinList(p.scope) + '</td><td>' + (p.bid_manager || "&#8213;") + '</td>' +
          '<td class="num">' + fmtDate(p.bsd) + '</td><td>' + statusPill + '</td>';
      } else {
        var mini = '<div class="mini-stepper" data-pid="' + p.id + '">&#8230;</div>';
        tr2.innerHTML = '<td class="' + estClass + '">' + p.est_no + '</td><td><span class="proj-name">' + p.name + '</span></td>' +
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
    // These items default to Not Required unless the BM explicitly flips
    // them -- everything else still defaults to Applicable. A remembered
    // pick (item 79) from this BM's own past triages always wins over
    // either default. Item 171 originally hardcoded just 5.4/8.4; the rest
    // come from "Default BM Triage.xlsx" (mapped from that sheet's old
    // pre-department-split item numbering to each item's current item_no
    // by matching description text, the same technique used for the L1
    // Excel-formula work -- see seed.py's item 127 renumber comments for
    // the department splits this crosses).
    var NOT_REQUIRED_BY_DEFAULT = {
      "1.1": true, "1.2": true, "1.3": true, "1.4": true, "1.5": true, "1.7": true,
      "1.13": true, "1.14": true, "1.15": true, "1.18": true, "1.19": true, "1.20": true,
      "3.4": true, "3.7": true, "3.8": true, "3.9": true,
      "4.5": true,
      "5.4": true, "5.5": true, "6.3": true,
      "7.3": true, "7.4": true,
      "8.2": true, "8.3": true, "8.4": true,
      "10.3": true, "10.4": true,
      "15.1": true, "15.2": true, "16.1": true,
    };
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
    markAllBtn.onclick = async function () {
      if (!(await customConfirm("Mark all " + pending.length + " item(s) as Applicable?"))) return;
      toggleButtons.forEach(function (t) {
        state[t.id] = true;
        t.appBtn.classList.add("active"); t.notBtn.classList.remove("active");
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
      refreshNavBadges();
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

  // Item [nav badges]: pending-count badge on 5 sidebar nav items, same
  // .nav-badge/.textContent pattern assignedBadge already uses (loadAssigned,
  // above). Unlike that one, these need to populate on a fresh load too, not
  // just when their own view is visited -- called from INIT below and from
  // both the role-select and acting-email change handlers.
  async function refreshNavBadges() {
    try {
      var bmQs = "actor_role=" + encodeURIComponent(CURRENT_ROLE);
      if (CURRENT_ROLE !== "Admin") bmQs += "&actor_email=" + encodeURIComponent(actingEmail());
      var bmRows = await api("/api/projects/bm-triage-status?" + bmQs);
      document.getElementById("bmTriageBadge").textContent = bmRows.filter(function (r) { return r.status !== "done"; }).length || "";
    } catch (e) { /* not scoped to a real BM yet -- leave blank rather than error */ }

    // Open Questions is Admin-only server-side (403 otherwise) and the nav
    // item itself is hidden for every other role -- skip the fetch entirely.
    if (CURRENT_ROLE === "Admin") {
      try {
        var tickets = await api("/api/support?actor_role=Admin");
        document.getElementById("ticketsBadge").textContent = tickets.filter(function (t) { return t.status === "open"; }).length || "";
      } catch (e) {}
    } else {
      document.getElementById("ticketsBadge").textContent = "";
    }

    try {
      var annQs = "?limit=500";
      if (CURRENT_ROLE !== "Admin") annQs += "&actor_role=" + encodeURIComponent(CURRENT_ROLE) + "&actor_email=" + encodeURIComponent(passiveIdentity());
      var anns = await api("/api/announcements" + annQs);
      var lastSeen = localStorage.getItem("annLastSeenAt");
      var unread = lastSeen ? anns.filter(function (a) { return new Date(a.created_at) > new Date(lastSeen); }).length : anns.length;
      document.getElementById("announcementsBadge").textContent = unread || "";
    } catch (e) {}

    // Reminders badge -- same unseen-since-localStorage-timestamp pattern
    // as Announcements above, its own key since the two tabs are read
    // independently. Skipped for Viewer, matching the nav item itself being
    // hidden for that role (canSeeReminders()).
    if (canSeeReminders()) {
      try {
        var remQs = "?limit=500&category=reminders";
        if (CURRENT_ROLE !== "Admin") remQs += "&actor_role=" + encodeURIComponent(CURRENT_ROLE) + "&actor_email=" + encodeURIComponent(passiveIdentity());
        var rems = await api("/api/announcements" + remQs);
        var remLastSeen = localStorage.getItem("remLastSeenAt");
        var remUnread = remLastSeen ? rems.filter(function (a) { return new Date(a.created_at) > new Date(remLastSeen); }).length : rems.length;
        document.getElementById("remindersBadge").textContent = remUnread || "";
      } catch (e) {}
    } else {
      document.getElementById("remindersBadge").textContent = "";
    }

    // L0/L1 "new" projects -- no per-viewer seen-tracking precedent exists
    // anywhere in this app for projects (unlike Announcements above), so
    // this is a global count, same for every viewer: created today (local
    // calendar day), not a rolling window -- toDateString() compares only
    // the local Y/M/D, so this naturally resets at local midnight rather
    // than needing an explicit timer.
    try {
      var projects = await api("/api/projects");
      var todayStr = new Date().toDateString();
      var isNew = function (p) { return p.created_at && new Date(p.created_at).toDateString() === todayStr; };
      document.getElementById("l0Badge").textContent = projects.filter(function (p) { return p.stage === "L0" && isNew(p); }).length || "";
      document.getElementById("l1Badge").textContent = projects.filter(function (p) { return p.stage === "L1" && isNew(p); }).length || "";
    } catch (e) {}

    // Follow Up is Admin-only server-side and its nav item is hidden for
    // every other role -- same skip-the-fetch pattern as Open Questions
    // above. Badge sums both request queues that actually live on that
    // page, so a pending extension/hold request an SME hasn't acted on yet
    // still surfaces to Admin as a fallback.
    if (CURRENT_ROLE === "Admin") {
      try {
        var reassigns = await api("/api/deliverables/reassignment-requests?status=pending");
        var dueDateReqs = await api("/api/deliverables/due-date-requests?status=pending");
        var smeNoms = await api("/api/departments/sme-nominations?status=pending");
        document.getElementById("followupBadge").textContent = (reassigns.length + dueDateReqs.length + smeNoms.length) || "";
      } catch (e) {}
    } else {
      document.getElementById("followupBadge").textContent = "";
    }
  }

  /* ================= DELIVERABLE DETAIL MODAL ================= */
  document.getElementById("delivModalClose").addEventListener("click", closeDelivModal);
  document.getElementById("delivModalOverlay").addEventListener("click", function (e) {
    if (e.target.id === "delivModalOverlay") closeDelivModal();
  });
  function closeDelivModal() { document.getElementById("delivModalOverlay").hidden = true; }

  // Item [checkmark tofu fix]: the Unicode check mark character (U+2713)
  // was rendering as a fallback "tofu" box in the bold .fs-dot font weight
  // instead of an actual check -- not every font/weight combination ships
  // a glyph for it. An inline SVG stroke path renders identically
  // everywhere, no font glyph lookup involved. Sized in `em` (not a fixed
  // px) so it scales with .fs-dot's own font-size, which is what already
  // differs between the real 40px stepper and the tour's 26px mock version.
  // Declared here, before TOUR_STEPS, because TOUR_STEPS's array literal
  // calls milestoneMock() immediately at load time -- a plain `var` below
  // TOUR_STEPS would still be hoisted, but its assignment wouldn't have run
  // yet, so milestoneMock would see it as undefined the first time.
  // Item [checkmark still boxy]: a *stroked* path (round caps + round join)
  // was the culprit -- at the small rendered size the thick rounded ends
  // and the joint blob together into something that reads as a chunky
  // square rather than a crisp check. Switched to a *filled* checkmark
  // shape (a single solid polygon, no stroke-width/cap/join at all to go
  // wrong) -- but the Material check glyph turned out to have the same
  // problem one level up: it's a stocky, near-square silhouette by design
  // (built to fill a square icon grid solidly), so at ~14px it still read
  // as a blob/box rather than a tick. Swapped for a thinner, more
  // elongated checkmark (FontAwesome's, tall aspect ratio) whose silhouette
  // doesn't approximate a square at any render size.
  var FS_CHECK_SVG = '<svg width="0.95em" height="1.1em" viewBox="0 0 448 512" fill="currentColor">' +
    '<path d="M438.6 105.4c12.5 12.5 12.5 32.8 0 45.3l-256 256c-12.5 12.5-32.8 12.5-45.3 0l-128-128c-12.5-12.5-12.5-32.8 0-45.3s32.8-12.5 45.3 0L160 338.7 393.4 105.4c12.5-12.5 32.8-12.5 45.3 0z"/></svg>';

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
        '<div class="tour-flow-strip">' +
        '<span class="stage-badge l0">&#128196; L0 &middot; Tendering</span>' +
        '<span class="tour-flow-arrow">&#8594;</span>' +
        '<span class="stage-badge l1">&#128294; L1 &middot; Early Execution</span>' +
        "</div>" +
        '<p class="tour-step-text">The <b>L0/L1 System</b> is Algihaz\'s control framework for managing the ' +
        "full tender-to-early-execution lifecycle, from tender announcement at <b>L0</b>, through " +
        "lowest-price notification, and into the early project execution stage at <b>L1</b>.</p>" +
        '<p class="tour-step-text">Since its official launch in <b>December 2024</b>, the system has evolved ' +
        "from a set of Excel-based tracking sheets into a structured, cross-functional framework for " +
        "deliverable ownership, deadline control, stakeholder coordination, performance monitoring, and " +
        "management visibility. The system is now also expanding to support international L0/L1 " +
        "tenders.</p>" +
        '<p class="tour-step-text">This walkthrough covers where the system came from, how the two stages ' +
        "work, and how to actually use this portal day to day. Seventeen short steps &#8212; use Next/Back " +
        "or the dots below.</p>",
    },
    {
      eyebrow: "The Story So Far",
      title: "System Implementation Timeline",
      body:
        '<p class="tour-step-text">Rolled out in stages since <b>Aug 2024</b>, official operation launched ' +
        "<b>Dec 2024</b>, now running <b>343 L0 tenders</b> and <b>45 L1 projects</b> through it, with " +
        "International L0/L1 Development and a New L1 Model both already underway.</p>" +
        '<div class="tt-layout">' +
        '<div class="tt-steps">' +
        '<div class="tt-step">Developed new Procedure along with a defined scheme</div>' +
        '<div class="tt-step">Engaged key departments for input and collaboration</div>' +
        '<div class="tt-step">Obtained Management Approvals</div>' +
        '<div class="tt-step pilot">Ran a pilot for testing' +
        '<div class="tt-step-aside"><span class="tt-aside-dot"></span>NAJRAN BSP L1 Stage</div></div>' +
        '<div class="tt-step">Conducted Introduction meetings and explained the process and objectives</div>' +
        '<div class="tt-step">Received and Evaluated Quality of deliverables</div>' +
        '<div class="tt-step">Tracked departments\' response proposed timeline</div>' +
        "</div>" +
        '<div class="tour-timeline">' +
        '<div class="tt-axis">' +
        '<span style="left:0%;">Aug 24</span>' +
        '<span style="left:18%;">Dec 24</span>' +
        '<span style="left:40%;">May 25</span>' +
        '<span style="left:55%;">Sep 25</span>' +
        '<span style="left:75%;">Feb 26</span>' +
        '<span style="left:88%;">Apr 26</span>' +
        '<span style="left:100%;" class="today">Today</span>' +
        "</div>" +
        '<div class="tt-track">' +
        '<div class="tt-callout-tag" style="left:9%;" title="Analyzed departments\' willingness to adapt the new system">Analyzed depts.\' willingness</div>' +
        '<div class="tt-bar row0 orange" style="left:0%;width:18%;" title="Standard L0/L1 Development">Standard L0/L1 Development</div>' +
        '<div class="tt-bar row1 green" style="left:3%;width:13%;" title="Pilot &#8211; NAJRAN BSP (L1 Stage)">Pilot &#8211; NAJRAN BSP (L1)</div>' +
        '<div class="tt-marker" style="left:18%;"><div class="tt-dot"></div><div class="tt-lbl">Official Operation Launched</div></div>' +
        '<div class="tt-bar row0 orange" style="left:40%;width:15%;" title="International L0/L1 Development">International L0/L1 Development</div>' +
        '<div class="tt-bar row0 green" style="left:75%;width:13%;" title="New L1 Model Development">New L1 Model Development</div>' +
        "</div>" +
        '<div class="tt-detail-grid">' +
        '<div class="tt-detail orange"><b>Standard L0/L1 Development</b><ul>' +
        "<li>Recurring one-on-one meetings set up with all departments</li>" +
        "<li>Shared workflow diagram of deliverables for departments</li>" +
        "<li>Shared folder set up with a tree matching the deliverables</li>" +
        "<li>Follow-up framework implemented to address delays or lack of response</li>" +
        "</ul></div>" +
        '<div class="tt-detail orange"><b>International L0/L1 Development</b><ul>' +
        "<li>Initiated development of the International Projects System</li>" +
        "<li>Prepared a new version of the L0/L1 stages for international projects</li>" +
        "<li>Introduced a new stage &#8212; &quot;L-Pre Stage&quot;</li>" +
        "<li>Conducted workshops with every involved department</li>" +
        "<li>Gathering feedback and refining the final outputs</li>" +
        "</ul></div>" +
        "</div>" +
        '<div class="tt-stats">' +
        '<div class="tt-stat">343&times;<span>L0 Projects</span></div>' +
        '<div class="tt-stat dark">45&times;<span>L1 Projects</span></div>' +
        "</div>" +
        "</div>" +
        "</div>",
    },
    {
      eyebrow: "How It Works · L0",
      title: "Tendering Stage",
      body:
        '<p class="tour-step-text">A tender opens at <b>L0 Announcement (M1)</b>. Site visit, pre-bid meeting, ' +
        "and pre-bid clarification deadlines get announced, and every department (Operations, " +
        "Supply Chain, Engineering, Planning/Cost Control, Contract, HR, Finance, SHEQ, IT, Risk, " +
        "Fleet/FM) prepares its own deliverables in parallel with predefined, agreed-upon due dates. " +
        "The <b>Project Schedule (M3)</b> anchors most department due dates. Technical offers circulate " +
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
      title: "Early Execution Stage / Post-Bid Stage",
      body:
        '<p class="tour-step-text">Once we receive a notification from the client that Algihaz is L1, the ' +
        "tender enters a new stage called <b>L1 Stage</b>, which goes through several milestones as " +
        "follows: <b>L1 Announcement (M1)</b>, an <b>Early Mobilization Plan (M2)</b>, then full " +
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
      eyebrow: "How It Works",
      title: "Owner & SME — Submit, Review, Approve",
      body:
        '<p class="tour-step-text">Every deliverable has an <b>Owner</b> (does the work) and one or more ' +
        "<b>SME</b>s (reviews it) &#8212; assigned by default from the catalog, or reassigned to " +
        "someone else via an Admin-approved request. The cycle between them is the same for every " +
        "single item on the platform:</p>" +
        '<div class="mock-fs">' +
        milestoneMock([
          ["1", "Owner Submits", true], ["2", "SME Reviews", false, true],
          ["3", "Approved", false],
        ]) +
        "</div>" +
        '<ul class="tour-list">' +
        "<li>The Owner submits by <b>uploading a file</b>, or by <b>Mark Completed</b> with just a " +
        "comment when there's genuinely no document to attach</li>" +
        "<li>That moves it to <b>Pending SME Review</b> &#8212; the assigned SME(s) get notified, with " +
        "a day to act before it's flagged as slow to review</li>" +
        "<li>The SME <b>Approves</b> it (Completed, credited under Calculation Criteria) or " +
        "<b>Rejects</b> it with a comment explaining why</li>" +
        "<li>A rejection sends it right back to the Owner &#8212; fixing it and resubmitting starts " +
        "the same review cycle over again</li>" +
        "</ul>" +
        '<div class="tour-callout">&#128203; If an SME marks their own item Completed directly, it skips ' +
        "the review step entirely &#8212; there's no reviewing yourself. Every step, on every item, is " +
        "recorded in a full activity log, and anyone (not just the Owner/SME) can follow an item to " +
        "get notified of updates.</div>",
    },
    {
      eyebrow: "Tracking & Scoring",
      title: "Two Independent Status Axes",
      body:
        '<p class="tour-step-text">Every deliverable is tracked on <b>two separate axes</b>, not one merged ' +
        "status. <b>Progress</b> is how far the work itself has gotten; <b>Deadline</b> is where it " +
        "stands against its due date &#8212; a deliverable can be In Progress and also Due, or " +
        "Completed and also Late, at the same time.</p>" +
        '<div class="modal-section-title" style="margin:0 0 6px;">Progress</div>' +
        pillLegendMock([
          ["neutral", "No Progress Yet"], ["warn", "In Progress"], ["warn", "Pending SME Review"],
          ["good", "Completed"], ["crit", "Rejected"],
        ]) +
        '<div class="modal-section-title">Deadline</div>' +
        pillLegendMock([
          ["neutral", "Not Due"], ["crit", "Due"], ["good", "On Time"], ["good", "Early"],
          ["crit", "Late"], ["warn", "On Hold"],
        ]) +
        '<div class="tour-callout">&#128161; Not Required and Pending BM Triage sit outside both axes ' +
        "entirely &#8212; there's nothing to track a deadline against until the item is even confirmed " +
        "applicable.</div>",
    },
    {
      eyebrow: "Tracking & Scoring",
      title: "Calculation Criteria",
      body:
        '<p class="tour-step-text">Once a deliverable is Completed, it earns a point value based on exactly ' +
        "how it landed against its due date &#8212; this is what feeds the Performance and Top " +
        "Achievers rankings.</p>" +
        '<table class="tour-table"><thead><tr><th>Timing</th><th>Points</th></tr></thead><tbody>' +
        tourPtsRow("good", "Early", "1.1 pts &#8211; a 10% bonus") +
        tourPtsRow("good", "On Time", "1.0 pts") +
        tourPtsRow("warn", "1&#8211;7 days late", "0.9 pts") +
        tourPtsRow("warn", "8&#8211;14 days late", "0.8 pts") +
        tourPtsRow("crit", "15&#8211;21 days late", "0.7 pts") +
        tourPtsRow("crit", "22&#8211;28 days late", "0.6 pts") +
        tourPtsRow("crit", "Not submitted in time", "0 pts") +
        "</tbody></table>" +
        '<div class="tour-callout">&#128202; The exact point value earned shows right on the deliverable ' +
        "once it's Completed &#8212; in its own row and inside its detail popup, not just buried in a " +
        "report.</div>",
    },
    {
      eyebrow: "Tracking & Scoring",
      title: "Performance & Top Achievers",
      body:
        '<p class="tour-step-text">Every Calculation Criteria point rolls up into <b>Performance</b> &#8212; ' +
        "on-time-rate rankings by department and by person, split by L0/L1, with a trend chart of how " +
        "each has moved over time. <b>Top Achievers</b> highlights the best-performing Owners and " +
        "SMEs specifically.</p>" +
        '<div class="mock-window"><div class="mock-titlebar"><div class="mock-dot-3"></div>' +
        '<div class="mock-dot-3"></div><div class="mock-dot-3"></div><span>Performance</span></div>' +
        rankRowMock(1, "Tendering Department", 92) +
        rankRowMock(2, "Engineering Department", 81) +
        rankRowMock(3, "Planning", 74) +
        "</div>" +
        '<div class="tour-callout">&#9881; An Admin can turn individual catalog items on or off for scoring ' +
        "via <b>Manage Tracking</b> &#8212; not every item should count toward the same on-time-rate " +
        "(a milestone-linked date, for instance, might not).</div>",
    },
    {
      eyebrow: "Requests & Reminders",
      title: "Automated Reminders",
      body:
        '<p class="tour-step-text">A nightly check runs automatically, no one has to remember to send ' +
        "anything:</p>" +
        '<div class="tour-feature-list">' +
        featureRowMock("&#9200;", "accent", "1 Day Before It's Due", "Owners get a heads-up nudge before the deadline hits.") +
        featureRowMock("&#128293;", "crit", "Escalating When Overdue", "Reminders repeat at <b>2, 7, and 14 days</b> late.") +
        featureRowMock("&#128231;", "good", "Batched, Not Spammed", "Several items due the same day become <b>one email per Owner</b>, not one per item.") +
        featureRowMock("&#129309;", "warn", "Extension or Hold", "Can't hit a date? Request an <b>Extension</b> (move it) or a <b>Hold</b> (pause lateness for missing data/a blocker) &#8212; goes to the SME or an Admin to decide, and nudges again after <b>3 days</b> if nobody has.") +
        "</div>" +
        '<p class="tour-step-text">Every reminder links straight to the exact item, and lives in its own ' +
        '<b>Reminders</b> tab &#8212; kept separate from Announcements so day-to-day news and ' +
        "\"you need to act on this\" nudges don't get mixed together.</p>",
    },
    {
      eyebrow: "Around the Portal",
      title: "Announcements",
      body:
        '<p class="tour-step-text">The general program news feed, not the action-oriented one covered on ' +
        "the last slide. Every one of these is logged automatically as it happens:</p>" +
        '<div class="mock-window"><div class="mock-titlebar"><div class="mock-dot-3"></div>' +
        '<div class="mock-dot-3"></div><div class="mock-dot-3"></div><span>Announcements</span></div>' +
        '<div class="mock-ann-list" style="margin:12px;">' +
        announcementRowMock("&#127942;", "M3 Reached &#8211; Handing Over", "Est-1553 milestone M3 has been reached.") +
        announcementRowMock("&#9989;", "Deliverable Approved", "6.1 Prepare Temporary Project Budget was reviewed and approved.") +
        announcementRowMock("&#128276;", "New L1 Stage Commenced", "Est-1553 has entered L1. Deliverables for M1 &amp; M2 attached.") +
        "</div></div>" +
        '<ul class="tour-list">' +
        "<li>A new L0 tender announced, or a project entering L1</li>" +
        "<li>A milestone reached, or the Bid Submission Date extended</li>" +
        "<li>A document added, or a deliverable approved</li>" +
        "<li>A cross-department unlock &#8212; a predecessor being approved just freed up someone " +
        "else's item</li>" +
        "</ul>" +
        '<p class="tour-step-text">Org-wide items like these are visible to <b>everyone</b> regardless of ' +
        "role; anything addressed to specific people (a rejection, an assignment) stays private to " +
        "them and Admin. Filter by type or date to find something specific.</p>",
    },
    {
      eyebrow: "Around the Portal",
      title: "BM Triage",
      body:
        '<p class="tour-step-text">Not every catalog item applies to every tender. When a new L0 tender is ' +
        "created, its <b>Bid Manager</b> gets a short list to mark <b>Applicable</b> or <b>Not " +
        "Required</b> before real tracking starts &#8212; and has <b>24 hours</b> to do it, or the " +
        "platform blocks further action with a reminder until it's done.</p>" +
        '<div class="mock-window"><div class="mock-titlebar"><div class="mock-dot-3"></div>' +
        '<div class="mock-dot-3"></div><div class="mock-dot-3"></div><span>BM Triage Status</span></div>' +
        '<div class="mock-deliv-list" style="margin:12px;">' +
        deliverableMock("Est-1782", "132kV Substation &#8211; Riyadh", "good", "Done") +
        deliverableMock("Est-1801", "OHTL Corridor &#8211; Jazan", "warn", "Reminded") +
        deliverableMock("Est-1804", "GIS Package &#8211; Dammam", "crit", "Pending") +
        "</div></div>" +
        '<div class="tour-callout">&#9989; Every active tender\'s triage progress shows in one place, so an ' +
        "Admin can see at a glance who's still holding things up.</div>",
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
        '<div class="mock-stat-row-label">Deliverables Deadline Status</div>' +
        '<div class="mock-stat-row">' +
        statMock("Not Due", "508", "neutral") + statMock("Due", "36", "warn") + statMock("Early", "6", "good") +
        statMock("On Time", "0", "good") + statMock("Late", "5", "crit") +
        "</div>" +
        '<div class="mock-stat-row-label">Deliverables Progress Status</div>' +
        '<div class="mock-stat-row">' +
        statMock("No Progress Yet", "285", "neutral") + statMock("In Progress", "0", "warn") + statMock("Pending SME Review", "0", "warn") +
        statMock("Completed", "11", "good") + statMock("Rejected", "2", "crit") +
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
        "regular deliverables, and a live <b>Today</b> line shows exactly where the project stands " +
        "right now.</p>" +
        '<div class="mock-window"><div class="mock-titlebar"><div class="mock-dot-3"></div>' +
        '<div class="mock-dot-3"></div><div class="mock-dot-3"></div><span>Timeline</span></div>' +
        '<div class="mock-body mock-gantt-wrap" style="padding:10px 14px;">' +
        '<div class="mock-gantt-today" style="left:calc(96px + 8px + (100% - 104px) * .5);"></div>' +
        ganttRowMock("1.1 Announcement", 4, 10, "neutral", true) +
        ganttRowMock("1.7 Estimate Program", 8, 34, "crit", false) +
        ganttRowMock("2.4 Risk Register", 22, 26, "warn", false) +
        ganttRowMock("3.5 PO Approval", 34, 20, "warn", false) +
        ganttRowMock("5.3 Project Schedule", 30, 40, "good", true) +
        ganttRowMock("6.1 Temp. Budget", 48, 18, "neutral", false) +
        "</div></div>",
    },
    {
      eyebrow: "Around the Portal · Admin",
      title: "Follow Up",
      body:
        '<p class="tour-step-text">The Admin triage hub for everything that needs a nudge or a decision, in ' +
        "one place:</p>" +
        '<div class="mock-window"><div class="mock-titlebar"><div class="mock-dot-3"></div>' +
        '<div class="mock-dot-3"></div><div class="mock-dot-3"></div><span>Follow Up</span></div>' +
        '<div class="fu-stats" style="padding:12px 14px;">' +
        '<div class="fu-stat critical"><span class="fu-stat-num">12</span><span class="fu-stat-lbl">Critical</span></div>' +
        '<div class="fu-stat"><span class="fu-stat-num">36</span><span class="fu-stat-lbl">Overdue Total</span></div>' +
        '<div class="fu-stat"><span class="fu-stat-num">4</span><span class="fu-stat-lbl">Depts Affected</span></div>' +
        "</div>" +
        '<details class="fu-dept-group" open><summary><span class="fu-dept-name">Engineering Department</span>' +
        '<span class="fu-dept-tags"><span class="fu-dept-count has-critical">5 overdue</span></span></summary>' +
        '<div class="fu-row"><div class="fu-row-main"><div class="fu-row-title">4.3 &middot; Site Investigation Requirements</div>' +
        '<div class="fu-row-sub"><span>Est-1553</span><span class="sep">&middot;</span><span>Owner: A.Rahman</span></div></div>' +
        '<div class="fu-row-side"><span class="fu-overdue-badge critical">18 days overdue</span></div></div>' +
        "</details>" +
        '<details class="fu-dept-group"><summary><span class="fu-dept-name">Supply Chain</span>' +
        '<span class="fu-dept-tags"><span class="fu-dept-count">3 overdue</span></span></summary></details>' +
        "</div>" +
        '<ul class="tour-list">' +
        "<li>Pending <b>Due-Date Requests</b> (Extensions &amp; Holds) awaiting a decision</li>" +
        "<li>Pending <b>Reassignment Requests</b> &#8212; an Owner asking to hand an item to someone else</li>" +
        "<li>Every <b>overdue deliverable</b> across the whole portal, grouped by department, most " +
        "overdue first, with a Critical (15+ days) severity filter</li>" +
        "</ul>" +
        '<div class="tour-callout">&#128276; Remind one stubborn item, or send to everyone currently shown ' +
        "&#8212; both are one click, and each department's group stays collapsed until you open it so " +
        "the page isn't a wall of rows.</div>",
    },
    {
      eyebrow: "Around the Portal",
      title: "Ask the Team",
      body:
        '<p class="tour-step-text">A question about a specific tender, project or deliverable doesn\'t have ' +
        "to go through email or chat &#8212; raise it straight to the Admins from inside the portal, " +
        "and track it in your own <b>My Requests</b> list.</p>" +
        '<div class="mock-window"><div class="mock-titlebar"><div class="mock-dot-3"></div>' +
        '<div class="mock-dot-3"></div><div class="mock-dot-3"></div><span>Open Questions</span></div>' +
        '<div class="mock-deliv-list" style="margin:12px;">' +
        deliverableMock("Est-1553", "Why is item 5.3 still showing as pending?", "warn", "Open") +
        deliverableMock("Est-1620", "Can we get the KB link for the BSD extension rules?", "good", "Resolved") +
        "</div></div>" +
        '<p class="tour-step-text">Admins see every open thread in one place under <b>Open Questions</b>, ' +
        "reply (optionally pulling in a saved Knowledge Base answer instead of retyping the same " +
        "explanation), and mark it resolved &#8212; you get notified the moment they do.</p>",
    },
    {
      eyebrow: "You're Ready",
      title: "Finding Your Way Around",
      body:
        '<p class="tour-step-text">Quick reference for the rest of the nav:</p>' +
        '<div class="tour-feature-list">' +
        featureRowMock("&#128194;", "accent", "L0 Tenders / L1 Projects / Timeline", "The full project lists and the pooled Gantt view.") +
        featureRowMock("&#128203;", "accent", "Assigned Deliverables", "Every deliverable assigned to you, filterable by L0/L1 and status.") +
        featureRowMock("&#128276;", "good", "Announcements", "General program news, filterable by type and date.") +
        featureRowMock("&#9200;", "warn", "Reminders", "Everything that needs your action: due-soon/overdue nudges, request updates.") +
        featureRowMock("&#9989;", "good", "BM Triage Status", "Every active tender's applicable/not-required progress.") +
        featureRowMock("&#128200;", "accent", "Performance", "On-time-rate tracking by department, feeding Top Achievers.") +
        featureRowMock("&#128172;", "accent", "Q/A &#8211; Ask the Team", "Raise a question, track your own requests.") +
        featureRowMock("&#128736;", "crit", "Admin Only", "Reports, Top Achievers, Focal Points, Follow Up, Open Questions.") +
        "</div>" +
        '<div class="tour-callout">&#127881; That\'s the full picture &#8212; close this and start ' +
        "exploring. You can reopen this walkthrough anytime from the nav.</div>",
    },
  ];

  function statMock(label, value, tone) {
    return '<div class="mock-stat' + (tone ? " tone-" + tone : "") + '"><div class="label">' + label +
      '</div><div class="value">' + value + "</div></div>";
  }
  function tourPtsRow(tone, timing, pts) {
    return '<tr><td><span class="tour-dot-ic ' + tone + '"></span><b>' + timing + "</b></td><td>" + pts + "</td></tr>";
  }
  function featureRowMock(icon, tone, label, desc) {
    return '<div class="tour-feature-row"><div class="tour-feature-ic ' + tone + '">' + icon + "</div>" +
      "<div><b>" + label + '</b><div class="tour-feature-desc">' + desc + "</div></div></div>";
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
      return '<div class="' + cls + '" style="flex:1;"><div class="fs-dot" style="width:36px;height:36px;font-size:12px;">' +
        (done ? FS_CHECK_SVG : code) + '</div><div class="fs-label">' + label + "</div></div>";
    }).join("");
  }
  // Item [walkthrough expansion]: a real-pill legend row for slides
  // explaining a status vocabulary (Progress/Deadline) -- same .pill markup
  // the live app renders, just laid out as a reference strip instead of on
  // a live deliverable.
  function pillLegendMock(items) {
    return '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px;">' +
      items.map(function (it) {
        return '<span class="pill ' + it[0] + '"><span class="dot"></span>' + it[1] + "</span>";
      }).join("") + "</div>";
  }
  // Item [walkthrough expansion]: same .rank-row/.rank-bar-fill markup the
  // real Reports/Top Achievers page renders, just fed illustrative numbers.
  function rankRowMock(rank, name, pct) {
    return '<div class="rank-row"><div class="rank-num">' + rank + '</div>' +
      '<div class="rank-name">' + name + '</div>' +
      '<div class="rank-bar-track"><div class="rank-bar-fill" style="width:' + pct + '%;"></div></div>' +
      '<div class="rank-val">' + pct + '%</div></div>';
  }
  function announcementRowMock(icon, title, body) {
    return '<div class="mock-ann-row"><div class="mock-ann-ic">' + icon + '</div>' +
      '<div><div class="mock-ann-title">' + title + '</div><div class="mock-ann-body">' + body + "</div></div></div>";
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
  function closeTour() {
    document.getElementById("tourOverlay").hidden = true;
    // The "L0/L1 History" nav item has no real page of its own -- it just
    // opens this modal (see loadJourney) -- so closing it while that's the
    // active view would otherwise strand the user on its bare fallback
    // screen (an empty background with just a "reopen" button). Land back
    // on the Dashboard instead, same as if they'd navigated there directly.
    if (!document.getElementById("view-journey").hidden) switchView("dashboard");
  }
  document.getElementById("tourStartBtn").addEventListener("click", function () { openTour(false); });
  document.getElementById("tourClose").addEventListener("click", closeTour);
  document.getElementById("tourPrev").addEventListener("click", function () {
    if (tourStep > 0) { tourStep--; renderTourStep(); }
  });
  document.getElementById("tourNext").addEventListener("click", function () {
    if (tourStep < TOUR_STEPS.length - 1) { tourStep++; renderTourStep(); return; }
    // Reaching the last slide via "Next" already leaves it on screen to
    // read -- clicking "Done" itself is the real "I'm finished" action, so
    // it closes the tour exactly like the X does (same dashboard-redirect
    // logic in closeTour() if it was opened from the Walkthrough tab).
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
    var authorized = isAssigned({ owner_emails: d.owner_emails, sme_emails: d.sme_emails });
    var body = document.getElementById("delivModalBody");
    body.innerHTML = "";

    var meta = el("div", "modal-meta-grid");
    // Item 134 rework: SME is no longer editable from here -- it's set as
    // a catalog default in Focal Points instead, so every new project
    // picks it up automatically rather than being patched one project at
    // a time from this popup.
    var metaRows = [["Owner", (d.owner_emails && d.owner_emails.length) ? d.owner_emails.join(", ") : "&#8213;"], ["SME", (d.sme_emails && d.sme_emails.length) ? d.sme_emails.join(", ") : "&#8213;"],
     ["Due Date", dueDateHtml(d)],
     ["Status", statusPillsHtml(d)]];
    // Item [early bonus]: once Completed, show the real point value earned
    // under the Calculation Criteria, not just the pass/fail status pill.
    if (d.points_earned !== null && d.points_earned !== undefined) {
      metaRows.push(["Points Earned", pointsEarnedLabel(d.points_earned)]);
    }
    metaRows.forEach(function (m) {
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

    // Item [closed-project bug]: this modal is a separate render path from
    // the deliverables list row (renderDeliverables), which already hides
    // every state-changing button once currentProjectTerminal is true --
    // this one had no matching check at all, so an Owner could still
    // upload against a closed project through the modal even though the
    // list row correctly showed it as read-only. Gate on the project's own
    // terminal flag from this deliverable's own API response (not the
    // module-level currentProjectTerminal, which reflects whichever
    // project openDetail last loaded and can be wrong here -- this modal
    // is also reachable via a deep link or the Assigned Deliverables list,
    // without openDetail ever having run for this item's own project).
    if (d.project_terminal) {
      actionsRow.appendChild(el("span", "locked-note", "&#128274; Project closed &#8212; read-only"));
    } else {

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
            body: JSON.stringify({ to_email: toEmail, reason: reason, from_email: (d.owner_emails || []).join(", ") }),
          });
        } catch (err) {
          showToast("Could not request reassignment – " + apiErrorDetail(err), true);
          return;
        }
        showToast("Reassignment requested — pending admin approval");
      });
      actionsRow.appendChild(reassignBtn);
    }

    // Item [due-date requests]: Owner (or Admin) can ask for more time or
    // flag a blocker, subject to SME/Admin approval -- only while there's
    // no request already pending and the item isn't already on hold.
    var canRequestDueDateChange = (d.status === "no_progress" || d.status === "in_progress" || d.status === "rejected")
      && !d.pending_due_date_request && !d.on_hold;
    if (authorized && canRequestDueDateChange && can("upload")) {
      var itemLabel = d.item_no + " &middot; " + d.name;
      var extendBtn2 = el("button", "btn", "Request Extension");
      extendBtn2.addEventListener("click", function () { openDueDateRequestModal(d.id, "extension", itemLabel, refreshModal); });
      var holdBtn = el("button", "btn", "Put On Hold");
      holdBtn.addEventListener("click", function () { openDueDateRequestModal(d.id, "hold", itemLabel, refreshModal); });
      actionsRow.appendChild(extendBtn2); actionsRow.appendChild(holdBtn);
    }

    // Assigned SME or Admin decides a pending extension/hold request --
    // same can("review") gate Confirm Completion/Send Back uses above,
    // matching the backend's rules.can_act(..., resolve_smes(sub)) (Admin
    // passes automatically).
    if (authorized && d.pending_due_date_request && can("review")) {
      var req = d.pending_due_date_request;
      var label = req.kind === "extension" ? "Extension" : "Hold";
      var approveBtn = el("button", "btn primary", "Approve " + label);
      approveBtn.addEventListener("click", async function () {
        try {
          await api("/api/deliverables/due-date-requests/" + req.id + "/decide", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approved: true, comment: "", actor_role: CURRENT_ROLE, actor_email: actingEmail() }),
          });
        } catch (err) {
          showToast("Could not approve &#8211; " + apiErrorDetail(err), true);
          return;
        }
        showToast(label + " approved");
        refreshModal();
      });
      var rejectBtn = el("button", "btn ghost-crit", "Reject " + label);
      rejectBtn.addEventListener("click", async function () {
        var comment = prompt("Reason for rejecting (optional):", "") || "";
        try {
          await api("/api/deliverables/due-date-requests/" + req.id + "/decide", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approved: false, comment: comment, actor_role: CURRENT_ROLE, actor_email: actingEmail() }),
          });
        } catch (err) {
          showToast("Could not reject &#8211; " + apiErrorDetail(err), true);
          return;
        }
        showToast(label + " rejected");
        refreshModal();
      });
      actionsRow.appendChild(approveBtn); actionsRow.appendChild(rejectBtn);
    }

    // Owner (or Admin) ends an active hold.
    if (authorized && d.on_hold && can("upload")) {
      var resumeBtn = el("button", "btn primary", "Resume");
      resumeBtn.addEventListener("click", async function () {
        try {
          await api("/api/deliverables/" + d.id + "/resume?actor_role=" + encodeURIComponent(CURRENT_ROLE) +
            "&actor_email=" + encodeURIComponent(actingEmail()), { method: "POST" });
        } catch (err) {
          showToast("Could not resume &#8211; " + apiErrorDetail(err), true);
          return;
        }
        showToast(d.item_no + " resumed");
        refreshModal();
      });
      actionsRow.appendChild(resumeBtn);
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

    } // !d.project_terminal

    var isOwnerOrAdmin = CURRENT_ROLE === "Admin" ||
      (actingEmail() && (d.owner_emails || []).map(function (e) { return (e || "").trim().toLowerCase(); }).indexOf(actingEmail().trim().toLowerCase()) !== -1);
    // Item 108: reopening a Not Required item undoes an admin's earlier
    // call, so it's admin-only — symmetric with markNotRequiredButton's
    // own gating, unlike the approved case which the owner can also do.
    var canReopen = (d.status === "approved" && isOwnerOrAdmin) || (d.status === "not_required" && CURRENT_ROLE === "Admin");
    if (canReopen) {
      var reopenBtn = el("button", "btn ghost-crit", "Reopen");
      reopenBtn.addEventListener("click", async function () {
        var confirmMsg = d.status === "not_required"
          ? "It'll go back into the normal workflow and need a submission again."
          : "It'll go back into the normal workflow for more work.";
        if (!(await customConfirm(confirmMsg, { title: "Reopen " + d.item_no + "?", danger: true, okLabel: "Reopen" }))) return;
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
    // Admin escape hatch: downstream predecessor-chained items anchor off
    // this deliverable's real completion date (reviewed_at), not its
    // planned due_date -- if that recorded date is wrong (test/placeholder
    // data, a mis-set approval) it silently pulls every dependent item's
    // schedule along with it. Lets an admin correct it directly rather than
    // Reopen + re-approve just to fix a date.
    if (CURRENT_ROLE === "Admin" && d.status === "approved") {
      var editCompletionBtn = el("button", "btn", "Edit Completion Date");
      editCompletionBtn.addEventListener("click", function () {
        openChecklistEditModal({
          type: "date",
          title: "Edit Completion Date",
          eyebrow: "Items chained off " + d.item_no + " recompute their due dates from this date.",
          selected: d.reviewed_at ? d.reviewed_at.slice(0, 10) : "",
          onSave: function (nextDate) {
            if (!nextDate) { showToast("Pick a date", true); return; }
            api("/api/deliverables/" + d.id + "/completion-date", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ completion_date: nextDate, actor_role: CURRENT_ROLE, actor_email: actingEmail() }),
            }).then(function () {
              closeChecklistEditModal();
              showToast("Completion date updated");
              refreshModal();
            }).catch(function (err) { showToast("Could not update &#8211; " + apiErrorDetail(err), true); });
          },
        });
      });
      actionsRow.appendChild(editCompletionBtn);
    }
    body.appendChild(actionsRow);

    // Item 143 (2nd revision): workflow nudges -- a reminder to close out
    // once documents are in, or while waiting on the SME's confirmation.
    if (authorized && d.on_hold) {
      body.appendChild(el("div", "modal-hint", "On hold" + (d.hold_reason ? " &#8211; " + d.hold_reason : "") + "."));
    } else if (authorized && d.pending_due_date_request) {
      var pr = d.pending_due_date_request;
      body.appendChild(el("div", "modal-hint",
        (pr.kind === "extension" ? "Extension" : "Hold") + " requested" +
        (pr.kind === "extension" && pr.requested_due_date ? " (new date: " + fmtDate(pr.requested_due_date) + ")" : "") +
        " &#8211; awaiting SME/Admin decision. &#8220;" + pr.reason + "&#8221;"));
    } else if (authorized && d.status === "in_progress") {
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

  // Item [due-date requests]: Owner's Request Extension / Put On Hold form --
  // a proper small modal (date + reason) rather than the raw prompt()
  // dialogs the older Reassign button still uses, reusing the same
  // .modal-card/.modal-body shell as the checklist-edit modal.
  function openDueDateRequestModal(submissionId, kind, itemLabel, onDone) {
    var isExtension = kind === "extension";
    document.getElementById("dueDateRequestEyebrow").textContent = itemLabel;
    document.getElementById("dueDateRequestTitle").textContent = isExtension ? "Request Extension" : "Put On Hold";
    document.getElementById("dueDateRequestDateField").style.display = isExtension ? "" : "none";
    document.getElementById("dueDateRequestDate").value = "";
    var reasonLabel = document.getElementById("dueDateRequestReasonLabel");
    reasonLabel.innerHTML = (isExtension ? "Reason" : "Reason (missing data / technical issue)") + ' <span class="req">*</span>';
    var reasonInput = document.getElementById("dueDateRequestReason");
    reasonInput.value = "";
    var submitBtn = document.getElementById("dueDateRequestSubmit");
    var newSubmitBtn = submitBtn.cloneNode(true); // drop any listener from a previous open
    submitBtn.parentNode.replaceChild(newSubmitBtn, submitBtn);
    newSubmitBtn.addEventListener("click", async function () {
      var reason = reasonInput.value.trim();
      if (!reason) { showToast("A reason is required", true); return; }
      var dateVal = document.getElementById("dueDateRequestDate").value;
      if (isExtension && !dateVal) { showToast("A requested due date is required", true); return; }
      try {
        await api("/api/deliverables/" + submissionId + "/" + kind + "-request", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            reason: reason, requested_due_date: isExtension ? dateVal : null,
            actor_name: CURRENT_ROLE, actor_role: CURRENT_ROLE, actor_email: actingEmail(),
          }),
        });
      } catch (err) {
        showToast("Could not submit request &#8211; " + apiErrorDetail(err), true);
        return;
      }
      document.getElementById("dueDateRequestOverlay").hidden = true;
      showToast((isExtension ? "Extension" : "Hold") + " requested &#8211; pending SME/Admin approval");
      if (onDone) onDone();
    });
    document.getElementById("dueDateRequestOverlay").hidden = false;
  }
  document.getElementById("dueDateRequestClose").addEventListener("click", function () {
    document.getElementById("dueDateRequestOverlay").hidden = true;
  });
  document.getElementById("dueDateRequestCancel").addEventListener("click", function () {
    document.getElementById("dueDateRequestOverlay").hidden = true;
  });

  // Self-service SME nomination (open to everyone, no role/assignment gate --
  // that's the whole point) -- same small-modal shape as the due-date-
  // request form above, just not tied to a submission.
  document.getElementById("becomeSmeBtn").addEventListener("click", function () {
    document.getElementById("smeNomEmail").value = passiveIdentity();
    document.getElementById("smeNomName").value = "";
    document.getElementById("smeNomReason").value = "";
    document.getElementById("smeNomOverlay").hidden = false;
  });
  function closeSmeNomModal() { document.getElementById("smeNomOverlay").hidden = true; }
  document.getElementById("smeNomClose").addEventListener("click", closeSmeNomModal);
  document.getElementById("smeNomCancel").addEventListener("click", closeSmeNomModal);
  document.getElementById("smeNomSubmit").addEventListener("click", async function () {
    var email = document.getElementById("smeNomEmail").value.trim();
    if (!email) { showToast("Email is required", true); return; }
    try {
      await api("/api/departments/sme-nominations", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email,
          name: document.getElementById("smeNomName").value.trim() || null,
          reason: document.getElementById("smeNomReason").value.trim() || null,
        }),
      });
    } catch (err) {
      showToast("Could not submit &#8211; " + apiErrorDetail(err), true);
      return;
    }
    localStorage.setItem("myEmail", email);
    closeSmeNomModal();
    showToast("Nomination submitted &#8211; pending admin approval");
  });

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
    var extendBtn = document.getElementById("dExtendBsdBtn");
    extendBtn.hidden = !(p.stage === "L0" && can("create") && !currentProjectTerminal);
    extendBtn.onclick = function () {
      openChecklistEditModal({
        type: "date",
        title: "Extend Bid Submission Date",
        eyebrow: "Every dependent deliverable due date recalculates automatically, and every user is notified.",
        selected: p.bsd || "",
        onSave: function (nextDate) {
          if (!nextDate) { showToast("Pick a date", true); return; }
          api("/api/projects/" + id + "/details", {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ bsd: nextDate, actor_role: CURRENT_ROLE }),
          }).then(function () {
            closeChecklistEditModal();
            showToast("Bid Submission Date extended &#8211; announced to all users");
            openDetail(id);
          }).catch(function (err) { showToast("Could not update &#8211; " + apiErrorDetail(err), true); });
        },
      });
    };
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
    var l0LinkBtn = document.getElementById("dL0LinkBtn");
    if (p.stage === "L1" && p.l0_source_id) {
      l0LinkBtn.hidden = false;
      l0LinkBtn.onclick = function () { openDetail(p.l0_source_id); };
    } else {
      l0LinkBtn.hidden = true;
    }
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
    var buLabel = (p.business_units && p.business_units.length) ? sortBusinessUnits(p.business_units).join(" / ") : "&#8213;";
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
         ["Region", joinList(p.region), "region"], ["Scope", joinList(p.scope), "scope"], ["Business Unit", buLabel, "bu"],
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
            openChecklistEditModal({
              type: "text",
              title: "Edit RFX Number",
              placeholder: "RFX Number",
              selected: p.rfx_number || "",
              onSave: function (nextRfx) {
                api("/api/projects/" + id + "/details", {
                  method: "PATCH", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ rfx_number: nextRfx || null, actor_role: CURRENT_ROLE }),
                }).then(function () { closeChecklistEditModal(); showToast("RFX updated"); openDetail(id); })
                  .catch(function (err) { showToast("Could not update &#8211; " + apiErrorDetail(err), true); });
              },
            });
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
            openChecklistEditModal({
              title: "Edit Region",
              options: ropts.regions,
              selected: p.region || [],
              hasOther: true,
              otherValue: p.region_other || "",
              onSave: function (regionArr, regionOther) {
                if (!regionArr.length) { showToast("Select at least one Region", true); return; }
                api("/api/projects/" + id + "/details", {
                  method: "PATCH", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ region: regionArr, region_other: regionOther || null, actor_role: CURRENT_ROLE }),
                }).then(function () { closeChecklistEditModal(); showToast("Region updated"); openDetail(id); })
                  .catch(function (err) { showToast("Could not update &#8211; " + apiErrorDetail(err), true); });
              },
            });
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
      // Item [milestone stepper redesign]: the connecting line's filled
      // portion reaches exactly to the last-reached dot's own center, not
      // just some fraction of the row -- same center-of-column math as the
      // dots themselves (col i's center sits at (i+.5)/count of the row),
      // translated into the ::before/::after line's own coordinate space
      // (which starts 4% in from the row edge, per .fs-row::before).
      var progressPct = lastDoneIdx >= 0 ? Math.max(0, ((lastDoneIdx + 0.5) / ms.length) * 100 - 4) : 0;
      stepper.style.setProperty("--fs-progress", progressPct + "%");
      ms.forEach(function (m, i) {
        var cls = "fs-step" + (m.reached ? " done" : (i === lastDoneIdx + 1 ? " current" : ""));
        var step = el("div", cls);
        step.appendChild(el("div", "fs-dot", m.reached ? FS_CHECK_SVG : m.code));
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
    var tenderDocs = await api("/api/projects/" + id + "/tender-documents");
    var deptNames = [];
    allDelivs.forEach(function (d) { if (deptNames.indexOf(d.department) === -1) deptNames.push(d.department); });
    var folders = document.getElementById("dFolders");
    folders.innerHTML = "";
    document.getElementById("dFolderCount").textContent = (deptNames.length + 1) + " total";
    currentDeptOpen = deptNames.length ? deptNames[0] : null;

    // Folder 0: plain project-level file storage, not a department -- no
    // due date, owner, SME, or tracking of any kind, so it's built here as
    // its own row rather than through makeFolderRow/renderDeliverables.
    var tdRow = el("div", "folder-row");
    tdRow.innerHTML =
      '<div class="folder-left"><span class="folder-ic">&#128196;</span><div><div class="folder-name">0. Tender Documents</div>' +
      '<div class="folder-focal">' + tenderDocs.length + " file" + (tenderDocs.length === 1 ? "" : "s") + '</div></div></div>' +
      '<div class="folder-right"></div>';
    tdRow.addEventListener("click", function () {
      document.querySelectorAll(".folder-row").forEach(function (r) { r.classList.remove("active"); });
      tdRow.classList.add("active");
      currentDeptOpen = null;
      document.getElementById("dDeliverTitle").textContent = "Tender Documents";
      renderTenderDocs(tenderDocs, id);
    });
    folders.appendChild(tdRow);

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

  // Item [action-comment-modal]: replaces the native prompt()/confirm()
  // pair used for Mark Completed / Confirm Completion / Send Back with a
  // real, centered modal. Returns a Promise resolving to {comment, file}
  // on Confirm, or null on Cancel/close -- same call shape as the old
  // `var x = prompt(...); if (x === null) return;` pattern it replaces.
  function openActionCommentModal(cfg) {
    return new Promise(function (resolve) {
      document.getElementById("actionCommentTitle").textContent = cfg.title;
      document.getElementById("actionCommentHint").textContent = cfg.hint || "";
      var textEl = document.getElementById("actionCommentText");
      textEl.value = cfg.defaultValue || "";
      textEl.placeholder = cfg.placeholder || "";
      var fileRow = document.getElementById("actionCommentFileRow");
      var fileInput = document.getElementById("actionCommentFile");
      var fileNameEl = document.getElementById("actionCommentFileName");
      fileInput.value = "";
      fileNameEl.textContent = "";
      fileRow.hidden = !cfg.allowFile;
      var confirmBtn = document.getElementById("actionCommentConfirm");
      confirmBtn.textContent = cfg.confirmLabel;
      confirmBtn.className = "btn " + (cfg.confirmVariant === "crit" ? "ghost-crit" : "primary");
      var cancelBtn = document.getElementById("actionCommentCancel");
      var closeBtn = document.getElementById("actionCommentClose");
      var overlay = document.getElementById("actionCommentOverlay");

      function cleanup() {
        overlay.hidden = true;
        confirmBtn.removeEventListener("click", onConfirm);
        cancelBtn.removeEventListener("click", onCancel);
        closeBtn.removeEventListener("click", onCancel);
        fileInput.removeEventListener("change", onFileChange);
      }
      function onFileChange() { fileNameEl.textContent = fileInput.files[0] ? fileInput.files[0].name : ""; }
      function onConfirm() {
        var comment = textEl.value.trim();
        if (cfg.required && !comment) {
          showToast(cfg.requiredMessage || "A comment is required", true);
          return;
        }
        var file = fileInput.files[0] || null;
        cleanup();
        resolve({ comment: comment, file: file });
      }
      function onCancel() { cleanup(); resolve(null); }

      confirmBtn.addEventListener("click", onConfirm);
      cancelBtn.addEventListener("click", onCancel);
      closeBtn.addEventListener("click", onCancel);
      fileInput.addEventListener("change", onFileChange);
      overlay.hidden = false;
      textEl.focus();
    });
  }

  // Item 46 (picker rework): a small reusable edit modal covering every
  // real-picker case this project detail page needs -- checkboxes
  // (Scope/Business Unit/Region), a single dropdown (Bid Manager), a
  // native date input (every anchor date), or a plain text field (RFX) --
  // instead of a free-text prompt() for any of them.
  // cfg.type: "checklist" (default) | "select" | "date" | "text".
  var _checklistEditSave = null;
  function openChecklistEditModal(cfg) {
    document.getElementById("checklistEditEyebrow").textContent = cfg.eyebrow || "";
    document.getElementById("checklistEditTitle").textContent = cfg.title;
    var grid = document.getElementById("checklistEditGrid");
    var otherInput = document.getElementById("checklistEditOtherInput");
    var selectEl = document.getElementById("checklistEditSelect");
    var dateEl = document.getElementById("checklistEditDateInput");
    var textEl = document.getElementById("checklistEditTextInput");
    grid.style.display = "none";
    otherInput.style.display = "none";
    selectEl.style.display = "none";
    dateEl.style.display = "none";
    textEl.style.display = "none";

    if (cfg.type === "text") {
      textEl.value = cfg.selected || "";
      textEl.placeholder = cfg.placeholder || "";
      textEl.style.display = "";
      _checklistEditSave = function () { cfg.onSave(textEl.value.trim()); };
    } else if (cfg.type === "select") {
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

  // Custom-styled replacement for native confirm() -- same modal shell as
  // the rest of the app instead of the browser's own unstyled dialog.
  // Promise-based so call sites just `await customConfirm(...)`.
  var _confirmResolve = null;
  function customConfirm(message, opts) {
    opts = opts || {};
    document.getElementById("confirmTitle").textContent = opts.title || "Are you sure?";
    document.getElementById("confirmMessage").textContent = message;
    var okBtn = document.getElementById("confirmOkBtn");
    okBtn.textContent = opts.okLabel || "OK";
    okBtn.className = "btn " + (opts.danger ? "ghost-crit" : "primary");
    document.getElementById("confirmOverlay").hidden = false;
    return new Promise(function (resolve) { _confirmResolve = resolve; });
  }
  function _settleConfirm(result) {
    document.getElementById("confirmOverlay").hidden = true;
    if (_confirmResolve) { var r = _confirmResolve; _confirmResolve = null; r(result); }
  }
  document.getElementById("confirmOkBtn").addEventListener("click", function () { _settleConfirm(true); });
  document.getElementById("confirmCancelBtn").addEventListener("click", function () { _settleConfirm(false); });
  document.getElementById("confirmClose").addEventListener("click", function () { _settleConfirm(false); });

  // PDFs, images, and text open inline in a browser tab on their own --
  // Office formats (Word/Excel/PowerPoint) never do, regardless of any
  // server header, because browsers simply have no built-in renderer for
  // them and fall back to downloading. Route just those through Microsoft's
  // Office Online viewer (needs a real absolute, publicly-fetchable URL --
  // works on the deployed pilot, not off a bare localhost dev server).
  var _OFFICE_VIEWER_EXTS = ["doc", "docx", "xls", "xlsx", "ppt", "pptx"];
  function tenderDocViewUrl(fileName, fileUrl) {
    var ext = (fileName.split(".").pop() || "").toLowerCase();
    if (_OFFICE_VIEWER_EXTS.indexOf(ext) === -1) return fileUrl;
    var absolute = location.origin + fileUrl;
    return "https://view.officeapps.live.com/op/view.aspx?src=" + encodeURIComponent(absolute);
  }
  // A browser's native file dialog can't offer an in-dialog toggle between
  // picking files vs. a folder -- that choice has to be made before the
  // dialog opens. This is the closest real equivalent to "one button": a
  // single visible button that pops a tiny two-option menu (Files/Folder),
  // each wired to click a real (hidden) <input>, one plain and one
  // webkitdirectory. Reused everywhere a Tender Documents upload control
  // is needed instead of two separate buttons.
  function fileOrFolderButton(label, fileInput, folderInput) {
    var wrap = el("span", "upload-choice-wrap");
    var btn = el("button", "btn", label + " &#9662;");
    btn.type = "button";
    var menu = el("div", "upload-choice-menu");
    var filesOpt = el("button", "upload-choice-opt", "&#128196; Files&#8230;");
    var folderOpt = el("button", "upload-choice-opt", "&#128193; Folder&#8230;");
    filesOpt.type = "button"; folderOpt.type = "button";
    filesOpt.addEventListener("click", function (e) { e.stopPropagation(); menu.classList.remove("open"); fileInput.click(); });
    folderOpt.addEventListener("click", function (e) { e.stopPropagation(); menu.classList.remove("open"); folderInput.click(); });
    menu.appendChild(filesOpt); menu.appendChild(folderOpt);
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      var opening = !menu.classList.contains("open");
      document.querySelectorAll(".upload-choice-menu.open").forEach(function (m) { m.classList.remove("open"); });
      if (opening) menu.classList.add("open");
    });
    document.addEventListener("click", function () { menu.classList.remove("open"); });
    wrap.appendChild(btn); wrap.appendChild(menu);
    return wrap;
  }
  // Uploads a FileList to the given project/folder, one request per file
  // (relative_path carries a folder pick's own structure, see
  // upload_tender_document). Returns the count that actually succeeded.
  async function uploadTenderDocFiles(projectId, fileList, currentPath, isFolder) {
    var ok = 0;
    for (var i = 0; i < fileList.length; i++) {
      var f = fileList[i];
      var rel = isFolder ? f.webkitRelativePath : f.name;
      var fullRel = currentPath ? currentPath + "/" + rel : rel;
      var fd = new FormData();
      fd.append("file", f);
      fd.append("relative_path", fullRel);
      fd.append("actor_name", CURRENT_ROLE + " (pilot)");
      fd.append("actor_role", CURRENT_ROLE);
      fd.append("actor_email", actingEmail());
      try {
        await api("/api/projects/" + projectId + "/tender-documents", { method: "POST", body: fd });
        ok++;
      } catch (err) {
        showToast('"' + f.name + '" failed to upload &#8211; ' + apiErrorDetail(err), true);
      }
    }
    return ok;
  }
  // Folder 0 is a real navigable tree, not a flat list -- folder_path on
  // each doc (e.g. "Drawings/Civil") groups documents client-side into
  // subfolders you click into, with a breadcrumb back to the root, same
  // interaction shape as the Departments folder list beside it.
  function renderTenderDocs(docs, projectId) {
    var currentPath = "";
    function refresh() {
      api("/api/projects/" + projectId + "/tender-documents").then(function (fresh) {
        docs = fresh;
        draw();
      });
    }
    function draw() {
      var wrap = document.getElementById("dDeliverables");
      wrap.innerHTML = "";
      var prefix = currentPath ? currentPath + "/" : "";
      var childFolders = {}, childFiles = [];
      docs.forEach(function (d) {
        var fp = d.folder_path || "";
        if (fp === currentPath) {
          childFiles.push(d);
        } else if (fp.indexOf(prefix) === 0) {
          var nextSeg = fp.slice(prefix.length).split("/")[0];
          childFolders[nextSeg] = (childFolders[nextSeg] || 0) + 1;
        }
      });
      var folderNames = Object.keys(childFolders).sort();
      document.getElementById("dDeliverCount").textContent =
        (folderNames.length + childFiles.length) + " item" + (folderNames.length + childFiles.length === 1 ? "" : "s");

      // Breadcrumb -- root + one clickable segment per path part, so you can
      // jump back to any ancestor folder in one click, not just "up one".
      var crumb = el("div", "deliv-row");
      var crumbBody = el("div", "deliv-body");
      var rootLink = el("a", "", "0. Tender Documents");
      rootLink.href = "#"; rootLink.style.fontWeight = "700"; rootLink.style.color = currentPath ? "var(--purple-1)" : "var(--ink-900)";
      rootLink.addEventListener("click", function (e) { e.preventDefault(); currentPath = ""; draw(); });
      crumbBody.appendChild(rootLink);
      var acc = "";
      (currentPath ? currentPath.split("/") : []).forEach(function (seg, idx, arr) {
        acc = acc ? acc + "/" + seg : seg;
        var accPath = acc;
        var isLast = idx === arr.length - 1;
        crumbBody.appendChild(document.createTextNode(" / "));
        var segLink = el("a", "", seg);
        segLink.href = "#"; segLink.style.fontWeight = "700";
        segLink.style.color = isLast ? "var(--ink-900)" : "var(--purple-1)";
        segLink.addEventListener("click", function (e) { e.preventDefault(); currentPath = accPath; draw(); });
        crumbBody.appendChild(segLink);
      });
      crumb.appendChild(crumbBody);
      wrap.appendChild(crumb);

      if (can("create")) {
        var uploadRow = el("div", "deliv-row");
        var fileInput = el("input"); fileInput.type = "file"; fileInput.multiple = true; fileInput.style.display = "none";
        var folderInput = el("input"); folderInput.type = "file"; folderInput.webkitdirectory = true; folderInput.multiple = true; folderInput.style.display = "none";
        fileInput.addEventListener("change", async function () {
          if (!fileInput.files.length) return;
          var ok = await uploadTenderDocFiles(projectId, fileInput.files, currentPath, false);
          if (ok) showToast(ok + " file" + (ok === 1 ? "" : "s") + " uploaded");
          refresh();
        });
        folderInput.addEventListener("change", async function () {
          if (!folderInput.files.length) return;
          var ok = await uploadTenderDocFiles(projectId, folderInput.files, currentPath, true);
          if (ok) showToast(ok + " file" + (ok === 1 ? "" : "s") + " uploaded");
          refresh();
        });
        uploadRow.appendChild(fileOrFolderButton("Upload", fileInput, folderInput));
        uploadRow.appendChild(fileInput); uploadRow.appendChild(folderInput);
        wrap.appendChild(uploadRow);
      }

      if (!folderNames.length && !childFiles.length) {
        wrap.appendChild(el("div", "deliv-row", '<span style="color:var(--ink-500);font-size:12.5px;">No tender documents here yet.</span>'));
        return;
      }
      folderNames.forEach(function (name) {
        var count = childFolders[name];
        var childPath = currentPath ? currentPath + "/" + name : name;
        var row = el("div", "folder-row");
        row.innerHTML =
          '<div class="folder-left"><span class="folder-ic">&#128193;</span><div><div class="folder-name">' + name + '</div>' +
          '<div class="folder-focal">' + count + " file" + (count === 1 ? "" : "s") + '</div></div></div>';
        row.addEventListener("click", function () { currentPath = childPath; draw(); });
        if (can("create")) {
          var folderRight = el("div", "folder-right");
          var delFolderBtn = el("button", "btn ghost-crit", "Delete Folder");
          delFolderBtn.addEventListener("click", async function (e) {
            e.stopPropagation();
            if (!(await customConfirm("This deletes " + count + " file" + (count === 1 ? "" : "s") + " and cannot be undone.",
              { title: 'Delete "' + name + '"?', danger: true, okLabel: "Delete" }))) return;
            try {
              await api("/api/projects/" + projectId + "/tender-documents/folder?path=" + encodeURIComponent(childPath) +
                "&actor_role=" + encodeURIComponent(CURRENT_ROLE) + "&actor_email=" + encodeURIComponent(actingEmail()),
                { method: "DELETE" });
              showToast("Folder deleted");
              refresh();
            } catch (err) {
              showToast("Could not delete folder &#8211; " + apiErrorDetail(err), true);
            }
          });
          folderRight.appendChild(delFolderBtn);
          row.appendChild(folderRight);
        }
        wrap.appendChild(row);
      });
      childFiles.forEach(function (d) {
        var row = el("div", "deliv-row");
        var body = el("div", "deliv-body");
        var link = el("a", "deliv-name", d.file_name);
        link.href = tenderDocViewUrl(d.file_name, d.file_url); link.target = "_blank"; link.rel = "noopener";
        link.style.color = "var(--purple-1)";
        body.appendChild(link);
        body.appendChild(el("div", "folder-focal",
          "Uploaded by " + (d.uploaded_by || "&#8213;") + " &middot; " + fmtDate(d.uploaded_at ? d.uploaded_at.slice(0, 10) : null)));
        row.appendChild(body);
        if (can("create")) {
          var delBtn = el("button", "btn", "Remove");
          delBtn.addEventListener("click", async function () {
            if (!(await customConfirm("This removes the file and cannot be undone.",
              { title: 'Remove "' + d.file_name + '"?', danger: true, okLabel: "Remove" }))) return;
            try {
              await api("/api/projects/" + projectId + "/tender-documents/" + d.id +
                "?actor_role=" + encodeURIComponent(CURRENT_ROLE) + "&actor_email=" + encodeURIComponent(actingEmail()),
                { method: "DELETE" });
              showToast("Document removed");
              refresh();
            } catch (err) {
              showToast("Could not remove &#8211; " + apiErrorDetail(err), true);
            }
          });
          row.appendChild(delBtn);
        }
        wrap.appendChild(row);
      });
    }
    draw();
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
      var row = el("div", "deliv-row");
      row.dataset.sid = String(d.id);
      var body = el("div", "deliv-body");
      var nameEl = el("div", "deliv-name", d.name);
      nameEl.title = d.name;
      body.appendChild(nameEl);
      // Item 169: a null due_date pending a milestone reads as a stalled
      // "Due —" otherwise, with no explanation of what it's actually
      // waiting on.
      var dueLabel = d.due_date ? ("Due " + dueDateHtml(d)) : (d.awaiting_note || "Due " + fmtDate(d.due_date));
      // Item [early bonus]: once Completed, show the real point value
      // earned right in the list row, not just inside the detail modal.
      var pointsHtml = (d.points_earned !== null && d.points_earned !== undefined)
        ? ' &middot; ' + pointsEarnedLabel(d.points_earned) : "";
      body.appendChild(el("div", "deliv-due", '<span class="deliv-due-date">' + dueLabel + '</span> ' + statusPillsHtml(d) + pointsHtml));
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
      var result = await openActionCommentModal({
        title: "Mark Completed", hint: "Describe how this was completed — no file to attach here.",
        placeholder: "e.g. Uploaded via email, confirmed by client…",
        required: true, requiredMessage: "A comment is required to mark this complete",
        confirmLabel: "Mark Completed", allowFile: false,
      });
      if (!result) return;
      var comment = result.comment;
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
      // Item [auto-refresh]: same full reload as an SME approval -- see review().
      location.reload();
    });
    return btn;
  }
  function markNotRequiredButton(submissionId, after) {
    after = after || refreshCurrentFolder;
    var btn = el("button", "btn ghost-crit", "Mark Not Required");
    btn.addEventListener("click", async function () {
      if (!(await customConfirm("It won't need a due date or a submission.", { title: "Mark as Not Required?" }))) return;
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
    // Item 152's optional attachment (e.g. a marked-up file or reference
    // doc) is now just part of the same modal's file row, instead of a
    // separate confirm()+file-picker step.
    var result = approved
      ? await openActionCommentModal({
          title: "Confirm Completion", hint: "Add a comment (optional).",
          placeholder: "Optional comment…", confirmLabel: "Confirm", allowFile: true,
        })
      : await openActionCommentModal({
          title: "Send Back", hint: "Reason for rejection (shown to the owner).",
          defaultValue: "Please review and resubmit with updated supporting documents.",
          confirmLabel: "Send Back", confirmVariant: "crit", allowFile: true,
        });
    if (!result) return;
    var comment = result.comment || null;
    var file = result.file;
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
    // Item [auto-refresh]: an approval reaches a real Completed state, so a
    // full reload replaces the usual in-place after() -- guarantees every
    // stale surface (sidebar badge, dashboard stats, other open panes)
    // reflects it, not just the list/modal the click happened in. A
    // rejection isn't "completed," so it keeps the lighter in-place refresh.
    if (approved) { location.reload(); return; }
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
  document.getElementById("ganttWbsFilter").addEventListener("change", applyGanttFilters);
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
    var wbsSel = document.getElementById("ganttWbsFilter");
    wbsSel.innerHTML = '<option value="">All WBS Categories</option>';
    wbsSel.value = "";
    // WBS categorization (from "Gantt chart WBS.xlsx") only applies to L1 --
    // L0 rows carry category=null and stay flat/ungrouped, so the filter
    // would just be a dead control there.
    wbsSel.hidden = ganttStage !== "L1";
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
    // Rows arrive pre-sorted by WBS category (backend's GANTT_WBS_CATEGORY_ORDER),
    // so preserving first-seen order here reproduces that order without
    // duplicating the category list in JS.
    var wbsSel = document.getElementById("ganttWbsFilter");
    var seenCats = [];
    ganttRowsUnfiltered.forEach(function (r) { if (r.category && seenCats.indexOf(r.category) === -1) seenCats.push(r.category); });
    wbsSel.innerHTML = '<option value="">All WBS Categories</option>';
    seenCats.forEach(function (cat) {
      var o = el("option", "", cat); o.value = cat;
      wbsSel.appendChild(o);
    });
    legend.innerHTML = "";
    if (ganttIsPooled) {
      // Timeline-display-only: TBU/PBU/DBU/BBU are 4 real, separate
      // departments everywhere else in the app (folders, focal points,
      // performance) -- only the Gantt legend collapses them into one "2.
      // Operation Units" swatch, since they already share one color (same
      // department_number) and 4 near-identical legend rows was just visual
      // noise here. The BU itself still shows -- as a note on each bar's own
      // label below, not as a separate legend entry.
      var seenOpUnitsBU = sortedDeptNames.some(function (name) { return /^Operation Units \((TBU|PBU|DBU|BBU)\)$/.test(name); });
      sortedDeptNames.forEach(function (name) {
        if (/^Operation Units \((TBU|PBU|DBU|BBU)\)$/.test(name)) return;
        var lg = el("span", "lg");
        lg.innerHTML = '<span class="sw" style="background:' + deptColor(seenDepts[name]) + '"></span>';
        lg.appendChild(document.createTextNode(deptLabel(name, seenDepts[name])));
        legend.appendChild(lg);
      });
      if (seenOpUnitsBU) {
        var opLg = el("span", "lg");
        opLg.innerHTML = '<span class="sw" style="background:' + deptColor(2) + '"></span>';
        opLg.appendChild(document.createTextNode("2. Operation Units"));
        legend.appendChild(opLg);
      }
    } else {
      // Per-project view colors bars by deadline/status instead of
      // department (see the barCls branch below) -- three tones is all
      // that logic actually produces: "crit" for Due or Rejected, "good"
      // for Completed, "neutral" for everything else (Not Due, On Hold,
      // and any deadline_status MATRIX_BUCKET_META doesn't cover) -- .gantt-
      // bar.neutral is actually var(--purple-1), not a grey, so the swatch
      // has to match that or it reads as an unexplained extra color.
      [["var(--good)", "Completed"], ["var(--crit)", "Due / Rejected"], ["var(--purple-1)", "Not Due"]].forEach(function (pair) {
        var lg = el("span", "lg");
        lg.innerHTML = '<span class="sw" style="background:' + pair[0] + '"></span>';
        lg.appendChild(document.createTextNode(pair[1]));
        legend.appendChild(lg);
      });
    }
    legend.className = "ann-type-key gantt-dept-legend";
    legend.style.display = "";

    applyGanttFilters();
  }

  function applyGanttFilters() {
    var dept = document.getElementById("ganttDeptFilter").value;
    var wbs = document.getElementById("ganttWbsFilter").value;
    var deadline = document.getElementById("ganttDeadlineFilter").value;
    var progress = document.getElementById("ganttProgressFilter").value;
    var rows = ganttRowsUnfiltered.filter(function (r) {
      return (!dept || r.department === dept) && (!wbs || r.category === wbs) &&
        (!deadline || r.deadline_status === deadline) && (!progress || r.status === progress);
    });
    drawGanttRows(rows, ganttIsPooled);
  }

  function drawGanttRows(rows, isPooled) {
    var axis = document.getElementById("ganttAxis");
    var wrap = document.getElementById("ganttRows");
    axis.innerHTML = "";
    wrap.innerHTML = "";
    // Est only exists as its own column in the pooled (cross-project)
    // Timeline -- shifts the track offset (axis padding + gridlines) right
    // by its width + gap when shown, computed here instead of two parallel
    // CSS layouts. Matches the .gantt-frozen-cols row padding/gap/widths.
    var ROW_PAD = 14, GAP = 12, LABEL_W = 210, EST_W = 70, COL_W = 80;
    var trackOffset = ROW_PAD + LABEL_W + GAP + (isPooled ? EST_W + GAP : 0) + COL_W + GAP + COL_W + GAP;
    var estHeader = document.getElementById("ganttEstColHeader");
    estHeader.hidden = !isPooled;
    axis.style.paddingLeft = trackOffset + "px";
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

    // Day row -- Friday/Saturday is this app's weekend everywhere else
    // (rules.skip_weekend_forward etc.), so those columns get a highlight
    // here too instead of reading identically to a working day.
    var dayRow = el("div", "gantt-axis-row day");
    for (var d = min; d < max; d += DAY) {
      var dDate = new Date(d);
      var isWeekend = dDate.getDay() === 5 || dDate.getDay() === 6; // Fri=5, Sat=6
      var dSeg = el("span", isWeekend ? "weekend" : "", String(dDate.getDate()));
      dSeg.style.width = PX_PER_DAY + "px";
      dayRow.appendChild(dSeg);
    }
    dayRow.style.width = trackWidthPx + "px";
    axis.appendChild(dayRow);

    // Gridlines overlay (month boundaries + week ticks + today marker), aligned under the track area.
    var gridlines = el("div", "gantt-gridlines");
    gridlines.style.width = trackWidthPx + "px";
    gridlines.style.left = trackOffset + "px";
    // Weekend bands (Friday/Saturday) -- full row height, so a weekend
    // reads as a weekend all the way down through the bars, not just in
    // the day-number row above.
    for (var wd = min; wd < max; wd += DAY) {
      var wdDate = new Date(wd);
      if (wdDate.getDay() === 5 || wdDate.getDay() === 6) {
        var wdBand = el("div", "gantt-gridline weekend-band");
        wdBand.style.left = px(wd) + "px";
        wdBand.style.width = PX_PER_DAY + "px";
        gridlines.appendChild(wdBand);
      }
    }
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

    // L1's rows carry a WBS category (Milestones, Budget, Early Activities,
    // etc, from "Gantt chart WBS.xlsx") and arrive pre-grouped by it from
    // the backend sort -- a header row goes in wherever it changes from the
    // previous row. L0 rows have category=null and stay flat/ungrouped.
    var lastCategory = undefined;
    rows.forEach(function (r) {
      if (r.category !== undefined && r.category !== lastCategory) {
        var catHeader = el("div", "gantt-cat-header", r.category);
        wrap.appendChild(catHeader);
        lastCategory = r.category;
      }
      var s = new Date(r.start + "T00:00:00").getTime();
      var e = new Date(r.end + "T00:00:00").getTime() + DAY;
      var leftPx = px(s);
      var widthPx = Math.max(4, px(e) - px(s));
      var row = el("div", "gantt-row");
      // The legend collapses TBU/PBU/DBU/BBU into one "Operation Units"
      // swatch (see above), so which BU this particular bar belongs to
      // would otherwise be invisible -- noted on the label itself instead.
      var buMatch = /^Operation Units \((TBU|PBU|DBU|BBU)\)$/.exec(r.department);
      var buNote = buMatch ? ' <span class="gantt-bu-note">(' + buMatch[1] + ")</span>" : "";
      var label = el("div", "gantt-label", "<b>" + r.item_no + "</b> &middot; " + r.short_name + buNote);
      label.title = r.name;
      var frozenCols = el("div", "gantt-frozen-cols");
      frozenCols.appendChild(label);
      if (isPooled) frozenCols.appendChild(el("div", "gantt-est-col", r.est_no));
      frozenCols.appendChild(el("div", "gantt-start-col", fmtDate(r.start)));
      frozenCols.appendChild(el("div", "gantt-finish-col", fmtDate(r.end)));
      row.appendChild(frozenCols);
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
  var perfData = null;
  var perfSearchTerm = "";
  var perfCompareSelected = {};  // department name -> true
  var perfChipSelected = {};  // department name -> true, independent multi-select
  var perfStatusFilter = null;  // { level: "l1"|"l0", status: "Excellent"|"Acceptable"|"Needs Action" } | null
  var PERF_MONTH_ORDER = ["Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Current"];
  var PERF_COLORS = ["#667eea", "#764ba2", "#10b981", "#f59e0b", "#ef4444", "#06b6d4", "#8b5cf6", "#ec4899"];
  function perfStatusClass(status) {
    if (status === "Excellent") return "excellent";
    if (status === "Acceptable") return "acceptable";
    if (status === "Needs Action") return "needs-action";
    return "na";
  }
  function perfPct(pct) { return pct === null || pct === undefined ? "&#8213;" : pct + "%"; }
  // "Monthly Trend & Variance" wording -- the design spec's arrow+word
  // convention (Improved/Declined/Stable), kept separate from the raw
  // signed variance number so a card can show both side by side.
  function perfTrendWord(level) {
    if (level.trend === "no_baseline") return '<span class="perf-trend no_baseline">&#8213; No Baseline</span>';
    var arrow = level.trend === "up" ? "&#8593;" : (level.trend === "down" ? "&#8595;" : "&#8594;");
    var word = level.trend === "up" ? "Improved" : (level.trend === "down" ? "Declined" : "Stable");
    return '<span class="perf-trend ' + level.trend + '">' + arrow + " " + word + "</span>";
  }
  function perfVariance(level) {
    if (level.trend === "no_baseline") return "";
    var sign = level.variance > 0 ? "+" : "";
    return '<span class="pc2-variance ' + level.trend + '">' + sign + level.variance + "%</span>";
  }
  function perfYtd(level) {
    if (!level.ytd) return '<div class="pc2-flex-row"><span class="pc2-ytd-range">&#8213;</span></div>';
    var y = level.ytd;
    var cls = y.delta > 0 ? "up" : (y.delta < 0 ? "down" : "stable");
    var sign = y.delta > 0 ? "+" : "";
    return '<div class="pc2-flex-row">' +
      '<span class="pc2-ytd-range">vs ' + y.month + ": " + y.from + "% &rarr; " + y.to + '%</span>' +
      '<span class="pc2-ytd-delta ' + cls + '">' + sign + y.delta + '%</span>' +
      "</div>";
  }
  // Item [performance history]: minimal inline trend chart, shared by the
  // card sparkline and the Compare/History modal's bigger version -- one or
  // more series (department histories) plotted on a shared axis. Dots are
  // absolutely-positioned divs, not SVG <circle>s, since the SVG stretches
  // non-uniformly and circles would distort into ellipses; the line itself
  // (a <polyline>) doesn't have that problem.
  function _perfFmtTick(v) {
    var r = Math.round(v * 10) / 10;
    return (Math.round(r) === r ? r.toFixed(0) : r.toFixed(1)) + "%";
  }
  function buildTrendChartHtml(seriesList, heightPx, alignToTable) {
    var allMonths = [];
    seriesList.forEach(function (s) {
      s.points.forEach(function (p) { if (allMonths.indexOf(p.month) === -1) allMonths.push(p.month); });
    });
    allMonths.sort(function (a, b) { return PERF_MONTH_ORDER.indexOf(a) - PERF_MONTH_ORDER.indexOf(b); });
    if (!allMonths.length) return '<div class="perf-chart-empty">No history yet</div>';
    var allPcts = [];
    seriesList.forEach(function (s) { s.points.forEach(function (p) { if (p.pct !== null && p.pct !== undefined) allPcts.push(p.pct); }); });
    var minV = allPcts.length ? Math.min.apply(null, allPcts) : 0;
    var maxV = allPcts.length ? Math.max.apply(null, allPcts) : 100;
    if (maxV === minV) { minV -= 5; maxV += 5; }
    var pad = (maxV - minV) * 0.15;
    minV -= pad; maxV += pad;
    if (minV < 0) minV = 0;
    if (maxV > 100) maxV = 100;
    // Same formula drives the gridline/tick positions and the dot/line
    // positions, so they always land in exact alignment with each other.
    // In table-aligned mode (Compare/History modals, which show the same
    // periods/departments as columns in a table right above the chart)
    // each point sits at the CENTER of its own equal-width slice, same as
    // how the table's own header text centers within its column -- not
    // spread edge-to-edge, which drifted out of alignment with the table.
    function xPos(i) {
      if (allMonths.length <= 1) return 50;
      return alignToTable ? ((i + 0.5) / allMonths.length) * 100 : (i / (allMonths.length - 1)) * 100;
    }
    function yPos(pct) { return maxV === minV ? 50 : 100 - ((pct - minV) / (maxV - minV)) * 100; }
    var svgHtml = "", dotsHtml = "";
    seriesList.forEach(function (s) {
      var byMonth = {};
      s.points.forEach(function (p) { byMonth[p.month] = p.pct; });
      var coords = [];
      allMonths.forEach(function (m, i) {
        var pct = byMonth[m];
        if (pct === null || pct === undefined) return;
        coords.push([xPos(i), yPos(pct)]);
      });
      if (coords.length > 1) {
        var poly = coords.map(function (c) { return c[0] + "," + c[1]; }).join(" ");
        svgHtml += '<polyline points="' + poly + '" fill="none" stroke="' + s.color +
          '" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round" />';
      }
      coords.forEach(function (c, ci) {
        var isLast = ci === coords.length - 1;
        var size = isLast ? 8 : 5;
        dotsHtml += '<div class="spark-dot' + (isLast ? " last" : "") + '" style="left:' + c[0] + "%;top:" + c[1] +
          "%;background:" + s.color + ";width:" + size + "px;height:" + size + "px;margin-left:-" + (size / 2) +
          "px;margin-top:-" + (size / 2) + 'px;" title="' + s.label + '"></div>';
      });
    });
    var labelsHtml = allMonths.map(function (m, i) {
      return '<span class="spark-label" style="left:' + xPos(i) + '%;">' + m + "</span>";
    }).join("");
    var legendHtml = seriesList.length > 1
      ? '<div class="spark-legend">' + seriesList.map(function (s) {
          return '<span class="spark-legend-item"><span class="dot" style="background:' + s.color + '"></span>' + s.label + "</span>";
        }).join("") + "</div>"
      : "";
    var midV = (minV + maxV) / 2;
    var axisHtml = [maxV, midV, minV].map(function (v, i) {
      return '<span style="top:' + (i * 50) + '%;">' + _perfFmtTick(v) + "</span>";
    }).join("");
    var gridHtml = [0, 50, 100].map(function (top) {
      return '<div class="spark-gridline" style="top:' + top + '%;"></div>';
    }).join("");
    var alignCls = alignToTable ? " pcmp-aligned" : "";
    return '<div class="spark-chart-row' + alignCls + '" style="height:' + (heightPx || 90) + 'px;">' +
      '<div class="spark-axis' + alignCls + '">' + axisHtml + "</div>" +
      '<div class="spark-plot">' +
        '<div class="spark-gridlines">' + gridHtml + "</div>" +
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" class="spark-svg">' + svgHtml + "</svg>" +
        dotsHtml +
      "</div></div>" +
      '<div class="spark-labels-row"><div class="spark-axis-spacer' + alignCls + '"></div>' +
      '<div class="spark-labels">' + labelsHtml + "</div></div>" + legendHtml;
  }
  function renderPerfCol(d, levelKey, levelLabel) {
    var lv = d[levelKey];
    var statusCls = perfStatusClass(lv.status);
    var clickable = lv.percentage !== null ? " pc2-pct-clickable" : "";
    var html = '<div class="pc2-title">' + levelLabel + " Performance</div>" +
      '<div class="pc2-pct ' + statusCls + clickable + '" data-dept="' + d.name.replace(/"/g, "&quot;") +
      '" data-level="' + levelKey + '">' + perfPct(lv.percentage) + "</div>" +
      '<span class="pc2-status ' + statusCls + '">' + lv.status + "</span>" +
      '<div class="pc2-label">Monthly Trend &amp; Variance</div>' +
      '<div class="pc2-flex-row">' + perfTrendWord(lv) + perfVariance(lv) + "</div>" +
      '<div class="pc2-label">YTD Trend' + (lv.ytd ? " (vs " + lv.ytd.month + ")" : "") + "</div>" +
      perfYtd(lv) +
      '<div class="pc2-label">Yearly Trend (2026)</div>' +
      buildTrendChartHtml([{ label: d.name, color: levelKey === "l1" ? "#1f9d5c" : "#cc6a1e", points: lv.history }], 70);
    return html;
  }
  function perfTrackedDepts() {
    return perfData.departments.filter(function (d) { return d.has_data; });
  }
  function renderPerfCards() {
    var wrap = document.getElementById("perfCardGrid");
    wrap.innerHTML = "";
    var chipNames = Object.keys(perfChipSelected);
    var tracked = perfTrackedDepts();
    var depts = tracked.filter(function (d) {
      if (perfSearchTerm && d.name.toLowerCase().indexOf(perfSearchTerm) === -1) return false;
      if (chipNames.length && !perfChipSelected[d.name]) return false;
      if (perfStatusFilter && d[perfStatusFilter.level].status !== perfStatusFilter.status) return false;
      return true;
    });
    var footer = document.getElementById("perfDeptFooter");
    if (footer) footer.textContent = "Showing " + depts.length + " of " + tracked.length + " departments.";
    if (!depts.length) { wrap.appendChild(el("div", "empty-state", "No departments match your filters.")); return; }
    depts.forEach(function (d) {
      var card = el("div", "card perf-card2");
      var head = el("div", "perf-card2-head");
      head.appendChild(el("div", "perf-card2-name", d.name));
      var actions = el("div", "perf-card2-actions");
      var historyBtn = el("button", "perf-history-btn", "History");
      historyBtn.addEventListener("click", function (e) { e.stopPropagation(); openPerfHistoryModal(d); });
      actions.appendChild(historyBtn);
      var compareLbl = el("label", "perf-compare-check");
      var compareCb = document.createElement("input");
      compareCb.type = "checkbox";
      compareCb.checked = !!perfCompareSelected[d.name];
      compareCb.addEventListener("click", function (e) { e.stopPropagation(); });
      compareCb.addEventListener("change", function () {
        if (compareCb.checked) perfCompareSelected[d.name] = true; else delete perfCompareSelected[d.name];
        renderPerfCompareBar();
      });
      compareLbl.appendChild(compareCb);
      compareLbl.appendChild(document.createTextNode("Compare"));
      actions.appendChild(compareLbl);
      head.appendChild(actions);
      card.appendChild(head);
      var cols = el("div", "perf-card2-cols");
      var c1 = el("div", "perf-card2-col l1");
      c1.innerHTML = renderPerfCol(d, "l1", "L1");
      var c0 = el("div", "perf-card2-col l0");
      c0.innerHTML = renderPerfCol(d, "l0", "L0");
      cols.appendChild(c1); cols.appendChild(c0);
      card.appendChild(cols);
      wrap.appendChild(card);
    });
  }
  function renderPerfCompareBar() {
    var names = Object.keys(perfCompareSelected);
    var bar = document.getElementById("perfCompareBar");
    if (!bar) return;
    if (!names.length) { bar.hidden = true; return; }
    bar.hidden = false;
    document.getElementById("perfCompareCount").textContent = names.length + " selected";
    document.getElementById("perfCompareGo").disabled = names.length < 2;
  }
  function perfStatusFor(pct, minAcceptable) {
    if (pct === null || pct === undefined) return "N/A";
    if (pct >= 90) return "Excellent";
    if (pct >= minAcceptable) return "Acceptable";
    return "Needs Action";
  }
  // Item [performance history]: per-card "History" -- pick any 2+ recorded
  // periods for just that one department and compare them, laid out as a
  // period-over-period comparison: each column's Change is vs the column
  // immediately to its left (not vs the first month, which is what the
  // card's own YTD row already shows), and the first selected column reads
  // "baseline" since there's nothing before it to compare against.
  function openPerfHistoryModal(d) {
    var allMonths = [];
    ["l1", "l0"].forEach(function (levelKey) {
      d[levelKey].history.forEach(function (p) { if (allMonths.indexOf(p.month) === -1) allMonths.push(p.month); });
    });
    allMonths.sort(function (a, b) { return PERF_MONTH_ORDER.indexOf(a) - PERF_MONTH_ORDER.indexOf(b); });
    var selected = {};
    allMonths.slice(-2).forEach(function (m) { selected[m] = true; });

    function renderHistoryBody() {
      var chosen = allMonths.filter(function (m) { return selected[m]; });
      var pillsHtml = '<div class="pmonth-picker"><div class="pmonth-label">Select 2+ months to compare:</div>' +
        '<div class="pmonth-pills">' + allMonths.map(function (m) {
          return '<button type="button" class="pmonth-pill' + (selected[m] ? " active" : "") + '" data-month="' +
            m + '">' + m + "</button>";
        }).join("") + "</div></div>";
      var sectionsHtml = ["l1", "l0"].map(function (levelKey) {
        var lv = d[levelKey];
        var byMonth = {};
        lv.history.forEach(function (p) { byMonth[p.month] = p.pct; });
        var periods = chosen.map(function (m) { return { month: m, pct: byMonth.hasOwnProperty(m) ? byMonth[m] : null }; });
        var levelLabel = levelKey.toUpperCase() + " Performance";
        var rows = "";
        rows += '<tr class="pcmp-head-row"><td></td>' + periods.map(function (p) { return "<td>" + p.month + "</td>"; }).join("") + "</tr>";
        rows += "<tr><td>Performance</td>" + periods.map(function (p) {
          var st = perfStatusFor(p.pct, d.min_acceptable);
          var clickable = p.month === "Current" && p.pct !== null ? " pc2-pct-clickable" : "";
          var attrs = p.month === "Current" ? ' data-dept="' + d.name.replace(/"/g, "&quot;") + '" data-level="' + levelKey + '"' : "";
          return '<td class="pcmp-pct ' + perfStatusClass(st) + clickable + '"' + attrs + ">" + perfPct(p.pct) + "</td>";
        }).join("") + "</tr>";
        rows += "<tr><td>Status</td>" + periods.map(function (p) {
          var st = perfStatusFor(p.pct, d.min_acceptable);
          return '<td><span class="pc2-status ' + perfStatusClass(st) + '">' + st + "</span></td>";
        }).join("") + "</tr>";
        rows += "<tr><td>Change</td>" + periods.map(function (p, i) {
          if (i === 0) return '<td><span class="pc2-ytd-range">baseline</span></td>';
          var prev = periods[i - 1];
          if (p.pct === null || p.pct === undefined || prev.pct === null || prev.pct === undefined) return "<td>&#8213;</td>";
          var delta = p.pct - prev.pct;
          var cls = delta > 0 ? "up" : (delta < 0 ? "down" : "stable");
          var sign = delta > 0 ? "+" : "";
          return '<td><span class="pc2-ytd-delta ' + cls + '">' + sign + delta.toFixed(2) + '%</span>' +
            '<div class="pc2-ytd-sub">vs ' + prev.month + "</div></td>";
        }).join("") + "</tr>";
        var seriesList = [{ label: d.name, color: levelKey === "l1" ? "#667eea" : "#764ba2", points: periods }];
        return '<div class="pcmp-section-head">' + levelLabel + "</div>" +
          '<div class="pcmp-table-wrap"><table class="pcmp-table pcmp-align-table"><tbody>' + rows + "</tbody></table></div>" +
          buildTrendChartHtml(seriesList, 170, true);
      }).join("");
      var body = document.getElementById("perfCompareBody");
      body.innerHTML = pillsHtml + sectionsHtml;
      body.querySelectorAll(".pmonth-pill").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var m = btn.dataset.month;
          if (selected[m]) {
            if (Object.keys(selected).length <= 2) return;
            delete selected[m];
          } else {
            selected[m] = true;
          }
          renderHistoryBody();
        });
      });
    }
    document.getElementById("perfCompareTitle").innerHTML = d.name + " &#8211; Period Comparison";
    renderHistoryBody();
    document.getElementById("perfCompareOverlay").hidden = false;
  }
  function openPerfCompareModal(depts) {
    document.getElementById("perfCompareTitle").innerHTML = "Department Comparison";
    var body = document.getElementById("perfCompareBody");
    body.innerHTML = ["l1", "l0"].map(function (levelKey) {
      var levelLabel = levelKey.toUpperCase() + " Performance";
      var rows = "";
      rows += '<tr class="pcmp-head-row"><td></td>' + depts.map(function (d) {
        return "<td>" + d.name + "</td>";
      }).join("") + "</tr>";
      rows += "<tr><td>Performance</td>" + depts.map(function (d) {
        var lv = d[levelKey];
        var clickable = lv.percentage !== null ? " pc2-pct-clickable" : "";
        return '<td class="pcmp-pct ' + perfStatusClass(lv.status) + clickable + '" data-dept="' +
          d.name.replace(/"/g, "&quot;") + '" data-level="' + levelKey + '">' + perfPct(lv.percentage) + "</td>";
      }).join("") + "</tr>";
      rows += "<tr><td>Status</td>" + depts.map(function (d) {
        var lv = d[levelKey];
        return '<td><span class="pc2-status ' + perfStatusClass(lv.status) + '">' + lv.status + "</span></td>";
      }).join("") + "</tr>";
      rows += "<tr><td>Monthly Trend</td>" + depts.map(function (d) {
        return "<td>" + perfTrendWord(d[levelKey]) + "</td>";
      }).join("") + "</tr>";
      rows += "<tr><td>Yearly Trend</td>" + depts.map(function (d) {
        var lv = d[levelKey];
        if (!lv.ytd) return "<td>&#8213;</td>";
        var cls = lv.ytd.delta > 0 ? "up" : (lv.ytd.delta < 0 ? "down" : "stable");
        var sign = lv.ytd.delta > 0 ? "+" : "";
        return '<td><span class="pc2-ytd-delta ' + cls + '">' + sign + lv.ytd.delta + '%</span>' +
          '<div class="pc2-ytd-sub">vs ' + lv.ytd.month + ": " + lv.ytd.from + "% &rarr; " + lv.ytd.to + "%</div></td>";
      }).join("") + "</tr>";
      var seriesList = depts.map(function (d, i) {
        return { label: d.name, color: PERF_COLORS[i % PERF_COLORS.length], points: d[levelKey].history };
      });
      return '<div class="pcmp-section-head">' + levelLabel + "</div>" +
        '<div class="pcmp-table-wrap"><table class="pcmp-table pcmp-align-table"><tbody>' + rows + "</tbody></table></div>" +
        buildTrendChartHtml(seriesList, 170, true);
    }).join("");
    document.getElementById("perfCompareOverlay").hidden = false;
  }
  function closePerfCompareModal() { document.getElementById("perfCompareOverlay").hidden = true; }
  document.getElementById("perfCompareClose").addEventListener("click", closePerfCompareModal);
  document.getElementById("perfCompareOverlay").addEventListener("click", function (e) { if (e.target === this) closePerfCompareModal(); });
  document.getElementById("perfCompareGo").addEventListener("click", function () {
    var names = Object.keys(perfCompareSelected);
    if (names.length < 2) return;
    var depts = perfData.departments.filter(function (d) { return perfCompareSelected[d.name]; });
    openPerfCompareModal(depts);
  });
  document.getElementById("perfCompareClear").addEventListener("click", function () {
    perfCompareSelected = {};
    renderPerfCompareBar();
    renderPerfCards();
  });
  // Item [performance history]: "click a percentage to see the math" --
  // itemized cohort breakdown, per architecture_map.md section 5's
  // "drill-down why this score" modal. Delegated so it works from the
  // card grid and the Compare/History modal's Current-period cells alike.
  async function openPerfBreakdownModal(deptName, levelKey) {
    var data;
    try {
      data = await api("/api/dashboard/performance/breakdown?department=" + encodeURIComponent(deptName) +
        "&stage=" + encodeURIComponent(levelKey.toUpperCase()));
    } catch (err) { showToast("Could not load breakdown &#8211; " + apiErrorDetail(err), true); return; }
    document.getElementById("perfBreakdownTitle").innerHTML = deptName + " &#8211; " + levelKey.toUpperCase() + " Calculation Breakdown";
    var body = document.getElementById("perfBreakdownBody");
    var html = "";
    if (data.aggregation === "per_item_averaged") {
      html += '<p class="pbd-note">L0 averages each deliverable item\'s own submitted &#247; due ratio, then averages those ratios equally.</p>';
      html += '<table class="pcmp-table pbd-table"><thead><tr><th>Item</th><th>Name</th><th>Points</th><th>Due</th><th>Ratio</th></tr></thead><tbody>';
      data.per_item_groups.forEach(function (g) {
        html += "<tr><td>" + g.item_no + "</td><td>" + g.name + "</td><td>" + g.points + "</td><td>" + g.due + "</td><td>" + g.pct + "%</td></tr>";
      });
      html += "</tbody></table>";
      html += '<div class="pbd-total">Overall = average of ' + data.per_item_groups.length + ' item ratios = <b>' +
        (data.overall_pct === null ? "&#8213;" : data.overall_pct + "%") + "</b></div>";
    } else {
      html += '<p class="pbd-note">L1 pools every due submission\'s points into one ratio.</p>';
      html += '<div class="pbd-total">Overall = ' + data.overall_points + " points &#247; " + data.overall_due +
        " due items = <b>" + (data.overall_pct === null ? "&#8213;" : data.overall_pct + "%") + "</b></div>";
    }
    html += '<table class="pcmp-table pbd-table"><thead><tr><th>Item</th><th>Name</th><th>Project</th><th>Due</th><th>Submitted</th><th>Status</th><th>Points</th></tr></thead><tbody>';
    data.items.forEach(function (it) {
      html += "<tr><td>" + it.item_no + "</td><td>" + it.name + "</td><td>" + it.project + "</td>" +
        "<td>" + (it.due_date ? fmtDate(it.due_date) : "&#8213;") + "</td>" +
        "<td>" + (it.submitted_date ? fmtDate(it.submitted_date) : "Not submitted") + "</td>" +
        "<td>" + it.status + "</td><td>" + it.points + "</td></tr>";
    });
    html += "</tbody></table>";
    body.innerHTML = html;
    document.getElementById("perfBreakdownOverlay").hidden = false;
  }
  function closePerfBreakdownModal() { document.getElementById("perfBreakdownOverlay").hidden = true; }
  document.getElementById("perfBreakdownClose").addEventListener("click", closePerfBreakdownModal);
  document.getElementById("perfBreakdownOverlay").addEventListener("click", function (e) { if (e.target === this) closePerfBreakdownModal(); });
  [document.getElementById("perfCardGrid"), document.getElementById("perfCompareBody")].forEach(function (container) {
    container.addEventListener("click", function (e) {
      var target = e.target.closest(".pc2-pct-clickable");
      if (!target) return;
      openPerfBreakdownModal(target.dataset.dept, target.dataset.level);
    });
  });
  document.getElementById("perfSearch").addEventListener("input", function (e) {
    perfSearchTerm = e.target.value.trim().toLowerCase();
    renderPerfChips();
    renderPerfCards();
  });
  document.getElementById("perfPrintBtn").addEventListener("click", function () { window.print(); });
  function renderPerfSummaryCards() {
    var strip = document.getElementById("perfSummaryStrip");
    strip.innerHTML = "";
    var tracked = perfTrackedDepts();
    ["l1", "l0"].forEach(function (levelKey) {
      var vals = tracked.map(function (d) { return d[levelKey].percentage; }).filter(function (v) { return v !== null; });
      var avg = vals.length ? Math.round((vals.reduce(function (a, b) { return a + b; }, 0) / vals.length) * 10) / 10 : null;
      var counts = { Excellent: 0, Acceptable: 0, "Needs Action": 0 };
      tracked.forEach(function (d) { var st = d[levelKey].status; if (counts.hasOwnProperty(st)) counts[st]++; });
      var totalRated = counts.Excellent + counts.Acceptable + counts["Needs Action"];
      var projectCount = levelKey === "l1" ? perfData.l1_project_count : perfData.l0_project_count;
      var card = el("div", "card perf-summary-card2 " + levelKey);
      var barSegs = ["Excellent", "Acceptable", "Needs Action"].map(function (status) {
        var n = counts[status];
        var w = totalRated ? (n / totalRated * 100) : 0;
        return '<div class="psb-seg ' + perfStatusClass(status) + '" style="width:' + w + '%;"></div>';
      }).join("");
      var hasFilter = perfStatusFilter && perfStatusFilter.level === levelKey;
      var legendHtml = ["Excellent", "Acceptable", "Needs Action"].map(function (status) {
        var active = hasFilter && perfStatusFilter.level === levelKey && perfStatusFilter.status === status;
        var dim = hasFilter && !active;
        return '<span class="psc2-legend-item ' + perfStatusClass(status) + (active ? " active" : "") + (dim ? " dim" : "") +
          '" data-level="' + levelKey + '" data-status="' + status + '"><span class="dot"></span>' + counts[status] + " " + status + "</span>";
      }).join("");
      card.innerHTML = '<div class="psc2-head"><span class="psc2-title">' + levelKey.toUpperCase() + ' Performance</span>' +
        '<span class="psc2-avg">' + (avg === null ? "&#8213;" : avg + "%") + ' <span class="psc2-avg-lbl">AVG</span></span></div>' +
        '<div class="psc2-pill">Total Number of ' + levelKey.toUpperCase() + " Projects: " + projectCount + "</div>" +
        '<div class="psc2-body">' +
          '<div class="psc2-count psc2-count-clickable' + (hasFilter ? " dim" : "") + '"><b>' + totalRated + '</b><span>DEPARTMENTS</span></div>' +
          '<div class="psc2-bar-wrap"><div class="psc2-bar">' + barSegs + '</div>' +
            '<div class="psc2-legend">' + legendHtml + "</div></div>" +
        "</div>" +
        '<div class="psc2-hint">Click a status to filter</div>';
      strip.appendChild(card);
      card.querySelectorAll("[data-status]").forEach(function (item) {
        item.addEventListener("click", function () {
          var level = item.dataset.level, status = item.dataset.status;
          perfStatusFilter = (perfStatusFilter && perfStatusFilter.level === level && perfStatusFilter.status === status)
            ? null : { level: level, status: status };
          renderPerfSummaryCards();
          renderPerfCards();
        });
      });
      // Design spec: clicking the count/average area clears every active
      // filter (status, chips, search) at once, not just this card's own.
      card.querySelector(".psc2-count-clickable").addEventListener("click", function () {
        perfStatusFilter = null;
        perfChipSelected = {};
        perfSearchTerm = "";
        document.getElementById("perfSearch").value = "";
        renderPerfSummaryCards();
        renderPerfChips();
        renderPerfCards();
      });
    });
  }
  function renderPerfChips() {
    var wrap = document.getElementById("perfDeptChips");
    wrap.innerHTML = "";
    perfTrackedDepts().forEach(function (d) {
      var dim = perfSearchTerm && d.name.toLowerCase().indexOf(perfSearchTerm) === -1;
      var chip = el("span", "perf-chip" + (perfChipSelected[d.name] ? " active" : "") + (dim ? " dim" : ""),
        d.name);
      chip.addEventListener("click", function () {
        if (perfChipSelected[d.name]) delete perfChipSelected[d.name]; else perfChipSelected[d.name] = true;
        renderPerfChips();
        renderPerfCards();
      });
      wrap.appendChild(chip);
    });
  }
  async function loadPerformance() {
    perfData = await api("/api/dashboard/performance");
    document.getElementById("perfFreshness").textContent = "Data as of " + fmtDate(perfData.data_as_of);
    renderPerfSummaryCards();
    renderPerfChips();
    renderPerfCards();
    renderPerfCompareBar();
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
    extension_requested: "&#8987;", extension_approved: "&#9989;", extension_rejected: "&#10060;",
    hold_requested: "&#9208;", hold_approved: "&#9989;", hold_rejected: "&#10060;", resumed: "&#9654;",
    completion_date_edited: "&#128197;",
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

  // Item [multi-SME]: roster-only, multi-value picker -- chips for each
  // already-picked email plus a typeahead input that only ever offers real
  // L0-L1 Group members (filtered by role when one's given), never free
  // text. Returns {getValues} so the caller's Save button can read the
  // current selection without keeping its own state.
  var _rosterCache = null;
  async function _getRoster() {
    if (!_rosterCache) _rosterCache = await api("/api/departments/users");
    return _rosterCache;
  }
  function renderRosterPicker(container, selected, rosterPool, placeholder) {
    container.innerHTML = "";
    container.className = "roster-picker";
    var current = (selected || []).slice();
    var chips = el("div", "roster-picker-chips");
    function renderChips() {
      chips.innerHTML = "";
      current.forEach(function (email) {
        var chip = el("span", "roster-picker-chip", "");
        chip.appendChild(document.createTextNode(email));
        var x = el("span", "roster-picker-chip-x", "&#10005;");
        x.addEventListener("click", function () {
          current = current.filter(function (e) { return e !== email; });
          renderChips();
        });
        chip.appendChild(x);
        chips.appendChild(chip);
      });
    }
    renderChips();
    var input = el("input", "roster-picker-input"); input.type = "text"; input.placeholder = placeholder;
    var dropdown = el("div", "roster-picker-dropdown"); dropdown.hidden = true;
    function showMatches() {
      var term = input.value.trim().toLowerCase();
      dropdown.innerHTML = "";
      if (!term) { dropdown.hidden = true; return; }
      var matches = rosterPool.filter(function (u) {
        if (current.indexOf(u.email) !== -1) return false;
        return u.email.toLowerCase().indexOf(term) === 0 || (u.name || "").toLowerCase().indexOf(term) === 0;
      }).slice(0, 8);
      if (!matches.length) { dropdown.hidden = true; return; }
      matches.forEach(function (u) {
        var opt = el("div", "roster-picker-option", (u.name ? u.name + " " : "") + "&#8211; " + u.email);
        opt.addEventListener("mousedown", function (e) {
          e.preventDefault();
          current.push(u.email);
          renderChips();
          input.value = "";
          dropdown.hidden = true;
        });
        dropdown.appendChild(opt);
      });
      dropdown.hidden = false;
    }
    input.addEventListener("input", showMatches);
    input.addEventListener("focus", showMatches);
    input.addEventListener("blur", function () { setTimeout(function () { dropdown.hidden = true; }, 150); });
    var inputWrap = el("div", "roster-picker-input-wrap");
    inputWrap.appendChild(input); inputWrap.appendChild(dropdown);
    container.appendChild(chips); container.appendChild(inputWrap);
    return { getValues: function () { return current.slice(); } };
  }

  var _fpRows = [];
  var _fpRoster = [];
  function _fpFilterValues() {
    return {
      dept: document.getElementById("fpFilterDept").value,
      item: document.getElementById("fpFilterItem").value,
      owner: document.getElementById("fpFilterOwner").value,
      sme: document.getElementById("fpFilterSme").value,
    };
  }
  function _fpPopulateFilterOptions() {
    var depts = [], items = [], owners = {}, smes = {};
    _fpRows.forEach(function (d) {
      if (depts.indexOf(d.department) === -1) depts.push(d.department);
      items.push(d);
      (d.owner_emails || []).forEach(function (e) { owners[e] = true; });
      (d.default_sme_emails || []).forEach(function (e) { smes[e] = true; });
    });
    function fill(selectId, options, placeholder) {
      var sel = document.getElementById(selectId);
      var current = sel.value;
      sel.innerHTML = "";
      var placeholderOpt = el("option", "", placeholder); placeholderOpt.value = "";
      sel.appendChild(placeholderOpt);
      options.forEach(function (o) {
        var opt = el("option", "", o.label); opt.value = o.value; sel.appendChild(opt);
      });
      if (options.some(function (o) { return o.value === current; })) sel.value = current;
    }
    fill("fpFilterDept", depts.map(function (d) { return { value: d, label: d }; }), "All Departments");
    fill("fpFilterItem", items.map(function (d) { return { value: d.id, label: d.item_no + " · " + d.name }; }), "All Deliverables");
    fill("fpFilterOwner", Object.keys(owners).sort().map(function (e) { return { value: e, label: e }; }), "All Owners");
    fill("fpFilterSme", Object.keys(smes).sort().map(function (e) { return { value: e, label: e }; }), "All SMEs");
  }
  function _fpRenderStats(rows) {
    var owners = {}, smes = {};
    rows.forEach(function (d) {
      (d.owner_emails || []).forEach(function (e) { owners[e] = true; });
      (d.default_sme_emails || []).forEach(function (e) { smes[e] = true; });
    });
    document.getElementById("fpStats").innerHTML =
      "<span><b>" + Object.keys(owners).length + "</b> Owner(s) assigned</span>" +
      "<span><b>" + Object.keys(smes).length + "</b> SME(s) assigned</span>" +
      "<span><b>" + rows.length + "</b> deliverable(s) shown</span>";
  }
  function _fpRenderRows(rows) {
    var smeRoster = _fpRoster.filter(function (u) { return u.role === "SME"; });
    var ownerRoster = _fpRoster.filter(function (u) { return u.role === "Owner"; });
    var tbody = document.getElementById("focalPointsBody");
    tbody.innerHTML = "";
    if (!rows.length) {
      var emptyTr = el("tr");
      var emptyTd = el("td", "empty-state", "No deliverables match this filter.");
      emptyTd.setAttribute("colspan", "6");
      emptyTr.appendChild(emptyTd);
      tbody.appendChild(emptyTr);
      _fpRenderStats(rows);
      return;
    }
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
      // Tendering (unlike the Owner email, which Tendering always routes to
      // that project's own Bid Manager instead) -- no per-project popup
      // edit anymore, this catalog default is the one place for it.
      // Item [multi-SME]: both pickers are roster-only and multi-value --
      // any of the picked SMEs can approve/reject a submission of this item.
      var ownerPicker = null;
      if (d.is_tendering_bm) {
        var noteCell = el("td", "muted", "Defaults to the project's Bid Manager");
        tr.appendChild(noteCell);
      } else {
        var ownerCell = el("td");
        ownerPicker = renderRosterPicker(ownerCell, d.owner_emails, ownerRoster,
          d.department_focal_email ? "Defaults to " + d.department_focal_email : "Add an owner…");
        tr.appendChild(ownerCell);
      }
      var smeCell = el("td");
      var smePicker = renderRosterPicker(smeCell, d.default_sme_emails, smeRoster, "Add an SME…");
      tr.appendChild(smeCell);
      var saveBtn = el("button", "btn", "Save");
      saveBtn.addEventListener("click", async function () {
        var body = { default_sme_emails: smePicker.getValues() };
        if (ownerPicker) body.default_owner_emails = ownerPicker.getValues();
        try {
          await api("/api/departments/deliverable-focal/" + d.id, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
        } catch (err) {
          showToast("Could not save &#8211; " + apiErrorDetail(err), true);
          return;
        }
        // Keep the in-memory rows (and therefore stats/filters) in sync
        // with what was just saved, without a full re-fetch.
        d.default_sme_emails = smePicker.getValues();
        if (ownerPicker) d.owner_emails = ownerPicker.getValues();
        _fpPopulateFilterOptions();
        _fpRenderStats(_fpApplyFilters());
        showToast("Updated for " + d.item_no);
      });
      var tdSave = el("td"); tdSave.appendChild(saveBtn);
      tr.appendChild(tdSave);
      tbody.appendChild(tr);
    });
    _fpRenderStats(rows);
  }
  function _fpApplyFilters() {
    var f = _fpFilterValues();
    return _fpRows.filter(function (d) {
      if (f.dept && d.department !== f.dept) return false;
      if (f.item && String(d.id) !== f.item) return false;
      if (f.owner && (d.owner_emails || []).indexOf(f.owner) === -1) return false;
      if (f.sme && (d.default_sme_emails || []).indexOf(f.sme) === -1) return false;
      return true;
    });
  }
  ["fpFilterDept", "fpFilterItem", "fpFilterOwner", "fpFilterSme"].forEach(function (id) {
    document.getElementById(id).addEventListener("change", function () { _fpRenderRows(_fpApplyFilters()); });
  });
  document.getElementById("fpFilterClear").addEventListener("click", function () {
    ["fpFilterDept", "fpFilterItem", "fpFilterOwner", "fpFilterSme"].forEach(function (id) {
      document.getElementById(id).value = "";
    });
    _fpRenderRows(_fpApplyFilters());
  });

  async function loadFocalDeliverables(stage) {
    _fpRows = await api("/api/departments/deliverable-focal?stage=" + stage);
    _fpRoster = await _getRoster();
    _fpPopulateFilterOptions();
    _fpRenderRows(_fpApplyFilters());
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
    // Item [due-date requests]: same .aq-row list pattern as Reassignment
    // Requests right below it, covering both extension and hold kinds.
    var ddReqs = await api("/api/deliverables/due-date-requests?status=pending");
    var ddWrap = document.getElementById("dueDateReqList");
    document.getElementById("dueDateReqCount").textContent = ddReqs.length || "";
    ddWrap.innerHTML = "";
    if (!ddReqs.length) {
      ddWrap.appendChild(el("div", "empty-state", "No pending extension/hold requests."));
    } else {
      ddReqs.forEach(function (r) {
        var row = el("div", "aq-row");
        var main = el("div", "aq-main");
        var kindLabel = r.kind === "extension" ? "Extension" : "Hold";
        main.appendChild(el("div", "aq-title", kindLabel + " &middot; " + r.item_no + " &middot; " + r.name));
        main.appendChild(el("div", "aq-sub",
          '<span>' + r.est_no + '</span><span class="sep">&middot;</span>' +
          '<span>' + r.requested_by_email + '</span>' +
          (r.kind === "extension" ? '<span class="sep">&middot;</span><span>' + fmtDate(r.current_due_date) + ' &#8594; ' + fmtDate(r.requested_due_date) + '</span>' : "") +
          '<span class="sep">&middot;</span><span>' + r.reason + '</span>'));
        row.appendChild(main);
        var actions = el("div", "deliv-actions");
        var appr = el("button", "btn primary", "Approve");
        appr.addEventListener("click", async function () {
          await api("/api/deliverables/due-date-requests/" + r.id + "/decide", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approved: true, comment: "", actor_role: CURRENT_ROLE, actor_email: actingEmail() }),
          });
          showToast(kindLabel + " approved");
          loadFollowUp();
        });
        var rej = el("button", "btn ghost-crit", "Reject");
        rej.addEventListener("click", async function () {
          await api("/api/deliverables/due-date-requests/" + r.id + "/decide", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approved: false, comment: "", actor_role: CURRENT_ROLE, actor_email: actingEmail() }),
          });
          showToast(kindLabel + " rejected");
          loadFollowUp();
        });
        actions.appendChild(appr); actions.appendChild(rej);
        row.appendChild(actions);
        ddWrap.appendChild(row);
      });
    }

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

    var smeNoms = await api("/api/departments/sme-nominations?status=pending");
    var smeNomWrap = document.getElementById("smeNomList");
    document.getElementById("smeNomCount").textContent = smeNoms.length || "";
    smeNomWrap.innerHTML = "";
    if (!smeNoms.length) {
      smeNomWrap.appendChild(el("div", "empty-state", "No pending SME nominations."));
    } else {
      smeNoms.forEach(function (n) {
        var row = el("div", "aq-row");
        var main = el("div", "aq-main");
        main.appendChild(el("div", "aq-title", (n.name || n.email)));
        main.appendChild(el("div", "aq-sub",
          '<span>' + n.email + '</span>' +
          (n.reason ? '<span class="sep">&middot;</span><span>' + n.reason + '</span>' : "")));
        row.appendChild(main);
        var actions = el("div", "deliv-actions");
        var appr = el("button", "btn primary", "Approve");
        appr.addEventListener("click", async function () {
          await api("/api/departments/sme-nominations/" + n.id + "/decide", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approved: true, comment: "", actor_role: CURRENT_ROLE, actor_email: actingEmail() }),
          });
          showToast(n.email + " is now an SME");
          loadFollowUp();
        });
        var rej = el("button", "btn ghost-crit", "Reject");
        rej.addEventListener("click", async function () {
          var comment = prompt("Reason for declining (optional):", "") || "";
          await api("/api/departments/sme-nominations/" + n.id + "/decide", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approved: false, comment: comment, actor_role: CURRENT_ROLE, actor_email: actingEmail() }),
          });
          showToast("Nomination declined");
          loadFollowUp();
        });
        actions.appendChild(appr); actions.appendChild(rej);
        row.appendChild(actions);
        smeNomWrap.appendChild(row);
      });
    }

    // Item [follow-up redesign]: was one flat, unsorted, ungrouped list --
    // confusing once more than a handful of items are overdue at once. Now
    // grouped by Department (collapsed accordion, so the page opens calm
    // instead of a wall of rows), each row leads with a colored days-overdue
    // badge instead of a generic status pill, and a Severity filter +
    // Critical/15+-day threshold surfaces what actually needs attention
    // first. days_overdue itself now comes pre-computed from the backend.
    var FU_CRITICAL_DAYS = 15;
    var items = await api("/api/deliverables/follow-up");
    var deptSel = document.getElementById("fuDeptFilter");
    var estSel = document.getElementById("fuEstFilter");
    var focalSel = document.getElementById("fuFocalFilter");
    var severitySel = document.getElementById("fuSeverityFilter");
    var sortSel = document.getElementById("fuSortBy");
    var seenDepts = {}, seenEsts = {}, seenFocals = {};
    items.forEach(function (d) { seenDepts[d.department] = true; seenEsts[d.est_no] = true; if (d.focal) seenFocals[d.focal] = true; });
    deptSel.innerHTML = '<option value="">All Departments</option>';
    Object.keys(seenDepts).sort().forEach(function (n) { var o = el("option", "", n); o.value = n; deptSel.appendChild(o); });
    estSel.innerHTML = '<option value="">All Est Numbers</option>';
    Object.keys(seenEsts).sort().forEach(function (n) { var o = el("option", "", n); o.value = n; estSel.appendChild(o); });
    focalSel.innerHTML = '<option value="">All Focal Points</option>';
    Object.keys(seenFocals).sort().forEach(function (n) { var o = el("option", "", n); o.value = n; focalSel.appendChild(o); });

    function fuSeverity(d) { return d.days_overdue >= FU_CRITICAL_DAYS ? "critical" : "overdue"; }

    function renderFollowUpList() {
      var dept = deptSel.value, estNo = estSel.value, focal = focalSel.value, severity = severitySel.value;
      var filtered = items.filter(function (d) {
        return (!dept || d.department === dept) && (!estNo || d.est_no === estNo) &&
          (!focal || d.focal === focal) && (!severity || fuSeverity(d) === severity);
      });

      var statsWrap = document.getElementById("fuStats");
      statsWrap.innerHTML = "";
      var criticalCount = items.filter(function (d) { return fuSeverity(d) === "critical"; }).length;
      var deptCount = Object.keys(items.reduce(function (acc, d) { acc[d.department] = true; return acc; }, {})).length;
      [
        ["Overdue Total", items.length, false],
        ["Critical &#8211; 15+ Days", criticalCount, true],
        ["Departments Affected", deptCount, false],
      ].forEach(function (s) {
        statsWrap.appendChild(el("div", "fu-stat" + (s[2] ? " critical" : ""),
          '<span class="fu-stat-num">' + s[1] + '</span><span class="fu-stat-lbl">' + s[0] + '</span>'));
      });

      var wrap = document.getElementById("followUpList");
      wrap.innerHTML = "";
      if (!filtered.length) { wrap.appendChild(el("div", "empty-state", "Nothing due or overdue right now.")); return; }

      var byDept = {};
      filtered.forEach(function (d) { (byDept[d.department] = byDept[d.department] || []).push(d); });
      var deptNames = Object.keys(byDept);
      deptNames.forEach(function (n) { byDept[n].sort(function (a, b) { return b.days_overdue - a.days_overdue; }); });
      if (sortSel.value === "dept") {
        deptNames.sort();
      } else {
        deptNames.sort(function (a, b) { return byDept[b][0].days_overdue - byDept[a][0].days_overdue; });
      }

      deptNames.forEach(function (deptName) {
        var rows = byDept[deptName];
        var hasCritical = rows.some(function (d) { return fuSeverity(d) === "critical"; });
        var group = document.createElement("details");
        group.className = "fu-dept-group";
        var summary = document.createElement("summary");
        summary.appendChild(el("span", "fu-dept-name", deptLabel(deptName, null)));
        summary.appendChild(el("span", "fu-dept-tags",
          '<span class="fu-dept-count' + (hasCritical ? " has-critical" : "") + '">' + rows.length + ' overdue</span>'));
        group.appendChild(summary);
        rows.forEach(function (d) {
          var sev = fuSeverity(d);
          var row = el("div", "fu-row");
          var main = el("div", "fu-row-main");
          main.appendChild(el("div", "fu-row-title", d.item_no + " &middot; " + d.name));
          main.appendChild(el("div", "fu-row-sub",
            '<span>' + d.est_no + ' &#8211; ' + d.project_name + '</span><span class="sep">&middot;</span>' +
            '<span>Owner: ' + d.owner + '</span><span class="sep">&middot;</span>' +
            '<span>Focal: ' + d.focal + '</span><span class="sep">&middot;</span>' +
            '<span>Due ' + fmtDate(d.due_date) + '</span>'));
          row.appendChild(main);
          var side = el("div", "fu-row-side");
          side.appendChild(el("span", "fu-overdue-badge " + sev, d.days_overdue + " day" + (d.days_overdue === 1 ? "" : "s") + " overdue"));
          var remindBtn = el("button", "btn", "Remind");
          remindBtn.addEventListener("click", async function () {
            var res = await api("/api/deliverables/bulk-remind", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                submission_ids: [d.id], actor_role: CURRENT_ROLE,
                message: document.getElementById("fuMessage").value.trim() || null,
                cc_manager: document.getElementById("fuCcManager").checked,
              }),
            });
            showToast(res.sent ? "Reminder sent to " + d.owner : "Could not send &#8211; no assigned owner");
          });
          side.appendChild(remindBtn);
          row.appendChild(side);
          group.appendChild(row);
        });
        wrap.appendChild(group);
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
    severitySel.onchange = renderFollowUpList;
    sortSel.onchange = renderFollowUpList;
    renderFollowUpList();
    // Item [badge auto-refresh]: every Approve/Reject above reloads this
    // page via loadFollowUp(), so refreshing badges here (rather than at
    // each of the 4 action call sites individually) covers all of them in
    // one place -- the followupBadge count actually changes the moment a
    // request is decided, not only after a manual page reload.
    refreshNavBadges();
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
    // The question is only ever routed to Admins (blank target) or a real
    // SME email (never a name) -- when a specific SME is picked, only show
    // deliverables actually assigned to them on Focal Points, so the asker
    // can't pick an item that person has nothing to do with.
    var target = document.getElementById("supTarget").value;
    if (target) {
      var targetLower = target.trim().toLowerCase();
      delivs = delivs.filter(function (d) {
        return (d.sme_emails || []).some(function (e) { return (e || "").trim().toLowerCase() === targetLower; });
      });
    }
    delivs.forEach(function (d) {
      var opt = document.createElement("option");
      opt.value = d.item_no + " " + d.name; opt.textContent = d.item_no + " · " + d.name;
      sel.appendChild(opt);
    });
  }
  document.getElementById("supStage").addEventListener("change", _populateSupEstNo);
  document.getElementById("supEstNo").addEventListener("change", _populateSupDeliverable);
  document.getElementById("supTarget").addEventListener("change", _populateSupDeliverable);

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
      var who = m.author === "admin" ? "Admin" : (r.name || r.email || "Asker");
      var mrow = el("div", "deliv-comment", "<b>" + who + ":</b> " + m.body);
      main.appendChild(mrow);
    });
    row.appendChild(main);
    var side = el("div", "deliv-actions");
    if (r.status === "resolved") {
      side.appendChild(el("span", "pill good", '<span class="dot"></span>Resolved'));
    } else {
      side.appendChild(el("span", "pill warn", '<span class="dot"></span>Open'));
      if (opts.canReply) {
        var kbRefSelect = null;
        // Item 150/172.1: admin-only -- point this reply at an existing
        // knowledge base answer instead of writing a fresh one, so
        // resolving this ticket doesn't add a duplicate entry (the reply
        // still goes out to the asker either way).
        if (opts.kbEntries && opts.kbEntries.length) {
          kbRefSelect = el("select");
          kbRefSelect.appendChild(el("option", "", "Reference an existing answer&#8230;"));
          opts.kbEntries.forEach(function (e) {
            var o = el("option", "", "#" + e.id + " &middot; " + e.question.slice(0, 60));
            o.value = e.id;
            kbRefSelect.appendChild(o);
          });
          side.appendChild(kbRefSelect);
        }
        var replyBtn = el("button", "btn", "Reply");
        replyBtn.addEventListener("click", async function () {
          var picked = (kbRefSelect && kbRefSelect.value)
            ? opts.kbEntries.find(function (e) { return String(e.id) === kbRefSelect.value; }) : null;
          var result = await openActionCommentModal({
            title: "Reply",
            hint: opts.replyPlaceholder,
            placeholder: opts.replyPlaceholder,
            defaultValue: picked ? picked.answer : "",
            required: true,
            requiredMessage: "A reply message is required",
            confirmLabel: "Send Reply",
            allowFile: false,
          });
          if (!result) return;
          var payload = { body: result.comment, actor_role: CURRENT_ROLE, actor_email: myIdentity() };
          if (picked) payload.kb_reference_id = picked.id;
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
        side.appendChild(replyBtn);
      }
      if (opts.canResolve) {
        var resolveBtn = el("button", "btn", "Mark Resolved");
        resolveBtn.addEventListener("click", async function () {
          // If the admin picked a KB reference but resolved straight away
          // without hitting Reply, the asker would otherwise get nothing --
          // send them the referenced answer first so resolving always means
          // "they've been answered."
          var hasAdminReply = (r.messages || []).some(function (m) { return m.author === "admin"; });
          if (!hasAdminReply && kbRefSelect && kbRefSelect.value) {
            var picked = opts.kbEntries.find(function (e) { return String(e.id) === kbRefSelect.value; });
            if (picked) {
              try {
                await api("/api/support/" + r.id + "/reply", {
                  method: "POST", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    body: picked.answer, actor_role: CURRENT_ROLE, actor_email: myIdentity(),
                    kb_reference_id: picked.id,
                  }),
                });
              } catch (err) {
                showToast("Could not send the referenced answer &#8211; " + apiErrorDetail(err), true);
                return;
              }
            }
          }
          await api("/api/support/" + r.id + "/resolve?actor_role=" + CURRENT_ROLE, { method: "PATCH" });
          showToast("Marked resolved");
          refreshNavBadges();
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
            canReply: true, canResolve: false, replyEndpoint: "respond", replyPlaceholder: "Reply to the admin…",
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
        canReply: true, canResolve: true, replyEndpoint: "reply", replyPlaceholder: "Reply to the asker…",
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
    buildAnnouncementFilterUI();
    var qs = "?limit=500&category=news";
    if (CURRENT_ROLE !== "Admin") {
      qs += "&actor_role=" + encodeURIComponent(CURRENT_ROLE) + "&actor_email=" + encodeURIComponent(passiveIdentity());
    }
    announcementsAll = await api("/api/announcements" + qs);
    await _getEmailRoleMap();
    renderAnnouncements();
    // Item [nav badges]: opening this view marks everything currently
    // loaded as seen -- no read-tracking exists anywhere in the backend
    // (no real login to hang a per-user table off of), so this is a
    // per-browser localStorage timestamp, same trust level as the existing
    // myEmail cache.
    localStorage.setItem("annLastSeenAt", new Date().toISOString());
    document.getElementById("announcementsBadge").textContent = "";
  }
  // Item [reminders tab]: the row markup is identical between Announcements
  // and Reminders (same fields, same click-through) -- only the source
  // array and the container differ, so this is shared rather than
  // duplicated between renderAnnouncements() and renderReminders().
  function annRowEl(a) {
    var meta = annIcon(a);
    var row = el("div", "ann-row");
    row.appendChild(el("div", "ann-ic " + meta[1], meta[0]));
    var main = el("div", "ann-main");
    var when = new Date(a.created_at).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
    main.appendChild(el("div", "ann-top", '<span class="ann-title">' + a.title + '</span><span class="ann-time">' + when + '</span>'));
    main.appendChild(el("div", "ann-body", a.body));
    main.appendChild(el("div", "ann-meta", "To: <b>" + annAudienceTag(a, _emailRoleMap) + "</b> &middot; " + a.email_status));
    row.appendChild(main);
    if (a.submission_id || a.project_id) {
      row.style.cursor = "pointer";
      row.addEventListener("click", function () {
        if (a.submission_id) openDelivModal(a.submission_id);
        else openDetail(a.project_id);
      });
    }
    return row;
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
    list.forEach(function (a) { wrap.appendChild(annRowEl(a)); });
  }

  var remindersAll = [];
  async function loadReminders() {
    var qs = "?limit=500&category=reminders";
    if (CURRENT_ROLE !== "Admin") {
      qs += "&actor_role=" + encodeURIComponent(CURRENT_ROLE) + "&actor_email=" + encodeURIComponent(passiveIdentity());
    }
    remindersAll = await api("/api/announcements" + qs);
    await _getEmailRoleMap();
    renderReminders();
    localStorage.setItem("remLastSeenAt", new Date().toISOString());
    document.getElementById("remindersBadge").textContent = "";
  }
  function renderReminders() {
    var from = document.getElementById("remFromDate").value;
    var to = document.getElementById("remToDate").value;
    var list = remindersAll.filter(function (a) {
      var day = a.created_at.slice(0, 10);
      if (from && day < from) return false;
      if (to && day > to) return false;
      return true;
    });
    var wrap = document.getElementById("remindersList");
    wrap.innerHTML = "";
    if (!list.length) { wrap.appendChild(el("div", "empty-state", "No reminders match this filter.")); return; }
    list.forEach(function (a) { wrap.appendChild(annRowEl(a)); });
  }
  document.getElementById("remFromDate").addEventListener("change", renderReminders);
  document.getElementById("remToDate").addEventListener("change", renderReminders);
  document.getElementById("remClearFilters").addEventListener("click", function () {
    document.getElementById("remFromDate").value = "";
    document.getElementById("remToDate").value = "";
    renderReminders();
  });

  /* ================= CREATE PROJECT ================= */
  (function () {
    var fileInput = document.getElementById("cfTenderDocs");
    var folderInput = document.getElementById("cfTenderDocsFolder");
    var summary = document.getElementById("cfTenderDocsSummary");
    function updateSummary() {
      var n = fileInput.files.length + folderInput.files.length;
      summary.textContent = n ? n + " file" + (n === 1 ? "" : "s") + " selected" : "";
    }
    fileInput.addEventListener("change", updateSummary);
    folderInput.addEventListener("change", updateSummary);
    document.getElementById("cfTenderDocsUploadWrap").appendChild(fileOrFolderButton("Upload", fileInput, folderInput));
  })();
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
        await uploadTenderDocFiles(p.id, document.getElementById("cfTenderDocs").files, "", false);
        await uploadTenderDocFiles(p.id, document.getElementById("cfTenderDocsFolder").files, "", true);
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
    // Est numbers were failing (e.g. searching "1800"/"1553") because users
    // type bare digits, not the "Est-" prefix -- normalize both sides so a
    // digits-only search still counts as an exact Est-No match.
    var norm = function (s) { return s.toLowerCase().replace(/^est-/, ""); };
    var exact = match.filter(function (p) { return norm(p.est_no) === norm(v); });
    if (exact.length >= 1) {
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
  async function populateActingEmailQuickPick(isRetry) {
    var quickPick = document.getElementById("actingEmailQuickPick");
    if (CURRENT_ROLE !== "Owner" && CURRENT_ROLE !== "SME") { quickPick.style.display = "none"; return; }
    // A slow/failed fetch here (e.g. Render's free-tier cold start on the
    // very first request after idling) used to throw uncaught and leave the
    // quick-pick permanently stuck hidden with nothing but the placeholder --
    // no error shown anywhere, just silently broken until the next full role
    // switch happened to succeed. One quiet retry covers the transient case.
    var all, roster;
    try {
      all = await api("/api/deliverables");
      roster = await _getRoster();
    } catch (err) {
      if (!isRetry) return populateActingEmailQuickPick(true);
      console.error("Quick pick failed to load", err);
      return;
    }
    var counts = {};
    all.forEach(function (d) {
      var emails = CURRENT_ROLE === "Owner" ? (d.owner_emails || []) : (d.sme_emails || []);
      emails.forEach(function (email) {
        if (!counts[email]) counts[email] = { due: 0, pendingReview: 0 };
        if (d.deadline_status === "due") counts[email].due++;
        if (d.status === "pending_review") counts[email].pendingReview++;
      });
    });
    // Every roster member of this role is offered, not just whoever
    // already has assigned work -- a freshly-added Owner/SME with nothing
    // assigned yet still needs to be pickable to actually test as them.
    roster.filter(function (u) { return u.role === CURRENT_ROLE; }).forEach(function (u) {
      if (!counts[u.email]) counts[u.email] = { due: 0, pendingReview: 0 };
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
  document.getElementById("roleSelect").addEventListener("change", async function (e) {
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
    await _refreshCanSeeBmTriage();
    document.getElementById("bmTriageNavItem").hidden = !canSeeBmTriage();
    document.getElementById("assignedNavItem").hidden = !canSeeAssigned();
    document.getElementById("remindersNavItem").hidden = !canSeeReminders();
    populateActingEmailQuickPick();
    if (!showAdmin && ADMIN_ONLY_VIEWS.some(function (v) { return !document.getElementById("view-" + v).hidden; })) switchView("dashboard");
    if (!canSeeBmTriage() && !document.getElementById("view-bmtriage").hidden) switchView("dashboard");
    if (!canSeeAssigned() && !document.getElementById("view-assigned").hidden) switchView("dashboard");
    if (!canSeeReminders() && !document.getElementById("view-reminders").hidden) switchView("dashboard");
    if (currentProjectId && !document.getElementById("view-detail").hidden) openDetail(currentProjectId);
    if (!document.getElementById("view-announcements").hidden) loadAnnouncements();
    if (!document.getElementById("view-reminders").hidden) loadReminders();
    checkBmTriageDeadline();
    refreshNavBadges();
  });
  // Item [BM triage viewer bug]: on a page refresh, some browsers restore a
  // <select>'s prior value from before the reload without firing "change" --
  // the dropdown then visually shows e.g. "Viewer" while every piece of app
  // state (CURRENT_ROLE, the nav's hidden flags) is still sitting at the
  // "Admin" default, since nothing ever re-ran to sync them. This pilot has
  // no real login and doesn't persist the role choice across reloads by
  // design, so force the control back to the actual default on every load.
  document.getElementById("roleSelect").value = "Admin";
  document.getElementById("actingEmailQuickPick").addEventListener("change", function (e) {
    if (!e.target.value) return;
    document.getElementById("actingEmail").value = e.target.value;
    document.getElementById("actingEmail").dispatchEvent(new Event("change"));
  });
  document.getElementById("actingEmail").addEventListener("change", async function () {
    if (!document.getElementById("view-announcements").hidden) loadAnnouncements();
    if (!document.getElementById("view-reminders").hidden) loadReminders();
    // Item 183: "My Items" reads the acting-as-email identity live, so
    // switching who you're acting as should refresh the Dashboard's scoped
    // view immediately rather than showing stale data until the next visit.
    if (dashFocus === "mine" && !document.getElementById("view-dashboard").hidden) loadDashboard();
    checkBmTriageDeadline();
    await _refreshCanSeeBmTriage();
    document.getElementById("bmTriageNavItem").hidden = !canSeeBmTriage();
    if (!canSeeBmTriage() && !document.getElementById("view-bmtriage").hidden) switchView("dashboard");
    refreshNavBadges();
  });
  document.getElementById("themeToggle").addEventListener("click", function () {
    var root = document.documentElement;
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    this.textContent = next === "dark" ? "Light mode" : "Dark mode";
  });

  // Item 170: a native date input can't be restyled to show month names
  // while picking (the calendar/typed-value display is entirely
  // browser-controlled) -- so every date input on the page gets a small
  // read-only "16-Sep-2026" reading right after it instead, updating live
  // as soon as a value is picked, without giving up the native picker.
  document.querySelectorAll('input[type="date"]').forEach(function (input) {
    var preview = el("span", "date-preview");
    input.insertAdjacentElement("afterend", preview);
    var update = function () { preview.textContent = input.value ? fmtDate(input.value) : ""; };
    input.addEventListener("change", update);
    update();
  });

  /* ================= INIT ================= */
  // Item [BM triage viewer bug], part 2: a page restored from the browser's
  // back-forward cache (bfcache -- back/forward nav, some "reopen tab"
  // flows) resumes its exact frozen JS state without re-running any script
  // on this page at all -- so a role switched right before navigating away
  // stays showing in the dropdown, but every nav-visibility decision this
  // file makes only runs once, at initial script execution, and never
  // reruns. The only reliable fix is forcing a real reload when this
  // happens, so the whole app boots fresh instead of resuming stale state.
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) location.reload();
  });
  document.getElementById("todayLabel").textContent = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "2-digit", month: "long", year: "numeric" });
  // Item [nav badges]: piggybacking only on the role/acting-email change
  // handlers isn't enough -- CURRENT_ROLE starts hardcoded to "Admin" and
  // neither handler fires on a fresh load, so badges would stay empty
  // until the user manually touched role or acting-email.
  refreshNavBadges();

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

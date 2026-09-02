/* Mobile-app shell for the L0/L1 pilot -- everything genuinely new for the
   phone experience lives here and in css/mobile.css, physically isolated
   from app.js's own IIFE. Reaches into app.js's shared data-loaders/render
   helpers/state through the one deliberate seam it exports at the very end
   of its own IIFE: window.__app (see app.js's own comment there). This file
   never re-implements a status/deadline/weight/readiness calculation --
   it only renders what app.js and the backend already computed.

   Plain script (not type="module") to match app.js's own convention and
   because it needs window.__app to already exist -- loaded after app.js's
   own <script> tag in index.html.

   Loaded unconditionally on every device (like landing.css/js already are)
   -- the body.mobile-shell class is what actually turns any of this on; a
   desktop user never sees mobile.css apply since every rule in it is
   scoped under that class, and the JS below only ever *reads* state /
   toggles that one class + wires the bottom nav, it doesn't touch anything
   desktop-only until later phases add real render branches.
*/
(function () {
  "use strict";

  // Item [mobile-app] Phase 1: mode detection only. 780px is deliberately
  // between the existing 980px "tablet drawer" breakpoint (styles.css, the
  // sidebar going off-canvas) and the existing 640px "phone reflow" tier --
  // it defines a clean third tier for the bespoke mobile shell without
  // colliding with either of those pre-existing, still-in-use breakpoints.
  var MOBILE_MQ = window.matchMedia("(max-width: 780px)");

  function isMobileMode() {
    return MOBILE_MQ.matches;
  }

  function _applyModeClass() {
    document.body.classList.toggle("mobile-shell", isMobileMode());
  }

  // matchMedia's own change event should cover both resize and
  // orientation change (rotating a phone crosses the same width
  // threshold) on its own -- kept as the primary signal.
  if (MOBILE_MQ.addEventListener) {
    MOBILE_MQ.addEventListener("change", _applyModeClass);
  } else if (MOBILE_MQ.addListener) {
    // Safari <14 fallback -- addEventListener on a MediaQueryList is a
    // fairly recent addition.
    MOBILE_MQ.addListener(_applyModeClass);
  }
  // Belt-and-suspenders: a plain debounced window resize listener too --
  // some viewport-emulation contexts (browser devtools device toolbars,
  // automated testing tools) resize the layout viewport without reliably
  // firing a MediaQueryList "change" event the way a real device
  // rotation/window drag does, and this is cheap enough not to matter
  // either way (150ms debounce, single classList.toggle call).
  var _resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(_applyModeClass, 150);
  });

  // Applied as early as possible (this script runs at the end of <body>,
  // after app.js has already started its own boot sequence) so nothing
  // downstream ever has to guess whether the class is set yet.
  _applyModeClass();

  // Item [mobile-app] Phase 2: PWA baseline. Registered unconditionally
  // (not just under body.mobile-shell) -- a desktop Chrome/Edge user can
  // install the app too, and the SW itself is a pure app-shell cache, inert
  // for API calls either way (see sw.js's own header comment). Root scope
  // ("/", matching Service-Worker-Allowed on the backend route) so it can
  // control the whole app, not just /static/. Deliberately no top-level
  // error UI on failure -- this is a progressive enhancement, not a
  // requirement, and plenty of dev/incognito contexts legitimately have no
  // SW support or block registration.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function (err) {
        console.warn("l0l1: service worker registration failed", err);
      });
    });
  }

  // ---------------------------------------------------------------------
  // Item [mobile-app] Phase 3: bottom nav + "More" screen.
  // ---------------------------------------------------------------------
  // Icon path data below is deliberately duplicated from app.js's own
  // NAV_ICONS (app.js:739-763), not imported through window.__app -- it's
  // static SVG path data, not logic, and keeping it here is what actually
  // keeps this file "physically isolated" per this file's own header
  // comment: mobile.js owns 100% of the bottom nav / More screen's
  // behavior (clicks, active-state, icons) directly, rather than piggy-
  // backing on app.js's .nav-item click-wiring, which is a bare class
  // selector carrying the desktop rail's own visual styling that would
  // otherwise leak into this fixed-bottom, completely different context.
  function _mobileNavIcon(inner) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + inner + "</svg>";
  }
  var MOBILE_ICONS = {
    dashboard: _mobileNavIcon('<rect x="3.5" y="3.5" width="7.5" height="9" rx="1.5"/><rect x="13" y="3.5" width="7.5" height="5.5" rx="1.5"/><rect x="13" y="11" width="7.5" height="9.5" rx="1.5"/><rect x="3.5" y="14.5" width="7.5" height="6" rx="1.5"/>'),
    l0: _mobileNavIcon('<path d="M6 3.5h8l4 4v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-16a1 1 0 0 1 1-1z"/><path d="M14 3.5V8h4"/><path d="M8.5 12.5h7M8.5 15.5h7M8.5 18.5h4"/>'),
    l1: _mobileNavIcon('<path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h4.5l2 2.5h8A1.5 1.5 0 0 1 21 9v9A1.5 1.5 0 0 1 19.5 19.5H5A1.5 1.5 0 0 1 3.5 18z"/><path d="M8.5 13.5h3M8.5 16h5.5"/>'),
    assigned: _mobileNavIcon('<rect x="5.5" y="3.5" width="13" height="17" rx="2"/><rect x="9" y="2.5" width="6" height="3" rx="1"/><path d="M9 12.5l2 2 4-4.5"/>'),
    more: _mobileNavIcon('<circle cx="5" cy="12" r="1.8" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.8" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.8" fill="currentColor" stroke="none"/>'),
    journey: _mobileNavIcon('<circle cx="12" cy="12" r="9"/><path d="M15 9l-2 6-4-2-2 6" transform="rotate(20 12 12)"/><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/>'),
    gantt: _mobileNavIcon('<rect x="3.5" y="4.5" width="17" height="16" rx="2"/><path d="M3.5 9.5h17M8 3v3M16 3v3"/><rect x="12.5" y="12.5" width="4.5" height="4" rx=".6" fill="currentColor" stroke="none"/>'),
    announcements: _mobileNavIcon('<path d="M6 9a6 6 0 1 1 12 0c0 4.5 1.5 6 1.5 6h-15S6 13.5 6 9z"/><path d="M10 19a2 2 0 0 0 4 0"/>'),
    reminders: _mobileNavIcon('<circle cx="12" cy="13" r="7.5"/><path d="M12 9v4l2.5 1.5"/><path d="M5 4.5L2.5 7M19 4.5L21.5 7"/>'),
    bmtriage: _mobileNavIcon('<rect x="5.5" y="3.5" width="13" height="17" rx="2"/><rect x="9" y="2.5" width="6" height="3" rx="1"/><path d="M8.5 11.5h7M8.5 14.5h7M8.5 17.5h4"/>'),
    performance: _mobileNavIcon('<path d="M4 20V10M10 20V4M16 20v-7M21 20H3"/>'),
    deliverableformulas: _mobileNavIcon('<path d="M5 4.5a1.5 1.5 0 0 1 1.5-1.5H9a1.5 1.5 0 0 1 1.5 1.5v15A1.5 1.5 0 0 1 9 21H6.5A1.5 1.5 0 0 1 5 19.5z"/><path d="M13 6.3l2.4-.9a1.5 1.5 0 0 1 1.93.88l4.86 13.35a1.5 1.5 0 0 1-.9 1.92l-2.35.85a1.5 1.5 0 0 1-1.92-.9L12.16 8.1"/>'),
    masterpo: _mobileNavIcon('<path d="M6 3.5h9l4 4v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-16a1 1 0 0 1 1-1z"/><path d="M15 3.5V8h4M8.5 12h7M8.5 15h7M8.5 18h4" opacity=".55"/><path d="M4 6.5h1.6M4 10h1.6M4 13.5h1.6" opacity=".55"/>'),
    myrequests: _mobileNavIcon('<path d="M21.5 3.5L2.5 10.5l7 3 3 7z"/><path d="M21.5 3.5L12.5 13.5"/>'),
    support: _mobileNavIcon('<path d="M4 5.5h16A1.5 1.5 0 0 1 21.5 7v9a1.5 1.5 0 0 1-1.5 1.5H9l-4.5 4V17H4A1.5 1.5 0 0 1 2.5 15.5V7A1.5 1.5 0 0 1 4 5.5z"/><path d="M10 10.2a2 2 0 1 1 2.7 1.87c-.7.28-1.2.9-1.2 1.63v.1" /><circle cx="11.7" cy="16.2" r=".9" fill="currentColor" stroke="none"/>'),
    create: _mobileNavIcon('<path d="M12 5v14M5 12h14"/>'),
    reports: _mobileNavIcon('<rect x="3.5" y="3.5" width="17" height="17" rx="2"/><path d="M8 17V11M12 17V7M16 17v-5"/>'),
    scores: _mobileNavIcon('<path d="M8 4.5h8v4a4 4 0 0 1-8 0z"/><path d="M8 5.5H4.5v1a3.5 3.5 0 0 0 3.5 3.5M16 5.5h3.5v1a3.5 3.5 0 0 1-3.5 3.5"/><path d="M12 12.5V16M9 20h6M12 16a4 4 0 0 0 0 4"/>'),
    focalpoints: _mobileNavIcon('<path d="M6.5 3.5c.5 2 1.4 3.9 2.7 5.6.4.5.3 1.2-.1 1.6l-1.6 1.6a13.5 13.5 0 0 0 6.2 6.2l1.6-1.6c.4-.4 1.1-.5 1.6-.1 1.7 1.3 3.6 2.2 5.6 2.7v3.5c-8.8 0-17-8.2-17-17z"/>'),
    deliverablesconfig: _mobileNavIcon('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.04 1.56V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.96 19a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.56-1.04H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.96a1.7 1.7 0 0 0-.34-1.87l-.06-.06A2 2 0 1 1 7.03 4.2l.06.06A1.7 1.7 0 0 0 8.96 4.6a1.7 1.7 0 0 0 1.04-1.56V3a2 2 0 1 1 4 0v.09c0 .69.4 1.31 1.04 1.56.62.25 1.33.12 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87c.25.62.87 1.04 1.56 1.04H21a2 2 0 1 1 0 4h-.09c-.69 0-1.31.42-1.56 1.04z"/>'),
    requests: _mobileNavIcon('<path d="M3.5 12.5h5l1.5 3h4l1.5-3h5"/><path d="M6 12.5L4.2 6.2A1.5 1.5 0 0 1 5.65 4.5h12.7a1.5 1.5 0 0 1 1.45 1.7L18 12.5"/><rect x="3.5" y="12.5" width="17" height="6.5" rx="1.5"/>'),
    followup: _mobileNavIcon('<path d="M3 10.5v3a1.5 1.5 0 0 0 1.5 1.5H7l4.5 4V5l-4.5 4H4.5A1.5 1.5 0 0 0 3 10.5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>'),
    tickets: _mobileNavIcon('<circle cx="12" cy="12" r="9"/><path d="M9.3 9.3a2.7 2.7 0 1 1 3.9 2.4c-.8.4-1.5 1.1-1.5 2v.3"/><circle cx="12" cy="16.7" r=".9" fill="currentColor" stroke="none"/>'),
    archivedprojects: _mobileNavIcon('<rect x="3" y="4" width="18" height="4.5" rx="1"/><path d="M4.5 8.5V18a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5V8.5"/><path d="M10 13h4"/>'),
  };

  // Fill the 5 static bottom-nav buttons' icon spans once -- they never
  // change, unlike the More screen's rows which are rebuilt on every visit.
  document.querySelectorAll("#mobileBottomNav .mbn-item[data-view]").forEach(function (btn) {
    var ic = btn.querySelector(".mbn-ic");
    if (ic && MOBILE_ICONS[btn.dataset.view]) ic.innerHTML = MOBILE_ICONS[btn.dataset.view];
    btn.addEventListener("click", function () {
      window.__app.switchView(btn.dataset.view);
    });
  });

  // Bottom-nav active state follows location.hash, the same signal
  // switchView() itself already writes for every real nav view (app.js's
  // own item 99) -- listening here instead of wrapping switchView() means
  // this stays correct regardless of *what* triggered the navigation
  // (this bottom nav, the desktop rail, back/forward, a deep link), with
  // zero coupling to app.js's internals. A hash on a view that isn't one
  // of these 5 tabs (a More-screen destination like "reports", or no
  // "view=..." hash at all for "detail"/"triage" -- app.js:724) correctly
  // leaves every tab unhighlighted rather than guessing, since none of
  // them is actually showing -- Phase 9's project/tender drill-down is
  // where "detail" reached from L0/Assigned gets a real parent-tab answer.
  function _syncBottomNavActive() {
    var m = /^#view=([\w-]+)/.exec(location.hash);
    if (!m) return;
    document.querySelectorAll("#mobileBottomNav .mbn-item").forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.view === m[1]);
    });
  }
  window.addEventListener("hashchange", _syncBottomNavActive);
  _syncBottomNavActive();

  // Live-mirrors a desktop rail badge's count onto a bottom-nav badge --
  // can't reuse the same element id twice in one document, and the count
  // itself is computed deep inside app.js's loaders (loadProjectsTable,
  // loadAssigned), not exposed as a standalone value -- mirroring the
  // already-rendered DOM is simpler and can never drift from what the
  // desktop rail itself shows, without re-implementing that computation.
  function _mirrorBadge(sourceId, mirrorId) {
    var source = document.getElementById(sourceId);
    var mirror = document.getElementById(mirrorId);
    if (!source || !mirror) return;
    function sync() { mirror.textContent = source.textContent; }
    sync();
    new MutationObserver(sync).observe(source, { childList: true, characterData: true, subtree: true });
  }
  _mirrorBadge("l0Badge", "mbnL0Badge");
  _mirrorBadge("l1Badge", "mbnL1Badge");
  _mirrorBadge("assignedBadge", "mbnAssignedBadge");

  // "More" screen: grouped rows mirroring the desktop rail's own Workspace/
  // Admin split (index.html:209-258), minus the 4 tabs already in the
  // bottom nav. Rebuilt from scratch on every switchView("more") (wired
  // onto window.__app.LOADERS below, the same object switchView() itself
  // reads from), so admin-gating and the reminders/BM-triage role checks
  // are always read fresh off the desktop rail's own already-computed
  // .hidden state and can("create") -- never re-implemented here, and
  // never stale even if the acting role changed since this screen was
  // last open.
  var MORE_GROUPS = [
    { label: "Track", rows: [
      { view: "journey", label: "Discover L0/L1" },
      { view: "gantt", label: "Timeline" },
      { view: "announcements", label: "Announcements", badgeSrc: "announcementsBadge" },
      { view: "reminders", label: "Reminders", badgeSrc: "remindersBadge", hiddenSrc: "remindersNavItem" },
      { view: "bmtriage", label: "BM Triage Status", badgeSrc: "bmTriageBadge", hiddenSrc: "bmTriageNavItem" },
    ] },
    { label: "Insights", rows: [
      { view: "performance", label: "Performance" },
      { view: "deliverableformulas", label: "Deliverables Catalog" },
      { view: "masterpo", label: "Master POs List" },
    ] },
    { label: "Requests & Support", rows: [
      { view: "myrequests", label: "My Requests" },
      { view: "support", label: "Q/A – Ask the Team" },
    ] },
    { label: "Admin", adminOnly: true, rows: [
      { view: "create", label: "Create L0 / L1" },
      { view: "reports", label: "Reports" },
      { view: "scores", label: "Top Achievers" },
      { view: "focalpoints", label: "Focal Points" },
      { view: "deliverablesconfig", label: "Deliverables Configuration" },
      { view: "requests", label: "Requests", badgeSrc: "requestsBadge" },
      { view: "followup", label: "Follow Up" },
      { view: "tickets", label: "Open Questions", badgeSrc: "ticketsBadge" },
      { view: "archivedprojects", label: "Archived Projects" },
    ] },
  ];
  function _renderMoreScreen() {
    var host = document.getElementById("mobileMoreScreen");
    if (!host) return;
    var app = window.__app;
    host.innerHTML = "";
    MORE_GROUPS.forEach(function (group) {
      if (group.adminOnly && !app.can("create")) return;
      var visibleRows = group.rows.filter(function (row) {
        if (!row.hiddenSrc) return true;
        var srcEl = document.getElementById(row.hiddenSrc);
        return !srcEl || !srcEl.hidden;
      });
      if (!visibleRows.length) return;
      var groupEl = document.createElement("div");
      groupEl.className = "mobile-more-group";
      var labelEl = document.createElement("div");
      labelEl.className = "mobile-more-group-label";
      labelEl.textContent = group.label;
      groupEl.appendChild(labelEl);
      visibleRows.forEach(function (row) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "mobile-more-row";
        var icEl = document.createElement("span");
        icEl.className = "mmr-ic";
        icEl.innerHTML = MOBILE_ICONS[row.view] || "";
        var labelSpan = document.createElement("span");
        labelSpan.className = "mmr-label";
        labelSpan.textContent = row.label;
        btn.appendChild(icEl);
        btn.appendChild(labelSpan);
        if (row.badgeSrc) {
          var src = document.getElementById(row.badgeSrc);
          if (src && src.textContent) {
            var badgeEl = document.createElement("span");
            badgeEl.className = "mmr-badge";
            badgeEl.textContent = src.textContent;
            btn.appendChild(badgeEl);
          }
        }
        var chevron = document.createElement("span");
        chevron.className = "mmr-chevron";
        chevron.innerHTML = _mobileNavIcon('<path d="M9 5l7 7-7 7"/>');
        btn.appendChild(chevron);
        btn.addEventListener("click", function () { app.switchView(row.view); });
        groupEl.appendChild(btn);
      });
      host.appendChild(groupEl);
    });
  }
  window.__app.LOADERS.more = _renderMoreScreen;

  // Exposed for later phases (mobile render branches) and for debugging --
  // kept minimal on purpose.
  window.__mobile = {
    isMobileMode: isMobileMode,
  };
})();

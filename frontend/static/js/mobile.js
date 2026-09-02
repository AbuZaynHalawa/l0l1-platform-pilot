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

  // Exposed for later phases (bottom nav, mobile render branches) and for
  // debugging -- kept minimal on purpose for this first phase.
  window.__mobile = {
    isMobileMode: isMobileMode,
  };
})();

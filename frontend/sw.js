/* Service worker for the L0/L1 Platform PWA -- app-shell caching ONLY.
   Item [mobile-app] Phase 2. Served at root scope (/sw.js, via a dedicated
   backend route -- see backend/main.py's service_worker()) rather than from
   under /static/, because a SW's scope can never be broader than the path
   it's served from: registered at /static/sw.js it could only ever control
   pages under /static/, and the app itself is served from /.

   Strategy: network-first with a cache fallback, for the app shell only
   (HTML/CSS/JS/icons/manifest/font stylesheet). Try the network first and
   cache whatever comes back; fall back to the cached copy only when the
   network request itself fails (offline, or no connectivity). This is
   deliberately NOT a fixed install-time precache list: shell asset URLs
   carry a `?v=<mtime>` cache-busting query string from backend/main.py's
   index() route that changes on every deploy, so a hardcoded precache list
   would silently stop matching the very next deploy. Matching ignores that
   query string (ignoreSearch) so a cached entry still hits across a version
   bump; network-first means a signed-in user with connectivity always gets
   today's shell, and only ever sees a (possibly one-version-stale) cached
   shell when there's genuinely no network -- "installable and fast", not
   "offline-first": this is a live-data internal tool, not an offline app.

   /api/* and /local-files/* requests are explicitly passed through
   untouched -- never cached, never intercepted -- matching
   NoCacheStaticFiles's own philosophy (main.py:44-52). A cached tender
   status or deliverable list would be actively wrong, not just stale, so
   this SW must never be in a position to serve one.
*/
"use strict";

var SHELL_CACHE = "l0l1-shell-v1";

self.addEventListener("install", function () {
  // Take over as soon as install finishes rather than waiting for every
  // open tab to close -- shell assets are already versioned by their own
  // query string, so there's no "old shell talking to a new SW" hazard
  // that waiting would actually protect against here.
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys()
      .then(function (names) {
        return Promise.all(
          names
            .filter(function (name) { return name !== SHELL_CACHE; })
            .map(function (name) { return caches.delete(name); })
        );
      })
      .then(function () { return self.clients.claim(); })
  );
});

function isApiOrFiles(url) {
  return url.pathname.indexOf("/api/") === 0 || url.pathname.indexOf("/local-files/") === 0;
}

self.addEventListener("fetch", function (event) {
  var req = event.request;
  if (req.method !== "GET") return; // never intercept writes

  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // Google Fonts etc. -- browser handles those natively
  if (isApiOrFiles(url)) return; // explicit passthrough, no caching, ever

  event.respondWith(
    caches.open(SHELL_CACHE).then(function (cache) {
      return cache.match(req, { ignoreSearch: true }).then(function (cached) {
        return fetch(req)
          .then(function (res) {
            if (res && res.ok) cache.put(req, res.clone());
            return res;
          })
          .catch(function () {
            // Offline (or the network request itself failed) -- fall back
            // to whatever shell we already have; if we have nothing either,
            // this legitimately rejects, same as an uncached fetch would.
            if (cached) return cached;
            throw new Error("l0l1-sw: no network and nothing cached for " + req.url);
          });
      });
    })
  );
});

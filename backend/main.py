import asyncio
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse

from .database import engine
from . import models
from .routers import (
    projects, deliverables, announcements_router, dashboard, departments, milestones, gantt, support, po_line_items,
    deliverables_config, reports, ai_support, export,
)
from .scheduler import scheduler_loop

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Project Readiness (L0/L1) Platform (Pilot)")


@app.on_event("startup")
async def _start_scheduler():
    # Item [due-soon nudge] / [request escalation]: an in-process background
    # loop, not a host-specific cron job -- see scheduler.py's docstring.
    asyncio.create_task(scheduler_loop())

app.include_router(projects.router)
app.include_router(deliverables.router)
app.include_router(announcements_router.router)
app.include_router(dashboard.router)
app.include_router(departments.router)
app.include_router(milestones.router)
app.include_router(gantt.router)
app.include_router(support.router)
app.include_router(po_line_items.router)
app.include_router(deliverables_config.router)
app.include_router(reports.router)
app.include_router(ai_support.router)
app.include_router(export.router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
LOCAL_FILES_DIR = Path(__file__).resolve().parent.parent / "data" / "local_storage"


class NoCacheStaticFiles(StaticFiles):
    """Pilot ships frontend changes frequently — force browsers to always
    revalidate (still cheap, via ETag/If-None-Match) instead of silently
    serving a stale cached app.js/styles.css after a deploy.
    """
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", NoCacheStaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")
app.mount("/local-files", StaticFiles(directory=str(LOCAL_FILES_DIR)), name="local-files")


@app.get("/")
def index():
    # A tab left open across a deploy keeps its in-memory app.js/styles.css
    # no matter what Cache-Control says on /static — that only governs re-fetches.
    # Stamping the asset URLs with the file's own mtime forces a brand-new URL
    # (and therefore a real fetch) on every deploy that changes either file.
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    # landing.css/landing.js stamped the same way as app.js/styles.css --
    # deliberately NOT the vendored three.js/OrbitControls files under
    # static/js/vendor/. Those are referenced only via the import map's
    # bare "three" specifier, and OrbitControls.js's own internal
    # `import ... from 'three'` has to resolve to that exact same URL —
    # a query string here and not there (or a different one each deploy)
    # would make the browser treat them as two different module
    # identities. If the vendored files ever need cache-busting after a
    # version bump, do it by changing the filename, not a query string.
    # Item [mobile-app]: mobile.css/mobile.js stamped the same way -- plain
    # additive files, no import-map identity concerns like the vendored
    # three.js files have. manifest.json included too (Phase 2) -- same
    # stale-in-memory-tab concern doesn't really apply to it (browsers fetch
    # it lazily, not on every page load), but it's one more file whose icon
    # set could change later, and stamping it costs nothing.
    version = str(int(max(
        (FRONTEND_DIR / "static" / "app.js").stat().st_mtime,
        (FRONTEND_DIR / "static" / "styles.css").stat().st_mtime,
        (FRONTEND_DIR / "static" / "css" / "landing.css").stat().st_mtime,
        (FRONTEND_DIR / "static" / "js" / "landing.js").stat().st_mtime,
        (FRONTEND_DIR / "static" / "css" / "mobile.css").stat().st_mtime,
        (FRONTEND_DIR / "static" / "js" / "mobile.js").stat().st_mtime,
        (FRONTEND_DIR / "static" / "manifest.json").stat().st_mtime,
    )))
    html = html.replace('/static/app.js"', f'/static/app.js?v={version}"')
    html = html.replace('/static/styles.css"', f'/static/styles.css?v={version}"')
    html = html.replace('/static/css/landing.css"', f'/static/css/landing.css?v={version}"')
    html = html.replace('/static/js/landing.js"', f'/static/js/landing.js?v={version}"')
    html = html.replace('/static/css/mobile.css"', f'/static/css/mobile.css?v={version}"')
    html = html.replace('/static/js/mobile.js"', f'/static/js/mobile.js?v={version}"')
    html = html.replace('/static/manifest.json"', f'/static/manifest.json?v={version}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
def service_worker():
    # Item [mobile-app] Phase 2: served at root scope deliberately, NOT
    # under /static/ -- a service worker's scope can never be broader than
    # the path it's served from, and this one needs to control the whole
    # origin (including the '/' navigation itself), not just /static/.
    # No cache-busting query string on this route's own registration URL
    # (mobile.js registers plain "/sw.js") -- that's what lets the browser's
    # normal byte-diff update check work; a changing URL would instead
    # register a brand-new SW on every single deploy. media_type is set
    # explicitly rather than left to FileResponse's guess, since this
    # route (unlike /static/*) isn't a StaticFiles mount.
    sw_path = FRONTEND_DIR / "sw.js"
    return FileResponse(
        sw_path,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@app.get("/health")
def health():
    return {"status": "ok"}

import asyncio
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse

from .database import engine
from . import models
from .routers import (
    projects, deliverables, announcements_router, dashboard, departments, milestones, gantt, support, po_line_items,
)
from .scheduler import scheduler_loop

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Algihaz L0/L1 Platform (Pilot)")


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
    version = str(int(max(
        (FRONTEND_DIR / "static" / "app.js").stat().st_mtime,
        (FRONTEND_DIR / "static" / "styles.css").stat().st_mtime,
    )))
    html = html.replace('/static/app.js"', f'/static/app.js?v={version}"')
    html = html.replace('/static/styles.css"', f'/static/styles.css?v={version}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health():
    return {"status": "ok"}

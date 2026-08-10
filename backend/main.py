from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text

from .database import engine, DATABASE_URL
from . import models
from .routers import projects, deliverables, announcements_router, dashboard, departments, milestones, gantt, support

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Algihaz L0/L1 Platform (Pilot)")

app.include_router(projects.router)
app.include_router(deliverables.router)
app.include_router(announcements_router.router)
app.include_router(dashboard.router)
app.include_router(departments.router)
app.include_router(milestones.router)
app.include_router(gantt.router)
app.include_router(support.router)

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
    return FileResponse(str(FRONTEND_DIR / "index.html"), headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/_debug/enum")
def debug_enum():
    """Temporary diagnostic — remove once the enum migration is confirmed working."""
    if not DATABASE_URL.startswith("postgres"):
        return {"dialect": "not postgres", "database_url_prefix": DATABASE_URL[:15]}
    with engine.connect() as conn:
        udt_row = conn.execute(text(
            "SELECT column_name, udt_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'deliverable_submissions' AND column_name = 'status'"
        )).mappings().all()
        enum_type = udt_row[0]["udt_name"] if udt_row else None
        values = []
        if enum_type:
            values = [r[0] for r in conn.execute(text(
                "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
                "WHERE t.typname = :enum_type ORDER BY e.enumsortorder"
            ), {"enum_type": enum_type}).all()]
        return {"udt_row": [dict(r) for r in udt_row], "enum_type": enum_type, "current_values": values}

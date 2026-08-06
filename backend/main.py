from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .database import engine
from . import models
from .routers import projects, deliverables, announcements_router, dashboard, departments, milestones

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Algihaz L0/L1 Platform (Pilot)")

app.include_router(projects.router)
app.include_router(deliverables.router)
app.include_router(announcements_router.router)
app.include_router(dashboard.router)
app.include_router(departments.router)
app.include_router(milestones.router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
LOCAL_FILES_DIR = Path(__file__).resolve().parent.parent / "data" / "local_storage"

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")
app.mount("/local-files", StaticFiles(directory=str(LOCAL_FILES_DIR)), name="local-files")


@app.get("/")
def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/health")
def health():
    return {"status": "ok"}

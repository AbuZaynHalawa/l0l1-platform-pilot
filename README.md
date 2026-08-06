# Algihaz L0/L1 Platform — Pilot

Real backend (FastAPI + SQLAlchemy), real frontend, running against a local
SQLite database and local file storage by default so it's fully testable
without any external accounts. Swaps to real OneDrive/Outlook and a real
Postgres database via environment variables only — no code changes.

## Run locally

```
pip install -r requirements.txt
python -m backend.seed
uvicorn backend.main:app --reload
```

Open http://127.0.0.1:8000

## Deploy (Render)

This repo includes `render.yaml`. In the Render dashboard: **New** →
**Blueprint** → connect this repository → Render provisions both the web
service and a free Postgres database automatically, wired together.

**Known limitation on Render's free tier:** the free web service has no
persistent disk, so uploaded files (via the local storage stand-in) are
lost on restart/redeploy. The database persists correctly (separate managed
Postgres). This is resolved once `STORAGE_BACKEND=onedrive` is connected —
files then go to real, persistent OneDrive storage instead.

## Switching to real OneDrive + real email

1. Register an app at portal.azure.com (see comments at the top of
   `backend/providers/graph_auth.py` for exact steps).
2. Set env vars: `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`, `GRAPH_TENANT_ID`,
   `GRAPH_REFRESH_TOKEN` (obtained via the one-time device-code login —
   run `python -m backend.providers.graph_auth` once, locally, to get it).
3. Set `STORAGE_BACKEND=onedrive` and `MAIL_BACKEND=graph`.

Nothing else changes — every route already calls through the provider
interfaces in `backend/providers/`.

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db

router = APIRouter(prefix="/api/support", tags=["support"])


class SupportRequestCreate(BaseModel):
    name: str | None = None
    email: str
    stage: str | None = None
    est_no: str | None = None
    deliverable: str | None = None
    message: str


@router.get("")
def list_support_requests(actor_role: str = "Viewer", db: Session = Depends(get_db)):
    if actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can view support requests")
    rows = db.query(models.SupportRequest).order_by(models.SupportRequest.created_at.desc()).all()
    return [
        {
            "id": r.id, "name": r.name, "email": r.email, "stage": r.stage, "est_no": r.est_no,
            "deliverable": r.deliverable, "message": r.message, "status": r.status,
            "created_at": r.created_at, "resolved_at": r.resolved_at,
        }
        for r in rows
    ]


@router.post("")
def create_support_request(payload: SupportRequestCreate, db: Session = Depends(get_db)):
    if not payload.email.strip():
        raise HTTPException(400, "Email is required")
    if not payload.message.strip():
        raise HTTPException(400, "Message is required")
    req = models.SupportRequest(
        name=(payload.name or "").strip() or None, email=payload.email.strip(),
        stage=payload.stage or None, est_no=(payload.est_no or "").strip() or None,
        deliverable=(payload.deliverable or "").strip() or None, message=payload.message.strip(),
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return {"id": req.id, "status": "ok"}


@router.patch("/{request_id}/resolve")
def resolve_support_request(request_id: int, actor_role: str = "Viewer", db: Session = Depends(get_db)):
    if actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can resolve support requests")
    req = db.get(models.SupportRequest, request_id)
    if not req:
        raise HTTPException(404, "Request not found")
    req.status = "resolved"
    req.resolved_at = datetime.utcnow()
    db.commit()
    return {"status": "ok"}

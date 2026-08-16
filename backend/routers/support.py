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
    target_email: str | None = None  # item 37: null = Admins generally, else a specific SME
    message: str


def _serialize(r: models.SupportRequest, include_messages: bool = True) -> dict:
    out = {
        "id": r.id, "name": r.name, "email": r.email, "stage": r.stage, "est_no": r.est_no,
        "deliverable": r.deliverable, "target_email": r.target_email, "message": r.message, "status": r.status,
        "created_at": r.created_at, "resolved_at": r.resolved_at,
    }
    if include_messages:
        out["messages"] = [
            {"id": m.id, "author": m.author, "body": m.body, "created_at": m.created_at}
            for m in r.messages
        ]
    return out


@router.get("")
def list_support_requests(actor_role: str = "Viewer", db: Session = Depends(get_db)):
    if actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can view support requests")
    rows = db.query(models.SupportRequest).order_by(models.SupportRequest.created_at.desc()).all()
    return [_serialize(r) for r in rows]


@router.get("/mine")
def list_my_support_requests(email: str, db: Session = Depends(get_db)):
    """No real login exists in this pilot, so "mine" is just a match on the
    email the asker themselves typed in — same trust level as the rest of
    the app's client-reported actor_email/actor_role.
    """
    email = email.strip()
    if not email:
        raise HTTPException(400, "Email is required")
    rows = (
        db.query(models.SupportRequest)
        .filter(models.SupportRequest.email.ilike(email))
        .order_by(models.SupportRequest.created_at.desc())
        .all()
    )
    return [_serialize(r) for r in rows]


@router.get("/kb")
def list_kb_entries(db: Session = Depends(get_db)):
    """Item 150: the full knowledge base, unfiltered -- small enough dataset
    that search/category filtering happens client-side, same convention as
    Assigned Deliverables and Follow Up's own filters.
    """
    rows = db.query(models.KnowledgeBaseEntry).order_by(models.KnowledgeBaseEntry.id).all()
    return [
        {"id": r.id, "category": r.category, "question": r.question, "answer": r.answer,
         "created_at": r.created_at, "source_request_id": r.source_request_id}
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
        deliverable=(payload.deliverable or "").strip() or None,
        target_email=(payload.target_email or "").strip() or None, message=payload.message.strip(),
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return {"id": req.id, "status": "ok"}


class SupportReplyCreate(BaseModel):
    body: str
    actor_role: str = "Viewer"
    actor_email: str | None = None
    kb_reference_id: int | None = None  # item 150: admin reused an existing KB answer


@router.post("/{request_id}/reply")
def admin_reply(request_id: int, payload: SupportReplyCreate, db: Session = Depends(get_db)):
    if payload.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can reply from the inbox")
    req = db.get(models.SupportRequest, request_id)
    if not req:
        raise HTTPException(404, "Request not found")
    body = payload.body.strip()
    if not body:
        raise HTTPException(400, "Reply can't be empty")
    # Item 150: the first time an admin answers a question, it's auto-added
    # to the knowledge base -- unless the admin referenced an existing entry
    # instead, in which case this is a duplicate of a question already there
    # and no new entry gets created.
    already_answered = any(m.author == "admin" for m in req.messages)
    if payload.kb_reference_id is not None:
        if not db.get(models.KnowledgeBaseEntry, payload.kb_reference_id):
            raise HTTPException(404, "Referenced knowledge base entry not found")
    elif not already_answered:
        db.add(models.KnowledgeBaseEntry(
            category=req.stage or "General", question=req.message, answer=body, source_request_id=req.id,
        ))
    db.add(models.SupportMessage(request_id=req.id, author="admin", body=body))
    db.commit()
    return _serialize(req)


@router.post("/{request_id}/respond")
def asker_respond(request_id: int, payload: SupportReplyCreate, db: Session = Depends(get_db)):
    """The original asker's own reply — allowed until an admin marks the
    request resolved, matching item 77's "respond back until marked resolved".
    """
    req = db.get(models.SupportRequest, request_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if (payload.actor_email or "").strip().lower() != req.email.strip().lower():
        raise HTTPException(403, "Only the original asker can reply here")
    if req.status == "resolved":
        raise HTTPException(400, "This request is already resolved")
    body = payload.body.strip()
    if not body:
        raise HTTPException(400, "Reply can't be empty")
    db.add(models.SupportMessage(request_id=req.id, author="asker", body=body))
    db.commit()
    return _serialize(req)


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

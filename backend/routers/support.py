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
    """Item 150/172.1: the knowledge base, unfiltered beyond one rule --
    every entry must trace back to a closed topic. Entries are now only
    created when a ticket resolves, so this mainly guards against stale
    rows from before that change (created on first admin reply, possibly
    while the ticket was still open). Search/category filtering happens
    client-side, same convention as Assigned Deliverables and Follow Up.
    """
    rows = (
        db.query(models.KnowledgeBaseEntry)
        .outerjoin(models.SupportRequest, models.KnowledgeBaseEntry.source_request_id == models.SupportRequest.id)
        .filter(
            (models.KnowledgeBaseEntry.source_request_id.is_(None))
            | (models.SupportRequest.status == "resolved")
        )
        .order_by(models.KnowledgeBaseEntry.id)
        .all()
    )
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
    # Item 172.1: a reply on its own no longer adds anything to the
    # knowledge base -- see resolve_support_request() below, where that now
    # happens once the ticket is actually marked resolved. A reference to
    # an existing entry is still recorded here (on the message itself, so
    # it survives to resolve time) so resolving doesn't add a duplicate for
    # a question that's really the same as one already documented.
    if payload.kb_reference_id is not None:
        if not db.get(models.KnowledgeBaseEntry, payload.kb_reference_id):
            raise HTTPException(404, "Referenced knowledge base entry not found")
    db.add(models.SupportMessage(request_id=req.id, author="admin", body=body,
                                  kb_reference_id=payload.kb_reference_id))
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
    # Item 172.1: the knowledge base only gets a new entry once a ticket is
    # actually resolved, not on the first reply -- and only when this
    # question doesn't already have a home. Skip if an admin already pointed
    # this thread at an existing entry (nothing new to add), or if resolving
    # twice would otherwise create a duplicate.
    already_referenced = any(m.kb_reference_id is not None for m in req.messages)
    already_has_entry = db.query(models.KnowledgeBaseEntry).filter(
        models.KnowledgeBaseEntry.source_request_id == req.id
    ).first() is not None
    if not already_referenced and not already_has_entry:
        admin_replies = [m for m in req.messages if m.author == "admin"]
        if admin_replies:
            last_reply = max(admin_replies, key=lambda m: m.created_at)
            db.add(models.KnowledgeBaseEntry(
                category=req.stage or "General", question=req.message,
                answer=last_reply.body, source_request_id=req.id,
            ))
    db.commit()
    return {"status": "ok"}

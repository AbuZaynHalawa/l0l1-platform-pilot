from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from .. import models, schemas, announcements, rules
from ..database import get_db
from ..providers.storage import get_storage_provider, sanitize_segment

router = APIRouter(prefix="/api/deliverables", tags=["deliverables"])
_storage = get_storage_provider()


def _dept_label(name: str) -> str:
    parts = name.split(". ", 1)
    return parts[1] if len(parts) == 2 else name


def _follower_emails(db: Session, submission_id: int) -> list[str]:
    return [
        f.email for f in
        db.query(models.Follower).filter(models.Follower.submission_id == submission_id).all()
    ]


@router.get("")
def list_all_deliverables(status: str | None = None, actor_email: str | None = None, db: Session = Depends(get_db)):
    """Cross-project queue for the Assigned Deliverables page."""
    active_projects = db.query(models.Project).filter(models.Project.status == models.ProjectStatus.IN_PROGRESS).all()
    for p in active_projects:
        rules.recompute_project_due_dates(db, p)
    db.commit()

    q = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .join(models.Department)
        .join(models.Project)
        .filter(models.DeliverableSubmission.auto_completed.isnot(True))
    )
    subs = q.all()
    my_follows = set()
    if actor_email:
        my_follows = {
            f.submission_id for f in
            db.query(models.Follower).filter(models.Follower.email == actor_email.strip().lower()).all()
        }
    doc_counts = rules.document_counts(db, [s.id for s in subs])
    out = []
    for s in subs:
        if status and s.status.value != status:
            continue
        doc_total, doc_approved, doc_pending = doc_counts.get(s.id, (0, 0, 0))
        out.append({
            "id": s.id, "est_no": s.project.est_no, "project_name": s.project.name, "stage": s.project.stage.value,
            "department": s.definition.department.name, "department_number": s.definition.department.number,
            "item_no": s.definition.item_no,
            "name": rules.display_name(s.definition, s.project), "due_date": s.due_date, "status": s.status.value,
            "owner": s.owner_email or s.definition.default_owner_email or "Unassigned",
            "owner_email": s.owner_email or s.definition.default_owner_email,
            "sme_email": s.sme_email or s.definition.default_sme_email,
            "is_milestone": s.definition.is_milestone, "milestone_code": s.definition.milestone_code,
            "file_name": s.file_name, "file_url": _storage.file_url(s.file_ref) if s.file_ref else None,
            "review_comment": s.review_comment, "completion_note": rules.mark_complete_note(s),
            "following": s.id in my_follows,
            "doc_total": doc_total, "doc_approved": doc_approved, "doc_pending": doc_pending,
        })
    return out


@router.post("/{submission_id}/follow")
def toggle_follow(submission_id: int, payload: schemas.FollowRequest, db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    email = payload.email.strip().lower()
    if not email:
        raise HTTPException(400, "Email is required to follow a deliverable")
    existing = db.query(models.Follower).filter_by(submission_id=submission_id, email=email).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"following": False}
    db.add(models.Follower(submission_id=submission_id, email=email))
    db.commit()
    return {"following": True}


@router.post("/{submission_id}/upload")
async def upload_deliverable(submission_id: int, file: UploadFile = File(...),
                              actor_name: str = Form("Owner"), actor_role: str = Form("Owner"),
                              actor_email: str = Form(""), db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")

    assigned = sub.owner_email or sub.definition.default_owner_email
    if not rules.can_act(actor_role, actor_email, assigned):
        raise HTTPException(403, f"Only {assigned or 'the assigned owner'} or an Admin can upload this deliverable")
    if sub.status == models.SubmissionStatus.APPROVED:
        raise HTTPException(400, "This deliverable is already Completed")

    content = await file.read()
    folder = f"{sub.project.onedrive_folder_path}/{sanitize_segment(sub.definition.department.name)}"
    file_ref = _storage.upload_file(folder, file.filename, content)

    sub.file_name = file.filename
    sub.file_ref = file_ref
    sub.submitted_at = datetime.utcnow()
    # Item 143: unconditionally setting PENDING_REVIEW here also correctly
    # resets a stale PENDING_COMPLETION (owner said done, but here's a new
    # document -- that claim needs re-confirming) or REJECTED (a fresh
    # upload restarts the review cycle) row, for free.
    sub.status = models.SubmissionStatus.PENDING_REVIEW
    db.add(models.WorkflowHistory(submission_id=sub.id, action="submitted", actor_name=actor_name,
                                   note=f"Uploaded {file.filename}"))
    # Mirrored as a Document row too, so it shows up in the deliverable
    # popup's document list the same way an "Add Document" upload does —
    # one upload mechanism, one place it's visible, not two disconnected ones.
    db.add(models.Document(submission_id=sub.id, file_name=file.filename, file_ref=file_ref, uploaded_by=actor_name))
    db.commit()

    sme_email = sub.sme_email or sub.definition.default_sme_email
    if sme_email:
        announcements.sme_review_requested(db, sub.project, sme_email, sub.definition.item_no, sub.definition.name,
                                            submission_id=sub.id)
        db.add(models.WorkflowHistory(submission_id=sub.id, action="review_requested",
                                       actor_name="system", note=f"Sent to {sme_email}"))
        db.commit()
    announcements.followers_notified(db, sub.project, _follower_emails(db, sub.id),
                                      sub.definition.item_no, sub.definition.name, "uploaded", submission_id=sub.id)

    return {"status": "ok", "file_ref": file_ref}


def _document_out(d: "models.Document") -> dict:
    return {
        "id": d.id, "file_name": d.file_name, "file_url": _storage.file_url(d.file_ref),
        "uploaded_by": d.uploaded_by, "uploaded_at": d.uploaded_at, "status": d.status,
        "comment": d.comment, "reviewed_at": d.reviewed_at,
    }


@router.get("/{submission_id}/documents")
def list_documents(submission_id: int, db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    documents = (
        db.query(models.Document)
        .filter(models.Document.submission_id == submission_id)
        .order_by(models.Document.uploaded_at)
        .all()
    )
    return [_document_out(d) for d in documents]


@router.post("/{submission_id}/documents")
async def add_document(submission_id: int, file: UploadFile = File(...),
                        actor_name: str = Form("Owner"), actor_role: str = Form("Owner"),
                        actor_email: str = Form(""), db: Session = Depends(get_db)):
    """Adds a supplementary document to an already-submitted deliverable —
    e.g. extra supporting evidence while the SME is still reviewing, or a
    second/third document on a multi-doc deliverable arriving hours or days
    apart (item 143). Resets a stale PENDING_COMPLETION/REJECTED status back
    to PENDING_REVIEW, same reasoning as the primary upload -- new evidence
    means any earlier "done" or "rejected" call needs re-confirming.
    """
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    assigned = sub.owner_email or sub.definition.default_owner_email
    if not rules.can_act(actor_role, actor_email, assigned):
        raise HTTPException(403, f"Only {assigned or 'the assigned owner'} or an Admin can add documents to this deliverable")
    if sub.status == models.SubmissionStatus.APPROVED:
        raise HTTPException(400, "This deliverable is already Completed")

    content = await file.read()
    folder = f"{sub.project.onedrive_folder_path}/{sanitize_segment(sub.definition.department.name)}"
    file_ref = _storage.upload_file(folder, file.filename, content)

    doc = models.Document(submission_id=submission_id, file_name=file.filename, file_ref=file_ref, uploaded_by=actor_name)
    db.add(doc)
    if sub.status in (
        models.SubmissionStatus.NOT_DUE, models.SubmissionStatus.DUE, models.SubmissionStatus.OVERDUE,
        models.SubmissionStatus.PENDING_COMPLETION, models.SubmissionStatus.REJECTED,
    ):
        sub.status = models.SubmissionStatus.PENDING_REVIEW
        sub.submitted_at = sub.submitted_at or datetime.utcnow()
    db.add(models.WorkflowHistory(submission_id=submission_id, action="document_added", actor_name=actor_name,
                                   note=f"Added {file.filename}"))
    db.commit()
    db.refresh(doc)

    # Item 101: this now announces the same way the primary upload does —
    # it used to add the document silently with no notification at all.
    sme_email = sub.sme_email or sub.definition.default_sme_email
    if sme_email:
        announcements.document_added(db, sub.project, sme_email, sub.definition.item_no, sub.definition.name,
                                      file.filename, submission_id=sub.id)
    announcements.followers_notified(db, sub.project, _follower_emails(db, submission_id),
                                      sub.definition.item_no, sub.definition.name, "uploaded", submission_id=submission_id)
    return _document_out(doc)


@router.post("/documents/{document_id}/review")
def review_document(document_id: int, decision: schemas.ReviewDecision, db: Session = Depends(get_db)):
    doc = db.get(models.Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    sub = doc.submission
    assigned_sme = sub.sme_email or sub.definition.default_sme_email
    if not rules.can_act(decision.actor_role, decision.actor_email, assigned_sme):
        raise HTTPException(403, f"Only {assigned_sme or 'the assigned SME'} or an Admin can review this document")

    doc.status = "approved" if decision.approved else "rejected"
    doc.comment = decision.comment
    doc.reviewed_at = datetime.utcnow()
    db.add(models.WorkflowHistory(
        submission_id=sub.id, action="document_approved" if decision.approved else "document_rejected",
        actor_name=decision.reviewer_name, note=f"{doc.file_name}" + (f": {decision.comment}" if decision.comment else ""),
    ))
    db.commit()
    return _document_out(doc)


def _finalize_approval(db: Session, sub: "models.DeliverableSubmission", comment: str | None, actor_name: str) -> None:
    """Item 143: the one place a submission actually becomes Completed
    (status stays the APPROVED enum value — only its display label changed
    to "Completed" — so every existing predecessor/due-date/KPI/Gantt check
    keyed off APPROVED keeps working unchanged). Reached two ways: an SME's
    own Mark Completed (immediate), or an SME confirming an Owner's
    PENDING_COMPLETION claim via /review. Both call this so the cascade
    (due-date freeze, milestones, cross-department unlock, L1 completion)
    only lives in one place.
    """
    sub.status = models.SubmissionStatus.APPROVED
    sub.review_comment = comment
    sub.reviewed_at = datetime.utcnow()

    # Client-dependent items (Contract Signing, LOA, etc.) have no computable
    # due_date until they actually happen — completion IS that event, so
    # freeze a real date now so downstream predecessor-chained items can
    # anchor off it.
    if sub.due_date is None:
        sub.due_date = sub.reviewed_at.date()

    db.add(models.WorkflowHistory(submission_id=sub.id, action="approved", actor_name=actor_name, note=comment))
    db.commit()

    owner_email = sub.owner_email or sub.definition.default_owner_email or ""
    announcements.sme_decision(db, sub.project, owner_email, sub.definition.item_no, sub.definition.name,
                                True, comment, submission_id=sub.id)
    announcements.followers_notified(db, sub.project, _follower_emails(db, sub.id), sub.definition.item_no,
                                      sub.definition.name, "approved", submission_id=sub.id)

    if sub.definition.is_milestone:
        recipients = sorted({d.focal_point_email for d in db.query(models.Department).all() if d.focal_point_email} | rules.system_group_emails(db))
        announcements.milestone_reached(db, sub.project, recipients, sub.definition.milestone_code, sub.definition.name)
        if sub.definition.milestone_code == "M6" and sub.project.stage == models.Stage.L1:
            sub.project.contract_status = models.ContractStatus.SIGNED
            db.commit()
        if sub.definition.milestone_code == "M5" and sub.project.stage == models.Stage.L0:
            sub.project.status = models.ProjectStatus.SUBMITTED
            db.commit()

    # Snapshot due dates, recompute the whole project (correctly cascades
    # through however many chained levels), then notify whoever just
    # became actionable as a result — the real cross-department unlock.
    before = {
        s.id: s.due_date
        for s in db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.project_id == sub.project_id).all()
    }
    rules.recompute_project_due_dates(db, sub.project, force=True)
    db.commit()
    after_subs = db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.project_id == sub.project_id).all()
    trigger_label = f"{sub.definition.item_no} {sub.definition.name}"
    for s2 in after_subs:
        if s2.id == sub.id:
            continue
        if before.get(s2.id) is None and s2.due_date is not None:
            target_email = s2.owner_email or s2.definition.default_owner_email or ""
            announcements.cross_department_unlock(db, sub.project, target_email, trigger_label, s2.definition.item_no, s2.definition.name,
                                                    submission_id=s2.id)
            db.add(models.WorkflowHistory(submission_id=s2.id, action="unlocked",
                                           actor_name="system", note=f"Unlocked by approval of {trigger_label}"))
    db.commit()

    rules.check_l1_completion(db, sub.project)
    db.commit()


@router.post("/{submission_id}/mark-complete")
def mark_complete(submission_id: int, payload: schemas.MarkCompleteRequest, db: Session = Depends(get_db)):
    """Item 143: the deliverable's closing action, callable by the Owner OR
    the SME, for a comment-only completion or once every currently-uploaded
    document has been individually approved. The SME's own call finalizes
    immediately (via _finalize_approval); the Owner's call only flags it as
    PENDING_COMPLETION, awaiting the SME's confirm/reject through /review.
    """
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    if sub.status in (models.SubmissionStatus.PENDING_COMPLETION, models.SubmissionStatus.APPROVED):
        raise HTTPException(400, "Deliverable has already been marked complete")

    owner_email = sub.owner_email or sub.definition.default_owner_email
    sme_email = sub.sme_email or sub.definition.default_sme_email
    is_owner = rules.can_act(payload.actor_role, payload.actor_email, owner_email)
    is_sme = rules.can_act(payload.actor_role, payload.actor_email, sme_email)
    if not (is_owner or is_sme):
        raise HTTPException(403, f"Only {owner_email or 'the assigned owner'} or {sme_email or 'the assigned SME'} can complete this deliverable")

    pending_docs = (
        db.query(models.Document)
        .filter(models.Document.submission_id == submission_id, models.Document.status == "pending")
        .count()
    )
    if pending_docs:
        raise HTTPException(
            400,
            f"{pending_docs} document(s) on this deliverable are still awaiting individual review — "
            "review those first before marking it complete",
        )

    comment = payload.comment.strip()
    if not comment:
        raise HTTPException(400, "A comment is required to mark this complete")

    # SME wins ties (someone assigned as both owner and SME on the same
    # item) — their own Mark Completed is always the stronger, final action.
    if is_sme:
        _finalize_approval(db, sub, comment, payload.actor_name)
        return {"status": "ok", "completed": True}

    sub.submitted_at = sub.submitted_at or datetime.utcnow()
    sub.status = models.SubmissionStatus.PENDING_COMPLETION
    db.add(models.WorkflowHistory(submission_id=sub.id, action="mark_complete_requested",
                                   actor_name=payload.actor_name, note=comment))
    db.commit()

    if sme_email:
        announcements.sme_review_requested(db, sub.project, sme_email, sub.definition.item_no, sub.definition.name,
                                            submission_id=sub.id)
        db.add(models.WorkflowHistory(submission_id=sub.id, action="review_requested",
                                       actor_name="system", note=f"Sent to {sme_email}"))
        db.commit()
    announcements.followers_notified(db, sub.project, _follower_emails(db, sub.id),
                                      sub.definition.item_no, sub.definition.name, "marked completed")

    return {"status": "ok", "completed": False}


@router.post("/{submission_id}/review")
def review_deliverable(submission_id: int, decision: schemas.ReviewDecision, db: Session = Depends(get_db)):
    """Item 143: the SME's confirm/reject on an Owner's completion claim —
    only reachable from PENDING_COMPLETION now (was PENDING_REVIEW). There's
    no longer a whole-deliverable review while documents are still coming in
    — that's per-document review (/documents/{id}/review, unchanged) until
    someone calls Mark Completed.
    """
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    if sub.status != models.SubmissionStatus.PENDING_COMPLETION:
        raise HTTPException(400, "Deliverable is not awaiting completion confirmation")

    assigned_sme = sub.sme_email or sub.definition.default_sme_email
    if not rules.can_act(decision.actor_role, decision.actor_email, assigned_sme):
        raise HTTPException(403, f"Only {assigned_sme or 'the assigned SME'} or an Admin can review this deliverable")

    if decision.approved:
        # Structurally shouldn't be reachable (Mark Completed itself blocks
        # on pending docs), but cheap to keep as a defensive check.
        pending_docs = (
            db.query(models.Document)
            .filter(models.Document.submission_id == submission_id, models.Document.status == "pending")
            .count()
        )
        if pending_docs:
            raise HTTPException(
                400,
                f"{pending_docs} document(s) on this deliverable are still awaiting individual review — "
                "review those first",
            )
        _finalize_approval(db, sub, decision.comment, decision.reviewer_name)
        return {"status": "ok"}

    sub.status = models.SubmissionStatus.REJECTED
    sub.review_comment = decision.comment
    sub.reviewed_at = datetime.utcnow()
    db.add(models.WorkflowHistory(submission_id=sub.id, action="rejected", actor_name=decision.reviewer_name, note=decision.comment))
    db.commit()

    owner_email = sub.owner_email or sub.definition.default_owner_email or ""
    announcements.sme_decision(db, sub.project, owner_email, sub.definition.item_no, sub.definition.name,
                                False, decision.comment, submission_id=sub.id)
    announcements.followers_notified(db, sub.project, _follower_emails(db, sub.id), sub.definition.item_no,
                                      sub.definition.name, "rejected", submission_id=sub.id)

    return {"status": "ok"}


@router.post("/{submission_id}/reopen")
def reopen_deliverable(submission_id: int, actor_role: str = "Viewer", actor_email: str = "", db: Session = Depends(get_db)):
    """Sends an approved or Not-Required deliverable back into the normal
    workflow. Approved: for when something approved turns out to need more
    work — leaves the existing file/documents in place as a record, the
    owner uploads fresh work like any other resubmission. Not Required
    (item 108): undoes an earlier not-required call, e.g. a scope change
    makes the item relevant again — admin-only, symmetric with who's
    allowed to mark something Not Required in the first place.
    """
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")

    if sub.applicability == "not_required":
        if actor_role != "Admin":
            raise HTTPException(403, "Only an Admin can reopen a deliverable marked Not Required")
        sub.applicability = "applicable"
        db.add(models.WorkflowHistory(submission_id=sub.id, action="reopened", actor_name="Admin",
                                       note="Reopened from Not Required"))
        db.commit()
        rules.recompute_project_due_dates(db, sub.project, force=True)
        db.commit()
        return {"status": "ok"}

    if sub.status != models.SubmissionStatus.APPROVED:
        raise HTTPException(400, "Only an approved or Not-Required deliverable can be reopened")
    assigned = sub.owner_email or sub.definition.default_owner_email
    if not rules.can_act(actor_role, actor_email, assigned):
        raise HTTPException(403, f"Only {assigned or 'the assigned owner'} or an Admin can reopen this deliverable")

    sub.reviewed_at = None
    sub.review_comment = None
    sub.status = models.SubmissionStatus.NOT_DUE  # placeholder so refresh_status doesn't early-return on APPROVED
    rules.refresh_status(sub)
    db.add(models.WorkflowHistory(submission_id=sub.id, action="reopened", actor_name=actor_role,
                                   note="Reopened after approval"))
    db.commit()

    rules.recompute_project_due_dates(db, sub.project, force=True)
    db.commit()
    return {"status": "ok"}


@router.post("/{submission_id}/mark-not-required")
def mark_not_required(submission_id: int, actor_role: str = "Viewer", actor_email: str = "", db: Session = Depends(get_db)):
    """Admin override to retire a single deliverable as Not Required at any
    point, not just at the initial BM triage gate (item 86 originally only
    covered that one screen) — e.g. a scope change makes an item moot after
    the tender's already underway.
    """
    if actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can mark a deliverable Not Required")
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    if sub.definition.is_milestone:
        raise HTTPException(400, "Milestones can't be marked Not Required")
    if sub.status in (models.SubmissionStatus.PENDING_REVIEW, models.SubmissionStatus.APPROVED):
        raise HTTPException(400, "This deliverable already has submitted work — reopen it first")
    if sub.applicability == "not_required":
        return {"status": "ok"}

    sub.applicability = "not_required"
    db.add(models.WorkflowHistory(submission_id=sub.id, action="not_required", actor_name="Admin",
                                   note="Marked Not Required"))
    db.commit()

    rules.recompute_project_due_dates(db, sub.project, force=True)
    db.commit()

    announcements.followers_notified(db, sub.project, _follower_emails(db, sub.id), sub.definition.item_no,
                                      sub.definition.name, "marked Not Required", submission_id=sub.id)
    return {"status": "ok"}


@router.post("/{submission_id}/reassign-request")
def request_reassignment(submission_id: int, payload: schemas.ReassignRequestCreate, db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    to_email = payload.to_email.strip()
    if not to_email:
        raise HTTPException(400, "The new owner's email is required")
    # Item 88: the target must be a real, admin-managed roster member with
    # Owner (or Admin) permissions — not just any typed-in address, since
    # they're about to become responsible for actually delivering this item.
    target_user = db.query(models.User).filter(models.User.email.ilike(to_email)).first()
    if not target_user or target_user.role not in ("Owner", "Admin"):
        raise HTTPException(400, f"{to_email} must be a user with Owner permissions in the system roster (Focal Points &#8594; L0-L1 Group)")
    req = models.ReassignmentRequest(
        submission_id=submission_id,
        from_email=(payload.from_email or sub.owner_email or sub.definition.default_owner_email or "").strip() or None,
        to_email=to_email, reason=payload.reason,
    )
    db.add(req)
    db.commit()
    return {"status": "ok", "id": req.id}



@router.get("/reassignment-requests")
def list_reassignment_requests(status: str = "pending", db: Session = Depends(get_db)):
    q = db.query(models.ReassignmentRequest)
    if status:
        q = q.filter(models.ReassignmentRequest.status == status)
    reqs = q.order_by(models.ReassignmentRequest.requested_at.desc()).all()
    return [
        {
            "id": r.id, "submission_id": r.submission_id,
            "est_no": r.submission.project.est_no, "item_no": r.submission.definition.item_no,
            "name": r.submission.definition.name,
            "from_email": r.from_email, "to_email": r.to_email, "reason": r.reason,
            "status": r.status, "requested_at": r.requested_at,
        }
        for r in reqs
    ]


@router.post("/reassignment-requests/{request_id}/decide")
def decide_reassignment(request_id: int, decision: schemas.ReassignmentDecision, db: Session = Depends(get_db)):
    req = db.get(models.ReassignmentRequest, request_id)
    if not req:
        raise HTTPException(404, "Reassignment request not found")
    if req.status != "pending":
        raise HTTPException(400, "This request has already been decided")
    if decision.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can decide a reassignment request")
    req.status = "approved" if decision.approved else "rejected"
    req.decided_at = datetime.utcnow()
    if decision.approved:
        req.submission.owner_email = req.to_email
    db.commit()
    return {"status": "ok"}


@router.get("/follow-up")
def get_follow_up(department: str | None = None, project_id: int | None = None, db: Session = Depends(get_db)):
    """Every currently due/overdue deliverable, for the admin Follow Up page."""
    active_projects = db.query(models.Project).filter(models.Project.status == models.ProjectStatus.IN_PROGRESS).all()
    for p in active_projects:
        rules.recompute_project_due_dates(db, p)
    db.commit()
    q = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .join(models.Department)
        .join(models.Project)
        .filter(models.DeliverableSubmission.status.in_([models.SubmissionStatus.DUE, models.SubmissionStatus.OVERDUE]))
    )
    if department:
        q = q.filter(models.Department.name == department)
    if project_id:
        q = q.filter(models.DeliverableSubmission.project_id == project_id)
    subs = q.all()
    return [
        {
            "id": s.id, "est_no": s.project.est_no, "project_name": s.project.name, "project_id": s.project_id,
            "department": s.definition.department.name, "item_no": s.definition.item_no,
            "name": rules.display_name(s.definition, s.project), "due_date": s.due_date, "status": s.status.value,
            "owner": s.owner_email or s.definition.default_owner_email or "Unassigned",
            "focal": rules.deliverable_focal(s.definition, s.project) or "Unassigned",
        }
        for s in subs
    ]


@router.post("/bulk-remind")
def bulk_remind(payload: schemas.BulkRemindRequest, db: Session = Depends(get_db)):
    if payload.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can send reminders")
    subs = db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.id.in_(payload.submission_ids)).all()
    users_by_email = {u.email.strip().lower(): u for u in db.query(models.User).all()} if payload.cc_manager else {}
    sent = 0
    for s in subs:
        owner = s.owner_email or s.definition.default_owner_email
        if owner:
            cc = []
            if payload.cc_manager:
                u = users_by_email.get(owner.strip().lower())
                if u and u.manager_email:
                    cc.append(u.manager_email)
            announcements.reminder_sent(db, s.project, owner, s.definition.item_no, s.definition.name, s.due_date,
                                         submission_id=s.id, custom_message=payload.message, cc=cc)
            sent += 1
    return {"sent": sent}


@router.get("/{submission_id}")
def get_deliverable_detail(submission_id: int, actor_email: str | None = None, db: Session = Depends(get_db)):
    """Full detail for the deliverable popup: the item itself, its workflow
    history, and any supplementary documents on top of the primary file.

    Declared after every literal-path route in this router (reassignment-
    requests, follow-up, bulk-remind, etc.) on purpose — FastAPI matches
    routes in declaration order, so a single-segment catch-all like this one
    has to come last among GETs or it silently swallows every literal route
    that shares its segment count (this exact bug took down the Follow Up
    tab: /follow-up was being routed here first, failing int-parsing on
    "follow-up" as submission_id, and erroring out before ever reaching the
    real handler).
    """
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    history = (
        db.query(models.WorkflowHistory)
        .filter(models.WorkflowHistory.submission_id == submission_id)
        .order_by(models.WorkflowHistory.created_at)
        .all()
    )
    documents = (
        db.query(models.Document)
        .filter(models.Document.submission_id == submission_id)
        .order_by(models.Document.uploaded_at)
        .all()
    )
    following = False
    if actor_email:
        following = db.query(models.Follower).filter_by(
            submission_id=submission_id, email=actor_email.strip().lower()
        ).first() is not None
    return {
        "id": sub.id, "item_no": sub.definition.item_no, "name": rules.display_name(sub.definition, sub.project),
        "department": sub.definition.department.name, "department_number": sub.definition.department.number,
        "est_no": sub.project.est_no, "project_id": sub.project_id, "project_name": sub.project.name,
        "due_date": sub.due_date, "status": sub.status.value,
        "owner_email": sub.owner_email or sub.definition.default_owner_email,
        "sme_email": sub.sme_email or sub.definition.default_sme_email,
        "file_name": sub.file_name, "file_url": _storage.file_url(sub.file_ref) if sub.file_ref else None,
        "submitted_at": sub.submitted_at, "review_comment": sub.review_comment, "reviewed_at": sub.reviewed_at,
        "completion_note": rules.mark_complete_note(sub), "is_milestone": sub.definition.is_milestone,
        "milestone_code": sub.definition.milestone_code, "following": following,
        "history": [
            {"action": h.action, "actor": h.actor_name, "note": h.note, "at": h.created_at}
            for h in history
        ],
        "documents": [_document_out(d) for d in documents],
    }


@router.get("/{submission_id}/history")
def get_history(submission_id: int, db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    return [
        {"action": h.action, "actor": h.actor_name, "note": h.note, "at": h.created_at}
        for h in sorted(sub.history, key=lambda h: h.created_at)
    ]

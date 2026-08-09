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


def _can_act(actor_role: str, actor_email: str, assigned_email: str | None) -> bool:
    """Admins can always act. Otherwise the actor must be the specific person
    assigned to this deliverable (owner for uploads, SME for reviews) — not
    just 'anyone with the Owner/SME role', per the Modifications doc.
    """
    if actor_role == "Admin":
        return True
    if not assigned_email or not actor_email:
        return False
    return actor_email.strip().lower() == assigned_email.strip().lower()


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
    )
    subs = q.all()
    my_follows = set()
    if actor_email:
        my_follows = {
            f.submission_id for f in
            db.query(models.Follower).filter(models.Follower.email == actor_email.strip().lower()).all()
        }
    out = []
    for s in subs:
        if status and s.status.value != status:
            continue
        out.append({
            "id": s.id, "est_no": s.project.est_no, "project_name": s.project.name,
            "department": s.definition.department.name, "department_number": s.definition.department.number,
            "item_no": s.definition.item_no,
            "name": rules.display_name(s.definition, s.project), "due_date": s.due_date, "status": s.status.value,
            "owner": s.owner_email or s.definition.default_owner_email or "Unassigned",
            "is_milestone": s.definition.is_milestone, "milestone_code": s.definition.milestone_code,
            "file_name": s.file_name, "file_url": _storage.file_url(s.file_ref) if s.file_ref else None,
            "review_comment": s.review_comment, "completion_note": rules.mark_complete_note(s),
            "following": s.id in my_follows,
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
    if not _can_act(actor_role, actor_email, assigned):
        raise HTTPException(403, f"Only {assigned or 'the assigned owner'} or an Admin can upload this deliverable")

    content = await file.read()
    folder = f"{sub.project.onedrive_folder_path}/{sanitize_segment(sub.definition.department.name)}"
    file_ref = _storage.upload_file(folder, file.filename, content)

    sub.file_name = file.filename
    sub.file_ref = file_ref
    sub.submitted_at = datetime.utcnow()
    sub.status = models.SubmissionStatus.PENDING_REVIEW
    db.add(models.WorkflowHistory(submission_id=sub.id, action="submitted", actor_name=actor_name,
                                   note=f"Uploaded {file.filename}"))
    db.commit()

    sme_email = sub.sme_email or sub.definition.default_sme_email
    if sme_email:
        announcements.sme_review_requested(db, sub.project, sme_email, sub.definition.item_no, sub.definition.name)
        db.add(models.WorkflowHistory(submission_id=sub.id, action="review_requested",
                                       actor_name="system", note=f"Sent to {sme_email}"))
        db.commit()
    announcements.followers_notified(db, sub.project, _follower_emails(db, sub.id),
                                      sub.definition.item_no, sub.definition.name, "uploaded")

    return {"status": "ok", "file_ref": file_ref}


@router.post("/{submission_id}/mark-complete")
def mark_complete(submission_id: int, payload: schemas.MarkCompleteRequest, db: Session = Depends(get_db)):
    """Owner alternative to uploading a file: attests the deliverable is done
    with a required comment instead of a document. Still goes to the SME for
    approval, exactly like an upload — this only replaces the file, not the
    review workflow.
    """
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    if sub.status in (models.SubmissionStatus.PENDING_REVIEW, models.SubmissionStatus.APPROVED):
        raise HTTPException(400, "Deliverable has already been submitted")

    assigned = sub.owner_email or sub.definition.default_owner_email
    if not _can_act(payload.actor_role, payload.actor_email, assigned):
        raise HTTPException(403, f"Only {assigned or 'the assigned owner'} or an Admin can complete this deliverable")

    comment = payload.comment.strip()
    if not comment:
        raise HTTPException(400, "A comment is required to mark this complete without a file")

    sub.submitted_at = datetime.utcnow()
    sub.status = models.SubmissionStatus.PENDING_REVIEW
    db.add(models.WorkflowHistory(submission_id=sub.id, action="submitted", actor_name=payload.actor_name, note=comment))
    db.commit()

    sme_email = sub.sme_email or sub.definition.default_sme_email
    if sme_email:
        announcements.sme_review_requested(db, sub.project, sme_email, sub.definition.item_no, sub.definition.name)
        db.add(models.WorkflowHistory(submission_id=sub.id, action="review_requested",
                                       actor_name="system", note=f"Sent to {sme_email}"))
        db.commit()
    announcements.followers_notified(db, sub.project, _follower_emails(db, sub.id),
                                      sub.definition.item_no, sub.definition.name, "marked completed")

    return {"status": "ok"}


@router.post("/{submission_id}/review")
def review_deliverable(submission_id: int, decision: schemas.ReviewDecision, db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    if sub.status != models.SubmissionStatus.PENDING_REVIEW:
        raise HTTPException(400, "Deliverable is not awaiting review")

    assigned_sme = sub.sme_email or sub.definition.default_sme_email
    if not _can_act(decision.actor_role, decision.actor_email, assigned_sme):
        raise HTTPException(403, f"Only {assigned_sme or 'the assigned SME'} or an Admin can review this deliverable")

    sub.status = models.SubmissionStatus.APPROVED if decision.approved else models.SubmissionStatus.REJECTED
    sub.review_comment = decision.comment
    sub.reviewed_at = datetime.utcnow()

    # Client-dependent items (Contract Signing, LOA, etc.) have no computable
    # due_date until they actually happen — approval IS that event, so freeze
    # a real date now so downstream predecessor-chained items can anchor off it.
    if decision.approved and sub.due_date is None:
        sub.due_date = sub.reviewed_at.date()

    db.add(models.WorkflowHistory(
        submission_id=sub.id, action="approved" if decision.approved else "rejected",
        actor_name=decision.reviewer_name, note=decision.comment,
    ))
    db.commit()

    owner_email = sub.owner_email or sub.definition.default_owner_email or ""
    announcements.sme_decision(db, sub.project, owner_email, sub.definition.item_no, sub.definition.name,
                                decision.approved, decision.comment)
    announcements.followers_notified(db, sub.project, _follower_emails(db, sub.id), sub.definition.item_no,
                                      sub.definition.name, "approved" if decision.approved else "rejected")

    if decision.approved and sub.definition.is_milestone:
        recipients = sorted({d.focal_point_email for d in db.query(models.Department).all() if d.focal_point_email})
        announcements.milestone_reached(db, sub.project, recipients, sub.definition.milestone_code, sub.definition.name)
        if sub.definition.milestone_code == "M6" and sub.project.stage == models.Stage.L1:
            sub.project.contract_status = models.ContractStatus.SIGNED
            db.commit()
        if sub.definition.milestone_code == "M5" and sub.project.stage == models.Stage.L0:
            sub.project.status = models.ProjectStatus.SUBMITTED
            db.commit()

    if decision.approved:
        # Snapshot due dates, recompute the whole project (correctly cascades
        # through however many chained levels), then notify whoever just
        # became actionable as a result — the real cross-department unlock.
        before = {
            s.id: s.due_date
            for s in db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.project_id == sub.project_id).all()
        }
        rules.recompute_project_due_dates(db, sub.project)
        db.commit()
        after_subs = db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.project_id == sub.project_id).all()
        trigger_label = f"{sub.definition.item_no} {sub.definition.name}"
        for s2 in after_subs:
            if s2.id == sub.id:
                continue
            if before.get(s2.id) is None and s2.due_date is not None:
                target_email = s2.owner_email or s2.definition.default_owner_email or ""
                announcements.cross_department_unlock(db, sub.project, target_email, trigger_label, s2.definition.item_no, s2.definition.name)
                db.add(models.WorkflowHistory(submission_id=s2.id, action="unlocked",
                                               actor_name="system", note=f"Unlocked by approval of {trigger_label}"))
        db.commit()

        rules.check_l1_completion(db, sub.project)
        db.commit()

    return {"status": "ok"}


@router.post("/{submission_id}/reassign-request")
def request_reassignment(submission_id: int, payload: schemas.ReassignRequestCreate, db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    to_email = payload.to_email.strip()
    if not to_email:
        raise HTTPException(400, "The new owner's email is required")
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
        }
        for s in subs
    ]


@router.post("/bulk-remind")
def bulk_remind(payload: schemas.BulkRemindRequest, db: Session = Depends(get_db)):
    if payload.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can send reminders")
    subs = db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.id.in_(payload.submission_ids)).all()
    sent = 0
    for s in subs:
        owner = s.owner_email or s.definition.default_owner_email
        if owner:
            announcements.reminder_sent(db, s.project, owner, s.definition.item_no, s.definition.name, s.due_date)
            sent += 1
    return {"sent": sent}


@router.get("/{submission_id}/history")
def get_history(submission_id: int, db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    return [
        {"action": h.action, "actor": h.actor_name, "note": h.note, "at": h.created_at}
        for h in sorted(sub.history, key=lambda h: h.created_at)
    ]

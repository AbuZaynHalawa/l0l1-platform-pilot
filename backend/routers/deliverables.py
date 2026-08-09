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


@router.get("")
def list_all_deliverables(status: str | None = None, db: Session = Depends(get_db)):
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
    out = []
    for s in subs:
        if status and s.status.value != status:
            continue
        out.append({
            "id": s.id, "est_no": s.project.est_no, "project_name": s.project.name,
            "department": s.definition.department.name, "department_number": s.definition.department.number,
            "item_no": s.definition.item_no,
            "name": s.definition.name, "due_date": s.due_date, "status": s.status.value,
            "owner": s.owner_email or s.definition.default_owner_email or "Unassigned",
            "is_milestone": s.definition.is_milestone, "milestone_code": s.definition.milestone_code,
        })
    return out


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

    return {"status": "ok", "file_ref": file_ref}


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

    if decision.approved and sub.definition.is_milestone:
        recipients = sorted({d.focal_point_email for d in db.query(models.Department).all() if d.focal_point_email})
        announcements.milestone_reached(db, sub.project, recipients, sub.definition.milestone_code, sub.definition.name)
        if sub.definition.milestone_code == "M6" and sub.project.stage == models.Stage.L1:
            sub.project.contract_status = models.ContractStatus.SIGNED
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


@router.get("/{submission_id}/history")
def get_history(submission_id: int, db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    return [
        {"action": h.action, "actor": h.actor_name, "note": h.note, "at": h.created_at}
        for h in sorted(sub.history, key=lambda h: h.created_at)
    ]

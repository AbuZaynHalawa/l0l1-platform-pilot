from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from .. import models, schemas, announcements, rules
from ..database import get_db
from ..providers.storage import get_storage_provider

router = APIRouter(prefix="/api/deliverables", tags=["deliverables"])
_storage = get_storage_provider()


def _dept_label(name: str) -> str:
    parts = name.split(". ", 1)
    return parts[1] if len(parts) == 2 else name


@router.get("")
def list_all_deliverables(status: str | None = None, db: Session = Depends(get_db)):
    """Cross-project queue for the Assigned Deliverables page."""
    q = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .join(models.Department)
        .join(models.Project)
    )
    subs = q.all()
    for s in subs:
        rules.refresh_status(s)
    db.commit()
    out = []
    for s in subs:
        if status and s.status.value != status:
            continue
        out.append({
            "id": s.id, "est_no": s.project.est_no, "project_name": s.project.name,
            "department": s.definition.department.name, "item_no": s.definition.item_no,
            "name": s.definition.name, "due_date": s.due_date, "status": s.status.value,
            "owner": s.definition.department.focal_point_name or "Unassigned",
        })
    return out


@router.post("/{submission_id}/upload")
async def upload_deliverable(submission_id: int, file: UploadFile = File(...),
                              owner_name: str = Form("Owner"), db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")

    content = await file.read()
    folder = f"{sub.project.onedrive_folder_path}/{sub.definition.department.name}"
    file_ref = _storage.upload_file(folder, file.filename, content)

    sub.file_name = file.filename
    sub.file_ref = file_ref
    sub.submitted_at = datetime.utcnow()
    sub.status = models.SubmissionStatus.PENDING_REVIEW
    db.add(models.WorkflowHistory(submission_id=sub.id, action="submitted", actor_name=owner_name,
                                   note=f"Uploaded {file.filename}"))
    db.commit()

    dept = sub.definition.department
    if dept.focal_point_email:
        announcements.sme_review_requested(db, sub.project, dept.focal_point_email, sub.definition.item_no, sub.definition.name)
        db.add(models.WorkflowHistory(submission_id=sub.id, action="review_requested",
                                       actor_name="system", note=f"Sent to {dept.focal_point_name}"))
        db.commit()

    return {"status": "ok", "file_ref": file_ref}


@router.post("/{submission_id}/review")
def review_deliverable(submission_id: int, decision: schemas.ReviewDecision, db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    if sub.status != models.SubmissionStatus.PENDING_REVIEW:
        raise HTTPException(400, "Deliverable is not awaiting review")

    sub.status = models.SubmissionStatus.APPROVED if decision.approved else models.SubmissionStatus.REJECTED
    sub.review_comment = decision.comment
    sub.reviewed_at = datetime.utcnow()
    db.add(models.WorkflowHistory(
        submission_id=sub.id, action="approved" if decision.approved else "rejected",
        actor_name=decision.reviewer_name, note=decision.comment,
    ))
    db.commit()

    owner_email = (sub.owner.email if sub.owner else sub.definition.department.focal_point_email) or ""
    dept_label = _dept_label(sub.definition.department.name)
    announcements.sme_decision(db, sub.project, owner_email, sub.definition.item_no, sub.definition.name,
                                decision.approved, decision.comment)

    # Cross-department unlock: any OTHER definition whose predecessor is this item,
    # in the same project's stage, becomes actionable now that this one is approved.
    if decision.approved:
        unlocked_defs = db.query(models.DeliverableDefinition).filter(
            models.DeliverableDefinition.predecessor_item_no == sub.definition.item_no,
            models.DeliverableDefinition.stage == sub.definition.stage,
        ).all()
        for ud in unlocked_defs:
            unlocked_sub = (
                db.query(models.DeliverableSubmission)
                .filter(models.DeliverableSubmission.project_id == sub.project_id,
                        models.DeliverableSubmission.deliverable_definition_id == ud.id)
                .first()
            )
            if not unlocked_sub:
                continue
            target_email = ud.department.focal_point_email or ""
            trigger_label = f"{sub.definition.item_no} {sub.definition.name}"
            announcements.cross_department_unlock(db, sub.project, target_email, trigger_label, ud.item_no, ud.name)
            db.add(models.WorkflowHistory(submission_id=unlocked_sub.id, action="unlocked",
                                           actor_name="system", note=f"Unlocked by approval of {trigger_label}"))
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

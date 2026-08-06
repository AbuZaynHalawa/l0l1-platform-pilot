"""Milestones are derived from deliverable submissions, not manually tracked.
Per the real templates, specific items ARE the milestones (is_milestone=True);
a milestone is "reached" exactly when that item's submission is APPROVED.
There is deliberately no "mark reached" endpoint — see Modifications doc.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db

router = APIRouter(prefix="/api/projects", tags=["milestones"])


@router.get("/{project_id}/milestones")
def get_milestones(project_id: int, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    subs = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .filter(
            models.DeliverableSubmission.project_id == project_id,
            models.DeliverableDefinition.is_milestone == True,  # noqa: E712
        )
        .all()
    )
    subs.sort(key=lambda s: s.definition.milestone_code or "")
    out = []
    for s in subs:
        out.append({
            "code": s.definition.milestone_code,
            "name": s.definition.name,
            "item_no": s.definition.item_no,
            "submission_id": s.id,
            "due_date": s.due_date,
            "reached": s.status == models.SubmissionStatus.APPROVED,
            "actual_date": s.reviewed_at.date() if (s.status == models.SubmissionStatus.APPROVED and s.reviewed_at) else None,
            "status": s.status.value,
        })
    return out

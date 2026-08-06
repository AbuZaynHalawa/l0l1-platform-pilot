"""Read-only timeline views, derived from the same due-date data as the rest
of the app — no separate schedule is stored. A deliverable's bar runs from
whatever it's anchored to (announcement/BSD/site visit/pre-bid deadline, or
its predecessor's due date) through to its own due date.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db

router = APIRouter(prefix="/api/gantt", tags=["gantt"])


def _bar_start(db: Session, project: models.Project, d: models.DeliverableDefinition):
    if d.anchor_type == "announcement":
        return project.announcement_date
    if d.anchor_type == "bsd":
        return project.bsd
    if d.anchor_type == "site_visit":
        return project.site_visit_date
    if d.anchor_type == "pre_bid":
        return project.pre_bid_deadline
    if d.anchor_type == "predecessor" and d.predecessor_item_no:
        pred = (
            db.query(models.DeliverableSubmission)
            .join(models.DeliverableDefinition)
            .filter(
                models.DeliverableSubmission.project_id == project.id,
                models.DeliverableDefinition.item_no == d.predecessor_item_no,
                models.DeliverableDefinition.stage == d.stage,
            )
            .first()
        )
        return pred.due_date if pred else None
    return None


@router.get("/projects/{project_id}")
def get_project_gantt(project_id: int, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    subs = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .join(models.Department)
        .filter(models.DeliverableSubmission.project_id == project_id)
        .order_by(models.Department.order, models.DeliverableDefinition.item_no)
        .all()
    )
    rows = []
    for s in subs:
        d = s.definition
        if s.due_date is None:
            continue  # unscheduled: client-dependent not yet approved, or library/on_request items
        start = _bar_start(db, project, d) or s.due_date
        if start > s.due_date:
            start = s.due_date
        rows.append({
            "item_no": d.item_no, "name": d.name, "department": d.department.name,
            "start": start, "end": s.due_date, "status": s.status.value,
            "is_milestone": d.is_milestone, "milestone_code": d.milestone_code,
        })
    return rows


@router.get("/overview")
def get_overview_gantt(db: Session = Depends(get_db)):
    """One bar per active project, spanning announcement to its latest due date."""
    projects = (
        db.query(models.Project)
        .filter(models.Project.status == models.ProjectStatus.IN_PROGRESS)
        .order_by(models.Project.announcement_date)
        .all()
    )
    rows = []
    for p in projects:
        due_dates = [
            s.due_date
            for s in db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.project_id == p.id).all()
            if s.due_date
        ]
        end = max(due_dates) if due_dates else (p.bsd or p.announcement_date)
        rows.append({
            "id": p.id, "est_no": p.est_no, "name": p.name, "stage": p.stage.value,
            "start": p.announcement_date, "end": end, "status": p.status.value,
        })
    return rows

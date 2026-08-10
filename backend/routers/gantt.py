"""Read-only timeline views, derived from the same due-date data as the rest
of the app — no separate schedule is stored. A deliverable's bar runs from
whatever it's anchored to (announcement/BSD/site visit/pre-bid deadline, or
the next workday after its predecessor's due date) through to its own due date.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, rules
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
        if pred is None or pred.due_date is None:
            return None
        return rules.next_workday_after(pred.due_date)
    return None


@router.get("/projects/{project_id}")
def get_project_gantt(project_id: int, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    rules.recompute_project_due_dates(db, project)
    db.commit()
    subs = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .join(models.Department)
        .filter(models.DeliverableSubmission.project_id == project_id)
        .order_by(models.Department.number)
        .all()
    )
    subs.sort(key=lambda s: (s.definition.department.number or 0, rules.item_sort_key(s.definition.item_no)))
    rows = []
    for s in subs:
        d = s.definition
        if s.due_date is None:
            continue  # unscheduled: client-dependent not yet approved, or library/on_request items
        start = _bar_start(db, project, d) or s.due_date
        if start > s.due_date:
            start = s.due_date
        rows.append({
            "item_no": d.item_no, "name": rules.display_name(d, project), "short_name": d.short_name or d.name,
            "department": d.department.name, "department_number": d.department.number, "submission_id": s.id,
            "start": start, "end": s.due_date, "status": s.status.value,
            "is_milestone": d.is_milestone, "milestone_code": d.milestone_code,
        })
    return rows


@router.get("/timeline")
def get_stage_timeline(stage: str, db: Session = Depends(get_db)):
    """Every active project's deliverable-level bars for one stage, pooled
    together (not grouped by project) and sorted by due date — e.g. item 3.3
    from one project can sit right next to item 2.1 from another, whichever
    is due sooner.
    """
    projects = (
        db.query(models.Project)
        .filter(models.Project.stage == stage, models.Project.status == models.ProjectStatus.IN_PROGRESS)
        .all()
    )
    for p in projects:
        rules.recompute_project_due_dates(db, p)
    db.commit()

    rows = []
    if projects:
        proj_by_id = {p.id: p for p in projects}
        subs = (
            db.query(models.DeliverableSubmission)
            .join(models.DeliverableDefinition)
            .join(models.Department)
            .filter(models.DeliverableSubmission.project_id.in_(proj_by_id.keys()))
            .all()
        )
        for s in subs:
            if s.due_date is None:
                continue  # unscheduled: client-dependent not yet approved, or library/on_request items
            d = s.definition
            project = proj_by_id[s.project_id]
            start = _bar_start(db, project, d) or s.due_date
            if start > s.due_date:
                start = s.due_date
            rows.append({
                "item_no": d.item_no, "name": rules.display_name(d, project), "short_name": d.short_name or d.name,
                "department": d.department.name, "department_number": d.department.number,
                "est_no": project.est_no, "project_id": project.id, "project_name": project.name,
                "submission_id": s.id,
                "start": start, "end": s.due_date, "status": s.status.value,
                "is_milestone": d.is_milestone, "milestone_code": d.milestone_code,
            })
    rows.sort(key=lambda r: (r["end"], r["est_no"], rules.item_sort_key(r["item_no"])))
    return rows

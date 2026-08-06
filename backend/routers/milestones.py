from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, rules, announcements
from ..database import get_db

router = APIRouter(prefix="/api/projects", tags=["milestones"])


@router.get("/{project_id}/milestones")
def get_milestones(project_id: int, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    defs = db.query(models.MilestoneDefinition).filter(models.MilestoneDefinition.stage == project.stage).order_by(models.MilestoneDefinition.sequence).all()
    events = {e.milestone_definition_id: e for e in db.query(models.MilestoneEvent).filter(models.MilestoneEvent.project_id == project_id).all()}
    out = []
    for d in defs:
        e = events.get(d.id)
        out.append({
            "code": d.code, "name": d.name, "sequence": d.sequence,
            "planned_date": e.planned_date if e else None,
            "actual_date": e.actual_date if e else None,
            "reached": bool(e and e.reached),
        })
    return out


@router.post("/{project_id}/milestones/{code}/reach")
def reach_milestone(project_id: int, code: str, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    md = db.query(models.MilestoneDefinition).filter(
        models.MilestoneDefinition.stage == project.stage, models.MilestoneDefinition.code == code
    ).first()
    if not md:
        raise HTTPException(404, "Milestone not defined for this stage")

    event = db.query(models.MilestoneEvent).filter(
        models.MilestoneEvent.project_id == project_id, models.MilestoneEvent.milestone_definition_id == md.id
    ).first()
    if not event:
        event = models.MilestoneEvent(project_id=project_id, milestone_definition_id=md.id)
        db.add(event)
    event.actual_date = date.today()
    event.planned_date = event.planned_date or event.actual_date
    event.reached = True
    db.commit()

    # Recompute due dates for every submission in this project — cheap, and
    # correctly cascades through predecessor chains anchored off this milestone.
    all_defs = {
        d.item_no: d for d in db.query(models.DeliverableDefinition).filter(models.DeliverableDefinition.stage == project.stage)
    }
    subs = db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.project_id == project_id).all()
    by_item = {s.deliverable_definition_id: s for s in subs}
    ordered = sorted(subs, key=lambda s: 0 if s.definition.anchor_type == "milestone" else 1)
    for s in ordered:
        s.due_date = rules.compute_due_date(db, s.definition, project)
        rules.refresh_status(s)
    db.commit()

    recipients = sorted({d.focal_point_email for d in db.query(models.Department).all() if d.focal_point_email})
    announcements.milestone_reached(db, project, recipients, code, md.name)

    return {"status": "ok"}

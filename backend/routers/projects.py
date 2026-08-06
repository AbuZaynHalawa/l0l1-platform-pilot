import random
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, rules, announcements
from ..database import get_db
from ..providers.storage import get_storage_provider

router = APIRouter(prefix="/api/projects", tags=["projects"])
_storage = get_storage_provider()


def _next_est_no(db: Session) -> str:
    last = db.query(models.Project).order_by(models.Project.id.desc()).first()
    base = 1655
    if last and last.est_no.startswith("Est-"):
        try:
            base = max(base, int(last.est_no.replace("Est-", "")) + 1)
        except ValueError:
            pass
    return f"Est-{base}"


@router.get("", response_model=list[schemas.ProjectOut])
def list_projects(stage: str | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Project)
    if stage:
        q = q.filter(models.Project.stage == stage)
    return q.order_by(models.Project.created_at.desc()).all()


@router.post("", response_model=schemas.ProjectOut)
def create_project(payload: schemas.ProjectCreate, db: Session = Depends(get_db)):
    stage = models.Stage(payload.stage)
    est_no = _next_est_no(db)
    project = models.Project(
        est_no=est_no, name=payload.name, stage=stage, region=payload.region,
        scope=payload.scope, bid_manager=payload.bid_manager, project_manager=payload.project_manager,
        bsd=payload.bsd, announcement_date=date.today(),
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # Milestone M1 is reached the moment the project/stage is announced — every
    # other milestone (and everything anchored to it) stays unreached until a
    # future "milestone reached" action records it. Without this, no due date
    # in the whole deliverable catalog would ever have an anchor to resolve against.
    milestone_defs = db.query(models.MilestoneDefinition).filter(models.MilestoneDefinition.stage == stage).order_by(models.MilestoneDefinition.sequence).all()
    for i, md in enumerate(milestone_defs):
        is_m1 = i == 0
        db.add(models.MilestoneEvent(
            project_id=project.id, milestone_definition_id=md.id,
            planned_date=project.announcement_date if is_m1 else None,
            actual_date=project.announcement_date if is_m1 else None,
            reached=is_m1,
        ))
    db.commit()

    # Provision department folders (real OneDrive call once STORAGE_BACKEND=onedrive)
    folder_root = f"{stage.value}/{est_no} {payload.name}"
    _storage.create_folder(folder_root)
    project.onedrive_folder_path = folder_root
    for dept in db.query(models.Department).order_by(models.Department.order).all():
        _storage.create_folder(f"{folder_root}/{dept.name}")
    db.commit()

    # Instantiate deliverable submissions from the active catalog for this stage.
    # Predecessor-anchored items (e.g. 4.6 after 4.4) need their predecessor's
    # submission to exist first, so process milestone-anchored definitions first.
    defs = db.query(models.DeliverableDefinition).filter(
        models.DeliverableDefinition.stage == stage, models.DeliverableDefinition.active == True  # noqa: E712
    ).order_by(models.DeliverableDefinition.anchor_type.asc()).all()  # "milestone" before "predecessor" alphabetically
    for d in defs:
        due = rules.compute_due_date(db, d, project)
        sub = models.DeliverableSubmission(project_id=project.id, deliverable_definition_id=d.id, due_date=due)
        rules.refresh_status(sub)
        db.add(sub)
        db.flush()
    db.commit()

    recipients = sorted({
        dept.focal_point_email for dept in db.query(models.Department).all() if dept.focal_point_email
    })
    announcements.project_created(db, project, recipients)

    return project


@router.get("/{project_id}", response_model=schemas.ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.get("/{project_id}/deliverables", response_model=list[schemas.SubmissionOut])
def get_deliverables(project_id: int, department: str | None = None, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    q = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .join(models.Department)
        .filter(models.DeliverableSubmission.project_id == project_id)
    )
    if department:
        q = q.filter(models.Department.name == department)
    out = []
    for s in q.all():
        rules.refresh_status(s)
        out.append(schemas.SubmissionOut(
            id=s.id, item_no=s.definition.item_no, name=s.definition.name,
            department=s.definition.department.name, due_date=s.due_date, status=s.status.value,
            owner_name=s.owner.name if s.owner else s.definition.department.focal_point_name,
            file_name=s.file_name, submitted_at=s.submitted_at, review_comment=s.review_comment,
        ))
    db.commit()
    return out

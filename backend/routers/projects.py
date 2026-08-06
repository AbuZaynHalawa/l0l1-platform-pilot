from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, rules, announcements
from ..database import get_db
from ..providers.storage import get_storage_provider, sanitize_segment

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


def _provision_and_instantiate(db: Session, project: models.Project):
    """Shared by both L0 and L1 creation: provision folders, instantiate every
    active deliverable for this stage, compute due dates, auto-assign owners/SMEs.
    """
    stage = project.stage
    folder_root = f"{stage.value}/{sanitize_segment(project.est_no)} {sanitize_segment(project.name)}"
    _storage.create_folder(folder_root)
    project.onedrive_folder_path = folder_root

    defs = (
        db.query(models.DeliverableDefinition)
        .filter(models.DeliverableDefinition.stage == stage, models.DeliverableDefinition.active == True)  # noqa: E712
        .all()
    )
    dept_seen = set()
    for d in defs:
        if d.department_id not in dept_seen:
            _storage.create_folder(f"{folder_root}/{sanitize_segment(d.department.name)}")
            dept_seen.add(d.department_id)
        sub = models.DeliverableSubmission(
            project_id=project.id, deliverable_definition_id=d.id,
            owner_email=d.default_owner_email, sme_email=d.default_sme_email,
        )
        db.add(sub)
    db.commit()

    rules.recompute_project_due_dates(db, project)
    db.commit()

    # Auto-assign notification: one summary per distinct owner, per Modifications doc.
    subs = db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.project_id == project.id).all()
    by_owner: dict[str, int] = {}
    for s in subs:
        if s.owner_email:
            by_owner[s.owner_email] = by_owner.get(s.owner_email, 0) + 1
    for dept in {d.department for d in defs}:
        if dept.focal_point_email:
            count = sum(1 for s in subs if s.definition.department_id == dept.id)
            if count:
                announcements.owner_assigned(db, project, dept.focal_point_email, dept.name, count)


@router.get("", response_model=list[schemas.ProjectOut])
def list_projects(stage: str | None = None, status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Project)
    if stage:
        q = q.filter(models.Project.stage == stage)
    if status:
        q = q.filter(models.Project.status == status)
    return q.order_by(models.Project.created_at.desc()).all()


@router.post("/l0", response_model=schemas.ProjectOut)
def create_l0_project(payload: schemas.ProjectCreateL0, db: Session = Depends(get_db)):
    if payload.bid_manager not in models.BID_MANAGERS:
        raise HTTPException(400, "Bid Manager must be selected from the directory")
    if not payload.region:
        raise HTTPException(400, "Region is required")
    if not payload.scope:
        raise HTTPException(400, "Scope is required")

    est_no = _next_est_no(db)
    project = models.Project(
        est_no=est_no, name=payload.name, stage=models.Stage.L0,
        region=payload.region, region_other=payload.region_other,
        scope=payload.scope, scope_other=payload.scope_other,
        rfx_number=payload.rfx_number, bid_manager=payload.bid_manager,
        announcement_date=payload.announcement_date, bsd=payload.bsd,
        site_visit_date=payload.site_visit_date, pre_bid_deadline=payload.pre_bid_deadline,
        scope_contains_pbu=payload.scope_contains_pbu,
        status=models.ProjectStatus.IN_PROGRESS,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    _provision_and_instantiate(db, project)

    recipients = sorted({d.focal_point_email for d in db.query(models.Department).all() if d.focal_point_email})
    announcements.project_created(db, project, recipients)
    return project


@router.post("/l1", response_model=schemas.ProjectOut)
def create_l1_project(payload: schemas.ProjectCreateL1, db: Session = Depends(get_db)):
    l0 = db.get(models.Project, payload.l0_source_id)
    if not l0 or l0.stage != models.Stage.L0:
        raise HTTPException(404, "L0 tender not found")
    if l0.status != models.ProjectStatus.IN_PROGRESS:
        raise HTTPException(400, "Only in-progress L0 tenders can become L1 projects")

    est_no = _next_est_no(db)
    project = models.Project(
        est_no=est_no, name=l0.name, stage=models.Stage.L1,
        region=l0.region, region_other=l0.region_other, scope=l0.scope, scope_other=l0.scope_other,
        rfx_number=l0.rfx_number, bid_manager=l0.bid_manager,
        announcement_date=payload.announcement_date,
        l0_source_id=l0.id, status=models.ProjectStatus.IN_PROGRESS,
        contract_status=models.ContractStatus.NOT_SIGNED,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    _provision_and_instantiate(db, project)

    recipients = sorted({d.focal_point_email for d in db.query(models.Department).all() if d.focal_point_email})
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
    subs = q.all()
    subs.sort(key=lambda s: (s.definition.department.order, rules.item_sort_key(s.definition.item_no)))
    out = []
    for s in subs:
        rules.refresh_status(s)
        out.append(schemas.SubmissionOut(
            id=s.id, item_no=s.definition.item_no, name=s.definition.name,
            department=s.definition.department.name, due_date=s.due_date, status=s.status.value,
            owner_email=s.owner_email or s.definition.default_owner_email,
            sme_email=s.sme_email or s.definition.default_sme_email,
            file_name=s.file_name, submitted_at=s.submitted_at, review_comment=s.review_comment,
            is_milestone=s.definition.is_milestone, milestone_code=s.definition.milestone_code,
        ))
    db.commit()

    # L1 auto-completes when every deliverable is submitted (approved), per Modifications doc.
    if project.stage == models.Stage.L1 and project.status == models.ProjectStatus.IN_PROGRESS:
        all_subs = q.all()
        if all_subs and all(s.status == models.SubmissionStatus.APPROVED for s in all_subs):
            project.status = models.ProjectStatus.COMPLETED
            db.commit()

    return out

from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, rules, announcements
from ..database import get_db
from ..providers.storage import get_storage_provider, sanitize_segment

router = APIRouter(prefix="/api/projects", tags=["projects"])
_storage = get_storage_provider()


# Items 115/116: these Tendering Department items just restate data already
# captured directly on the project's own creation form -- auto-complete them
# immediately using that data instead of making someone redo it as a separate
# deliverable. Maps item_no -> the Project attribute providing the
# completion date. If that field is blank at creation (e.g. the optional
# Pre-Bid Meeting Date), the item falls back to the normal manual workflow
# instead. "1.5" (Assign Bid Manager) has no dedicated date field of its
# own -- it's anchored to announcement_date, since the BM is set the same
# moment the tender kicks off.
_L0_AUTO_DONE_FIELDS = {
    "1.1": "announcement_date",
    "1.2": "site_visit_date",
    "1.3": "pre_bid_meeting_date",
    "1.4": "pre_bid_deadline",
    "1.5": "announcement_date",
}
_L1_AUTO_DONE_FIELDS = {
    "1.1": "announcement_date",
}

# Item 140: item 85 excluded every Tendering Department item from BM triage
# (no "is this applicable to my project" call to make on your own
# department's work) -- these five are the exception, since whether they're
# even needed genuinely varies per tender the same way another
# department's items do.
_L0_TENDERING_TRIAGE_ITEMS = {"1.6", "1.7", "1.13", "1.14", "1.15"}


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
    defs = [d for d in defs if rules.is_bu_applicable(d, project)]
    auto_done_fields = _L0_AUTO_DONE_FIELDS if stage == models.Stage.L0 else _L1_AUTO_DONE_FIELDS
    dept_seen = set()
    auto_done_subs = []  # (sub, definition) pairs — WorkflowHistory needs real ids, added after the commit below
    for d in defs:
        if d.department_id not in dept_seen:
            _storage.create_folder(f"{folder_root}/{sanitize_segment(d.department.name)}")
            dept_seen.add(d.department_id)
        # New L0 non-milestone items start out unconfirmed — the BM must triage
        # each one as applicable or not-required before it gets a due date.
        # Milestones anchor the whole project's due-date chain, so they're
        # never subject to triage; L1 deliverables aren't gated at all.
        # Tendering Department items are the BM's own department's work —
        # there's no "is this applicable to my project" call to make on
        # your own department's items, so they're excluded too (item 85).
        needs_triage = stage == models.Stage.L0 and not d.is_milestone and (
            d.department.name != "Tendering Department" or d.item_no in _L0_TENDERING_TRIAGE_ITEMS
        )

        # Items 115/116: auto-complete Tendering items that just restate a
        # field already captured on this project's own creation form. 1.1
        # doubles as the M1 milestone, so this stays a genuine APPROVED
        # (not a separate status) -- milestone "reached" and predecessor
        # chaining both key off status==APPROVED and don't need to know
        # this was auto- rather than human-completed. auto_completed is
        # the flag that actually drives hiding it from tracking.
        auto_done_date = None
        if d.department.name == "Tendering Department":
            field = auto_done_fields.get(d.item_no)
            if field:
                auto_done_date = getattr(project, field, None)

        if auto_done_date:
            sub = models.DeliverableSubmission(
                project_id=project.id, deliverable_definition_id=d.id,
                owner_email=d.default_owner_email, sme_email=d.default_sme_email,
                applicability="applicable", status=models.SubmissionStatus.APPROVED,
                auto_completed=True, due_date=auto_done_date,
                submitted_at=datetime.combine(auto_done_date, datetime.min.time()),
                reviewed_at=datetime.combine(auto_done_date, datetime.min.time()),
                review_comment="Auto-completed from the project's own details.",
            )
            auto_done_subs.append(sub)
        else:
            sub = models.DeliverableSubmission(
                project_id=project.id, deliverable_definition_id=d.id,
                owner_email=d.default_owner_email, sme_email=d.default_sme_email,
                applicability="pending" if needs_triage else "applicable",
            )
        db.add(sub)
    db.commit()

    for sub in auto_done_subs:
        db.add(models.WorkflowHistory(submission_id=sub.id, action="auto_done", actor_name="system",
                                       note="Auto-completed from the project's own details"))
    if auto_done_subs:
        db.commit()

    rules.recompute_project_due_dates(db, project, force=True)
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


def _active_bid_manager_emails(db: Session) -> set[str]:
    return {b.email.lower() for b in db.query(models.BidManager).filter(models.BidManager.active == True).all()}  # noqa: E712


@router.post("/l0", response_model=schemas.ProjectOut)
def create_l0_project(payload: schemas.ProjectCreateL0, db: Session = Depends(get_db)):
    if (payload.bid_manager or "").lower() not in _active_bid_manager_emails(db):
        raise HTTPException(400, "Bid Manager must be selected from the directory")
    if not payload.region:
        raise HTTPException(400, "Region is required")
    if not payload.scope:
        raise HTTPException(400, "Scope is required")
    if "Other" in payload.region and not (payload.region_other or "").strip():
        raise HTTPException(400, "Specify the Other region")
    if "Other" in payload.scope and not (payload.scope_other or "").strip():
        raise HTTPException(400, "Specify the Other scope")
    est_no = payload.est_no.strip()
    if not est_no:
        raise HTTPException(400, "Est-Num is required")
    # Item 119: est_no is no longer globally unique -- an L1 deliberately
    # reuses its L0's own number -- so this only guards against two
    # different L0 tenders colliding, not against an L0/L1 pair sharing one.
    if db.query(models.Project).filter(models.Project.est_no == est_no, models.Project.stage == models.Stage.L0).first():
        raise HTTPException(400, f"Est-No {est_no} is already in use")

    business_units, needs_manual = rules.compute_business_units(payload.scope)
    if needs_manual:
        chosen = [b for b in (payload.business_units or []) if b in ("TBU", "PBU", "DBU", "BBU", "TBA")]
        if not chosen:
            raise HTTPException(400, "Business Unit is required for this scope (choose TBU/PBU/DBU/BBU, or TBA)")
        business_units = chosen

    project = models.Project(
        est_no=est_no, name=payload.name, stage=models.Stage.L0,
        region=payload.region, region_other=payload.region_other,
        scope=payload.scope, scope_other=payload.scope_other,
        rfx_number=payload.rfx_number, bid_manager=payload.bid_manager,
        announcement_date=payload.announcement_date, bsd=payload.bsd,
        site_visit_date=payload.site_visit_date, pre_bid_meeting_date=payload.pre_bid_meeting_date,
        pre_bid_deadline=payload.pre_bid_deadline,
        business_units=business_units, scope_contains_pbu="PBU" in business_units,
        status=models.ProjectStatus.IN_PROGRESS,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    _provision_and_instantiate(db, project)

    recipients = sorted({d.focal_point_email for d in db.query(models.Department).all() if d.focal_point_email} | rules.system_group_emails(db))
    announcements.project_created(db, project, recipients)
    return project


@router.post("/l1", response_model=schemas.ProjectOut)
def create_l1_project(payload: schemas.ProjectCreateL1, db: Session = Depends(get_db)):
    l0 = db.get(models.Project, payload.l0_source_id)
    if not l0 or l0.stage != models.Stage.L0:
        raise HTTPException(404, "L0 tender not found")
    if l0.status != models.ProjectStatus.IN_PROGRESS:
        raise HTTPException(400, "Only in-progress L0 tenders can become L1 projects")

    # Item 119: keep the L0's own Est number as-is -- same tender, later
    # stage, not a new one -- instead of minting a fresh one.
    project = models.Project(
        est_no=l0.est_no, name=l0.name, stage=models.Stage.L1,
        region=l0.region, region_other=l0.region_other, scope=l0.scope, scope_other=l0.scope_other,
        rfx_number=l0.rfx_number, bid_manager=l0.bid_manager,
        business_units=l0.business_units, scope_contains_pbu=l0.scope_contains_pbu,
        announcement_date=payload.announcement_date,
        l0_source_id=l0.id, status=models.ProjectStatus.IN_PROGRESS,
        contract_status=models.ContractStatus.NOT_SIGNED,
        project_manager=payload.project_manager,
    )
    db.add(project)
    # Item 119: the L0 stage is done the moment its L1 exists -- close it
    # out immediately instead of leaving it sitting as still "In Progress"
    # alongside its own L1.
    l0.status = models.ProjectStatus.SUBMITTED
    db.commit()
    db.refresh(project)

    _provision_and_instantiate(db, project)

    recipients = sorted({d.focal_point_email for d in db.query(models.Department).all() if d.focal_point_email} | rules.system_group_emails(db))
    announcements.project_created(db, project, recipients)
    return project


@router.delete("/{project_id}")
def delete_project(project_id: int, actor_role: str = "Viewer", db: Session = Depends(get_db)):
    """Removes a project and everything under it — mainly for cleaning up a
    mistaken or test entry. Cascades cover submissions and workflow history
    on their own; documents, followers, and reassignment requests aren't
    reverse-cascaded from the submission side, so they're cleared explicitly
    here. Announcements are detached (kept, project/submission refs nulled)
    rather than deleted, so the activity log isn't rewritten.
    """
    if actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can delete a project")
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if db.query(models.Project).filter(models.Project.l0_source_id == project_id).first():
        raise HTTPException(400, "This L0 tender has an L1 project sourced from it — delete that first")

    sub_ids = [row[0] for row in db.query(models.DeliverableSubmission.id).filter(models.DeliverableSubmission.project_id == project_id).all()]
    if sub_ids:
        db.query(models.Document).filter(models.Document.submission_id.in_(sub_ids)).delete(synchronize_session=False)
        db.query(models.Follower).filter(models.Follower.submission_id.in_(sub_ids)).delete(synchronize_session=False)
        db.query(models.ReassignmentRequest).filter(models.ReassignmentRequest.submission_id.in_(sub_ids)).delete(synchronize_session=False)
        db.query(models.Announcement).filter(models.Announcement.submission_id.in_(sub_ids)).update(
            {"submission_id": None}, synchronize_session=False)
    db.query(models.Announcement).filter(models.Announcement.project_id == project_id).update(
        {"project_id": None}, synchronize_session=False)

    db.delete(project)
    db.commit()
    return {"status": "ok"}


@router.get("/bm-triage-status")
def get_bm_triage_status(actor_role: str = "Viewer", actor_email: str = "", db: Session = Depends(get_db)):
    """Admin overview (item 79) of where every L0 tender's BM triage stands:
    done, still pending, or pending-with-a-reminder-already-sent. Item 110:
    a Bid Manager (anyone acting as their own roster email, not just Admin)
    can see the same view too, scoped to just their own assigned tenders.

    Declared here, before the /{project_id} catch-all below, on purpose —
    a literal single-segment route registered after a same-shape dynamic
    route gets swallowed by it (int-parsing 422 on "bm-triage-status" as
    project_id) the same way /follow-up once broke against /{submission_id}
    in deliverables.py. Literal routes always go first.
    """
    actor_email = actor_email.strip().lower()
    if actor_role != "Admin" and not actor_email:
        raise HTTPException(403, "Only an Admin, or a Bid Manager viewing their own tenders, can view BM triage status")
    q = db.query(models.Project).filter(
        models.Project.stage == models.Stage.L0, models.Project.status == models.ProjectStatus.IN_PROGRESS
    )
    if actor_role != "Admin":
        q = q.filter(models.Project.bid_manager.ilike(actor_email))
    projects = q.order_by(models.Project.created_at.desc()).all()
    out = []
    for p in projects:
        subs = db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.project_id == p.id).all()
        triageable = [s for s in subs if not s.definition.is_milestone]
        pending = sum(1 for s in triageable if s.applicability == "pending")
        if pending == 0:
            status = "done"
        elif p.last_triage_reminder_at:
            status = "reminded"
        else:
            status = "pending"
        out.append({
            "id": p.id, "est_no": p.est_no, "name": p.name, "bid_manager": p.bid_manager,
            "pending_count": pending, "total_count": len(triageable), "status": status,
            "last_reminder_at": p.last_triage_reminder_at,
        })
    return out


@router.get("/{project_id}", response_model=schemas.ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    project.pending_triage_count = (
        db.query(models.DeliverableSubmission)
        .filter(
            models.DeliverableSubmission.project_id == project_id,
            models.DeliverableSubmission.applicability == "pending",
        )
        .count()
    )
    return project


@router.post("/{project_id}/triage", response_model=schemas.ProjectOut)
def triage_l0_project(project_id: int, payload: schemas.TriageRequest, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project.stage != models.Stage.L0:
        raise HTTPException(400, "Only L0 tenders go through BM triage")
    if not rules.can_act(payload.actor_role, payload.actor_email, project.bid_manager):
        raise HTTPException(403, f"Only {project.bid_manager or 'the assigned Bid Manager'} or an Admin can triage this tender")

    subs_by_id = {
        s.id: s for s in
        db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.project_id == project_id).all()
    }
    bm = (project.bid_manager or "").strip()
    prefs_by_item = {}
    if bm:
        prefs_by_item = {
            p.item_no: p for p in
            db.query(models.BmTriagePreference).filter(models.BmTriagePreference.bid_manager == bm).all()
        }
    for item in payload.items:
        sub = subs_by_id.get(item.submission_id)
        if sub and not sub.definition.is_milestone:
            sub.applicability = "applicable" if item.applicable else "not_required"
            # Remember this BM's call per item_no (item 79) so it's the
            # pre-selected default the next time they triage a different
            # tender — most BMs repeat the same applicable/not-required
            # pattern project to project.
            if bm:
                existing_pref = prefs_by_item.get(sub.definition.item_no)
                if existing_pref:
                    existing_pref.applicable = item.applicable
                else:
                    new_pref = models.BmTriagePreference(bid_manager=bm, item_no=sub.definition.item_no, applicable=item.applicable)
                    db.add(new_pref)
                    prefs_by_item[sub.definition.item_no] = new_pref
    db.commit()

    rules.recompute_project_due_dates(db, project, force=True)
    db.commit()
    db.refresh(project)
    project.pending_triage_count = sum(1 for s in subs_by_id.values() if s.applicability == "pending")
    return project


@router.get("/{project_id}/triage-defaults")
def get_triage_defaults(project_id: int, db: Session = Depends(get_db)):
    """The assigned Bid Manager's remembered applicable/not-required calls
    (item 79), keyed by item_no, for pre-selecting the triage screen.
    """
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    bm = (project.bid_manager or "").strip()
    if not bm:
        return {}
    prefs = db.query(models.BmTriagePreference).filter(models.BmTriagePreference.bid_manager == bm).all()
    return {p.item_no: p.applicable for p in prefs}


@router.post("/{project_id}/triage-reminder")
def send_triage_reminder(project_id: int, actor_role: str = "Viewer", db: Session = Depends(get_db)):
    if actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can send a triage reminder")
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.bid_manager:
        raise HTTPException(400, "This tender has no Bid Manager assigned")
    pending = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .filter(
            models.DeliverableSubmission.project_id == project_id,
            models.DeliverableSubmission.applicability == "pending",
            models.DeliverableDefinition.is_milestone == False,  # noqa: E712
        )
        .count()
    )
    if not pending:
        raise HTTPException(400, "This tender's triage is already complete")
    announcements.triage_reminder(db, project, project.bid_manager, pending)
    project.last_triage_reminder_at = datetime.utcnow()
    db.commit()
    return {"status": "ok", "reminded": project.bid_manager}


@router.patch("/{project_id}/project-manager", response_model=schemas.ProjectOut)
def update_project_manager(project_id: int, payload: schemas.ProjectManagerUpdate, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    project.project_manager = (payload.project_manager or "").strip() or None
    db.commit()
    db.refresh(project)
    return project


@router.patch("/{project_id}/details", response_model=schemas.ProjectOut)
def update_project_details(project_id: int, payload: schemas.ProjectDetailsUpdate, db: Session = Depends(get_db)):
    if payload.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can edit these fields")
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    data = payload.model_dump(exclude_unset=True, exclude={"actor_role"})
    if "bid_manager" in data:
        active_emails = _active_bid_manager_emails(db)
        if (data["bid_manager"] or "").lower() not in active_emails:
            raise HTTPException(400, "Bid Manager must be selected from the directory")
        project.bid_manager = data["bid_manager"]
    if "region" in data:
        if not data["region"]:
            raise HTTPException(400, "Select at least one Region")
        project.region = data["region"]
    if "region_other" in data:
        project.region_other = data["region_other"]
    date_changed = False
    for field in ("announcement_date", "site_visit_date", "pre_bid_meeting_date", "pre_bid_deadline"):
        if field in data:
            setattr(project, field, data[field])
            date_changed = True
    db.commit()
    if date_changed:
        rules.recompute_project_due_dates(db, project, force=True)
        db.commit()
    db.refresh(project)
    return project


@router.patch("/{project_id}/status", response_model=schemas.ProjectOut)
def update_project_status(project_id: int, payload: schemas.ProjectStatusUpdate, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    valid = {"In Progress"} | ({"Submitted", "Cancelled"} if project.stage == models.Stage.L0 else {"Completed"})
    if payload.status not in valid:
        raise HTTPException(400, f"Invalid status for {project.stage.value}: must be one of {sorted(valid)}")
    project.status = models.ProjectStatus(payload.status)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}/history")
def get_project_history(project_id: int, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    rows = (
        db.query(models.WorkflowHistory)
        .join(models.DeliverableSubmission)
        .filter(models.DeliverableSubmission.project_id == project_id)
        .order_by(models.WorkflowHistory.created_at)
        .all()
    )
    return [
        {
            "action": h.action, "actor": h.actor_name, "note": h.note, "at": h.created_at,
            "item_no": h.submission.definition.item_no, "name": h.submission.definition.name,
        }
        for h in rows
    ]


@router.get("/{project_id}/deliverables", response_model=list[schemas.SubmissionOut])
def get_deliverables(project_id: int, department: str | None = None, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    # Not-yet-approved items' due dates can shift day to day (an overdue,
    # still-undone predecessor keeps pushing dependents forward), so this
    # checks on every read rather than only after the next approval event —
    # it's a cheap no-op past the first read of the day, see the docstring.
    rules.recompute_project_due_dates(db, project)
    db.commit()
    q = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .join(models.Department)
        .filter(models.DeliverableSubmission.project_id == project_id)
        .filter(models.DeliverableSubmission.auto_completed.isnot(True))
    )
    if department:
        q = q.filter(models.Department.name == department)
    subs = q.all()
    subs.sort(key=lambda s: (s.definition.department.number or 0, rules.item_sort_key(s.definition.item_no)))
    doc_counts = rules.document_counts(db, [s.id for s in subs])
    out = []
    for s in subs:
        deadline_key, deadline_days = rules.deadline_status(s)
        out.append(schemas.SubmissionOut(
            id=s.id, item_no=s.definition.item_no, name=rules.display_name(s.definition, project),
            department=s.definition.department.name, due_date=s.due_date, status=s.status.value,
            deadline_status=deadline_key, deadline_days=deadline_days, auto_completed=s.auto_completed,
            owner_email=s.owner_email or s.definition.default_owner_email,
            sme_email=s.sme_email or s.definition.default_sme_email,
            file_name=s.file_name, file_url=_storage.file_url(s.file_ref) if s.file_ref else None,
            submitted_at=s.submitted_at, review_comment=s.review_comment,
            completion_note=rules.mark_complete_note(s),
            is_milestone=s.definition.is_milestone, milestone_code=s.definition.milestone_code,
            doc_total=doc_counts.get(s.id, 0),
        ))
    db.commit()

    rules.check_l1_completion(db, project)
    db.commit()

    return out

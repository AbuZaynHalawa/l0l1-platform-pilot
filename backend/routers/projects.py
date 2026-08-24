from datetime import date, datetime
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
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


def _instantiate_deliverables(db: Session, project: models.Project):
    """The deliverable-generation core of _provision_and_instantiate, split
    out so a safe post-creation Scope/Business Unit change (see
    update_project_details) can re-run it against the new scope without
    redoing folder provisioning. Skips any DeliverableDefinition that
    already has a submission on this project -- a no-op on first creation
    (nothing exists yet), and on a scope resync it protects the
    auto-completed Tendering items (1.1-1.5, derived from the project's
    own date fields, unrelated to scope) from being duplicated.
    """
    stage = project.stage
    folder_root = project.onedrive_folder_path
    existing_pairs = {
        (s.deliverable_definition_id, s.po_line_item_id) for s in
        db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.project_id == project.id).all()
    }
    defs = (
        db.query(models.DeliverableDefinition)
        .filter(models.DeliverableDefinition.stage == stage, models.DeliverableDefinition.active == True)  # noqa: E712
        .all()
    )
    defs = [d for d in defs if rules.is_bu_applicable(d, project) and rules.is_scope_variant_applicable(d, project)
            and rules.is_international_applicable(d, project)]
    # [PO Lifecycle]: a line_item_category definition fans out one submission
    # per active PoLineItem in that category (comma-separated when a
    # definition spans two pools, e.g. "3.11" -> "early_activity,mep")
    # instead of the usual one submission total. `targets` holds the
    # PoLineItem to attach for each submission still needed (None for an
    # ordinary, non-fan-out definition).
    line_items_by_cat: dict[str, list] = {}
    for li in (db.query(models.PoLineItem)
               .filter(models.PoLineItem.project_id == project.id, models.PoLineItem.status == "active").all()):
        line_items_by_cat.setdefault(li.category, []).append(li)
    def _targets_for(d):
        if d.line_item_category:
            cats = [c.strip() for c in d.line_item_category.split(",")]
            return [li for c in cats for li in line_items_by_cat.get(c, [])
                    if (d.id, li.id) not in existing_pairs]
        return [None] if (d.id, None) not in existing_pairs else []

    auto_done_fields = _L0_AUTO_DONE_FIELDS if stage == models.Stage.L0 else _L1_AUTO_DONE_FIELDS
    dept_seen = set()
    new_depts = set()  # departments that actually got a new submission this call — notification uses this, not all of `defs`
    auto_done_subs = []  # (sub, definition) pairs — WorkflowHistory needs real ids, added after the commit below
    for d in defs:
        targets = _targets_for(d)
        if not targets:
            continue
        new_depts.add(d.department)
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
        # [L0 International]: "Tendering Department (International)" is the
        # same self-department exemption, just a differently-named row --
        # prefix match covers both without hardcoding the international name.
        is_tendering_dept = d.department.name.startswith("Tendering Department")
        needs_triage = stage == models.Stage.L0 and not d.is_milestone and (
            not is_tendering_dept or d.item_no in _L0_TENDERING_TRIAGE_ITEMS
        )

        # Items 115/116: auto-complete Tendering items that just restate a
        # field already captured on this project's own creation form. 1.1
        # doubles as the M1 milestone, so this stays a genuine APPROVED
        # (not a separate status) -- milestone "reached" and predecessor
        # chaining both key off status==APPROVED and don't need to know
        # this was auto- rather than human-completed. auto_completed is
        # the flag that actually drives hiding it from tracking.
        auto_done_date = None
        if is_tendering_dept:
            field = auto_done_fields.get(d.item_no)
            if field:
                auto_done_date = getattr(project, field, None)

        sme_emails = d.default_sme_emails or ([d.default_sme_email] if d.default_sme_email else [])
        owner_emails = d.default_owner_emails or ([d.default_owner_email] if d.default_owner_email else [])
        for li in targets:
            if auto_done_date:
                sub = models.DeliverableSubmission(
                    project_id=project.id, deliverable_definition_id=d.id, po_line_item_id=li.id if li else None,
                    owner_emails=owner_emails, sme_emails=sme_emails,
                    applicability="applicable", status=models.SubmissionStatus.APPROVED,
                    auto_completed=True, due_date=auto_done_date,
                    submitted_at=datetime.combine(auto_done_date, datetime.min.time()),
                    reviewed_at=datetime.combine(auto_done_date, datetime.min.time()),
                    review_comment="Auto-completed from the project's own details.",
                )
                auto_done_subs.append(sub)
            else:
                sub = models.DeliverableSubmission(
                    project_id=project.id, deliverable_definition_id=d.id, po_line_item_id=li.id if li else None,
                    owner_emails=owner_emails, sme_emails=sme_emails,
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
    for dept in new_depts:
        if dept.focal_point_email:
            count = sum(1 for s in subs if s.definition.department_id == dept.id)
            if count:
                announcements.owner_assigned(db, project, dept.focal_point_email, dept.name, count)


def _ensure_consultancy_line_item(db: Session, project: models.Project) -> None:
    """Consultancy PO is the one PO Lifecycle pool with no declaring item --
    unlike long-lead/early-activity/MEP/S-C (each fanned out from an
    owner's 1.2/4.1/2.11/2.17 selection), it always has exactly one known
    item (the project's Design & Engineering firm) per the original spec,
    so it needs to just always exist rather than waiting on an owner
    action that was never wired up to create it -- without this, "2.7"/
    "3.10" (both category="consultancy") have no PoLineItem to fan out
    against and simply never appear anywhere, including the Deliverables
    list.
    """
    if project.stage != models.Stage.L1:
        return
    existing = (
        db.query(models.PoLineItem)
        .filter(models.PoLineItem.project_id == project.id, models.PoLineItem.category == "consultancy",
                models.PoLineItem.status == "active")
        .first()
    )
    if not existing:
        db.add(models.PoLineItem(project_id=project.id, category="consultancy", name="Design & Engineering",
                                  source="fixed", status="active"))
        db.commit()


def _provision_and_instantiate(db: Session, project: models.Project):
    """Called once at L0/L1 creation: provision folders, then instantiate
    every active deliverable for this stage via _instantiate_deliverables.
    """
    stage = project.stage
    folder_root = f"{stage.value}/{sanitize_segment(project.est_no)} {sanitize_segment(project.name)}"
    _storage.create_folder(folder_root)
    _storage.create_folder(f"{folder_root}/Tender Documents")
    project.onedrive_folder_path = folder_root
    _ensure_consultancy_line_item(db, project)
    _instantiate_deliverables(db, project)


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
    # [L0 International]: Country replaces the KSA Region checkboxes for
    # these projects -- Region stays required (and unused) for a standard one.
    if payload.international:
        if not (payload.country or "").strip():
            raise HTTPException(400, "Country is required")
    elif not payload.region:
        raise HTTPException(400, "Region is required")
    if not payload.scope:
        raise HTTPException(400, "Scope is required")
    if not payload.international and "Other" in payload.region and not (payload.region_other or "").strip():
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

    if payload.international:
        # Every international tender's Operation Unit work is done by IBU
        # (the template's own Action-By column, universally) -- auto-assigned
        # rather than derived from scope, editable later like any other
        # project's business unit via the existing Edit Business Unit flow.
        business_units = ["IBU"]
    else:
        business_units, needs_manual = rules.compute_business_units(payload.scope)
        if needs_manual:
            chosen = [b for b in (payload.business_units or []) if b in ("TBU", "PBU", "DBU", "BBU", "TBA")]
            if not chosen:
                raise HTTPException(400, "Business Unit is required for this scope (choose TBU/PBU/DBU/BBU, or TBA)")
            business_units = chosen

    project = models.Project(
        est_no=est_no, name=payload.name, stage=models.Stage.L0,
        region=None if payload.international else payload.region,
        region_other=None if payload.international else payload.region_other,
        is_international=payload.international,
        country=(payload.country or "").strip() if payload.international else None,
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


def _auto_complete_2_3(db: Session, project: models.Project) -> None:
    """[2.3 <-> PM two-way sync]: setting a real PM (from any of three
    entry points -- L1 creation's own PM field, the project-manager PATCH
    endpoint, or 2.3's own picker, which calls that same endpoint)
    auto-completes "2.3" (Assignment of Temporary Project Manager &
    Project Engineer) -- this data already lives on the project, no one
    should have to redo it as a separate deliverable. Unlike items 115/116
    (which this was originally modeled on), 2.3 stays a fully ordinary
    completed submission -- NOT auto_completed=True -- since that flag
    hides a row from the Deliverables list/Gantt/performance entirely,
    right for a pure form-restatement but wrong here: a real PM was really
    assigned, and hiding it read as the deliverable having vanished rather
    than completed. Only ever completes forward (clearing PM never
    un-completes 2.3 -- that's a genuine Reopen, not something this should
    do silently). Every BU-variant "2.3" (TBU/PBU/DBU) gets it, in case
    more than one is active on a mixed-scope project.
    """
    if not project.project_manager:
        return
    subs = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .filter(models.DeliverableSubmission.project_id == project.id,
                models.DeliverableDefinition.item_no == "2.3",
                models.DeliverableSubmission.status != models.SubmissionStatus.APPROVED)
        .all()
    )
    for sub in subs:
        sub.status = models.SubmissionStatus.APPROVED
        sub.due_date = sub.due_date or date.today()
        sub.submitted_at = sub.submitted_at or datetime.utcnow()
        sub.reviewed_at = datetime.utcnow()
        sub.review_comment = f"Auto-completed: Project Manager set to {project.project_manager}."
        db.add(models.WorkflowHistory(submission_id=sub.id, action="auto_done", actor_name="system",
                                       note=sub.review_comment))
    if subs:
        db.commit()
        rules.recompute_project_due_dates(db, project, force=True)
        db.commit()


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
        bid_value=payload.bid_value,
    )
    db.add(project)
    # Item 119: the L0 stage is done the moment its L1 exists -- close it
    # out immediately instead of leaving it sitting as still "In Progress"
    # alongside its own L1.
    l0.status = models.ProjectStatus.SUBMITTED
    db.commit()
    db.refresh(project)

    _provision_and_instantiate(db, project)
    _auto_complete_2_3(db, project)
    db.refresh(project)

    # Folder 0: an L1 gets its own copies of the L0's tender documents (not a
    # shared reference) so a later addition on one side doesn't silently
    # appear on the other -- same "each stage owns its own data" model the
    # rest of _provision_and_instantiate already follows.
    l0_docs = db.query(models.TenderDocument).filter(models.TenderDocument.project_id == l0.id).all()
    if l0_docs:
        base_folder = f"{project.onedrive_folder_path}/Tender Documents"
        for doc in l0_docs:
            dest_folder = f"{base_folder}/{doc.folder_path}" if doc.folder_path else base_folder
            new_ref = _storage.copy_file(doc.file_ref, dest_folder, doc.file_name)
            db.add(models.TenderDocument(
                project_id=project.id, file_name=doc.file_name, file_ref=new_ref, folder_path=doc.folder_path or "",
                uploaded_by=(f"{doc.uploaded_by} (copied from L0)" if doc.uploaded_by else "Copied from L0"),
            ))
        db.commit()

    recipients = sorted({d.focal_point_email for d in db.query(models.Department).all() if d.focal_point_email} | rules.system_group_emails(db))
    announcements.project_created(db, project, recipients)
    return project


@router.get("/{project_id}/tender-documents")
def list_tender_documents(project_id: int, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    docs = (
        db.query(models.TenderDocument)
        .filter(models.TenderDocument.project_id == project_id)
        .order_by(models.TenderDocument.uploaded_at.desc())
        .all()
    )
    return [
        {"id": d.id, "file_name": d.file_name, "file_url": _storage.file_url(d.file_ref),
         "folder_path": d.folder_path or "", "uploaded_by": d.uploaded_by, "uploaded_at": d.uploaded_at}
        for d in docs
    ]


@router.post("/{project_id}/tender-documents")
async def upload_tender_document(
    project_id: int, file: UploadFile = File(...),
    # Folder uploads (browser sends each file's webkitRelativePath, e.g.
    # "Drawings/Civil/dwg1.pdf") set relative_path so the picked folder's
    # own structure carries into the platform instead of flattening; a
    # plain file upload leaves this blank and the file lands at the root.
    relative_path: str = Form(""),
    actor_name: str = Form("Admin"), actor_role: str = Form("Admin"), actor_email: str = Form(""),
    db: Session = Depends(get_db),
):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not rules.can_act(actor_role, actor_email, [project.bid_manager, project.project_manager]):
        raise HTTPException(403, "Only the assigned Bid Manager/Project Manager or an Admin can add tender documents")
    content = await file.read()
    rel_parts = [sanitize_segment(p) for p in (relative_path or "").split("/") if p.strip()]
    folder_path = "/".join(rel_parts[:-1]) if len(rel_parts) > 1 else ""
    file_name = rel_parts[-1] if rel_parts else file.filename
    base_folder = f"{project.onedrive_folder_path}/Tender Documents"
    folder = f"{base_folder}/{folder_path}" if folder_path else base_folder
    file_ref = _storage.upload_file(folder, file_name, content)
    doc = models.TenderDocument(
        project_id=project.id, file_name=file_name, file_ref=file_ref, folder_path=folder_path, uploaded_by=actor_name,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return {"id": doc.id, "file_name": doc.file_name, "file_url": _storage.file_url(doc.file_ref),
            "folder_path": doc.folder_path or "", "uploaded_by": doc.uploaded_by, "uploaded_at": doc.uploaded_at}


@router.delete("/{project_id}/tender-documents/folder")
def delete_tender_document_folder(project_id: int, path: str, actor_role: str = "Viewer", actor_email: str = "", db: Session = Depends(get_db)):
    """Removes an entire subfolder (and everything nested under it) in one
    call -- every doc whose folder_path is exactly `path` or starts with
    `path/`. Declared before the /{doc_id} route below on purpose: FastAPI
    would otherwise try to int-parse the literal segment "folder" as a
    doc_id and 404 before ever reaching this handler (same ordering
    footgun documented on get_bm_triage_status).
    """
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can delete files/folders")
    path = path.strip("/")
    if not path:
        raise HTTPException(400, "No folder specified")
    docs = db.query(models.TenderDocument).filter(models.TenderDocument.project_id == project_id).all()
    to_delete = [d for d in docs if d.folder_path == path or (d.folder_path or "").startswith(path + "/")]
    if not to_delete:
        raise HTTPException(404, "Folder not found")
    for d in to_delete:
        db.delete(d)
    db.commit()
    return {"status": "ok", "deleted": len(to_delete)}


@router.delete("/{project_id}/tender-documents/{doc_id}")
def delete_tender_document(project_id: int, doc_id: int, actor_role: str = "Viewer", actor_email: str = "", db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    doc = db.get(models.TenderDocument, doc_id)
    if not doc or doc.project_id != project_id:
        raise HTTPException(404, "Document not found")
    if actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can delete files/folders")
    db.delete(doc)
    db.commit()
    return {"status": "ok"}


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
    db.query(models.TenderDocument).filter(models.TenderDocument.project_id == project_id).delete(synchronize_session=False)

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
            "created_at": p.created_at,  # item 145: lets the client compute the 24h hard-block deadline
        })
    return out


def _can_view_bid_value(db: Session, project: models.Project, actor_role: str, actor_email: str) -> bool:
    if rules.can_act(actor_role, actor_email, project.bid_manager):
        return True
    email = (actor_email or "").strip().lower()
    if not email:
        return False
    return db.query(models.BidValueAccessRequest).filter(
        models.BidValueAccessRequest.project_id == project.id,
        models.BidValueAccessRequest.requested_by_email.ilike(email),
        models.BidValueAccessRequest.status == "approved",
    ).first() is not None


# Static paths below must stay ahead of GET "/{project_id}" -- FastAPI/
# Starlette matches routes in registration order, and a bare "{project_id}"
# segment would otherwise swallow e.g. "bid-value-requests" as a literal
# (non-numeric) project_id and 422 before ever reaching the real handler.
# Same reasoning as deliverables.py's reassignment-requests/due-date-requests.
@router.get("/bid-value-requests")
def list_bid_value_requests(status: str = "pending", db: Session = Depends(get_db)):
    q = db.query(models.BidValueAccessRequest)
    if status:
        q = q.filter(models.BidValueAccessRequest.status == status)
    reqs = q.order_by(models.BidValueAccessRequest.requested_at.desc()).all()
    return [
        {
            "id": r.id, "project_id": r.project_id, "est_no": r.project.est_no, "name": r.project.name,
            "requested_by_email": r.requested_by_email, "requested_by_name": r.requested_by_name,
            "status": r.status, "requested_at": r.requested_at, "decided_at": r.decided_at,
        }
        for r in reqs
    ]


@router.post("/bid-value-requests/{request_id}/decide")
def decide_bid_value_request(request_id: int, decision: schemas.BidValueAccessDecision, db: Session = Depends(get_db)):
    req = db.get(models.BidValueAccessRequest, request_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(400, "This request has already been decided")
    if decision.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can decide a Bid Value access request")
    req.status = "approved" if decision.approved else "rejected"
    req.decided_at = datetime.utcnow()
    db.commit()
    announcements.bid_value_access_decision(db, req.project, req.requested_by_email, decision.approved)
    return {"status": "ok"}


@router.get("/{project_id}/bid-value")
def get_bid_value(project_id: int, actor_role: str = "Viewer", actor_email: str = "", db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    can_edit = rules.can_act(actor_role, actor_email, project.bid_manager)
    visible = can_edit or _can_view_bid_value(db, project, actor_role, actor_email)
    request_status = None
    if not visible and actor_email:
        existing = (
            db.query(models.BidValueAccessRequest)
            .filter(models.BidValueAccessRequest.project_id == project_id,
                    models.BidValueAccessRequest.requested_by_email.ilike(actor_email.strip()))
            .order_by(models.BidValueAccessRequest.requested_at.desc())
            .first()
        )
        request_status = existing.status if existing else None
    return {
        "visible": visible, "can_edit": can_edit, "bid_value": project.bid_value if visible else None,
        "has_value": project.bid_value is not None, "request_status": request_status,
    }


@router.patch("/{project_id}/bid-value", response_model=schemas.ProjectOut)
def update_bid_value(project_id: int, payload: schemas.BidValueUpdate, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project.stage != models.Stage.L1:
        raise HTTPException(400, "Bid Value only applies to L1 projects")
    if not rules.can_act(payload.actor_role, payload.actor_email, project.bid_manager):
        raise HTTPException(403, f"Only {project.bid_manager or 'the assigned Bid Manager'} or an Admin can edit the Bid Value")
    project.bid_value = payload.bid_value
    db.commit()
    db.refresh(project)
    return project


@router.post("/{project_id}/bid-value/request-access")
def request_bid_value_access(project_id: int, payload: schemas.BidValueAccessRequestCreate, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    email = payload.actor_email.strip()
    if not email:
        raise HTTPException(400, "Your email is required")
    if _can_view_bid_value(db, project, "Viewer", email):
        raise HTTPException(400, "You already have access")
    existing = (
        db.query(models.BidValueAccessRequest)
        .filter(models.BidValueAccessRequest.project_id == project_id,
                models.BidValueAccessRequest.requested_by_email.ilike(email),
                models.BidValueAccessRequest.status == "pending")
        .first()
    )
    if existing:
        raise HTTPException(400, "A request is already pending")
    req = models.BidValueAccessRequest(project_id=project_id, requested_by_email=email,
                                        requested_by_name=payload.actor_name.strip() or None)
    db.add(req)
    db.commit()
    db.refresh(req)
    announcements.bid_value_access_requested(db, project, rules.admin_emails(db), email, payload.actor_name.strip() or None)
    return {"status": "ok", "id": req.id}


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

    _auto_complete_2_3(db, project)

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
    if "rfx_number" in data:
        project.rfx_number = data["rfx_number"]
    if "region" in data:
        if not data["region"]:
            raise HTTPException(400, "Select at least one Region")
        project.region = data["region"]
    if "region_other" in data:
        project.region_other = data["region_other"]
    if "country" in data:
        project.country = data["country"]
    if "scope" in data or "business_units" in data or "scope_other" in data:
        real_subs = (
            db.query(models.DeliverableSubmission)
            .filter(models.DeliverableSubmission.project_id == project.id,
                    models.DeliverableSubmission.auto_completed.isnot(True))
            .all()
        )
        # PENDING_TRIAGE/NOT_REQUIRED are the normal starting state for a
        # freshly-created L0 project (before the BM's applicable/not-
        # required call) -- not real progress, so they don't block this.
        _SAFE_STATUSES = {models.SubmissionStatus.NO_PROGRESS, models.SubmissionStatus.PENDING_TRIAGE,
                           models.SubmissionStatus.NOT_REQUIRED}
        if any(s.status not in _SAFE_STATUSES for s in real_subs):
            raise HTTPException(400, "Scope/Business Unit can only be changed before this project has any real "
                                      "progress (an upload or a completion) — this project already has work started.")
        new_scope = data.get("scope", project.scope)
        if not new_scope:
            raise HTTPException(400, "Scope is required")
        new_scope_other = data.get("scope_other", project.scope_other)
        if "Other" in new_scope and not (new_scope_other or "").strip():
            raise HTTPException(400, "Specify the Other scope")

        if project.is_international:
            # [L0 International]: IBU is auto-assigned, not scope-derived --
            # a scope edit here must never silently strip it back out via
            # compute_business_units (which has no concept of IBU at all).
            chosen = [b for b in (data.get("business_units") or []) if b == "IBU"]
            new_bus = chosen or ["IBU"]
        else:
            computed_bus, needs_manual = rules.compute_business_units(new_scope)
            if needs_manual:
                chosen = [b for b in (data.get("business_units") or []) if b in ("TBU", "PBU", "DBU", "BBU", "TBA")]
                if not chosen:
                    raise HTTPException(400, "Business Unit is required for this scope (choose TBU/PBU/DBU/BBU, or TBA)")
                new_bus = chosen
            elif "business_units" in data:
                # A manual override even though scope alone would auto-classify --
                # the same correction escape hatch the create form offers.
                chosen = [b for b in (data.get("business_units") or []) if b in ("TBU", "PBU", "DBU", "BBU", "TBA")]
                new_bus = chosen or computed_bus
            else:
                new_bus = computed_bus

        # Nothing real exists on these rows (guaranteed by the No Progress
        # check above), so they're safe to drop and regenerate from the new
        # scope -- but a few tables reference them without an ORM cascade:
        # WorkflowHistory cascades via the relationship on delete, Documents
        # can't exist yet (only an upload creates one, which would have
        # already failed the check above), but Followers/ReassignmentRequests
        # don't cascade, and a reminder could have been sent on a still-No-
        # Progress item, leaving an Announcement pointing at it.
        real_sub_ids = [s.id for s in real_subs]
        if real_sub_ids:
            db.query(models.Follower).filter(models.Follower.submission_id.in_(real_sub_ids)) \
                .delete(synchronize_session=False)
            db.query(models.ReassignmentRequest).filter(models.ReassignmentRequest.submission_id.in_(real_sub_ids)) \
                .delete(synchronize_session=False)
            db.query(models.Announcement).filter(models.Announcement.submission_id.in_(real_sub_ids)) \
                .update({models.Announcement.submission_id: None}, synchronize_session=False)
            for s in real_subs:
                db.delete(s)
            db.commit()

        project.scope = new_scope
        project.scope_other = new_scope_other
        project.business_units = new_bus
        project.scope_contains_pbu = "PBU" in new_bus
        db.commit()
        _instantiate_deliverables(db, project)
    date_changed = False
    old_bsd = project.bsd
    for field in ("announcement_date", "site_visit_date", "pre_bid_meeting_date", "pre_bid_deadline", "bsd"):
        if field in data:
            setattr(project, field, data[field])
            date_changed = True
    db.commit()
    if date_changed:
        rules.recompute_project_due_dates(db, project, force=True)
        db.commit()
    if "bsd" in data and data["bsd"] and data["bsd"] != old_bsd:
        recipients = sorted({d.focal_point_email for d in db.query(models.Department).all() if d.focal_point_email} | rules.system_group_emails(db))
        announcements.deadline_extended(
            db, project, recipients,
            old_bsd.isoformat() if old_bsd else "not set", data["bsd"].isoformat(),
        )
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
            # [PO Lifecycle] names the specific line item (e.g. "GIS Unit")
            # for a fan-out submission -- several rows can otherwise share
            # one bare item_no/name and read as indistinguishable.
            "item_no": h.submission.definition.item_no, "name": rules.submission_display_name(h.submission),
        }
        for h in rows
    ]


@router.get("/{project_id}/deliverables", response_model=list[schemas.SubmissionOut])
def get_deliverables(project_id: int, department: str | None = None, include_auto_completed: bool = False,
                      db: Session = Depends(get_db)):
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
    )
    # items 115/116 exclude auto-completed rows (1.1 etc) from the normal
    # Deliverables list -- they're not real tracked work. [PO Lifecycle] needs
    # 1.1 itself though, since it's a causal-chain context card there (the
    # anchor everything else needs) -- include_auto_completed opts back in.
    if not include_auto_completed:
        q = q.filter(models.DeliverableSubmission.auto_completed.isnot(True))
    if department:
        q = q.filter(models.Department.name == department)
    subs = q.all()
    subs.sort(key=lambda s: (s.definition.department.number or 0, rules.item_sort_key(s.definition.item_no)))
    doc_counts = rules.document_counts(db, [s.id for s in subs])
    pending_kinds = rules.pending_due_date_request_kinds(db, [s.id for s in subs])
    out = []
    for s in subs:
        deadline_key, deadline_days = rules.deadline_status(s)
        points_earned = (
            rules.kpi_points(s.due_date, s.submitted_at.date() if s.submitted_at else None)
            if s.status == models.SubmissionStatus.APPROVED else None
        )
        out.append(schemas.SubmissionOut(
            id=s.id, item_no=s.definition.item_no, name=rules.display_name(s.definition, project),
            department=s.definition.department.name, due_date=s.due_date, status=s.status.value,
            applicability=s.applicability or "applicable",
            deadline_status=deadline_key, deadline_days=deadline_days, auto_completed=s.auto_completed,
            owner_emails=rules.resolve_owners(s),
            sme_emails=rules.resolve_smes(s),
            file_name=s.file_name, file_url=_storage.file_url(s.file_ref) if s.file_ref else None,
            submitted_at=s.submitted_at, review_comment=s.review_comment,
            completion_note=rules.mark_complete_note(s),
            is_milestone=s.definition.is_milestone, milestone_code=s.definition.milestone_code,
            doc_total=doc_counts.get(s.id, 0),
            awaiting_note=rules.awaiting_milestone_note(db, s),
            points_earned=points_earned,
            pending_due_date_request_kind=pending_kinds.get(s.id),
            po_line_item_id=s.po_line_item_id,
            line_item_name=s.po_line_item.name if s.po_line_item_id else None,
        ))
    db.commit()

    rules.check_l1_completion(db, project)
    db.commit()

    return out

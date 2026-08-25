from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, rules, announcements
from ..database import get_db

router = APIRouter(prefix="/api/departments", tags=["departments"])


class FocalPointUpdate(BaseModel):
    focal_point_name: str | None = None
    focal_point_email: str | None = None


@router.get("")
def list_departments(include_inactive: bool = False, db: Session = Depends(get_db)):
    q = db.query(models.Department)
    if not include_inactive:
        q = q.filter(models.Department.active.is_not(False))  # NULL (pre-migration rows) counts as active
    depts = q.order_by(models.Department.number).all()
    return [
        {"id": d.id, "name": d.name, "number": d.number, "focal_point_name": d.focal_point_name,
         "focal_point_email": d.focal_point_email, "order": d.order, "is_international": bool(d.is_international),
         "active": d.active is not False}
        for d in depts
    ]


@router.patch("/{department_id}/focal-point")
def update_focal_point(department_id: int, payload: FocalPointUpdate, db: Session = Depends(get_db)):
    dept = db.get(models.Department, department_id)
    if not dept:
        raise HTTPException(404, "Department not found")
    dept.focal_point_name = (payload.focal_point_name or "").strip() or None
    dept.focal_point_email = (payload.focal_point_email or "").strip() or None
    db.commit()
    return {"id": dept.id, "name": dept.name, "number": dept.number,
            "focal_point_name": dept.focal_point_name, "focal_point_email": dept.focal_point_email}


# ---------------------------------------------------------------------------
# Department CRUD (Deliverables Configuration) -- plain add/remove only, no
# BU/scope-conditional-visibility UI (a new department shows on every
# applicable project by default, matching the existing fail-open behavior
# rules.is_bu_applicable/is_scope_variant_applicable already give any
# department name they don't recognize).
# ---------------------------------------------------------------------------
def _dept_snapshot(d: "models.Department") -> dict:
    return {"name": d.name, "order": d.order, "number": d.number,
            "is_international": bool(d.is_international), "active": d.active is not False}


def _log_department_change(db: Session, dept: "models.Department", change_type: str,
                            before: dict | None, after: dict, actor_email: str | None,
                            actor_name: str | None, summary: str) -> None:
    db.add(models.DepartmentChangeLog(
        department_id=dept.id, actor_email=actor_email or None, actor_name=actor_name or None,
        change_type=change_type, before_snapshot=before, after_snapshot=after, summary=summary,
    ))


class DepartmentCreate(BaseModel):
    name: str
    order: int = 0
    number: int | None = None
    is_international: bool = False
    actor_role: str = "Admin"
    actor_email: str = ""
    actor_name: str = ""


@router.post("", status_code=201)
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db)):
    if payload.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can add a department")
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Name is required")
    if db.query(models.Department).filter(models.Department.name.ilike(name)).first():
        raise HTTPException(400, f"A department named '{name}' already exists")
    dept = models.Department(name=name, order=payload.order, number=payload.number,
                              is_international=payload.is_international, active=True)
    db.add(dept)
    db.flush()
    _log_department_change(db, dept, "created", None, _dept_snapshot(dept),
                            payload.actor_email, payload.actor_name, f"Created department '{name}'")
    db.commit()
    return _dept_snapshot(dept) | {"id": dept.id}


class DepartmentUpdate(BaseModel):
    name: str | None = None
    order: int | None = None
    number: int | None = None
    is_international: bool | None = None
    actor_role: str = "Admin"
    actor_email: str = ""
    actor_name: str = ""


@router.patch("/{department_id}")
def update_department(department_id: int, payload: DepartmentUpdate, db: Session = Depends(get_db)):
    if payload.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can edit a department")
    dept = db.get(models.Department, department_id)
    if not dept:
        raise HTTPException(404, "Department not found")
    before = _dept_snapshot(dept)
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(400, "Name is required")
        clash = db.query(models.Department).filter(
            models.Department.name.ilike(name), models.Department.id != department_id,
        ).first()
        if clash:
            raise HTTPException(400, f"A department named '{name}' already exists")
        dept.name = name
    if payload.order is not None:
        dept.order = payload.order
    if payload.number is not None:
        dept.number = payload.number
    if payload.is_international is not None:
        dept.is_international = payload.is_international
    after = _dept_snapshot(dept)
    if after != before:
        _log_department_change(db, dept, "edited", before, after,
                                payload.actor_email, payload.actor_name, f"Edited department '{dept.name}'")
    db.commit()
    return after | {"id": dept.id}


class DepartmentActorOnly(BaseModel):
    actor_role: str = "Admin"
    actor_email: str = ""
    actor_name: str = ""


@router.delete("/{department_id}")
def delete_department(department_id: int, payload: DepartmentActorOnly = DepartmentActorOnly(), db: Session = Depends(get_db)):
    """Soft-delete (mirrors remove_bid_manager's active=False convention) --
    a department already referenced by existing projects/definitions keeps
    its real name/history; this only removes it from admin CRUD dropdowns
    and cascade-deactivates its own DeliverableDefinitions (same pattern
    seed.py's old-Operation-Units backfill already uses) so new projects
    stop being offered deliverables under a department that's gone.
    """
    if payload.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can remove a department")
    dept = db.get(models.Department, department_id)
    if not dept:
        raise HTTPException(404, "Department not found")
    before = _dept_snapshot(dept)
    dept.active = False
    deactivated = (
        db.query(models.DeliverableDefinition)
        .filter(models.DeliverableDefinition.department_id == department_id,
                models.DeliverableDefinition.active == True)  # noqa: E712
        .update({"active": False})
    )
    _log_department_change(db, dept, "deactivated", before, _dept_snapshot(dept),
                            payload.actor_email, payload.actor_name,
                            f"Removed department '{dept.name}'" + (f" ({deactivated} deliverable(s) deactivated with it)" if deactivated else ""))
    db.commit()
    return {"id": dept.id, "active": False, "deliverables_deactivated": deactivated}


@router.get("/change-history")
def list_department_change_history(department_id: int | None = None, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(models.DepartmentChangeLog).order_by(models.DepartmentChangeLog.changed_at.desc())
    if department_id is not None:
        q = q.filter(models.DepartmentChangeLog.department_id == department_id)
    rows = q.limit(limit).all()
    return [
        {"id": r.id, "department_id": r.department_id,
         "department_name": r.department.name if r.department else None,
         "changed_at": r.changed_at, "actor_email": r.actor_email, "actor_name": r.actor_name,
         "change_type": r.change_type, "summary": r.summary}
        for r in rows
    ]


@router.post("/change-history/{log_id}/revert")
def revert_department_change(log_id: int, payload: DepartmentActorOnly, db: Session = Depends(get_db)):
    if payload.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can revert a change")
    log = db.get(models.DepartmentChangeLog, log_id)
    if not log or not log.before_snapshot:
        raise HTTPException(404, "Change not found or has nothing to revert to")
    dept = db.get(models.Department, log.department_id)
    if not dept:
        raise HTTPException(404, "Department not found")
    before = _dept_snapshot(dept)
    snap = log.before_snapshot
    dept.name = snap["name"]
    dept.order = snap["order"]
    dept.number = snap["number"]
    dept.is_international = snap["is_international"]
    dept.active = snap["active"]
    _log_department_change(db, dept, "edited", before, _dept_snapshot(dept),
                            payload.actor_email, payload.actor_name, f"Reverted department '{dept.name}' to an earlier version")
    db.commit()
    return _dept_snapshot(dept) | {"id": dept.id}


@router.get("/options")
def get_create_options(db: Session = Depends(get_db)):
    """Reference lists for the Create L0/L1 form dropdowns."""
    bms = db.query(models.BidManager).filter(models.BidManager.active == True).all()  # noqa: E712
    return {
        "bid_managers": sorted([b.email for b in bms], key=str.lower),
        "regions": models.REGION_OPTIONS,
        "scopes": models.SCOPE_OPTIONS,
        "bu_uncovered_scopes": rules.BU_UNCOVERED_SCOPES,
        "business_units": ["TBU", "PBU", "DBU", "BBU", "TBA"],
    }


# ---------------------------------------------------------------------------
# Per-deliverable focal points (item 75) — the item-level override sitting
# above each department's own focal_point_email.
# ---------------------------------------------------------------------------
@router.get("/deliverable-focal")
def list_deliverable_focal(stage: str, international: bool = False, db: Session = Depends(get_db)):
    defs = (
        db.query(models.DeliverableDefinition)
        .join(models.Department)
        .filter(models.DeliverableDefinition.stage == stage, models.DeliverableDefinition.active == True,  # noqa: E712
                models.Department.is_international == international)
        .order_by(models.Department.number)
        .all()
    )
    defs.sort(key=lambda d: (d.department.number or 0, rules.item_sort_key(d.item_no)))
    return [
        {
            "id": d.id, "item_no": d.item_no, "name": d.name,
            "department": d.department.name, "department_number": d.department.number,
            # The "Deliverable's Owner Email" column edits actual ownership
            # (default_owner_emails) now, not the old notify-only focal
            # point concept -- department_focal_email is kept only as a
            # placeholder hint (there's nothing item-level to fall back to
            # for ownership the way there was for a focal contact).
            "owner_emails": d.default_owner_emails or ([d.default_owner_email] if d.default_owner_email else []),
            "department_focal_email": d.department.focal_point_email,
            "default_sme_emails": d.default_sme_emails or ([d.default_sme_email] if d.default_sme_email else []),
            # [L0 International]: "Tendering Department (International)" gets
            # the same BM-owns-it treatment as the standard department.
            "is_tendering_bm": d.department.name.startswith("Tendering Department"),
        }
        for d in defs
    ]


class DeliverableFocalUpdate(BaseModel):
    # Item [multi-SME/owner]: both fields are roster-only, multi-value picks
    # from the L0-L1 Group -- free text is no longer accepted here, every
    # email must match a real roster member (Owner role for the owner
    # field, SME role for the SME field) so the picker's suggestions are
    # always exactly what's allowed.
    default_owner_emails: list[str] = []
    default_sme_emails: list[str] = []


def _validate_roster_emails(db: Session, emails: list[str], require_role: str | None = None) -> list[str]:
    cleaned = [e.strip() for e in emails if e and e.strip()]
    if not cleaned:
        return []
    roster = {u.email.strip().lower(): u for u in db.query(models.User).all()}
    resolved = []
    for e in cleaned:
        u = roster.get(e.lower())
        if not u:
            raise HTTPException(400, f"{e} isn't in the L0-L1 Group roster (Focal Points &#8594; L0-L1 Group)")
        if require_role and u.role != require_role:
            raise HTTPException(400, f"{e} is a {u.role}, not a {require_role}")
        resolved.append(u.email)
    return resolved


@router.patch("/deliverable-focal/{definition_id}")
def update_deliverable_focal(definition_id: int, payload: DeliverableFocalUpdate, db: Session = Depends(get_db)):
    d = db.get(models.DeliverableDefinition, definition_id)
    if not d:
        raise HTTPException(404, "Deliverable definition not found")
    if not d.department.name.startswith("Tendering Department"):
        # Tendering Department's Owner is always that project's own Bid
        # Manager — not editable here, but its SME still is (below,
        # unconditional). Prefix match also covers "Tendering Department
        # (International)" -- [L0 International].
        d.default_owner_emails = _validate_roster_emails(db, payload.default_owner_emails, require_role="Owner") or None
    d.default_sme_emails = _validate_roster_emails(db, payload.default_sme_emails, require_role="SME") or None
    # A catalog default only feeds *new* submissions by itself -- without
    # this, changing it here would do nothing for every project that
    # already exists, which is most of them in practice. Safe to push onto
    # an existing submission only if nothing real has happened on it yet
    # (same safety gate item 46's Scope/BU resync uses) -- once someone's
    # actually uploaded or it's mid-review, changing who's responsible has
    # to go through Reassign / the SME's own action instead.
    _SAFE_STATUSES = {models.SubmissionStatus.NO_PROGRESS, models.SubmissionStatus.PENDING_TRIAGE,
                       models.SubmissionStatus.NOT_REQUIRED}
    untouched = (
        db.query(models.DeliverableSubmission)
        .filter(models.DeliverableSubmission.deliverable_definition_id == d.id,
                models.DeliverableSubmission.status.in_(_SAFE_STATUSES))
        .all()
    )
    for s in untouched:
        if not d.department.name.startswith("Tendering Department"):
            s.owner_emails = d.default_owner_emails
        s.sme_emails = d.default_sme_emails
    db.commit()
    return {
        "id": d.id, "owner_emails": d.default_owner_emails or [],
        "default_sme_emails": d.default_sme_emails or [],
        "resynced_submissions": len(untouched),
    }


# ---------------------------------------------------------------------------
# Performance tracking triage (item 117) — an admin call on whether a given
# catalog item should count toward on-time-rate / performance stats at all.
# Reuses the pre-existing (previously unwired) kpi_relevant column. NULL is
# treated the same as True (counts) so the mtime-only ALTER TABLE migration
# never silently drops every pre-existing item out of performance the
# moment this column first appears on a live database.
# ---------------------------------------------------------------------------
@router.get("/performance-triage")
def list_performance_triage(stage: str, international: bool = False, db: Session = Depends(get_db)):
    defs = (
        db.query(models.DeliverableDefinition)
        .join(models.Department)
        .filter(models.DeliverableDefinition.stage == stage, models.DeliverableDefinition.active == True,  # noqa: E712
                models.Department.is_international == international)
        .order_by(models.Department.number)
        .all()
    )
    defs.sort(key=lambda d: (d.department.number or 0, rules.item_sort_key(d.item_no)))
    return [
        {
            "id": d.id, "item_no": d.item_no, "name": d.name,
            "department": d.department.name, "department_number": d.department.number,
            "is_milestone": d.is_milestone,
            "kpi_relevant": d.kpi_relevant is not False,
        }
        for d in defs
    ]


class PerformanceTriageUpdate(BaseModel):
    kpi_relevant: bool


@router.patch("/performance-triage/{definition_id}")
def update_performance_triage(definition_id: int, payload: PerformanceTriageUpdate, db: Session = Depends(get_db)):
    d = db.get(models.DeliverableDefinition, definition_id)
    if not d:
        raise HTTPException(404, "Deliverable definition not found")
    d.kpi_relevant = payload.kpi_relevant
    db.commit()
    return {"id": d.id, "kpi_relevant": d.kpi_relevant is not False}


# ---------------------------------------------------------------------------
# Bid Manager roster (item 75) — replaces the old hardcoded BID_MANAGERS list.
# ---------------------------------------------------------------------------
@router.get("/bid-managers")
def list_bid_managers(db: Session = Depends(get_db)):
    bms = db.query(models.BidManager).order_by(models.BidManager.email).all()
    return [{"id": b.id, "email": b.email, "name": b.name, "active": b.active} for b in bms]


class BidManagerCreate(BaseModel):
    email: str
    name: str | None = None


@router.post("/bid-managers")
def add_bid_manager(payload: BidManagerCreate, db: Session = Depends(get_db)):
    email = payload.email.strip()
    if not email:
        raise HTTPException(400, "Email is required")
    existing = db.query(models.BidManager).filter(models.BidManager.email.ilike(email)).first()
    if existing:
        existing.active = True
        existing.name = (payload.name or "").strip() or existing.name
        db.commit()
        return {"id": existing.id, "email": existing.email, "name": existing.name, "active": existing.active}
    bm = models.BidManager(email=email, name=(payload.name or "").strip() or None)
    db.add(bm)
    db.commit()
    return {"id": bm.id, "email": bm.email, "name": bm.name, "active": bm.active}


class BidManagerNameUpdate(BaseModel):
    name: str | None = None


@router.patch("/bid-managers/{bid_manager_id}")
def update_bid_manager_name(bid_manager_id: int, payload: BidManagerNameUpdate, db: Session = Depends(get_db)):
    """Item 102 — the Name column in the Bid Managers sub-tab is editable."""
    bm = db.get(models.BidManager, bid_manager_id)
    if not bm:
        raise HTTPException(404, "Bid Manager not found")
    bm.name = (payload.name or "").strip() or None
    db.commit()
    return {"id": bm.id, "email": bm.email, "name": bm.name, "active": bm.active}


@router.delete("/bid-managers/{bid_manager_id}")
def remove_bid_manager(bid_manager_id: int, db: Session = Depends(get_db)):
    """Deactivates rather than deletes — a project already assigned to this
    Bid Manager keeps the plain-text name/email it stored at the time; this
    only removes them from the dropdown offered to new/edited projects.
    """
    bm = db.get(models.BidManager, bid_manager_id)
    if not bm:
        raise HTTPException(404, "Bid Manager not found")
    bm.active = False
    db.commit()
    return {"id": bm.id, "active": bm.active}


# ---------------------------------------------------------------------------
# System roster / "L0-L1 Group" (item 75) — every email with a stake in the
# portal, admin-managed. Admin/Owner/SME are the roles with real actions
# assigned elsewhere in the app; "Viewer" (the default) is everyone who just
# wants visibility into the portal's information with nothing actioned to them.
# ---------------------------------------------------------------------------
def _serialize_user(u: models.User) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "manager_email": u.manager_email}


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    users = db.query(models.User).order_by(models.User.role, models.User.name).all()
    return [_serialize_user(u) for u in users]


class UserCreate(BaseModel):
    name: str
    email: str
    role: str = "Viewer"
    manager_email: str | None = None


_USER_ROLES = {"Admin", "Owner", "SME", "Viewer"}


@router.post("/users")
def add_user(payload: UserCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    email = payload.email.strip()
    role = payload.role.strip() if payload.role else "Viewer"
    manager_email = (payload.manager_email or "").strip() or None
    if not name or not email:
        raise HTTPException(400, "Name and email are required")
    if role not in _USER_ROLES:
        raise HTTPException(400, f"Role must be one of: {', '.join(sorted(_USER_ROLES))}")
    existing = db.query(models.User).filter(models.User.email.ilike(email)).first()
    if existing:
        existing.name = name
        existing.role = role
        existing.manager_email = manager_email
        db.commit()
        return _serialize_user(existing)
    user = models.User(name=name, email=email, role=role, manager_email=manager_email)
    db.add(user)
    db.commit()
    return _serialize_user(user)


@router.delete("/users/{user_id}")
def remove_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    db.delete(user)
    db.commit()
    return {"deleted": user_id}


# ---------------------------------------------------------------------------
# SME self-nomination -- a user already in the L0-L1 Group roster picks one
# or more catalog items they see themselves fit to be SME for; admin
# approves/rejects each item individually (mirrors ReassignmentRequest/
# DueDateRequest's request-then-decide shape, one row per picked item
# instead of one row per submission click). Approving grants User.role=SME
# (if not already) and adds the nominee to that specific item's
# default_sme_emails -- a nomination alone never changes anything by itself.
# ---------------------------------------------------------------------------
def _serialize_nomination(n: models.SmeNomination) -> dict:
    d = n.definition
    return {
        "id": n.id, "email": n.email, "name": n.name, "status": n.status,
        "stage": d.stage.value if d else None, "item_no": d.item_no if d else None,
        "item_name": d.name if d else None,
        "department": d.department.name if d else None, "department_number": d.department.number if d else None,
        "requested_at": n.requested_at, "decided_at": n.decided_at,
        "decided_by_email": n.decided_by_email, "decision_comment": n.decision_comment,
    }


class SmeNominationCreate(BaseModel):
    email: str
    name: str | None = None
    definition_ids: list[int] = []


@router.post("/sme-nominations")
def create_sme_nomination(payload: SmeNominationCreate, db: Session = Depends(get_db)):
    email = payload.email.strip()
    if not email:
        raise HTTPException(400, "Email is required")
    if not payload.definition_ids:
        raise HTTPException(400, "Pick at least one item")
    user = db.query(models.User).filter(models.User.email.ilike(email)).first()
    if not user:
        raise HTTPException(400, "You need to be added to the L0-L1 Group first (Focal Points → L0-L1 Group)")

    created: list[models.SmeNomination] = []
    for def_id in payload.definition_ids:
        d = db.get(models.DeliverableDefinition, def_id)
        if not d:
            continue
        already_sme = email.lower() in [e.lower() for e in (d.default_sme_emails or [])]
        already_pending = db.query(models.SmeNomination).filter(
            models.SmeNomination.email.ilike(email),
            models.SmeNomination.deliverable_definition_id == def_id,
            models.SmeNomination.status == "pending",
        ).first()
        if already_sme or already_pending:
            continue
        created.append(models.SmeNomination(
            email=email, name=(payload.name or user.name or "").strip() or None, deliverable_definition_id=def_id,
        ))
    db.add_all(created)
    db.commit()

    if created:
        announcements.sme_nomination_requested(db, sorted(rules.admin_emails(db)), email, payload.name or user.name, len(created))
    return {"created": len(created), "skipped": len(payload.definition_ids) - len(created)}


@router.get("/sme-nominations")
def list_sme_nominations(status: str | None = None, db: Session = Depends(get_db)):
    q = (
        db.query(models.SmeNomination)
        .join(models.DeliverableDefinition)
        .join(models.Department)
        .order_by(models.SmeNomination.requested_at.desc())
    )
    if status:
        q = q.filter(models.SmeNomination.status == status)
    return [_serialize_nomination(n) for n in q.all()]


class SmeNominationDecision(BaseModel):
    approved: bool
    comment: str = ""
    actor_role: str = "Admin"
    actor_email: str = ""


@router.post("/sme-nominations/{nomination_id}/decide")
def decide_sme_nomination(nomination_id: int, payload: SmeNominationDecision, db: Session = Depends(get_db)):
    if payload.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can decide an SME nomination")
    nom = db.get(models.SmeNomination, nomination_id)
    if not nom:
        raise HTTPException(404, "Nomination not found")
    if nom.status != "pending":
        raise HTTPException(400, "This nomination has already been decided")

    d = nom.definition
    if payload.approved:
        user = db.query(models.User).filter(models.User.email.ilike(nom.email)).first()
        if user:
            user.role = "SME"
            if nom.name and not user.name:
                user.name = nom.name
        else:
            user = models.User(name=nom.name or nom.email, email=nom.email, role="SME")
            db.add(user)
            db.flush()

        current_defaults = d.default_sme_emails or []
        if user.email.lower() not in [e.lower() for e in current_defaults]:
            d.default_sme_emails = current_defaults + [user.email]

        # Same safety gate item 46's Scope/BU resync and update_deliverable_focal
        # above already use -- only pushed onto a submission that hasn't had
        # any real progress yet; once someone's uploaded or it's mid-review,
        # changing who's responsible has to go through Reassign instead.
        _SAFE_STATUSES = {models.SubmissionStatus.NO_PROGRESS, models.SubmissionStatus.PENDING_TRIAGE,
                           models.SubmissionStatus.NOT_REQUIRED}
        untouched = (
            db.query(models.DeliverableSubmission)
            .filter(models.DeliverableSubmission.deliverable_definition_id == d.id,
                    models.DeliverableSubmission.status.in_(_SAFE_STATUSES))
            .all()
        )
        for s in untouched:
            existing = s.sme_emails or []
            if user.email.lower() not in [e.lower() for e in existing]:
                s.sme_emails = existing + [user.email]

    nom.status = "approved" if payload.approved else "rejected"
    nom.decided_at = datetime.utcnow()
    nom.decided_by_email = payload.actor_email or None
    nom.decision_comment = payload.comment or None
    db.commit()

    announcements.sme_nomination_decision(db, nom.email, d.item_no, d.name, payload.approved, payload.comment)
    return _serialize_nomination(nom)


# ---------------------------------------------------------------------------
# Group Add Requests -- anyone already in the L0-L1 Group roster can request
# that a new email be added to it; an Admin approves/rejects before the
# email becomes a real roster member (mirrors SmeNomination's request-then-
# decide shape one row above, just targeting the roster itself instead of a
# specific catalog item).
# ---------------------------------------------------------------------------
_GROUP_REQUEST_ROLES = {"Owner", "SME", "Viewer"}  # Admin is never self-service


def _serialize_user_add_request(r: models.UserAddRequest) -> dict:
    return {
        "id": r.id, "email": r.email, "name": r.name, "role": r.role,
        "requested_by_email": r.requested_by_email, "requested_by_name": r.requested_by_name,
        "status": r.status, "requested_at": r.requested_at, "decided_at": r.decided_at,
        "decided_by_email": r.decided_by_email, "decision_comment": r.decision_comment,
    }


class UserAddRequestCreate(BaseModel):
    email: str
    name: str | None = None
    role: str = "Viewer"
    requested_by_email: str


@router.post("/user-add-requests")
def create_user_add_request(payload: UserAddRequestCreate, db: Session = Depends(get_db)):
    email = payload.email.strip()
    requested_by_email = payload.requested_by_email.strip()
    role = (payload.role or "Viewer").strip()
    if not email or not requested_by_email:
        raise HTTPException(400, "Email is required")
    if role not in _GROUP_REQUEST_ROLES:
        raise HTTPException(400, f"Role must be one of: {', '.join(sorted(_GROUP_REQUEST_ROLES))}")
    requester = db.query(models.User).filter(models.User.email.ilike(requested_by_email)).first()
    if not requester:
        raise HTTPException(400, "You need to be in the L0-L1 Group yourself to invite someone")
    if db.query(models.User).filter(models.User.email.ilike(email)).first():
        raise HTTPException(400, f"{email} is already in the L0-L1 Group")
    already_pending = db.query(models.UserAddRequest).filter(
        models.UserAddRequest.email.ilike(email), models.UserAddRequest.status == "pending",
    ).first()
    if already_pending:
        raise HTTPException(400, f"{email} already has a pending request")
    req = models.UserAddRequest(
        email=email, name=(payload.name or "").strip() or None, role=role,
        requested_by_email=requester.email, requested_by_name=requester.name,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    announcements.user_add_requested(db, sorted(rules.admin_emails(db)), req.email, req.name,
                                      requester.email, requester.name)
    return _serialize_user_add_request(req)


@router.get("/user-add-requests")
def list_user_add_requests(status: str | None = "pending", db: Session = Depends(get_db)):
    q = db.query(models.UserAddRequest).order_by(models.UserAddRequest.requested_at.desc())
    if status:
        q = q.filter(models.UserAddRequest.status == status)
    return [_serialize_user_add_request(r) for r in q.all()]


class UserAddRequestDecision(BaseModel):
    approved: bool
    comment: str = ""
    actor_role: str = "Admin"
    actor_email: str = ""


@router.post("/user-add-requests/{request_id}/decide")
def decide_user_add_request(request_id: int, payload: UserAddRequestDecision, db: Session = Depends(get_db)):
    if payload.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can decide a group add request")
    req = db.get(models.UserAddRequest, request_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(400, "This request has already been decided")
    if payload.approved:
        existing = db.query(models.User).filter(models.User.email.ilike(req.email)).first()
        if not existing:
            db.add(models.User(name=req.name or req.email, email=req.email, role=req.role))
    req.status = "approved" if payload.approved else "rejected"
    req.decided_at = datetime.utcnow()
    req.decided_by_email = payload.actor_email or None
    req.decision_comment = payload.comment or None
    db.commit()

    announcements.user_add_decision(db, req.requested_by_email, req.email, payload.approved, payload.comment)
    return _serialize_user_add_request(req)

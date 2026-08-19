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
def list_departments(db: Session = Depends(get_db)):
    depts = db.query(models.Department).order_by(models.Department.number).all()
    return [
        {"id": d.id, "name": d.name, "number": d.number, "focal_point_name": d.focal_point_name, "focal_point_email": d.focal_point_email}
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
def list_deliverable_focal(stage: str, db: Session = Depends(get_db)):
    defs = (
        db.query(models.DeliverableDefinition)
        .join(models.Department)
        .filter(models.DeliverableDefinition.stage == stage, models.DeliverableDefinition.active == True)  # noqa: E712
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
            "is_tendering_bm": d.department.name == "Tendering Department",
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
    if d.department.name != "Tendering Department":
        # Tendering Department's Owner is always that project's own Bid
        # Manager — not editable here, but its SME still is (below,
        # unconditional).
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
        if d.department.name != "Tendering Department":
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
def list_performance_triage(stage: str, db: Session = Depends(get_db)):
    defs = (
        db.query(models.DeliverableDefinition)
        .join(models.Department)
        .filter(models.DeliverableDefinition.stage == stage, models.DeliverableDefinition.active == True)  # noqa: E712
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
# SME self-nomination -- any user can request to become an SME; admin
# approval actually flips the roster role (mirrors ReassignmentRequest/
# DueDateRequest's request-then-decide shape, just not tied to a project).
# ---------------------------------------------------------------------------
def _serialize_nomination(n: models.SmeNomination) -> dict:
    return {
        "id": n.id, "email": n.email, "name": n.name, "reason": n.reason, "status": n.status,
        "requested_at": n.requested_at, "decided_at": n.decided_at,
        "decided_by_email": n.decided_by_email, "decision_comment": n.decision_comment,
    }


class SmeNominationCreate(BaseModel):
    email: str
    name: str | None = None
    reason: str | None = None


@router.post("/sme-nominations")
def create_sme_nomination(payload: SmeNominationCreate, db: Session = Depends(get_db)):
    email = payload.email.strip()
    if not email:
        raise HTTPException(400, "Email is required")
    existing_user = db.query(models.User).filter(models.User.email.ilike(email)).first()
    if existing_user and existing_user.role == "SME":
        raise HTTPException(400, "This email is already an SME")
    if db.query(models.SmeNomination).filter(
        models.SmeNomination.email.ilike(email), models.SmeNomination.status == "pending",
    ).first():
        raise HTTPException(400, "A nomination for this email is already pending")
    nom = models.SmeNomination(
        email=email, name=(payload.name or "").strip() or None, reason=(payload.reason or "").strip() or None,
    )
    db.add(nom)
    db.commit()
    db.refresh(nom)
    announcements.sme_nomination_requested(db, sorted(rules.admin_emails(db)), nom.email, nom.name, nom.reason)
    return _serialize_nomination(nom)


@router.get("/sme-nominations")
def list_sme_nominations(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(models.SmeNomination).order_by(models.SmeNomination.requested_at.desc())
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

    if payload.approved:
        user = db.query(models.User).filter(models.User.email.ilike(nom.email)).first()
        if user:
            user.role = "SME"
            if nom.name and not user.name:
                user.name = nom.name
        else:
            db.add(models.User(name=nom.name or nom.email, email=nom.email, role="SME"))

    nom.status = "approved" if payload.approved else "rejected"
    nom.decided_at = datetime.utcnow()
    nom.decided_by_email = payload.actor_email or None
    nom.decision_comment = payload.comment or None
    db.commit()

    announcements.sme_nomination_decision(db, nom.email, payload.approved, payload.comment)
    return _serialize_nomination(nom)

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, rules
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
            "focal_point_name": d.focal_point_name, "focal_point_email": d.focal_point_email,
            "department_focal_name": d.department.focal_point_name, "department_focal_email": d.department.focal_point_email,
            "is_tendering_bm": d.department.name == "Tendering Department",
        }
        for d in defs
    ]


class DeliverableFocalUpdate(BaseModel):
    focal_point_name: str | None = None
    focal_point_email: str | None = None


@router.patch("/deliverable-focal/{definition_id}")
def update_deliverable_focal(definition_id: int, payload: DeliverableFocalUpdate, db: Session = Depends(get_db)):
    d = db.get(models.DeliverableDefinition, definition_id)
    if not d:
        raise HTTPException(404, "Deliverable definition not found")
    if d.department.name == "Tendering Department":
        raise HTTPException(400, "Tendering Department's focal point is always that project's own Bid Manager — manage the Bid Manager roster instead")
    d.focal_point_name = (payload.focal_point_name or "").strip() or None
    d.focal_point_email = (payload.focal_point_email or "").strip() or None
    db.commit()
    return {"id": d.id, "focal_point_name": d.focal_point_name, "focal_point_email": d.focal_point_email}


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
@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    users = db.query(models.User).order_by(models.User.role, models.User.name).all()
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role} for u in users]


class UserCreate(BaseModel):
    name: str
    email: str
    role: str = "Viewer"


_USER_ROLES = {"Admin", "Owner", "SME", "Viewer"}


@router.post("/users")
def add_user(payload: UserCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    email = payload.email.strip()
    role = payload.role.strip() if payload.role else "Viewer"
    if not name or not email:
        raise HTTPException(400, "Name and email are required")
    if role not in _USER_ROLES:
        raise HTTPException(400, f"Role must be one of: {', '.join(sorted(_USER_ROLES))}")
    existing = db.query(models.User).filter(models.User.email.ilike(email)).first()
    if existing:
        existing.name = name
        existing.role = role
        db.commit()
        return {"id": existing.id, "name": existing.name, "email": existing.email, "role": existing.role}
    user = models.User(name=name, email=email, role=role)
    db.add(user)
    db.commit()
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


@router.delete("/users/{user_id}")
def remove_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    db.delete(user)
    db.commit()
    return {"deleted": user_id}

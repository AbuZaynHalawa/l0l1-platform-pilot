"""Deliverables Configuration -- admin CRUD over DeliverableDefinition
formulas/descriptions/branches, restore-to-default, change history + revert,
and the Owner/SME "suggest a formula change" request-then-decide flow. See
models.py's DeliverableFormulaBranch/DeliverableDefinitionChangeLog/
FormulaChangeRequest docstrings and rules.compute_due_date for the engine
this configures.

Route prefix stays /api/deliverables (the same domain deliverables.py's own
router already owns), but every route here has at least two path segments
after that prefix (admin/..., config/...) so none of them can ever collide
with deliverables.py's single-segment /{submission_id}-shaped routes,
regardless of router registration order in main.py.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, rules, announcements
from ..database import get_db

router = APIRouter(prefix="/api/deliverables", tags=["deliverables-config"])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _branch_out(b: "models.DeliverableFormulaBranch") -> dict:
    return {
        "id": b.id, "branch_order": b.branch_order, "condition_type": b.condition_type,
        "condition_value": b.condition_value, "anchor_type": b.anchor_type,
        "predecessor_item_no": b.predecessor_item_no, "offset_days": b.offset_days,
        "offset_direction": b.offset_direction, "workday_duration": bool(b.workday_duration),
        "tie_break": b.tie_break, "active": b.active,
    }


def _definition_snapshot(d: "models.DeliverableDefinition") -> dict:
    return {
        "item_no": d.item_no, "name": d.name, "short_name": d.short_name,
        "department_id": d.department_id, "deliverable_type": d.deliverable_type,
        "is_milestone": d.is_milestone, "milestone_code": d.milestone_code,
        "active": d.active,
        "branches": [_branch_out(b) for b in sorted(d.branches, key=lambda b: b.branch_order)],
    }


def _definition_out(d: "models.DeliverableDefinition") -> dict:
    return _definition_snapshot(d) | {
        "id": d.id, "stage": d.stage.value, "department": d.department.name,
        "department_number": d.department.number, "is_international": bool(d.department.is_international),
        "is_customized": bool(d.is_customized), "can_restore": bool(d.seed_key),
        "formula_text": rules.describe_formula_branches(d),
    }


class BranchIn(BaseModel):
    branch_order: int = 0
    condition_type: str = "always"
    condition_value: int | None = None
    anchor_type: str
    predecessor_item_no: str | None = None
    offset_days: int = 0
    offset_direction: str = "after"
    workday_duration: bool = False
    tie_break: str | None = None


_VALID_CONDITION_TYPES = {"always", "scope_contains_pbu", "site_visit_unset", "tender_window_lt_days"}
_VALID_ANCHOR_TYPES = {"announcement", "bsd", "site_visit", "pre_bid", "predecessor"}
_VALID_TIE_BREAKS = {"earliest_of_siblings", "latest_of_siblings"}


def _validate_branches(branches: list[BranchIn]) -> None:
    if not branches:
        raise HTTPException(400, "At least one branch is required (or leave the item as on-request/library instead)")
    orders = [b.branch_order for b in branches]
    if len(orders) != len(set(orders)):
        raise HTTPException(400, "Branch order values must be unique")
    for b in branches:
        if b.condition_type not in _VALID_CONDITION_TYPES:
            raise HTTPException(400, f"Unknown condition type: {b.condition_type}")
        if b.condition_type == "tender_window_lt_days" and not b.condition_value:
            raise HTTPException(400, "tender_window_lt_days needs a day count")
        if b.anchor_type not in _VALID_ANCHOR_TYPES:
            raise HTTPException(400, f"Unknown anchor type: {b.anchor_type}")
        if b.anchor_type == "predecessor" and not (b.predecessor_item_no or "").strip():
            raise HTTPException(400, "A predecessor item number is required for anchor type 'predecessor'")
        if b.offset_direction not in ("after", "before"):
            raise HTTPException(400, "offset_direction must be 'after' or 'before'")
        if b.tie_break and b.tie_break not in _VALID_TIE_BREAKS:
            raise HTTPException(400, f"Unknown tie_break: {b.tie_break}")
    has_conditional = any(b.condition_type != "always" for b in branches)
    if has_conditional and not any(b.condition_type == "always" for b in branches):
        raise HTTPException(400, "A conditional branch set needs a trailing 'always' branch as the fallback")


def _apply_branches(db: Session, definition: "models.DeliverableDefinition", branches: list[BranchIn]) -> None:
    """Replaces the full branch set and syncs the mirror columns -- the one
    code path used by both the admin's direct PUT .../branches endpoint and
    an approved formula-change suggestion, so they can never drift apart.
    """
    for old in list(definition.branches):
        db.delete(old)
    db.flush()
    for b in branches:
        db.add(models.DeliverableFormulaBranch(
            deliverable_definition_id=definition.id, branch_order=b.branch_order,
            condition_type=b.condition_type, condition_value=b.condition_value,
            anchor_type=b.anchor_type, predecessor_item_no=(b.predecessor_item_no or "").strip() or None,
            offset_days=b.offset_days, offset_direction=b.offset_direction,
            workday_duration=b.workday_duration, tie_break=b.tie_break, active=True,
        ))
    db.flush()
    db.refresh(definition)
    rules.sync_definition_mirror_columns(definition)


def _force_recompute_affected(db: Session, definition_id: int) -> int:
    """Recomputes every project with a submission against this definition,
    bypassing the once-a-day gate -- same pattern seed.py's own due-date-fix
    migrations already use.
    """
    projects = {
        s.project for s in db.query(models.DeliverableSubmission)
        .filter(models.DeliverableSubmission.deliverable_definition_id == definition_id)
        .all()
    }
    for proj in projects:
        rules.recompute_project_due_dates(db, proj, force=True)
    if projects:
        db.commit()
    return len(projects)


def _log_definition_change(db: Session, definition: "models.DeliverableDefinition", source: str, change_type: str,
                            before: dict | None, after: dict, actor_email: str | None, actor_name: str | None,
                            summary: str, origin_request_id: int | None = None) -> "models.DeliverableDefinitionChangeLog":
    log = models.DeliverableDefinitionChangeLog(
        deliverable_definition_id=definition.id, actor_email=actor_email or None, actor_name=actor_name or None,
        source=source, change_type=change_type, before_snapshot=before, after_snapshot=after,
        summary=summary, origin_request_id=origin_request_id,
    )
    db.add(log)
    db.flush()
    return log


def _require_admin(actor_role: str, action: str) -> None:
    if actor_role != "Admin":
        raise HTTPException(403, f"Only an Admin can {action}")


# ---------------------------------------------------------------------------
# Admin: DeliverableDefinition CRUD
# ---------------------------------------------------------------------------
@router.get("/admin/definitions")
def list_admin_definitions(stage: str | None = None, international: bool | None = None,
                            department_id: int | None = None, include_inactive: bool = False,
                            db: Session = Depends(get_db)):
    q = db.query(models.DeliverableDefinition).join(models.Department)
    if stage:
        q = q.filter(models.DeliverableDefinition.stage == stage)
    if international is not None:
        q = q.filter(models.Department.is_international == international)
    if department_id is not None:
        q = q.filter(models.DeliverableDefinition.department_id == department_id)
    if not include_inactive:
        q = q.filter(models.DeliverableDefinition.active == True)  # noqa: E712
    defs = q.order_by(models.Department.number, models.DeliverableDefinition.item_no).all()
    return [_definition_out(d) for d in defs]


@router.get("/admin/definitions/{definition_id}")
def get_admin_definition(definition_id: int, db: Session = Depends(get_db)):
    d = db.get(models.DeliverableDefinition, definition_id)
    if not d:
        raise HTTPException(404, "Deliverable not found")
    return _definition_out(d)


class DefinitionFieldsUpdate(BaseModel):
    item_no: str | None = None
    name: str | None = None
    short_name: str | None = None
    department_id: int | None = None
    deliverable_type: str | None = None
    is_milestone: bool | None = None
    milestone_code: str | None = None
    actor_role: str = "Admin"
    actor_email: str = ""
    actor_name: str = ""


@router.patch("/admin/definitions/{definition_id}")
def update_admin_definition(definition_id: int, payload: DefinitionFieldsUpdate, db: Session = Depends(get_db)):
    _require_admin(payload.actor_role, "edit a deliverable")
    d = db.get(models.DeliverableDefinition, definition_id)
    if not d:
        raise HTTPException(404, "Deliverable not found")
    before = _definition_snapshot(d)
    old_item_no = d.item_no

    if payload.item_no is not None:
        d.item_no = payload.item_no.strip()
    if payload.name is not None:
        d.name = payload.name.strip()
    if payload.short_name is not None:
        d.short_name = payload.short_name.strip() or None
    if payload.department_id is not None:
        dept = db.get(models.Department, payload.department_id)
        if not dept:
            raise HTTPException(400, "Department not found")
        d.department_id = payload.department_id
    if payload.deliverable_type is not None:
        d.deliverable_type = payload.deliverable_type
    if payload.is_milestone is not None:
        d.is_milestone = payload.is_milestone
    if payload.milestone_code is not None:
        d.milestone_code = payload.milestone_code.strip() or None
        d.milestone_name = d.milestone_code

    cascaded: list[str] = []
    if payload.item_no is not None and d.item_no != old_item_no:
        # [Known sharp edge]: other definitions' branches may reference the
        # old item_no as their own predecessor_item_no -- rewrite those too,
        # in the same transaction, so nothing silently stops resolving.
        dependents = (
            db.query(models.DeliverableFormulaBranch)
            .join(models.DeliverableDefinition)
            .filter(models.DeliverableDefinition.stage == d.stage,
                     models.DeliverableFormulaBranch.predecessor_item_no.isnot(None))
            .all()
        )
        for b in dependents:
            tokens = [t.strip() for t in (b.predecessor_item_no or "").split(",")]
            if old_item_no in tokens:
                b.predecessor_item_no = ",".join(d.item_no if t == old_item_no else t for t in tokens)
                if b.definition.item_no not in cascaded:
                    cascaded.append(b.definition.item_no)

    d.is_customized = True
    after = _definition_snapshot(d)
    summary = f"Edited {old_item_no} {d.name}" + (f" (renamed to {d.item_no})" if old_item_no != d.item_no else "")
    if cascaded:
        summary += f"; also updated the formula on: {', '.join(cascaded)}"
    _log_definition_change(db, d, "admin_edit", "field_edit", before, after,
                            payload.actor_email, payload.actor_name, summary)
    db.commit()
    return _definition_out(d)


class BranchesUpdate(BaseModel):
    branches: list[BranchIn]
    actor_role: str = "Admin"
    actor_email: str = ""
    actor_name: str = ""


@router.put("/admin/definitions/{definition_id}/branches")
def update_admin_definition_branches(definition_id: int, payload: BranchesUpdate, db: Session = Depends(get_db)):
    _require_admin(payload.actor_role, "edit a deliverable's formula")
    d = db.get(models.DeliverableDefinition, definition_id)
    if not d:
        raise HTTPException(404, "Deliverable not found")
    _validate_branches(payload.branches)
    before = _definition_snapshot(d)
    _apply_branches(db, d, payload.branches)
    d.is_customized = True
    after = _definition_snapshot(d)
    _log_definition_change(db, d, "admin_edit", "branch_edit", before, after,
                            payload.actor_email, payload.actor_name, f"Changed the formula for {d.item_no} {d.name}")
    db.commit()
    affected = _force_recompute_affected(db, d.id)
    return _definition_out(d) | {"projects_recomputed": affected}


class DefinitionActorOnly(BaseModel):
    actor_role: str = "Admin"
    actor_email: str = ""
    actor_name: str = ""


@router.post("/admin/definitions/{definition_id}/restore-default")
def restore_admin_definition_default(definition_id: int, payload: DefinitionActorOnly, db: Session = Depends(get_db)):
    from .. import seed as seed_module  # local import: seed.py imports rules, avoid a top-level cycle
    _require_admin(payload.actor_role, "restore a deliverable to its default")
    d = db.get(models.DeliverableDefinition, definition_id)
    if not d:
        raise HTTPException(404, "Deliverable not found")
    if not d.seed_key:
        raise HTTPException(400, "This deliverable was created directly in the admin UI -- there's no catalog default to restore")
    catalog = _find_catalog_tuple(d.seed_key)
    if not catalog:
        raise HTTPException(400, "This item no longer exists in the current catalog -- nothing to restore to")
    item_no, name, anchor, pred, offset, direction, dtype, ms = catalog
    before = _definition_snapshot(d)
    d.item_no = item_no
    d.name = name
    d.deliverable_type = dtype
    d.is_milestone = bool(ms)
    d.milestone_code = ms
    d.milestone_name = ms
    d.anchor_type = anchor
    d.predecessor_item_no = pred
    d.offset_days = offset
    d.offset_direction = direction
    d.is_customized = False
    for old in list(d.branches):
        db.delete(old)
    db.flush()
    db.refresh(d)
    for b in seed_module._seed_branches_for(d):
        db.add(models.DeliverableFormulaBranch(deliverable_definition_id=d.id, **b))
    db.flush()
    db.refresh(d)
    rules.sync_definition_mirror_columns(d)
    after = _definition_snapshot(d)
    _log_definition_change(db, d, "restore_default", "branch_edit", before, after,
                            payload.actor_email, payload.actor_name, f"Restored {d.item_no} {d.name} to its default formula")
    db.commit()
    affected = _force_recompute_affected(db, d.id)
    return _definition_out(d) | {"projects_recomputed": affected}


def _find_catalog_tuple(seed_key: str):
    """Looks up seed_key ("stage:item_no:department_id") against the live
    L0_ITEMS/L1_ITEMS/L0_INTERNATIONAL_ITEMS catalogs -- used by
    restore-default to get back to the CURRENT code's own values (not
    whatever was seeded years ago), same as upsert() itself would apply on
    the next deploy.
    """
    from .. import seed as seed_module
    db = None
    try:
        stage, item_no, dept_id_str = seed_key.split(":", 2)
        dept_id = int(dept_id_str)
    except ValueError:
        return None
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        dept = db.get(models.Department, dept_id)
        if not dept:
            return None
        dept_key_map = {
            "L0": seed_module.L0_DEPT, "L1": seed_module.L1_DEPT,
        }
        catalogs = []
        if stage == "L0":
            catalogs.append((seed_module.L0_ITEMS, seed_module.L0_DEPT))
            catalogs.append((seed_module.L0_INTERNATIONAL_ITEMS, seed_module.L0_INTERNATIONAL_DEPT))
        else:
            catalogs.append((seed_module.L1_ITEMS, seed_module.L1_DEPT))
        for items, dept_map_keys in catalogs:
            for row in items:
                row_item_no, row_dept_key = row[0], row[2]
                if row_item_no != item_no:
                    continue
                if dept_map_keys.get(row_dept_key) != dept.name:
                    continue
                # row shapes: L0/L0_INTERNATIONAL = 9-tuple (item_no,name,dkey,anchor,pred,offset,direction,dtype,ms)
                # L1 = 8-tuple (item_no,name,dkey,anchor,pred,offset,direction,ms) -- always date_driven
                if len(row) == 9:
                    return row[0], row[1], row[3], row[4], row[5], row[6], row[7], row[8]
                return row[0], row[1], row[3], row[4], row[5], row[6], "date_driven", row[7]
        return None
    finally:
        db.close()


class DefinitionCreate(BaseModel):
    stage: str
    item_no: str
    name: str
    department_id: int
    deliverable_type: str = "date_driven"
    is_milestone: bool = False
    milestone_code: str | None = None
    branches: list[BranchIn] = []
    actor_role: str = "Admin"
    actor_email: str = ""
    actor_name: str = ""


@router.post("/admin/definitions", status_code=201)
def create_admin_definition(payload: DefinitionCreate, db: Session = Depends(get_db)):
    _require_admin(payload.actor_role, "add a deliverable")
    if payload.stage not in ("L0", "L1"):
        raise HTTPException(400, "stage must be L0 or L1")
    item_no = payload.item_no.strip()
    name = payload.name.strip()
    if not item_no or not name:
        raise HTTPException(400, "Item number and name are required")
    dept = db.get(models.Department, payload.department_id)
    if not dept:
        raise HTTPException(400, "Department not found")
    if db.query(models.DeliverableDefinition).filter_by(
        stage=payload.stage, item_no=item_no, department_id=payload.department_id,
    ).first():
        raise HTTPException(400, f"{item_no} already exists in {dept.name}")
    if payload.deliverable_type == "date_driven":
        _validate_branches(payload.branches)
    d = models.DeliverableDefinition(
        stage=payload.stage, item_no=item_no, name=name, short_name=name, department_id=payload.department_id,
        deliverable_type=payload.deliverable_type, is_milestone=payload.is_milestone,
        milestone_code=payload.milestone_code, milestone_name=payload.milestone_code,
        is_customized=True, seed_key=None, active=True,
    )
    db.add(d)
    db.flush()
    if payload.branches:
        _apply_branches(db, d, payload.branches)
    _log_definition_change(db, d, "admin_edit", "created", None, _definition_snapshot(d),
                            payload.actor_email, payload.actor_name, f"Created {item_no} {name}")
    db.commit()
    return _definition_out(d) | {
        "note": "New deliverables only join the base project-instantiation flow -- PO Lifecycle tracking, "
                "the Tendering triage exemption, and auto-complete-from-project-field integrations stay code-only for now.",
    }


class ActiveToggle(BaseModel):
    active: bool
    actor_role: str = "Admin"
    actor_email: str = ""
    actor_name: str = ""


@router.patch("/admin/definitions/{definition_id}/active")
def toggle_admin_definition_active(definition_id: int, payload: ActiveToggle, db: Session = Depends(get_db)):
    _require_admin(payload.actor_role, "deactivate or reactivate a deliverable")
    d = db.get(models.DeliverableDefinition, definition_id)
    if not d:
        raise HTTPException(404, "Deliverable not found")
    before = _definition_snapshot(d)
    d.active = payload.active
    after = _definition_snapshot(d)
    verb = "Reactivated" if payload.active else "Deactivated"
    _log_definition_change(db, d, "admin_edit", "reactivated" if payload.active else "deactivated",
                            before, after, payload.actor_email, payload.actor_name, f"{verb} {d.item_no} {d.name}")
    db.commit()
    return _definition_out(d)


@router.get("/admin/change-history")
def list_admin_change_history(deliverable_definition_id: int | None = None, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(models.DeliverableDefinitionChangeLog).order_by(models.DeliverableDefinitionChangeLog.changed_at.desc())
    if deliverable_definition_id is not None:
        q = q.filter(models.DeliverableDefinitionChangeLog.deliverable_definition_id == deliverable_definition_id)
    rows = q.limit(limit).all()
    return [
        {"id": r.id, "deliverable_definition_id": r.deliverable_definition_id,
         "item_no": r.definition.item_no if r.definition else None,
         "item_name": r.definition.name if r.definition else None,
         "changed_at": r.changed_at, "actor_email": r.actor_email, "actor_name": r.actor_name,
         "source": r.source, "change_type": r.change_type, "summary": r.summary,
         "origin_request_id": r.origin_request_id}
        for r in rows
    ]


@router.post("/admin/change-history/{log_id}/revert")
def revert_admin_change(log_id: int, payload: DefinitionActorOnly, db: Session = Depends(get_db)):
    _require_admin(payload.actor_role, "revert a change")
    log = db.get(models.DeliverableDefinitionChangeLog, log_id)
    if not log or not log.before_snapshot:
        raise HTTPException(404, "Change not found or has nothing to revert to")
    d = db.get(models.DeliverableDefinition, log.deliverable_definition_id)
    if not d:
        raise HTTPException(404, "Deliverable not found")
    before = _definition_snapshot(d)
    snap = log.before_snapshot
    d.item_no = snap["item_no"]
    d.name = snap["name"]
    d.short_name = snap["short_name"]
    d.department_id = snap["department_id"]
    d.deliverable_type = snap["deliverable_type"]
    d.is_milestone = snap["is_milestone"]
    d.milestone_code = snap["milestone_code"]
    d.milestone_name = snap["milestone_code"]
    d.active = snap["active"]
    d.is_customized = True
    branch_payloads = [BranchIn(**{k: v for k, v in b.items() if k != "id"}) for b in snap["branches"]]
    if branch_payloads:
        _apply_branches(db, d, branch_payloads)
    after = _definition_snapshot(d)
    _log_definition_change(db, d, "revert", "field_edit", before, after,
                            payload.actor_email, payload.actor_name,
                            f"Reverted {d.item_no} {d.name} to an earlier version")
    db.commit()
    affected = _force_recompute_affected(db, d.id)
    return _definition_out(d) | {"projects_recomputed": affected}


# ---------------------------------------------------------------------------
# Owner/SME read-only formulas browse + suggest-a-change (request-then-decide,
# mirrors SmeNomination/UserAddRequest exactly -- see departments.py).
# ---------------------------------------------------------------------------
@router.get("/config/formulas")
def list_formulas(stage: str | None = None, international: bool | None = None,
                   department_id: int | None = None, db: Session = Depends(get_db)):
    q = (
        db.query(models.DeliverableDefinition)
        .join(models.Department)
        .filter(models.DeliverableDefinition.active == True)  # noqa: E712
    )
    if stage:
        q = q.filter(models.DeliverableDefinition.stage == stage)
    if international is not None:
        q = q.filter(models.Department.is_international == international)
    if department_id is not None:
        q = q.filter(models.DeliverableDefinition.department_id == department_id)
    defs = q.order_by(models.Department.number, models.DeliverableDefinition.item_no).all()
    return [
        {"id": d.id, "stage": d.stage.value, "item_no": d.item_no, "name": d.name,
         "department": d.department.name, "department_number": d.department.number,
         "is_international": bool(d.department.is_international),
         "branches": [_branch_out(b) for b in sorted(d.branches, key=lambda b: b.branch_order)],
         "formula_text": rules.describe_formula_branches(d)}
        for d in defs
    ]


def _serialize_formula_request(r: "models.FormulaChangeRequest") -> dict:
    d = r.definition
    return {
        "id": r.id, "deliverable_definition_id": r.deliverable_definition_id,
        "item_no": d.item_no if d else None, "item_name": d.name if d else None,
        "department": d.department.name if d else None,
        "requested_by_email": r.requested_by_email, "requested_by_name": r.requested_by_name,
        "current_summary": r.current_summary, "proposed_branches": r.proposed_branches,
        "proposed_formula_text": rules.describe_proposed_branches(r.proposed_branches),
        "comment": r.comment, "status": r.status,
        "requested_at": r.requested_at, "decided_at": r.decided_at,
        "decided_by_email": r.decided_by_email, "decision_comment": r.decision_comment,
    }


class FormulaChangeRequestCreate(BaseModel):
    deliverable_definition_id: int
    proposed_branches: list[BranchIn]
    comment: str
    actor_name: str | None = None
    actor_email: str


@router.post("/config/formula-change-requests", status_code=201)
def create_formula_change_request(payload: FormulaChangeRequestCreate, db: Session = Depends(get_db)):
    email = payload.actor_email.strip()
    comment = payload.comment.strip()
    if not email:
        raise HTTPException(400, "Email is required")
    if not comment:
        raise HTTPException(400, "A reason is required")
    d = db.get(models.DeliverableDefinition, payload.deliverable_definition_id)
    if not d:
        raise HTTPException(404, "Deliverable not found")
    _validate_branches(payload.proposed_branches)
    user = db.query(models.User).filter(models.User.email.ilike(email)).first()
    if not user:
        raise HTTPException(400, "You need to be in the L0-L1 Group to suggest a change (Focal Points → L0-L1 Group)")
    req = models.FormulaChangeRequest(
        deliverable_definition_id=d.id, requested_by_email=user.email, requested_by_name=user.name,
        current_summary=rules.describe_formula_branches(d),
        proposed_branches=[b.model_dump() for b in payload.proposed_branches],
        comment=comment,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    announcements.formula_change_requested(db, sorted(rules.admin_emails(db)), user.email, user.name, d.item_no, d.name)
    return _serialize_formula_request(req)


@router.get("/config/formula-change-requests")
def list_formula_change_requests(status: str | None = "pending", requested_by_email: str | None = None,
                                  db: Session = Depends(get_db)):
    q = db.query(models.FormulaChangeRequest).order_by(models.FormulaChangeRequest.requested_at.desc())
    if status:
        q = q.filter(models.FormulaChangeRequest.status == status)
    if requested_by_email:
        q = q.filter(models.FormulaChangeRequest.requested_by_email.ilike(requested_by_email.strip()))
    return [_serialize_formula_request(r) for r in q.all()]


class FormulaChangeDecision(BaseModel):
    approved: bool
    comment: str = ""
    actor_role: str = "Admin"
    actor_email: str = ""
    actor_name: str = ""


@router.post("/config/formula-change-requests/{request_id}/decide")
def decide_formula_change_request(request_id: int, payload: FormulaChangeDecision, db: Session = Depends(get_db)):
    _require_admin(payload.actor_role, "decide a formula change suggestion")
    req = db.get(models.FormulaChangeRequest, request_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(400, "This request has already been decided")
    d = req.definition
    if payload.approved:
        if not d:
            raise HTTPException(400, "The deliverable this suggestion targets no longer exists")
        branch_payloads = [BranchIn(**b) for b in req.proposed_branches]
        _validate_branches(branch_payloads)
        before = _definition_snapshot(d)
        _apply_branches(db, d, branch_payloads)
        d.is_customized = True
        after = _definition_snapshot(d)
        log = _log_definition_change(
            db, d, "suggestion_approved", "branch_edit", before, after,
            payload.actor_email, payload.actor_name,
            f"Approved {req.requested_by_name or req.requested_by_email}'s suggested formula change for {d.item_no} {d.name}",
            origin_request_id=req.id,
        )
        req.applied_change_log_id = log.id
    req.status = "approved" if payload.approved else "rejected"
    req.decided_at = datetime.utcnow()
    req.decided_by_email = payload.actor_email or None
    req.decision_comment = payload.comment or None
    db.commit()
    if payload.approved:
        _force_recompute_affected(db, d.id)
    announcements.formula_change_decision(db, req.requested_by_email, d.item_no if d else "?", d.name if d else "?",
                                           payload.approved, payload.comment)
    return _serialize_formula_request(req)

"""[PO Lifecycle]: the line-item registry (long-lead items from an owner-
uploaded Excel, early-activity/MEP from fixed checklists, S/C agreements
from manual entry, consultancy fixed at one) and the summary endpoint that
feeds the PO Lifecycle tab.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, rules
from ..database import get_db
from ..excel_parsing import parse_long_lead_workbook
from .projects import _instantiate_deliverables

router = APIRouter(prefix="/api/projects/{project_id}/po-line-items", tags=["po-line-items"])

# Every category's shared step chain, in order. A PoLineItem's own progress
# is read off whichever of these item_nos it actually has a submission for
# -- "sc" only ever has one of 3.8/2.18 active per project (gated by the
# existing rules.is_bu_applicable), so listing both here is harmless: only
# the one that was actually instantiated shows up in an item's own steps.
CATEGORY_STEP_SEQUENCE = {
    "long_lead": ["4.5", "2.2", "3.1", "3.2", "3.3", "3.4", "3.5", "3.6", "3.7"],
    "early_activity": ["2.6", "3.11"],
    "mep": ["2.14", "3.11"],
    "consultancy": ["2.7", "3.10"],
    "sc": ["3.8", "2.18"],
}

EARLY_ACTIVITY_TYPES = [
    "Geotechnical/Soil Investigation", "Topography Survey", "Route Survey",
    "Radar/GPR Survey", "Hydrology Study", "Environmental Study (ESIA)",
]
MEP_TYPES = ["HCIS Consultancy", "Fire Fighting Consultancy"]


def _get_project(db: Session, project_id: int) -> models.Project:
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _after_registry_change(db: Session, project: models.Project):
    """New PoLineItems need their step chains instantiated immediately, not
    on the next unrelated write -- same pattern _provision_and_instantiate
    already uses at project creation.
    """
    _instantiate_deliverables(db, project)
    rules.recompute_project_due_dates(db, project, force=True)
    db.commit()


@router.get("")
def list_po_line_items(project_id: int, category: str | None = None, db: Session = Depends(get_db)):
    _get_project(db, project_id)
    q = db.query(models.PoLineItem).filter(models.PoLineItem.project_id == project_id,
                                            models.PoLineItem.status == "active")
    if category:
        q = q.filter(models.PoLineItem.category == category)
    return [
        {"id": li.id, "category": li.category, "name": li.name, "source": li.source, "meta": li.meta}
        for li in q.order_by(models.PoLineItem.created_at).all()
    ]


@router.get("/checklist-options")
def checklist_options(project_id: int, db: Session = Depends(get_db)):
    """The fixed early-activity/MEP types, each flagged with whether it's
    already been ticked (an active PoLineItem exists for it) on this project.
    """
    _get_project(db, project_id)
    existing = {
        (li.category, (li.meta or {}).get("checklist_type"))
        for li in db.query(models.PoLineItem).filter(
            models.PoLineItem.project_id == project_id, models.PoLineItem.status == "active",
            models.PoLineItem.category.in_(["early_activity", "mep"])).all()
    }
    return {
        "early_activity": [{"type": t, "checked": ("early_activity", t) in existing} for t in EARLY_ACTIVITY_TYPES],
        "mep": [{"type": t, "checked": ("mep", t) in existing} for t in MEP_TYPES],
    }


@router.post("/excel-preview")
async def excel_preview(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    _get_project(db, project_id)
    content = await file.read()
    try:
        rows = parse_long_lead_workbook(content)
    except Exception:
        raise HTTPException(400, "Couldn't read that file as an Excel workbook")
    if not rows:
        raise HTTPException(400, "No items found — check the file has \"Local Material\" / "
                                  "\"Imported Material\" sheets with an ITEM DESCRIPTION column")
    return {"rows": rows}


class _ExcelCommitItem(BaseModel):
    name: str
    qty: float | None = None
    unit: str | None = None
    supplier: str | None = None
    delivery_est: str | None = None


class _ExcelCommitRequest(BaseModel):
    items: list[_ExcelCommitItem]
    actor_email: str = ""


@router.post("/excel-commit")
def excel_commit(project_id: int, body: _ExcelCommitRequest, db: Session = Depends(get_db)):
    project = _get_project(db, project_id)
    if not body.items:
        raise HTTPException(400, "No items to add")
    for item in body.items:
        db.add(models.PoLineItem(
            project_id=project.id, category="long_lead", name=item.name, source="excel",
            meta={"qty": item.qty, "unit": item.unit, "supplier": item.supplier, "delivery_est": item.delivery_est},
            created_by_email=body.actor_email or None,
        ))
    db.commit()
    _after_registry_change(db, project)
    return {"added": len(body.items)}


class _ManualAddRequest(BaseModel):
    category: str
    name: str
    actor_email: str = ""


@router.post("/manual")
def manual_add(project_id: int, body: _ManualAddRequest, db: Session = Depends(get_db)):
    project = _get_project(db, project_id)
    if body.category not in CATEGORY_STEP_SEQUENCE:
        raise HTTPException(400, "Unknown category")
    if not body.name.strip():
        raise HTTPException(400, "Name is required")
    li = models.PoLineItem(project_id=project.id, category=body.category, name=body.name.strip(),
                            source="manual", created_by_email=body.actor_email or None)
    db.add(li)
    db.commit()
    _after_registry_change(db, project)
    return {"id": li.id}


class _ChecklistToggleRequest(BaseModel):
    category: str  # early_activity | mep
    checklist_type: str
    checked: bool
    actor_email: str = ""


@router.post("/checklist-toggle")
def checklist_toggle(project_id: int, body: _ChecklistToggleRequest, db: Session = Depends(get_db)):
    project = _get_project(db, project_id)
    if body.category not in ("early_activity", "mep"):
        raise HTTPException(400, "checklist-toggle is only for early_activity / mep")
    valid_types = EARLY_ACTIVITY_TYPES if body.category == "early_activity" else MEP_TYPES
    if body.checklist_type not in valid_types:
        raise HTTPException(400, "Unknown checklist type for this category")

    existing = (
        db.query(models.PoLineItem)
        .filter(models.PoLineItem.project_id == project.id, models.PoLineItem.category == body.category)
        .all()
    )
    match = next((li for li in existing if (li.meta or {}).get("checklist_type") == body.checklist_type), None)

    if body.checked:
        if match and match.status == "active":
            return {"id": match.id}  # already ticked, no-op
        if match:
            match.status = "active"  # re-ticking a previously-unticked item resumes it, doesn't duplicate
        else:
            match = models.PoLineItem(project_id=project.id, category=body.category, name=body.checklist_type,
                                       source="checklist", meta={"checklist_type": body.checklist_type},
                                       created_by_email=body.actor_email or None)
            db.add(match)
    else:
        if not match or match.status != "active":
            return {"cancelled": False}
        match.status = "cancelled"  # soft-cancel only — existing submissions/history are never deleted
    db.commit()
    _after_registry_change(db, project)
    return {"id": match.id}


@router.post("/{line_item_id}/cancel")
def cancel_line_item(project_id: int, line_item_id: int, db: Session = Depends(get_db)):
    project = _get_project(db, project_id)
    li = db.query(models.PoLineItem).filter(models.PoLineItem.id == line_item_id,
                                             models.PoLineItem.project_id == project.id).first()
    if not li:
        raise HTTPException(404, "Line item not found")
    li.status = "cancelled"
    db.commit()
    return {"ok": True}


@router.get("/po-cycle-summary")
def po_cycle_summary(project_id: int, db: Session = Depends(get_db)):
    project = _get_project(db, project_id)
    rules.recompute_project_due_dates(db, project)  # cheap, daily-gated read (see rules.py docstring)
    db.commit()

    line_items = (
        db.query(models.PoLineItem)
        .filter(models.PoLineItem.project_id == project.id, models.PoLineItem.status == "active")
        .all()
    )
    subs = (
        db.query(models.DeliverableSubmission)
        .filter(models.DeliverableSubmission.project_id == project.id,
                models.DeliverableSubmission.po_line_item_id.isnot(None))
        .all()
    )
    subs_by_item: dict[int, dict[str, models.DeliverableSubmission]] = {}
    for s in subs:
        subs_by_item.setdefault(s.po_line_item_id, {})[s.definition.item_no] = s

    result: dict[str, dict] = {}
    for category, sequence in CATEGORY_STEP_SEQUENCE.items():
        cat_items = [li for li in line_items if li.category == category]
        items_out = []
        step_counts = {item_no: {"passed": 0, "total": 0} for item_no in sequence}
        counts = {"complete": 0, "in_progress": 0, "blocked": 0}
        for li in cat_items:
            item_subs = subs_by_item.get(li.id, {})
            item_seq = [item_no for item_no in sequence if item_no in item_subs]
            passed = 0
            current_item_no = None
            for item_no in item_seq:
                sub = item_subs[item_no]
                step_counts[item_no]["total"] += 1
                if sub.status == models.SubmissionStatus.APPROVED:
                    passed += 1
                    step_counts[item_no]["passed"] += 1
                elif current_item_no is None:
                    current_item_no = item_no
            fully_done = bool(item_seq) and passed == len(item_seq)
            if fully_done:
                item_status = "complete"
            elif current_item_no and item_subs[current_item_no].status == models.SubmissionStatus.NO_PROGRESS \
                    and rules.awaiting_milestone_note(db, item_subs[current_item_no]):
                item_status = "blocked"
            else:
                item_status = "in_progress"
            counts[item_status] += 1
            items_out.append({
                "id": li.id, "name": li.name, "source": li.source, "status": item_status,
                "step_position": passed, "total_steps": len(item_seq),
                "current_item_no": current_item_no,
            })
        result[category] = {"items": items_out, "step_counts": step_counts, "stats": counts}
    return result

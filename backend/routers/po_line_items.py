"""[PO Lifecycle]: the read-only summary the PO Lifecycle tab renders, plus
sync_from_submission -- the approval-time hook that turns a declaring
item's (1.2/4.1/2.11/2.17) po_selection into real PoLineItems. All owner
input (uploads, checklist ticks, S/C names) happens on the declaring
submission itself, through the normal Deliverables tab -- this module has
no write endpoints of its own.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, rules
from ..database import get_db

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

# Which item_no declares which categories, and how its po_selection maps to
# each -- the single source of truth sync_from_submission and the frontend
# modal both key off.
DECLARING_ITEM_NOS = ("1.2", "4.1", "2.11", "2.17")


def _get_project(db: Session, project_id: int) -> models.Project:
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def sync_from_submission(db: Session, sub: "models.DeliverableSubmission") -> None:
    """Reads sub.po_selection and diffs it against the PoLineItems this
    submission previously created (source_submission_id == sub.id):
    missing ones get created, ones no longer selected get soft-cancelled.
    Idempotent -- safe on a reopen -> edit selection -> re-approve cycle,
    which is exactly how a selection changes after the fact. Called once
    from _finalize_approval; never a route.
    """
    item_no = sub.definition.item_no
    if item_no not in DECLARING_ITEM_NOS:
        return
    selection = sub.po_selection or {}
    project = sub.project

    def set_item_submissions_applicability(li, applicability: str):
        # Cancelling a PoLineItem must also stand its own submissions down --
        # otherwise a deselected item leaves its 2.6/3.11/etc. rows sitting
        # in the Deliverables list forever as actionable ghosts nobody can
        # ever actually complete. Re-selecting reverses it the same way.
        db.query(models.DeliverableSubmission).filter(
            models.DeliverableSubmission.po_line_item_id == li.id,
        ).update({"applicability": applicability}, synchronize_session=False)

    def sync_category(category: str, desired_names: list[str], source: str, meta_by_name: dict | None = None):
        meta_by_name = meta_by_name or {}
        existing = db.query(models.PoLineItem).filter(
            models.PoLineItem.source_submission_id == sub.id,
            models.PoLineItem.category == category,
        ).all()
        existing_by_name = {li.name: li for li in existing}
        for name in desired_names:
            li = existing_by_name.get(name)
            if li:
                if li.status != "active":
                    li.status = "active"
                    set_item_submissions_applicability(li, "applicable")
                if name in meta_by_name:
                    li.meta = meta_by_name[name]
            else:
                db.add(models.PoLineItem(
                    project_id=project.id, category=category, name=name, source=source,
                    meta=meta_by_name.get(name), status="active", source_submission_id=sub.id,
                ))
        for name, li in existing_by_name.items():
            if name not in desired_names and li.status == "active":
                li.status = "cancelled"
                set_item_submissions_applicability(li, "not_required")

    if item_no == "1.2":
        long_lead_rows = [r for r in (selection.get("long_lead_items") or []) if r.get("name")]
        names = [r["name"] for r in long_lead_rows]
        meta_map = {r["name"]: {k: r.get(k) for k in ("qty", "unit", "supplier", "delivery_est")}
                    for r in long_lead_rows}
        sync_category("long_lead", names, "excel", meta_map)
        mep_selected = [t for t in (selection.get("mep_selected") or []) if t in MEP_TYPES]
        sync_category("mep", mep_selected, "checklist")
    elif item_no == "4.1":
        selected = [t for t in (selection.get("selected") or []) if t in EARLY_ACTIVITY_TYPES]
        sync_category("early_activity", selected, "checklist")
    elif item_no in ("2.11", "2.17"):
        items = [n.strip() for n in (selection.get("items") or []) if n and n.strip()]
        sync_category("sc", items, "manual")

    db.commit()
    from .projects import _instantiate_deliverables
    _instantiate_deliverables(db, project)  # fans out the new items' step chains, recomputes due dates, commits


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


@router.get("/po-cycle-summary")
def po_cycle_summary(project_id: int, db: Session = Depends(get_db)):
    project = _get_project(db, project_id)
    rules.recompute_project_due_dates(db, project)  # cheap, daily-gated read (see rules.py docstring)
    db.commit()

    line_items = (
        db.query(models.PoLineItem)
        .filter(models.PoLineItem.project_id == project.id, models.PoLineItem.status == "active",
                # Only items that came from a real 1.2/4.1/2.11/2.17 selection --
                # excludes the synthetic "Item 1 (migrated)" rows the one-time
                # backfill created for pre-existing production progress. Their
                # underlying submissions stay real and trackable in the normal
                # Deliverables tab; this summary just doesn't surface them as
                # a named registry item anymore.
                models.PoLineItem.source_submission_id.isnot(None))
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
        subs_per_step: dict[str, list] = {item_no: [] for item_no in sequence}  # [PO Lifecycle pro-rata]
        counts = {"complete": 0, "in_progress": 0, "blocked": 0}
        for li in cat_items:
            item_subs = subs_by_item.get(li.id, {})
            item_seq = [item_no for item_no in sequence if item_no in item_subs]
            passed = 0
            current_item_no = None
            for item_no in item_seq:
                sub = item_subs[item_no]
                step_counts[item_no]["total"] += 1
                subs_per_step[item_no].append(sub)
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
        for item_no, item_subs in subs_per_step.items():
            step_counts[item_no]["score"] = rules.item_group_kpi_pct(item_subs) if item_subs else None
        result[category] = {"items": items_out, "step_counts": step_counts, "stats": counts}
    return result

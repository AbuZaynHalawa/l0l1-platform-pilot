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
    "long_lead": ["3.12", "4.5", "2.2", "3.1", "3.2", "4.6", "3.3", "3.4", "3.5", "3.6", "3.7"],
    "early_activity": ["3.12", "2.6", "3.11"],
    "mep": ["3.12", "2.14", "3.11"],
    "consultancy": ["2.7", "3.10"],
    "sc": ["3.12", "3.8", "2.18"],
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

# The reverse direction -- which declaring item_no(s) a category's own items
# won't exist without. "sc" has two candidates since which one actually
# applies depends on project scope (OHTL/UGC vs SS); "consultancy" has none
# -- it's auto-created at project creation (projects._ensure_consultancy_line_item),
# never gated on a declaring item at all. Used by projects.get_deliverables
# to name the right declaring item(s) in a placeholder's "Pending X" note.
CATEGORY_DECLARING_ITEM_NOS = {
    "long_lead": ["1.2"], "mep": ["1.2"], "early_activity": ["4.1"], "sc": ["2.11", "2.17"],
}


def declaring_item_nos_for(line_item_category: str) -> list[str]:
    """line_item_category can be comma-separated (e.g. "early_activity,mep"
    for 3.11, all four pools for 3.12) -- collect every distinct declaring
    item_no across all of it, in a stable order.
    """
    result: list[str] = []
    for cat in line_item_category.split(","):
        for item_no in CATEGORY_DECLARING_ITEM_NOS.get(cat.strip(), []):
            if item_no not in result:
                result.append(item_no)
    return result


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
        step_counts = {item_no: {"passed": 0, "total": 0, "in_progress": 0, "no_progress": 0} for item_no in sequence}
        subs_per_step: dict[str, list] = {item_no: [] for item_no in sequence}  # [PO Lifecycle pro-rata]
        counts = {"complete": 0, "in_progress": 0, "blocked": 0}
        for li in cat_items:
            item_subs = subs_by_item.get(li.id, {})
            item_seq = [item_no for item_no in sequence if item_no in item_subs]
            passed = 0
            approved_item_nos = []
            highest_approved_index = -1
            for idx, item_no in enumerate(item_seq):
                sub = item_subs[item_no]
                step_counts[item_no]["total"] += 1
                subs_per_step[item_no].append(sub)
                # [3.12 not-required]: an item that doesn't need prequalification
                # (S/C too small, vendor already qualified, etc.) is marked
                # Not Required rather than actually approved -- counts exactly
                # like a real approval here so it doesn't sit forever as a
                # phantom blocker on this line item's chain.
                if sub.status == models.SubmissionStatus.APPROVED or sub.applicability == "not_required":
                    passed += 1
                    step_counts[item_no]["passed"] += 1
                    approved_item_nos.append(item_no)
                    highest_approved_index = idx
                elif sub.status in (models.SubmissionStatus.IN_PROGRESS, models.SubmissionStatus.PENDING_REVIEW):
                    step_counts[item_no]["in_progress"] += 1
                else:
                    step_counts[item_no]["no_progress"] += 1
            # [PO Lifecycle out-of-order completion] some real predecessor
            # chains are parallel, not strictly sequential (e.g. 2.2 and 3.1
            # both gate on 4.5 directly, not on each other) -- a later step
            # can genuinely get approved while an earlier one in the display
            # sequence hasn't. "Skipped" names those bypassed earlier steps
            # explicitly instead of miscounting them as done (position <
            # count would silently mark them complete) or hiding that
            # they're still technically open. "Next" is the real frontier:
            # the first not-approved step after the furthest actual
            # progress, not just the first not-approved step overall.
            skipped_item_nos = [
                item_no for idx, item_no in enumerate(item_seq)
                if idx < highest_approved_index and item_no not in approved_item_nos
            ]
            current_item_no = None
            for idx, item_no in enumerate(item_seq):
                if idx > highest_approved_index and item_no not in approved_item_nos:
                    current_item_no = item_no
                    break
            fully_done = bool(item_seq) and passed == len(item_seq)
            # [PO Lifecycle clickable items]: the one submission worth opening
            # for this line item -- whichever step is currently blocking it,
            # or (once fully done) the last step in its chain, so clicking a
            # completed item still lands on its real, approved submission.
            open_submission_id = item_subs[current_item_no].id if current_item_no else \
                (item_subs[item_seq[-1]].id if item_seq else None)
            current_status = item_subs[current_item_no].status if current_item_no else None
            if fully_done:
                item_status = "complete"
            elif current_status == models.SubmissionStatus.REJECTED:
                item_status = "blocked"
            elif current_status == models.SubmissionStatus.NO_PROGRESS \
                    and rules.awaiting_milestone_note(db, item_subs[current_item_no]):
                item_status = "blocked"
            else:
                item_status = "in_progress"
            counts[item_status] += 1
            items_out.append({
                "id": li.id, "name": li.name, "source": li.source, "status": item_status,
                "step_position": passed, "total_steps": len(item_seq),
                "current_item_no": current_item_no, "open_submission_id": open_submission_id,
                # [PO Lifecycle clickable items] one submission id per step in
                # THIS line item's own chain -- lets each segment of its
                # progress bar open its own real submission, not just the
                # single current/last one open_submission_id points at.
                "step_submission_ids": {item_no: s.id for item_no, s in item_subs.items()},
                "approved_item_nos": approved_item_nos, "skipped_item_nos": skipped_item_nos,
                # [PO Lifecycle] the raw status of whichever step is
                # currently blocking this item -- lets the UI show e.g.
                # "Rejected" specifically instead of a generic "blocked".
                "current_item_status": item_subs[current_item_no].status.value if current_item_no else None,
            })
        for item_no, item_subs in subs_per_step.items():
            step_counts[item_no]["score"] = rules.item_group_kpi_pct(item_subs) if item_subs else None
        result[category] = {"items": items_out, "step_counts": step_counts, "stats": counts}
    return result


@router.post("/mark-all-not-required/{item_no}")
def mark_all_not_required(project_id: int, item_no: str, actor_role: str = "Viewer", db: Session = Depends(get_db)):
    """Bulk version of deliverables.mark_not_required, scoped to one item_no
    across every one of this project's fan-out line items at once -- built
    for 3.12 (prequalification), where most named items on a given project
    often don't need it at all and ticking "Not Required" one by one across
    10+ line items is real, repetitive Admin busywork.
    """
    if actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can bulk mark deliverables Not Required")
    project = _get_project(db, project_id)
    subs = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .filter(models.DeliverableSubmission.project_id == project_id,
                models.DeliverableDefinition.item_no == item_no,
                models.DeliverableSubmission.applicability != "not_required",
                models.DeliverableSubmission.status.notin_([
                    models.SubmissionStatus.IN_PROGRESS, models.SubmissionStatus.PENDING_REVIEW,
                    models.SubmissionStatus.APPROVED,
                ]))
        .all()
    )
    for sub in subs:
        sub.applicability = "not_required"
        db.add(models.WorkflowHistory(submission_id=sub.id, action="not_required", actor_name="Admin",
                                       note="Marked Not Required (bulk)"))
    if subs:
        db.commit()
        rules.recompute_project_due_dates(db, project, force=True)
        db.commit()
    return {"status": "ok", "count": len(subs)}

"""Reports landing page: read-only, admin-only aggregate views that don't
belong to any single project or department page. Performance Report and
Overview PO Report reuse existing endpoints directly (dashboard.performance,
po_line_items.po_cycle_summary) -- this module only holds the two reports
that need a genuinely new cross-project aggregation: Master PO (every PO
line item across every L1 project) and Budget Status (items 6.1/6.2/6.3
across every L1 project).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, rules
from ..database import get_db
from .po_line_items import po_cycle_summary

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _require_admin(actor_role: str) -> None:
    if actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can view this report")


@router.get("/master-po")
def get_master_po_report(actor_role: str = "Viewer", db: Session = Depends(get_db)):
    """Every PO line item across every active L1 project, flattened -- the
    same per-project data the PO Lifecycle tab (po_cycle_summary) already
    computes, just called once per project and tagged with that project's
    identity instead of scoped to one project's own detail page.
    """
    _require_admin(actor_role)
    projects = (
        db.query(models.Project)
        .filter(models.Project.stage == models.Stage.L1, models.Project.archived.is_not(True))
        .order_by(models.Project.est_no)
        .all()
    )
    rows = []
    for p in projects:
        summary = po_cycle_summary(project_id=p.id, db=db)
        for category, cat_data in summary.items():
            for item in cat_data["items"]:
                rows.append({
                    "est_no": p.est_no, "project_name": p.name, "bid_manager": p.bid_manager,
                    "category": category, "name": item["name"], "source": item["source"],
                    "status": item["status"], "step_position": item["step_position"],
                    "total_steps": item["total_steps"], "current_item_no": item["current_item_no"],
                    "current_item_status": item["current_item_status"],
                })
    return rows


# [Budget Status]: items 6.1/6.2/6.3 track ordinary deliverable-submission
# workflow status -- no dollar-amount field exists anywhere in the schema
# for these (confirmed with Yasser, out of scope this round). This report
# surfaces exactly what's real: where each of the 3 stands, per project.
_BUDGET_ITEM_NOS = ("6.1", "6.2", "6.3")


@router.get("/budget-status")
def get_budget_status_report(actor_role: str = "Viewer", db: Session = Depends(get_db)):
    _require_admin(actor_role)
    projects = (
        db.query(models.Project)
        .filter(models.Project.stage == models.Stage.L1, models.Project.archived.is_not(True))
        .order_by(models.Project.est_no)
        .all()
    )
    rows = []
    for p in projects:
        subs = (
            db.query(models.DeliverableSubmission)
            .join(models.DeliverableDefinition)
            .filter(models.DeliverableSubmission.project_id == p.id,
                    models.DeliverableDefinition.item_no.in_(_BUDGET_ITEM_NOS))
            .all()
        )
        by_item = {s.definition.item_no: s for s in subs}
        for item_no in _BUDGET_ITEM_NOS:
            s = by_item.get(item_no)
            if not s:
                continue
            deadline_key, deadline_days = rules.deadline_status(s)
            rows.append({
                "est_no": p.est_no, "project_name": p.name, "bid_manager": p.bid_manager,
                "item_no": item_no, "item_name": s.definition.name, "status": s.status.value,
                "owner_emails": rules.resolve_owners(s), "due_date": s.due_date,
                "deadline_status": deadline_key, "deadline_days": deadline_days,
                "file_name": s.file_name,
            })
    return rows

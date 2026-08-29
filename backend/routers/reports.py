"""Reports landing page: read-only, admin-only aggregate views that don't
belong to any single project or department page. Performance Report reuses
/api/dashboard/performance directly (see loadReportPerformance in app.js) --
this module holds the three that need a genuinely new cross-project
aggregation: Master PO (every PO line item across every L1 project, flat),
Overview PO (the same data, rolled up to one card per project -- see
app.js's loadReportOverviewPo), and Budget Status (items 6.1/6.2/6.3 across
every L1 project).
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, rules
from ..database import get_db
from .po_line_items import po_cycle_summary

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _require_admin(actor_role: str) -> None:
    if actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can view this report")


# [PO Status report design]: the reference dashboard (Dashboard Design
# System Reference.md, built from a real Excel-driven PO tracker) has a
# genuinely different data source than this app -- it tracks literal PO
# document numbers and signed dates; this app's PO Lifecycle tracks
# workflow steps (3.1, 3.2, etc.). Confirmed with Yasser: keep that
# reference's exact visual language (3-tier signed/not-due/pending-due
# status, delay badges, category/project cards) but derive it from what
# this app actually has -- open_submission_id's own due_date/submitted_at,
# via the same rules.deadline_status() every other page already uses as
# its single source of truth for due/overdue.
def _po_status_and_delay(item_status: str, sub: "models.DeliverableSubmission | None") -> dict:
    if not sub:
        return {"po_status": "not-due", "delay_label": "&#8213;", "delay_badge": "neutral", "final_due_date": None, "actual_or_signed": None}
    if item_status == "complete":
        # Signed -- delay is how the final step actually landed vs its own
        # due date (deadline_status already classifies a completed item as
        # early/on_time/late from submitted_at vs due_date).
        deadline_key, deadline_days = rules.deadline_status(sub)
        days = abs(deadline_days) if deadline_days is not None else 0
        late = deadline_key == "late"
        return {
            "po_status": "signed",
            "delay_label": (f"{days}d late" if late else f"{days}d early/on time"),
            "delay_badge": "needs-action" if late else "excellent",
            "final_due_date": sub.due_date, "actual_or_signed": sub.submitted_at.date() if sub.submitted_at else None,
        }
    # Not yet signed -- still in progress or blocked on the current step.
    deadline_key, deadline_days = rules.deadline_status(sub)
    if deadline_key == "due":
        return {
            "po_status": "pending-due", "delay_label": f"{abs(deadline_days)}d overdue", "delay_badge": "needs-action",
            "final_due_date": sub.due_date, "actual_or_signed": None,
        }
    # deadline_status() deliberately never gives a day-count for "not_due"
    # (nothing else in this app displays "due in N days" -- everywhere else
    # just shows the flat "Not Due" status), so compute it directly here.
    days_until = (sub.due_date - date.today()).days if (deadline_key == "not_due" and sub.due_date) else None
    return {
        "po_status": "not-due",
        "delay_label": (f"Due in {days_until}d" if days_until is not None else "&#8213;"),
        "delay_badge": "neutral",
        "final_due_date": sub.due_date, "actual_or_signed": None,
    }


@router.get("/master-po")
def get_master_po_report(actor_role: str = "Viewer", db: Session = Depends(get_db)):
    """Every PO line item across every active L1 project, flattened -- the
    same per-project data the PO Lifecycle tab (po_cycle_summary) already
    computes, just called once per project and tagged with that project's
    identity instead of scoped to one project's own detail page.

    Item 12: read-only for every role now, not admin-only -- it also backs
    the user-facing "Master PO" nav tab, not just the admin Reports page.
    """
    projects = (
        db.query(models.Project)
        .filter(models.Project.stage == models.Stage.L1, models.Project.archived.is_not(True))
        .order_by(models.Project.est_no)
        .all()
    )
    rows = []
    for p in projects:
        summary = po_cycle_summary(project_id=p.id, db=db)
        sub_ids = [item["open_submission_id"] for cat in summary.values() for item in cat["items"] if item["open_submission_id"]]
        subs_by_id = {}
        if sub_ids:
            subs_by_id = {s.id: s for s in db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.id.in_(sub_ids)).all()}
        for category, cat_data in summary.items():
            for item in cat_data["items"]:
                sub = subs_by_id.get(item["open_submission_id"])
                enrich = _po_status_and_delay(item["status"], sub)
                rows.append({
                    "est_no": p.est_no, "project_name": p.name, "bid_manager": p.bid_manager,
                    "project_manager": p.project_manager,
                    "contract_status": p.contract_status.value if p.contract_status else None,
                    "department": sub.definition.department.name if sub else None,
                    "category": category, "name": item["name"], "source": item["source"],
                    "status": item["status"], "step_position": item["step_position"],
                    "total_steps": item["total_steps"], "current_item_no": item["current_item_no"],
                    "current_item_status": item["current_item_status"],
                })
                rows[-1].update(enrich)
    return rows


# [Budget Status]: items 6.1/6.2/6.3 track ordinary deliverable-submission
# workflow status -- no dollar-amount field exists anywhere in the schema
# for these (confirmed with Yasser, out of scope this round). This report
# surfaces exactly what's real: where each of the 3 stands, per project.
#
# One row per project, each of the 3 items nested by item_no rather than a
# flat per-item row -- the report itself is one line per project (a 3-
# segment progress bar, PO-Lifecycle-style: click a segment to open that
# submission, same awaiting_note/deadline_status this app already computes
# everywhere else), and app.js's poSingleStatus/poPill/poIcon (the exact
# functions the real PO Lifecycle tab's own single-item cards use) read
# this same {status, awaiting_note, deadline_status} shape directly -- one
# status-tier implementation, not a second one reinvented here.
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
        rules.recompute_project_due_dates(db, p)  # cheap, daily-gated read
        db.commit()
        subs = (
            db.query(models.DeliverableSubmission)
            .join(models.DeliverableDefinition)
            .filter(models.DeliverableSubmission.project_id == p.id,
                    models.DeliverableDefinition.item_no.in_(_BUDGET_ITEM_NOS))
            .all()
        )
        by_item = {s.definition.item_no: s for s in subs}
        items = {}
        for item_no in _BUDGET_ITEM_NOS:
            s = by_item.get(item_no)
            if not s:
                items[item_no] = None
                continue
            deadline_key, deadline_days = rules.deadline_status(s)
            items[item_no] = {
                "submission_id": s.id, "item_name": s.definition.name, "status": s.status.value,
                "owner_emails": rules.resolve_owners(s), "due_date": s.due_date,
                "deadline_status": deadline_key, "deadline_days": deadline_days,
                "awaiting_note": rules.awaiting_milestone_note(db, s), "file_name": s.file_name,
            }
        rows.append({
            "est_no": p.est_no, "project_name": p.name, "bid_manager": p.bid_manager,
            "contract_status": p.contract_status.value if p.contract_status else None,
            "items": items,
        })
    return rows

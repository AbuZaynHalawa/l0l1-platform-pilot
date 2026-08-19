"""Read-only timeline views, derived from the same due-date data as the rest
of the app — no separate schedule is stored. A deliverable's bar runs from
whatever it's anchored to (announcement/BSD/site visit/pre-bid deadline, or
the next workday after its predecessor's due date) through to its own due date.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, rules
from ..database import get_db

router = APIRouter(prefix="/api/gantt", tags=["gantt"])


# The 8 L1 items with hardcoded Start/End formulas in New L1 Template
# (Final).xlsx (rows 13/19/30/31/45/47/57/70) don't all anchor their bar's
# visual START the same way their due date (End) does -- three distinct
# patterns, verified formula-by-formula rather than assumed uniform:
#   ("predecessor", item_no)  Start = next_workday_after(that OTHER item's
#       due_date) -- a genuinely different item than whichever one drives
#       this item's own due date (e.g. 2.2's due date chains off 4.5, but
#       its Start column chains off 6.1 instead).
#   ("start_of", item_no)     Start = next_workday_after(that item's OWN
#       bar-start), not its due_date -- a Start-to-Start relationship: e.g.
#       3.1 (Issue RFQ) can begin the moment 4.5 (technical offer review)
#       itself begins, even though 3.1 can't finish until days after 4.5
#       finishes (that Finish-to-Finish+lag part is what the due-date
#       formula already captures).
#   ("duration_back", n)      Start = this item's own due_date, minus n
#       working days -- a fixed-length bar with no predecessor tie at all
#       (14.1's Start formula counts backward from its own End, not
#       forward from anything).
# Item 7.1 needs no entry: its Start formula already resolves to the same
# next_workday_after(predecessor's due_date) the default branch below
# already computes, off the same predecessor (1.5) driving its due date.
_GANTT_START_OVERRIDES: dict[str, tuple[str, object]] = {
    "2.2": ("predecessor", "6.1"),
    "2.8": ("predecessor", "3.11"),
    "3.1": ("start_of", "4.5"),
    "3.2": ("predecessor", "2.2"),
    "4.4": ("start_of", "3.9"),
    "4.6": ("start_of", "3.2"),
    "14.1": ("duration_back", 15),
}


def _find_submission(db: Session, project: models.Project, item_no: str, stage) -> models.DeliverableSubmission | None:
    return (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .filter(
            models.DeliverableSubmission.project_id == project.id,
            models.DeliverableDefinition.item_no == item_no,
            models.DeliverableDefinition.stage == stage,
        )
        .first()
    )


def _bar_start(db: Session, project: models.Project, d: models.DeliverableDefinition, due_date=None):
    override = _GANTT_START_OVERRIDES.get(d.item_no) if d.stage == models.Stage.L1 else None
    if override:
        kind, value = override
        if kind == "duration_back":
            return rules.subtract_workdays(due_date, value) if due_date else None
        other = _find_submission(db, project, value, d.stage)
        if other is None or other.due_date is None:
            return None
        if kind == "predecessor":
            return rules.next_workday_after(other.due_date)
        # kind == "start_of": recurse into the OTHER item's own bar-start
        # (which may itself be a plain predecessor anchor -- no override
        # needed there, the recursion falls through to the default branch).
        other_start = _bar_start(db, project, other.definition, other.due_date)
        return rules.next_workday_after(other_start) if other_start else None

    if d.anchor_type == "announcement":
        return project.announcement_date
    if d.anchor_type == "bsd":
        return project.bsd
    if d.anchor_type == "site_visit":
        return project.site_visit_date
    if d.anchor_type == "pre_bid":
        return project.pre_bid_deadline
    if d.anchor_type == "predecessor" and d.predecessor_item_no:
        pred = _find_submission(db, project, d.predecessor_item_no, d.stage)
        if pred is None or pred.due_date is None:
            return None
        return rules.next_workday_after(pred.due_date)
    return None


@router.get("/projects/{project_id}")
def get_project_gantt(project_id: int, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    rules.recompute_project_due_dates(db, project)
    db.commit()
    subs = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .join(models.Department)
        .filter(models.DeliverableSubmission.project_id == project_id)
        .order_by(models.Department.number)
        .all()
    )
    subs.sort(key=lambda s: (s.definition.department.number or 0, rules.item_sort_key(s.definition.item_no)))
    rows = []
    for s in subs:
        d = s.definition
        if s.due_date is None:
            continue  # unscheduled: client-dependent not yet approved, or library/on_request items
        if s.auto_completed:
            continue  # items 115/116: not real tracked work, keep off the chart
        start = _bar_start(db, project, d, s.due_date) or s.due_date
        if start > s.due_date:
            start = s.due_date
        rows.append({
            "item_no": d.item_no, "name": rules.display_name(d, project), "short_name": d.short_name or d.name,
            "department": d.department.name, "department_number": d.department.number, "submission_id": s.id,
            "start": start, "end": s.due_date, "status": s.status.value, "deadline_status": rules.deadline_status(s)[0],
            "is_milestone": d.is_milestone, "milestone_code": d.milestone_code,
        })
    return rows


@router.get("/timeline")
def get_stage_timeline(stage: str, db: Session = Depends(get_db)):
    """Every active project's deliverable-level bars for one stage, pooled
    together (not grouped by project) and sorted by due date — e.g. item 3.3
    from one project can sit right next to item 2.1 from another, whichever
    is due sooner.
    """
    projects = (
        db.query(models.Project)
        .filter(models.Project.stage == stage, models.Project.status == models.ProjectStatus.IN_PROGRESS)
        .all()
    )
    for p in projects:
        rules.recompute_project_due_dates(db, p)
    db.commit()

    rows = []
    if projects:
        proj_by_id = {p.id: p for p in projects}
        subs = (
            db.query(models.DeliverableSubmission)
            .join(models.DeliverableDefinition)
            .join(models.Department)
            .filter(models.DeliverableSubmission.project_id.in_(proj_by_id.keys()))
            .all()
        )
        for s in subs:
            if s.due_date is None:
                continue  # unscheduled: client-dependent not yet approved, or library/on_request items
            if s.auto_completed:
                continue  # items 115/116: not real tracked work, keep off the chart
            d = s.definition
            project = proj_by_id[s.project_id]
            start = _bar_start(db, project, d, s.due_date) or s.due_date
            if start > s.due_date:
                start = s.due_date
            rows.append({
                "item_no": d.item_no, "name": rules.display_name(d, project), "short_name": d.short_name or d.name,
                "department": d.department.name, "department_number": d.department.number,
                "est_no": project.est_no, "project_id": project.id, "project_name": project.name,
                "submission_id": s.id,
                "start": start, "end": s.due_date, "status": s.status.value, "deadline_status": rules.deadline_status(s)[0],
                "is_milestone": d.is_milestone, "milestone_code": d.milestone_code,
            })
    rows.sort(key=lambda r: (r["end"], r["est_no"], rules.item_sort_key(r["item_no"])))
    return rows

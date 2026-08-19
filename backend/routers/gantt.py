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

# L0's own early Tendering admin/announcement items (M1, then site
# visit/pre-bid/bid-bond/estimate-program logistics) -- excluded from the
# Gantt/Timeline chart specifically, not from the deliverables list or
# anywhere else; most are auto-completed from the project's own date
# fields anyway (see _L0_AUTO_DONE_FIELDS in projects.py) and just cluttered
# the chart with same-day slivers at the very start of every L0 tender.
_GANTT_L0_EXCLUDED_ITEMS = {"1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7"}

# WBS grouping for the L1 timeline, from "Gantt chart WBS.xlsx" (its own
# item numbers are the OLD pre-renumber scheme -- each one mapped to its
# current item_no here by description match, the same technique used for
# the earlier due-date/gantt-start formula work; see seed.py's own
# renumber-history comments for the department splits this crosses).
# Order matters: categories render in this order, not alphabetically.
GANTT_WBS_CATEGORY_ORDER = [
    "Milestones", "Budget", "Early Activities", "Design Firm", "Long Lead Items",
    "Site Activities", "Project Finance", "Project Documents",
    "Other Deliverables after Contract Signature", "Other",
]
_GANTT_WBS_CATEGORIES: dict[str, str] = {
    # Milestones
    "1.1": "Milestones", "1.2": "Milestones", "1.3": "Milestones",
    "1.4": "Milestones", "1.5": "Milestones", "1.6": "Milestones",
    # Budget
    "2.1": "Budget", "2.13": "Budget", "6.1": "Budget", "6.2": "Budget",
    # Early Activities
    "4.1": "Early Activities", "2.6": "Early Activities", "2.14": "Early Activities", "3.11": "Early Activities",
    # Design Firm
    "4.3": "Design Firm", "3.9": "Design Firm", "4.4": "Design Firm", "2.7": "Design Firm",
    # 3.10 wasn't in "Gantt chart WBS.xlsx" at all (fell into "Other" by
    # default) -- issuing the Design Firm's own agreement/PO is clearly
    # part of the same flow as the rest of this category.
    "3.10": "Design Firm",
    # Long Lead Items
    "4.5": "Long Lead Items", "2.2": "Long Lead Items", "3.1": "Long Lead Items", "3.2": "Long Lead Items",
    "4.6": "Long Lead Items", "4.2": "Long Lead Items", "3.3": "Long Lead Items", "3.4": "Long Lead Items",
    "3.5": "Long Lead Items", "3.6": "Long Lead Items", "3.7": "Long Lead Items", "3.8": "Long Lead Items",
    "2.18": "Long Lead Items",
    # Site Activities (includes the sheet's unlabeled "2.10."-headed rows --
    # topography/geotechnical site investigation, same theme)
    "2.3": "Site Activities", "2.17": "Site Activities", "2.11": "Site Activities", "2.4": "Site Activities",
    "2.16": "Site Activities", "16.1": "Site Activities", "2.9": "Site Activities", "4.7": "Site Activities",
    "2.8": "Site Activities",
    # 2.10 (permits) wasn't in the sheet either -- governmental/local
    # authority permitting is site-work logistics, same theme as the rest
    # of this category.
    "2.10": "Site Activities",
    # Project Finance
    "10.1": "Project Finance", "9.1": "Project Finance", "9.2": "Project Finance",
    # Project Documents
    "12.3": "Project Documents", "11.2": "Project Documents", "8.1": "Project Documents",
    "11.1": "Project Documents", "12.1": "Project Documents", "12.4": "Project Documents",
    "12.5": "Project Documents", "2.15": "Project Documents", "3.12": "Project Documents",
    "2.5": "Project Documents", "4.8": "Project Documents", "5.1": "Project Documents",
    "5.3": "Project Documents", "2.12": "Project Documents", "5.2": "Project Documents",
    "5.4": "Project Documents", "14.1": "Project Documents",
    # 12.2 (HSSE Staffing plan) wasn't in the sheet either -- its sibling
    # 11.2 (Quality Staffing plan) already sits in this category, same item
    # split across departments the same way Risk Register etc. are.
    "12.2": "Project Documents",
    # Other Deliverables after Contract Signature
    "7.1": "Other Deliverables after Contract Signature", "15.1": "Other Deliverables after Contract Signature",
    "10.2": "Other Deliverables after Contract Signature", "9.3": "Other Deliverables after Contract Signature",
    "6.3": "Other Deliverables after Contract Signature",
}


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


def _wbs_category(d: models.DeliverableDefinition) -> str | None:
    """None for L0 (the WBS sheet only covers L1) so the frontend keeps L0
    flat, ungrouped, exactly as before this feature.
    """
    if d.stage != models.Stage.L1:
        return None
    return _GANTT_WBS_CATEGORIES.get(d.item_no, "Other")


def _category_sort_index(category: str | None) -> int:
    """L0 rows (category=None) all share index 0, so they sort purely by
    start date among themselves -- unchanged, ungrouped behavior.
    """
    if category is None:
        return 0
    try:
        return GANTT_WBS_CATEGORY_ORDER.index(category)
    except ValueError:
        return len(GANTT_WBS_CATEGORY_ORDER)


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
    seen_item_nos = set()  # Operation Units' TBU/PBU/DBU/BBU split means the same
    # item_no can have several submissions on one project -- one bar per
    # item_no is plenty for a schedule view, so only the first (by the sort
    # above) of each is kept.
    for s in subs:
        d = s.definition
        if s.due_date is None:
            continue  # unscheduled: client-dependent not yet approved, or library/on_request items
        if s.auto_completed:
            continue  # items 115/116: not real tracked work, keep off the chart
        if d.stage == models.Stage.L0 and d.item_no in _GANTT_L0_EXCLUDED_ITEMS:
            continue
        if d.item_no in seen_item_nos:
            continue
        seen_item_nos.add(d.item_no)
        start = _bar_start(db, project, d, s.due_date) or s.due_date
        if start > s.due_date:
            start = s.due_date
        rows.append({
            "item_no": d.item_no, "name": rules.display_name(d, project), "short_name": d.short_name or d.name,
            "department": d.department.name, "department_number": d.department.number, "submission_id": s.id,
            "start": start, "end": s.due_date, "status": s.status.value, "deadline_status": rules.deadline_status(s)[0],
            "is_milestone": d.is_milestone, "milestone_code": d.milestone_code, "category": _wbs_category(d),
        })
    rows.sort(key=lambda r: (_category_sort_index(r["category"]), r["start"], r["end"], rules.item_sort_key(r["item_no"])))
    return rows


@router.get("/timeline")
def get_stage_timeline(stage: str, db: Session = Depends(get_db)):
    """Every active project's deliverable-level bars for one stage, pooled
    together (not grouped by project) and sorted by start date — e.g. item
    3.3 from one project can sit right next to item 2.1 from another,
    whichever starts sooner.
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
        seen_item_nos = set()  # (project_id, item_no) -- same dedup as get_project_gantt,
        # keyed per-project here since pooling must NOT collapse the same
        # item_no across different projects.
        for s in subs:
            if s.due_date is None:
                continue  # unscheduled: client-dependent not yet approved, or library/on_request items
            if s.auto_completed:
                continue  # items 115/116: not real tracked work, keep off the chart
            d = s.definition
            if d.stage == models.Stage.L0 and d.item_no in _GANTT_L0_EXCLUDED_ITEMS:
                continue
            if (s.project_id, d.item_no) in seen_item_nos:
                continue
            seen_item_nos.add((s.project_id, d.item_no))
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
                "is_milestone": d.is_milestone, "milestone_code": d.milestone_code, "category": _wbs_category(d),
            })
    rows.sort(key=lambda r: (_category_sort_index(r["category"]), r["start"], r["end"], r["est_no"], rules.item_sort_key(r["item_no"])))
    return rows

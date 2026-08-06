"""Due-date rule engine, matching the real formulas in L0 Template (Final).xlsx
column O and New L1 Template (Final).xlsx columns I/K/L, verbatim where possible.

Milestones are derived, not stored: a milestone is "reached" exactly when its
linked deliverable (is_milestone=True) has status APPROVED for that project.
"""
from datetime import date, timedelta
from sqlalchemy.orm import Session

from . import models

# L0 items 1.8/1.9/1.10 branch on whether the project's scope includes PBU —
# the one recurring conditional pattern in the real template. Not exposed as
# a form field yet (Modifications doc doesn't ask for one), so it defaults
# false; the branch is implemented so it's correct the day that field exists.
PBU_CONDITIONAL_ITEMS = {"1.8", "1.9", "1.10"}


def item_sort_key(item_no: str):
    """Numeric sort key for item numbers like '1.10' — plain string sort
    would put '1.10' before '1.2', since '1' < '2' lexicographically.
    """
    try:
        return tuple(int(p) for p in item_no.split("."))
    except ValueError:
        return (999, 999)


def _skip_weekend_forward(d: date) -> date:
    while d.weekday() in (4, 5):  # Friday=4, Saturday=5
        d += timedelta(days=1)
    return d


def _skip_weekend_backward(d: date) -> date:
    while d.weekday() in (4, 5):
        d -= timedelta(days=1)
    return d


def _get_submission(db: Session, project_id: int, item_no: str, stage) -> "models.DeliverableSubmission | None":
    return (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .filter(
            models.DeliverableSubmission.project_id == project_id,
            models.DeliverableDefinition.item_no == item_no,
            models.DeliverableDefinition.stage == stage,
        )
        .first()
    )


def compute_due_date(db: Session, definition: models.DeliverableDefinition, project: models.Project) -> date | None:
    """Resolves a deliverable definition's due date for a specific project."""
    anchor_type = definition.anchor_type

    if anchor_type == "announcement":
        anchor = project.announcement_date
        if anchor is None:
            return None
        result = anchor + timedelta(days=definition.offset_days or 0)
        return _skip_weekend_forward(result)

    if anchor_type == "bsd":
        anchor = project.bsd
        if anchor is None:
            return None
        result = anchor - timedelta(days=definition.offset_days or 0)
        return _skip_weekend_backward(result)

    if anchor_type == "site_visit":
        anchor = project.site_visit_date
        if anchor is None:
            return None  # optional field — stays undated until it's provided
        result = anchor + timedelta(days=definition.offset_days or 0)
        return _skip_weekend_forward(result)

    if anchor_type == "pre_bid":
        # Modifications doc: if Pre-Bid Clarification Deadline isn't entered,
        # treat the deadline as immediate — i.e. today, not undated.
        anchor = project.pre_bid_deadline or date.today()
        result = anchor - timedelta(days=definition.offset_days or 0)
        return _skip_weekend_backward(result)

    if anchor_type == "predecessor":
        pred_item_no = definition.predecessor_item_no
        # PBU-conditional branch (L0 items 1.8/1.9/1.10): if scope includes PBU,
        # anchor to 4.4 + 1 workday instead of the normal M1-anchored chain.
        if definition.item_no in PBU_CONDITIONAL_ITEMS and getattr(project, "scope_contains_pbu", False):
            pred_item_no = "4.4"
            pred_sub = _get_submission(db, project.id, pred_item_no, definition.stage)
            if pred_sub is None or pred_sub.due_date is None:
                return None
            return _skip_weekend_forward(pred_sub.due_date + timedelta(days=1))

        if not pred_item_no:
            return None
        pred_sub = _get_submission(db, project.id, pred_item_no, definition.stage)
        if pred_sub is None or pred_sub.due_date is None:
            return None
        offset = definition.offset_days or 0
        if definition.offset_direction == "before":
            result = pred_sub.due_date - timedelta(days=offset)
            return _skip_weekend_backward(result)
        else:
            result = pred_sub.due_date + timedelta(days=offset)
            return _skip_weekend_forward(result)

    # "client_dependent" and library/on_request (anchor_type is None) both have no computable date.
    return None


def refresh_status(submission: models.DeliverableSubmission) -> None:
    """Recomputes status from due_date + submission state. Doesn't touch
    pending_review/approved/rejected — those only change through the
    submit/approve/reject actions, not by the passage of time.
    """
    if submission.status in (
        models.SubmissionStatus.PENDING_REVIEW,
        models.SubmissionStatus.APPROVED,
        models.SubmissionStatus.REJECTED,
    ):
        return
    if submission.due_date is None:
        submission.status = models.SubmissionStatus.NOT_DUE
        return
    submission.status = (
        models.SubmissionStatus.OVERDUE if date.today() > submission.due_date else models.SubmissionStatus.NOT_DUE
    )


def recompute_project_due_dates(db: Session, project: models.Project) -> None:
    """Recomputes every submission's due date for a project, in an order that
    lets predecessor chains resolve (announcement/bsd roots first, then
    predecessor-chained items, repeated until stable — chains in the real
    templates are shallow, a few passes is always enough).
    """
    subs = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .filter(models.DeliverableSubmission.project_id == project.id)
        .all()
    )
    for _pass in range(6):
        changed = False
        for s in subs:
            # Once approved, a submission's due_date is frozen — this matters most for
            # "client_dependent" items (Contract Signing, LOA, etc.): approving one
            # freezes its due_date to the real approval date, so downstream
            # predecessor-chained items get a real anchor instead of staying
            # unresolvable forever. Recomputing it would wipe that back to None.
            if s.status == models.SubmissionStatus.APPROVED:
                continue
            new_due = compute_due_date(db, s.definition, project)
            if new_due != s.due_date:
                s.due_date = new_due
                changed = True
            refresh_status(s)
        if not changed:
            break


def kpi_points(due_date: date | None, submitted_date: date | None, grace_days: int = 4) -> float | None:
    """The Calculation Criteria rule from architecture_map.md section 4.3, verbatim."""
    if due_date is None:
        return None
    if submitted_date is None:
        return 0.0 if date.today() > due_date else None
    days_late = (submitted_date - due_date).days - grace_days
    if days_late <= 0:
        return 1.0
    if days_late <= 7:
        return 0.9
    if days_late <= 14:
        return 0.8
    if days_late <= 21:
        return 0.7
    if days_late <= 28:
        return 0.6
    return 0.0

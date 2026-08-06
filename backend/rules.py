"""Due-date rule engine — same logic documented in architecture_map.md section 4.1,
now actually executable instead of described. Friday/Saturday weekend, milestone-
or predecessor-anchored offsets.
"""
from datetime import date, timedelta
from sqlalchemy.orm import Session

from . import models


def _skip_weekend_forward(d: date) -> date:
    while d.weekday() in (4, 5):  # Friday=4, Saturday=5
        d += timedelta(days=1)
    return d


def _skip_weekend_backward(d: date) -> date:
    while d.weekday() in (4, 5):
        d -= timedelta(days=1)
    return d


def compute_due_date(db: Session, definition: models.DeliverableDefinition, project: models.Project) -> date | None:
    """Resolves a deliverable definition's due date for a specific project."""
    anchor: date | None = None

    if definition.anchor_type == "milestone" and definition.anchor_milestone_code:
        event = (
            db.query(models.MilestoneEvent)
            .join(models.MilestoneDefinition)
            .filter(
                models.MilestoneEvent.project_id == project.id,
                models.MilestoneDefinition.code == definition.anchor_milestone_code,
            )
            .first()
        )
        if event:
            anchor = event.actual_date or event.planned_date

    elif definition.anchor_type == "predecessor" and definition.predecessor_item_no:
        pred_submission = (
            db.query(models.DeliverableSubmission)
            .join(models.DeliverableDefinition)
            .filter(
                models.DeliverableSubmission.project_id == project.id,
                models.DeliverableDefinition.item_no == definition.predecessor_item_no,
            )
            .first()
        )
        if pred_submission:
            anchor = pred_submission.due_date

    if anchor is None:
        return None

    offset = definition.offset_days or 0
    if definition.offset_direction == "before":
        result = anchor - timedelta(days=offset)
        return _skip_weekend_backward(result)
    else:
        result = anchor + timedelta(days=offset)
        return _skip_weekend_forward(result)


def refresh_status(submission: models.DeliverableSubmission) -> None:
    """Recomputes status from due_date + submission state. Doesn't touch
    approved/rejected/pending_review — those only change through the
    approve/reject/submit actions themselves, not by the passage of time.
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

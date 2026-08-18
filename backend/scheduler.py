"""In-process nightly checks (item [due-soon nudge] / [request escalation]).

A plain asyncio loop started from main.py's startup hook, not a host-specific
cron service -- this way it ships as ordinary app code and behaves the same
whether it's running on Render or on the company's own server later, with
nothing to reconfigure on migration. Runs once immediately at startup (so a
restart never loses more than the time it was down) and then every hour;
every check below is idempotent via a stored marker, so an hourly tick costs
nothing extra on a day where nothing is due.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from . import models, rules, announcements
from .database import SessionLocal

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 3600
ESCALATE_AFTER_DAYS = 3
# Statuses where the Owner still has a real action to take -- a completed,
# rejected-and-not-yet-reworked... no: REJECTED *is* an owner action state
# (they need to resubmit), only PENDING_REVIEW (already submitted, waiting
# on someone else) and the terminal/no-due-date statuses are excluded.
_DUE_SOON_ELIGIBLE = {models.SubmissionStatus.NO_PROGRESS, models.SubmissionStatus.IN_PROGRESS,
                      models.SubmissionStatus.REJECTED}


def _run_due_soon_check(db: Session) -> None:
    tomorrow = date.today() + timedelta(days=1)
    subs = (
        db.query(models.DeliverableSubmission)
        .join(models.Project)
        .filter(models.Project.status == models.ProjectStatus.IN_PROGRESS,
                models.DeliverableSubmission.due_date == tomorrow,
                models.DeliverableSubmission.status.in_(_DUE_SOON_ELIGIBLE),
                models.DeliverableSubmission.auto_completed.isnot(True),
                models.DeliverableSubmission.on_hold.isnot(True))
        .all()
    )
    for s in subs:
        if s.due_soon_reminded_for_date == s.due_date:
            continue
        owner_emails = rules.resolve_owners(s)
        if owner_emails:
            announcements.due_soon_reminder(db, s.project, owner_emails, s.definition.item_no,
                                             s.definition.name, s.due_date, submission_id=s.id)
        s.due_soon_reminded_for_date = s.due_date
        db.commit()


def _run_escalation_check(db: Session) -> None:
    cutoff = datetime.utcnow() - timedelta(days=ESCALATE_AFTER_DAYS)
    reqs = (
        db.query(models.DueDateRequest)
        .filter(models.DueDateRequest.status == "pending",
                models.DueDateRequest.escalated_at.is_(None),
                models.DueDateRequest.requested_at <= cutoff)
        .all()
    )
    if not reqs:
        return
    admins = rules.admin_emails(db)
    for r in reqs:
        sub = r.submission
        sme_emails = rules.resolve_smes(sub)
        recipients = sorted({e.strip().lower() for e in (list(sme_emails) + list(admins)) if e})
        days_pending = (datetime.utcnow() - r.requested_at).days
        announcements.due_date_request_escalated(db, sub.project, recipients, sub.definition.item_no,
                                                   sub.definition.name, r.kind, days_pending, submission_id=sub.id)
        r.escalated_at = datetime.utcnow()
        db.commit()


def run_daily_checks() -> None:
    db = SessionLocal()
    try:
        _run_due_soon_check(db)
        _run_escalation_check(db)
    except Exception:
        logger.exception("Scheduled reminder check failed")
        db.rollback()
    finally:
        db.close()


async def scheduler_loop() -> None:
    while True:
        await asyncio.to_thread(run_daily_checks)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

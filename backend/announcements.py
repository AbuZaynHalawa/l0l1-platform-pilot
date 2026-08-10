"""Announcement/notification service — the real version of the pitch demo's
pushAnnouncement() mechanism. Every call here does two things: persists an
Announcement row (so the Announcements page and dashboards read one shared
history) and actually sends mail through whichever MailProvider is configured.
"""
from sqlalchemy.orm import Session

from . import models
from .providers.mail import get_mail_provider

_mail = get_mail_provider()


def _create(db: Session, *, type: models.AnnouncementType, title: str, body: str,
            recipients: list[str], project: models.Project | None = None,
            submission_id: int | None = None) -> models.Announcement:
    status = _mail.send_mail(recipients, title, body) if recipients else "simulated"
    ann = models.Announcement(
        type=type, title=title, body=body,
        recipients=", ".join(recipients) if recipients else "",
        project_id=project.id if project else None,
        submission_id=submission_id,
        email_status=status,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return ann


def project_created(db: Session, project: models.Project, recipients: list[str]) -> models.Announcement:
    if project.stage == models.Stage.L1:
        title = "L1 Stage Commenced"
        body = (f"{project.est_no} &#8211; {project.name} has entered L1. Deliverables for M1 &amp; M2 are "
                f"attached; M3&#8211;M6 will be announced as each milestone is reached.")
    else:
        title = "New L0 Tender Announced"
        body = (f"{project.est_no} &#8211; {project.name}. Deliverables list and due dates attached, "
                f"shared folder provisioned automatically.")
    return _create(db, type=models.AnnouncementType.BROADCAST, title=title, body=body,
                    recipients=recipients, project=project)


def owner_assigned(db: Session, project: models.Project, owner_email: str, dept_name: str, count: int) -> models.Announcement:
    title = "Deliverables Assigned to You"
    body = f"{count} deliverable(s) on {project.est_no} are due, with due dates and a link to your folder."
    return _create(db, type=models.AnnouncementType.OWNER, title=title, body=body,
                    recipients=[owner_email], project=project)


def sme_review_requested(db: Session, project: models.Project, sme_email: str, item_no: str, item_name: str,
                          submission_id: int | None = None) -> models.Announcement:
    title = "Review Requested &#8211; SME Action Needed"
    body = (f"{item_no} {item_name} was submitted on {project.est_no} and is now awaiting your review. "
            f"<b>You have 1 day to review and submit feedback.</b>")
    return _create(db, type=models.AnnouncementType.SME_REQUEST, title=title, body=body,
                    recipients=[sme_email], project=project, submission_id=submission_id)


def sme_decision(db: Session, project: models.Project, owner_email: str, item_no: str, item_name: str,
                  approved: bool, comment: str | None = None, submission_id: int | None = None) -> models.Announcement:
    if approved:
        title = "Deliverable Approved"
        body = f"{item_no} {item_name} on {project.est_no} was reviewed and approved."
    else:
        title = "Deliverable Rejected &#8211; Resubmission Needed"
        note = comment or "Please review and resubmit with updated supporting documents."
        body = f"{item_no} {item_name} on {project.est_no} was rejected: &quot;{note}&quot;"
    ann_type = models.AnnouncementType.SME_DECISION
    return _create(db, type=ann_type, title=title, body=body, recipients=[owner_email], project=project,
                    submission_id=submission_id)


def cross_department_unlock(db: Session, project: models.Project, newly_active_owner_email: str,
                             trigger_item: str, unlocked_item_no: str, unlocked_item_name: str,
                             submission_id: int | None = None) -> models.Announcement:
    title = "Deliverable Unlocked &#8211; Predecessor Approved"
    body = (f"{trigger_item} being approved on {project.est_no} unlocks "
            f"{unlocked_item_no} {unlocked_item_name}.")
    return _create(db, type=models.AnnouncementType.UNLOCK, title=title, body=body,
                    recipients=[newly_active_owner_email], project=project, submission_id=submission_id)


def deadline_extended(db: Session, project: models.Project, recipients: list[str], old_date: str, new_date: str) -> models.Announcement:
    title = "Bid Submission Date Extended"
    body = f"{project.est_no} &#8211; {project.name}: BSD moved from {old_date} to {new_date}. All dependent due dates recalculated automatically."
    return _create(db, type=models.AnnouncementType.DEADLINE, title=title, body=body,
                    recipients=recipients, project=project)


def milestone_reached(db: Session, project: models.Project, recipients: list[str], code: str, name: str) -> models.Announcement:
    title = f"{code} Reached &#8211; {name}"
    body = (f"{project.est_no} &#8211; {project.name}: milestone {code} ({name}) has been reached. "
            f"Please find the updated deliverables and due dates reflecting this on the project page.")
    return _create(db, type=models.AnnouncementType.DEADLINE, title=title, body=body,
                    recipients=recipients, project=project)


def reminder_sent(db: Session, project: models.Project, owner_email: str, item_no: str, item_name: str,
                   due_date, submission_id: int | None = None) -> models.Announcement:
    title = f"Reminder &#8211; {item_no} is due"
    due_str = due_date.isoformat() if due_date else "unspecified"
    body = f"{item_no} {item_name} on {project.est_no} is due ({due_str}). Please submit as soon as possible."
    return _create(db, type=models.AnnouncementType.DEADLINE, title=title, body=body,
                    recipients=[owner_email], project=project, submission_id=submission_id)


def followers_notified(db: Session, project: models.Project, recipients: list[str],
                        item_no: str, item_name: str, event_label: str,
                        submission_id: int | None = None) -> models.Announcement | None:
    if not recipients:
        return None
    title = f"Followed Item Update &#8211; {item_no}"
    body = f"{item_no} {item_name} on {project.est_no} was just {event_label}."
    return _create(db, type=models.AnnouncementType.DEADLINE, title=title, body=body,
                    recipients=recipients, project=project, submission_id=submission_id)


def project_closed(db: Session, project: models.Project, recipients: list[str]) -> models.Announcement:
    title = "Project Closed"
    reason = "Contract Signed" if project.stage == models.Stage.L1 else "Bid Submitted"
    body = f"{project.est_no} &#8211; {project.name} is now closed ({reason})."
    return _create(db, type=models.AnnouncementType.CLOSED, title=title, body=body,
                    recipients=recipients, project=project)

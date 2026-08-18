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


def sme_review_requested(db: Session, project: models.Project, sme_emails: list[str], item_no: str, item_name: str,
                          submission_id: int | None = None, owner_emails: list[str] | None = None) -> models.Announcement:
    """Item 165: the Owner(s) who asked for review need to see this too, not
    just the SME(s) who have to act on it -- all are recipients now. Item
    [multi-SME/owner]: every assigned SME and every assigned Owner is a
    recipient, since any one of the SMEs can act on it.
    """
    title = "Review Requested &#8211; SME Action Needed"
    body = (f"{item_no} {item_name} was submitted on {project.est_no} and is now awaiting your review. "
            f"<b>You have 1 day to review and submit feedback.</b>")
    recipients = sorted({e for e in (list(sme_emails) + list(owner_emails or [])) if e})
    return _create(db, type=models.AnnouncementType.SME_REQUEST, title=title, body=body,
                    recipients=recipients, project=project, submission_id=submission_id)


def document_added(db: Session, project: models.Project, sme_emails: list[str], item_no: str, item_name: str,
                    file_name: str, submission_id: int | None = None) -> models.Announcement:
    """Item 165: general news (everyone sees it, per the DOC_ADDED type),
    while still emailing every assigned SME directly since they're the ones
    who need to act on it.
    """
    title = "Document Added &#8211; New Supporting File"
    body = f"{file_name} was added to {item_no} {item_name} on {project.est_no}."
    return _create(db, type=models.AnnouncementType.DOC_ADDED, title=title, body=body,
                    recipients=sorted({e for e in sme_emails if e}), project=project, submission_id=submission_id)


def sme_decision(db: Session, project: models.Project, owner_emails: list[str], item_no: str, item_name: str,
                  approved: bool, comment: str | None = None, submission_id: int | None = None) -> models.Announcement:
    """Item 165: an approval is general news (DELIVERABLE_APPROVED, everyone
    sees it) same as a milestone or unlock; a rejection stays private
    feedback to the Owner(s) (SME_DECISION), not something to broadcast.
    Item [multi-owner]: every assigned Owner is a recipient on a rejection.
    """
    if approved:
        title = "Deliverable Approved"
        body = f"{item_no} {item_name} on {project.est_no} was reviewed and approved."
        ann_type = models.AnnouncementType.DELIVERABLE_APPROVED
    else:
        title = "Deliverable Rejected &#8211; Resubmission Needed"
        note = comment or "Please review and resubmit with updated supporting documents."
        body = f"{item_no} {item_name} on {project.est_no} was rejected: &quot;{note}&quot;"
        ann_type = models.AnnouncementType.SME_DECISION
    return _create(db, type=ann_type, title=title, body=body, recipients=sorted({e for e in owner_emails if e}),
                    project=project, submission_id=submission_id)


def due_date_request(db: Session, project: models.Project, sme_emails: list[str], owner_emails: list[str],
                      item_no: str, item_name: str, kind: str, reason: str,
                      submission_id: int | None = None) -> models.Announcement:
    """Item [due-date requests]: an Owner asked for an extension or a hold on
    one deliverable -- notify the assigned SME(s) (who can decide) and, per
    the sme_review_requested precedent, the requesting Owner(s) too so they
    have a record it went out.
    """
    label = "Extension" if kind == "extension" else "Hold"
    title = f"{label} Requested &#8211; SME Action Needed"
    body = (f"{item_no} {item_name} on {project.est_no}: a {label.lower()} was requested &#8211; "
            f"&quot;{reason}&quot;. Awaiting your decision.")
    ann_type = models.AnnouncementType.EXTENSION_REQUEST if kind == "extension" else models.AnnouncementType.HOLD_REQUEST
    recipients = sorted({e for e in (list(sme_emails) + list(owner_emails)) if e})
    return _create(db, type=ann_type, title=title, body=body,
                    recipients=recipients, project=project, submission_id=submission_id)


def due_date_decision(db: Session, project: models.Project, owner_emails: list[str], item_no: str, item_name: str,
                       kind: str, approved: bool, comment: str | None = None,
                       submission_id: int | None = None) -> models.Announcement:
    """Item [due-date requests]: notify the requesting Owner(s) of the
    SME/Admin's decision -- private feedback either way (unlike a normal
    approval, this isn't general program news), same treatment sme_decision
    gives a rejection.
    """
    label = "Extension" if kind == "extension" else "Hold"
    if approved:
        title = f"{label} Approved"
        body = f"{item_no} {item_name} on {project.est_no}: your {label.lower()} request was approved."
    else:
        title = f"{label} Rejected"
        note = comment or "No reason given."
        body = f"{item_no} {item_name} on {project.est_no}: your {label.lower()} request was rejected: &quot;{note}&quot;"
    ann_type = models.AnnouncementType.EXTENSION_DECISION if kind == "extension" else models.AnnouncementType.HOLD_DECISION
    return _create(db, type=ann_type, title=title, body=body, recipients=sorted({e for e in owner_emails if e}),
                    project=project, submission_id=submission_id)


def due_date_request_escalated(db: Session, project: models.Project, recipients: list[str],
                                item_no: str, item_name: str, kind: str, days_pending: int,
                                submission_id: int | None = None) -> models.Announcement:
    """Item [request escalation]: the nightly check's nudge for a due-date
    request nobody has decided on after 3 days -- same SME(s) as the
    original ask, plus every Admin as a fallback (an SME might have missed
    the first notification entirely; Admin can decide any item regardless
    of assignment). Fires once per request -- see DueDateRequest.escalated_at.
    """
    label = "Extension" if kind == "extension" else "Hold"
    title = f"Still Pending &#8211; {label} Request Needs a Decision"
    body = (f"{item_no} {item_name} on {project.est_no}: a {label.lower()} request has been waiting "
            f"{days_pending} days with no decision. Please review it.")
    ann_type = models.AnnouncementType.EXTENSION_REQUEST if kind == "extension" else models.AnnouncementType.HOLD_REQUEST
    return _create(db, type=ann_type, title=title, body=body, recipients=sorted({e for e in recipients if e}),
                    project=project, submission_id=submission_id)


def due_soon_reminders_batch(db: Session, owner_email: str, offset_days: int,
                              items: list[dict]) -> models.Announcement:
    """Item [due-soon nudge]: one consolidated email per Owner per threshold,
    not one per deliverable -- an Owner with 6 items due the same day gets a
    single email listing all 6, not 6 separate ones. `items` all share the
    same due date (the scheduler only batches same-day, same-threshold
    items): [{"est_no", "item_no", "name"}, ...]. Spans potentially several
    projects, so this isn't tied to one project/submission_id the way a
    single-item announcement is -- the detail lives in the body instead.
    """
    when = "tomorrow" if offset_days == 1 else f"in {offset_days} days"
    title = "Due Tomorrow" if offset_days == 1 else f"Due in {offset_days} Days"
    if len(items) > 1:
        title += f" &#8211; {len(items)} Deliverables"
    lines = "".join(f"&#8226; {it['item_no']} {it['name']} ({it['est_no']})<br>" for it in items)
    body = f"The following deliverable(s) are due {when}:<br>{lines}"
    return _create(db, type=models.AnnouncementType.DEADLINE, title=title, body=body, recipients=[owner_email])


def cross_department_unlock(db: Session, project: models.Project, newly_active_owner_emails: list[str],
                             trigger_item: str, unlocked_item_no: str, unlocked_item_name: str,
                             submission_id: int | None = None) -> models.Announcement:
    title = "Deliverable Unlocked &#8211; Predecessor Approved"
    body = (f"{trigger_item} being approved on {project.est_no} unlocks "
            f"{unlocked_item_no} {unlocked_item_name}.")
    return _create(db, type=models.AnnouncementType.UNLOCK, title=title, body=body,
                    recipients=sorted({e for e in newly_active_owner_emails if e}), project=project, submission_id=submission_id)


def deadline_extended(db: Session, project: models.Project, recipients: list[str], old_date: str, new_date: str) -> models.Announcement:
    title = "Bid Submission Date Extended"
    body = f"{project.est_no} &#8211; {project.name}: BSD moved from {old_date} to {new_date}. All dependent due dates recalculated automatically."
    return _create(db, type=models.AnnouncementType.BSD_EXTENDED, title=title, body=body,
                    recipients=recipients, project=project)


def milestone_reached(db: Session, project: models.Project, recipients: list[str], code: str, name: str) -> models.Announcement:
    title = f"{code} Reached &#8211; {name}"
    body = (f"{project.est_no} &#8211; {project.name}: milestone {code} ({name}) has been reached. "
            f"Please find the updated deliverables and due dates reflecting this on the project page.")
    return _create(db, type=models.AnnouncementType.MILESTONE, title=title, body=body,
                    recipients=recipients, project=project)


def triage_reminder(db: Session, project: models.Project, bm_email: str, pending_count: int) -> models.Announcement:
    """Item 79's "Remind" action on the admin BM Triage Status page — nudges
    the assigned Bid Manager that they still have pending applicable/
    not-required calls to make, project-level (no single submission_id).
    """
    title = f"Reminder &#8211; BM Triage still pending on {project.est_no}"
    body = f"{project.est_no} &#8211; {project.name} still has {pending_count} deliverable(s) awaiting your applicable / not-required call."
    return _create(db, type=models.AnnouncementType.DEADLINE, title=title, body=body,
                    recipients=[bm_email], project=project)


def reminder_sent(db: Session, project: models.Project, owner_email: str, item_no: str, item_name: str,
                   due_date, submission_id: int | None = None, custom_message: str | None = None,
                   cc: list[str] | None = None) -> models.Announcement:
    title = f"Reminder &#8211; {item_no} is due"
    if custom_message:
        body = custom_message
    else:
        due_str = due_date.isoformat() if due_date else "unspecified"
        body = f"{item_no} {item_name} on {project.est_no} is due ({due_str}). Please submit as soon as possible."
    recipients = [owner_email] + [c for c in (cc or []) if c and c.lower() != owner_email.lower()]
    return _create(db, type=models.AnnouncementType.DEADLINE, title=title, body=body,
                    recipients=recipients, project=project, submission_id=submission_id)


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

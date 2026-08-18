"""Announcement/notification service — the real version of the pitch demo's
pushAnnouncement() mechanism. Every call here does two things: persists an
Announcement row (so the Announcements page and dashboards read one shared
history) and actually sends mail through whichever MailProvider is configured.
"""
import os
from sqlalchemy.orm import Session

from . import models
from .providers.mail import get_mail_provider

_mail = get_mail_provider()

# Item [deep links]: APP_BASE_URL defaults to the current Render pilot URL so
# links work with zero setup today, but is meant to be overridden via env
# var once this moves to the company's own domain -- no code change needed
# then, same portability approach as the scheduler.
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://l0l1-platform.onrender.com").rstrip("/")

# Item [keyword highlighting]: darker, email-safe shades of the app's own
# semantic palette (good/crit/warn in styles.css) -- the UI's lighter shades
# are tuned for pill backgrounds, too low-contrast for plain body text on a
# white email background.
_COLORS = {"good": "#1e7e42", "crit": "#c0392b", "warn": "#b9770e"}


def _b(text) -> str:
    """Neutral emphasis -- item numbers and Est numbers, the reference keys
    a reader scans for first."""
    return f"<b>{text}</b>"


def _hl(text, kind: str) -> str:
    """Colored emphasis for the one word/phrase in a message that carries
    its actual news -- approved/rejected/overdue/etc."""
    return f'<b style="color:{_COLORS.get(kind, "#2c3e50")};">{text}</b>'


def _deliverable_link(submission_id: int, label: str = "Open in the platform") -> str:
    return f'<a href="{APP_BASE_URL}/#deliverable={submission_id}">{label} &#8594;</a>'


def _project_link(project_id: int, label: str = "Open in the platform") -> str:
    return f'<a href="{APP_BASE_URL}/#project={project_id}">{label} &#8594;</a>'


# Item [email signature]: applied once, centrally, in _create() below rather
# than pasted into all sixteen functions above -- one source of truth means
# every announcement type (including any added later) gets the same
# logo/sign-off automatically, with nothing to keep in sync by hand. Inline
# styles throughout, not a <style> block or CSS classes -- most email
# clients (Outlook/Graph included) strip external and <head> CSS entirely.
def _signature_html() -> str:
    return (
        '<div style="margin-top:24px;padding-top:16px;border-top:1px solid #e2e5ee;'
        'font-family:Segoe UI,Arial,sans-serif;">'
        f'<img src="{APP_BASE_URL}/static/logo.png" alt="Algihaz" style="height:26px;display:block;margin-bottom:6px;">'
        '<div style="font-size:12px;color:#65718c;">Algihaz &#8211; Integrated Program (L0/L1) Platform</div>'
        '</div>'
    )


def _create(db: Session, *, type: models.AnnouncementType, title: str, body: str,
            recipients: list[str], project: models.Project | None = None,
            submission_id: int | None = None, greeting: str = "Team") -> models.Announcement:
    """`greeting` names the role this message is actually addressed to (SME,
    Owner, Bid Manager...), not a per-recipient lookup -- a single call can
    still go to a mixed list (e.g. SME(s) + the requesting Owner together),
    so this is the primary audience the copy is written for, not a promise
    every recipient holds that exact role. Defaults to "Team" for the
    portal-wide broadcasts that have no one primary role.
    """
    greeting_html = f'<p style="margin:0 0 14px;">Dear {greeting},</p>'
    full_body = greeting_html + body + _signature_html()
    status = _mail.send_mail(recipients, title, full_body) if recipients else "simulated"
    ann = models.Announcement(
        type=type, title=title, body=full_body,
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
        body = (f"{_b(project.est_no)} &#8211; {project.name} has entered {_hl('L1', 'good')}. Deliverables for "
                f"M1 &amp; M2 are attached; M3&#8211;M6 will be announced as each milestone is reached.")
    else:
        title = "New L0 Tender Announced"
        body = (f"{_b(project.est_no)} &#8211; {project.name}. Deliverables list and due dates attached, "
                f"shared folder provisioned automatically.")
    body += f"<br><br>{_project_link(project.id)}"
    return _create(db, type=models.AnnouncementType.BROADCAST, title=title, body=body,
                    recipients=recipients, project=project, greeting="Team")


def owner_assigned(db: Session, project: models.Project, owner_email: str, dept_name: str, count: int) -> models.Announcement:
    title = "Deliverables Assigned to You"
    body = (f"{_b(count)} deliverable(s) on {_b(project.est_no)} are due, with due dates in your folder.<br><br>"
            f"{_project_link(project.id, 'View your deliverables')}")
    return _create(db, type=models.AnnouncementType.OWNER, title=title, body=body,
                    recipients=[owner_email], project=project, greeting="Owner")


def sme_review_requested(db: Session, project: models.Project, sme_emails: list[str], item_no: str, item_name: str,
                          submission_id: int | None = None, owner_emails: list[str] | None = None) -> models.Announcement:
    """Item 165: the Owner(s) who asked for review need to see this too, not
    just the SME(s) who have to act on it -- all are recipients now. Item
    [multi-SME/owner]: every assigned SME and every assigned Owner is a
    recipient, since any one of the SMEs can act on it.
    """
    title = "Review Requested &#8211; SME Action Needed"
    body = (f"{_b(item_no)} {item_name} was submitted on {_b(project.est_no)} and is now awaiting your review. "
            f"{_hl('You have 1 day to review and submit feedback.', 'warn')}")
    if submission_id is not None:
        body += f"<br><br>{_deliverable_link(submission_id, 'Review it now')}"
    recipients = sorted({e for e in (list(sme_emails) + list(owner_emails or [])) if e})
    return _create(db, type=models.AnnouncementType.SME_REQUEST, title=title, body=body,
                    recipients=recipients, project=project, submission_id=submission_id, greeting="SME")


def document_added(db: Session, project: models.Project, sme_emails: list[str], item_no: str, item_name: str,
                    file_name: str, submission_id: int | None = None) -> models.Announcement:
    """Item 165: general news (everyone sees it, per the DOC_ADDED type),
    while still emailing every assigned SME directly since they're the ones
    who need to act on it.
    """
    title = "Document Added &#8211; New Supporting File"
    body = f"{file_name} was added to {_b(item_no)} {item_name} on {_b(project.est_no)}."
    if submission_id is not None:
        body += f"<br><br>{_deliverable_link(submission_id)}"
    return _create(db, type=models.AnnouncementType.DOC_ADDED, title=title, body=body,
                    recipients=sorted({e for e in sme_emails if e}), project=project, submission_id=submission_id,
                    greeting="SME")


def sme_decision(db: Session, project: models.Project, owner_emails: list[str], item_no: str, item_name: str,
                  approved: bool, comment: str | None = None, submission_id: int | None = None) -> models.Announcement:
    """Item 165: an approval is general news (DELIVERABLE_APPROVED, everyone
    sees it) same as a milestone or unlock; a rejection stays private
    feedback to the Owner(s) (SME_DECISION), not something to broadcast.
    Item [multi-owner]: every assigned Owner is a recipient on a rejection.
    """
    if approved:
        title = "Deliverable Approved"
        body = f"{_b(item_no)} {item_name} on {_b(project.est_no)} was reviewed and {_hl('approved', 'good')}."
        ann_type = models.AnnouncementType.DELIVERABLE_APPROVED
    else:
        title = "Deliverable Rejected &#8211; Resubmission Needed"
        note = comment or "Please review and resubmit with updated supporting documents."
        body = f"{_b(item_no)} {item_name} on {_b(project.est_no)} was {_hl('rejected', 'crit')}: &quot;{note}&quot;"
        ann_type = models.AnnouncementType.SME_DECISION
    if submission_id is not None:
        label = "View it" if approved else "Resubmit it"
        body += f"<br><br>{_deliverable_link(submission_id, label)}"
    return _create(db, type=ann_type, title=title, body=body, recipients=sorted({e for e in owner_emails if e}),
                    project=project, submission_id=submission_id, greeting="Owner")


def due_date_request(db: Session, project: models.Project, sme_emails: list[str], owner_emails: list[str],
                      item_no: str, item_name: str, kind: str, reason: str,
                      submission_id: int | None = None) -> models.Announcement:
    """Item [due-date requests]: an Owner asked for an extension or a hold on
    one deliverable -- notify the assigned SME(s) (who can decide) and, per
    the sme_review_requested precedent, the requesting Owner(s) too so they
    have a record it went out.
    """
    label = "Extension" if kind == "extension" else "Hold"
    article = "an" if kind == "extension" else "a"
    title = f"{label} Requested &#8211; SME Action Needed"
    body = (f"{_b(item_no)} {item_name} on {_b(project.est_no)}: {article} {_hl(label.lower(), 'warn')} was "
            f"requested &#8211; &quot;{reason}&quot;. Awaiting your decision.")
    if submission_id is not None:
        body += f"<br><br>{_deliverable_link(submission_id, 'Decide now')}"
    ann_type = models.AnnouncementType.EXTENSION_REQUEST if kind == "extension" else models.AnnouncementType.HOLD_REQUEST
    recipients = sorted({e for e in (list(sme_emails) + list(owner_emails)) if e})
    return _create(db, type=ann_type, title=title, body=body,
                    recipients=recipients, project=project, submission_id=submission_id, greeting="SME")


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
        body = f"{_b(item_no)} {item_name} on {_b(project.est_no)}: your {label.lower()} request was {_hl('approved', 'good')}."
    else:
        title = f"{label} Rejected"
        note = comment or "No reason given."
        body = (f"{_b(item_no)} {item_name} on {_b(project.est_no)}: your {label.lower()} request was "
                f"{_hl('rejected', 'crit')}: &quot;{note}&quot;")
    if submission_id is not None:
        body += f"<br><br>{_deliverable_link(submission_id)}"
    ann_type = models.AnnouncementType.EXTENSION_DECISION if kind == "extension" else models.AnnouncementType.HOLD_DECISION
    return _create(db, type=ann_type, title=title, body=body, recipients=sorted({e for e in owner_emails if e}),
                    project=project, submission_id=submission_id, greeting="Owner")


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
    article = "an" if kind == "extension" else "a"
    title = f"Still Pending &#8211; {label} Request Needs a Decision"
    body = (f"{_b(item_no)} {item_name} on {_b(project.est_no)}: {article} {label.lower()} request has been "
            f"waiting {_hl(f'{days_pending} days', 'crit')} with no decision. Please review it.")
    if submission_id is not None:
        body += f"<br><br>{_deliverable_link(submission_id, 'Decide now')}"
    ann_type = models.AnnouncementType.EXTENSION_REQUEST if kind == "extension" else models.AnnouncementType.HOLD_REQUEST
    return _create(db, type=ann_type, title=title, body=body, recipients=sorted({e for e in recipients if e}),
                    project=project, submission_id=submission_id, greeting="Team")


def deadline_reminders_batch(db: Session, owner_email: str, offset: int,
                              items: list[dict]) -> models.Announcement:
    """Item [deadline reminders]: one consolidated email per Owner per
    threshold, not one per deliverable -- an Owner with 6 items due (or
    overdue by) the same day gets a single email listing all 6, not 6
    separate ones. `items` all share the same due date (the scheduler only
    batches same-day, same-threshold items):
    [{"est_no", "item_no", "name", "submission_id"}, ...]. Spans potentially
    several projects, so this isn't tied to one project/submission_id the
    way a single-item announcement is -- each row links to its own
    deliverable directly instead (item [deep links]).

    offset < 0: a proactive nudge, N days before due (only -1 in practice).
    offset > 0: an escalating overdue reminder, N days after due (2/7/14).
    """
    if offset < 0:
        days = -offset
        when = "tomorrow" if days == 1 else f"in {days} days"
        title = "Due Tomorrow" if days == 1 else f"Due in {days} Days"
        lead = f"The following deliverable(s) are due {_hl(when, 'warn')}:"
    else:
        day_word = "day" if offset == 1 else "days"
        title = f"Overdue by {offset} {day_word.capitalize()}"
        lead = f"The following deliverable(s) are now {_hl(f'{offset} {day_word} overdue', 'crit')}:"
    if len(items) > 1:
        title += f" &#8211; {len(items)} Deliverables"
    lines = "".join(
        f'&#8226; <a href="{APP_BASE_URL}/#deliverable={it["submission_id"]}">{_b(it["item_no"])} {it["name"]}</a> '
        f'({it["est_no"]})<br>'
        for it in items
    )
    body = f"{lead}<br>{lines}"
    return _create(db, type=models.AnnouncementType.DEADLINE, title=title, body=body, recipients=[owner_email],
                    greeting="Owner")


def cross_department_unlock(db: Session, project: models.Project, newly_active_owner_emails: list[str],
                             trigger_item: str, unlocked_item_no: str, unlocked_item_name: str,
                             submission_id: int | None = None) -> models.Announcement:
    title = "Deliverable Unlocked &#8211; Predecessor Approved"
    body = (f"{_b(trigger_item)} being approved on {_b(project.est_no)} unlocks "
            f"{_b(unlocked_item_no)} {unlocked_item_name}.")
    if submission_id is not None:
        body += f"<br><br>{_deliverable_link(submission_id)}"
    return _create(db, type=models.AnnouncementType.UNLOCK, title=title, body=body,
                    recipients=sorted({e for e in newly_active_owner_emails if e}), project=project,
                    submission_id=submission_id, greeting="Owner")


def deadline_extended(db: Session, project: models.Project, recipients: list[str], old_date: str, new_date: str) -> models.Announcement:
    title = "Bid Submission Date Extended"
    body = (f"{_b(project.est_no)} &#8211; {project.name}: BSD moved from {old_date} to {_hl(new_date, 'warn')}. "
            f"All dependent due dates recalculated automatically.<br><br>{_project_link(project.id)}")
    return _create(db, type=models.AnnouncementType.BSD_EXTENDED, title=title, body=body,
                    recipients=recipients, project=project)


def milestone_reached(db: Session, project: models.Project, recipients: list[str], code: str, name: str) -> models.Announcement:
    title = f"{code} Reached &#8211; {name}"
    body = (f"{_b(project.est_no)} &#8211; {project.name}: milestone {_hl(f'{code} ({name})', 'good')} has been "
            f"reached. Please find the updated deliverables and due dates reflecting this on the project page."
            f"<br><br>{_project_link(project.id)}")
    return _create(db, type=models.AnnouncementType.MILESTONE, title=title, body=body,
                    recipients=recipients, project=project)


def triage_reminder(db: Session, project: models.Project, bm_email: str, pending_count: int) -> models.Announcement:
    """Item 79's "Remind" action on the admin BM Triage Status page — nudges
    the assigned Bid Manager that they still have pending applicable/
    not-required calls to make, project-level (no single submission_id).
    """
    title = f"Reminder &#8211; BM Triage still pending on {project.est_no}"
    body = (f"{_b(project.est_no)} &#8211; {project.name} still has "
            f"{_hl(f'{pending_count} deliverable(s)', 'warn')} awaiting your applicable / not-required call."
            f"<br><br>{_project_link(project.id, 'Triage them now')}")
    return _create(db, type=models.AnnouncementType.DEADLINE, title=title, body=body,
                    recipients=[bm_email], project=project, greeting="Bid Manager")


def reminder_sent(db: Session, project: models.Project, owner_email: str, item_no: str, item_name: str,
                   due_date, submission_id: int | None = None, custom_message: str | None = None,
                   cc: list[str] | None = None) -> models.Announcement:
    title = f"Reminder &#8211; {item_no} is due"
    if custom_message:
        body = custom_message
    else:
        due_str = due_date.isoformat() if due_date else "unspecified"
        body = f"{_b(item_no)} {item_name} on {_b(project.est_no)} is due ({_hl(due_str, 'warn')}). Please submit as soon as possible."
    if submission_id is not None:
        body += f"<br><br>{_deliverable_link(submission_id, 'Submit it now')}"
    recipients = [owner_email] + [c for c in (cc or []) if c and c.lower() != owner_email.lower()]
    return _create(db, type=models.AnnouncementType.DEADLINE, title=title, body=body,
                    recipients=recipients, project=project, submission_id=submission_id, greeting="Owner")


def followers_notified(db: Session, project: models.Project, recipients: list[str],
                        item_no: str, item_name: str, event_label: str,
                        submission_id: int | None = None) -> models.Announcement | None:
    if not recipients:
        return None
    title = f"Followed Item Update &#8211; {item_no}"
    body = f"{_b(item_no)} {item_name} on {_b(project.est_no)} was just {_b(event_label)}."
    if submission_id is not None:
        body += f"<br><br>{_deliverable_link(submission_id)}"
    return _create(db, type=models.AnnouncementType.DEADLINE, title=title, body=body,
                    recipients=recipients, project=project, submission_id=submission_id)


def project_closed(db: Session, project: models.Project, recipients: list[str]) -> models.Announcement:
    title = "Project Closed"
    reason = "Contract Signed" if project.stage == models.Stage.L1 else "Bid Submitted"
    body = (f"{_b(project.est_no)} &#8211; {project.name} is now closed ({_hl(reason, 'good')})."
            f"<br><br>{_project_link(project.id)}")
    return _create(db, type=models.AnnouncementType.CLOSED, title=title, body=body,
                    recipients=recipients, project=project)

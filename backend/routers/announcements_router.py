from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/announcements", tags=["announcements"])

# Item 158/159/160, reworked by item 165: org-wide news is visible to
# everyone regardless of role -- new tender/L1 stage (BROADCAST), a tender
# closing (CLOSED), a milestone being reached (MILESTONE), a BSD extension
# (BSD_EXTENDED), a document landing on a deliverable (DOC_ADDED), a
# deliverable being approved (DELIVERABLE_APPROVED), and a cross-department
# unlock (UNLOCK) are all facts about the program as a whole, not private to
# whoever's directly involved. Everything else is addressed to specific
# people via `recipients`, so a non-admin only sees it if their own acting
# email is actually in that list -- an SME shouldn't see "Deliverables
# Assigned to You" for an Owner, a Viewer (no acting email at all) sees
# only the general items, and a rejection (SME_DECISION) stays private
# feedback to the Owner rather than general news.
_ALWAYS_VISIBLE_TYPES = {
    models.AnnouncementType.BROADCAST, models.AnnouncementType.CLOSED,
    models.AnnouncementType.MILESTONE, models.AnnouncementType.BSD_EXTENDED,
    models.AnnouncementType.DOC_ADDED, models.AnnouncementType.DELIVERABLE_APPROVED,
    models.AnnouncementType.UNLOCK,
}


@router.get("", response_model=list[schemas.AnnouncementOut])
def list_announcements(limit: int = 50, actor_role: str | None = None, actor_email: str | None = None,
                        mine: bool = False, stage: str | None = None, category: str = "news",
                        db: Session = Depends(get_db)):
    """Item [reminders tab]: `category` splits one shared table into two
    tabs the same way `kind` already splits DueDateRequest instead of two
    near-duplicate tables -- "news" (the default, everything except
    DEADLINE) is the Announcements tab; "reminders" (DEADLINE only) is the
    separate Reminders tab. DEADLINE covers the nightly due-soon/overdue
    nudge, the manual Send Reminder action, the BM Triage nudge, and
    Followed Item Updates -- all of them read as "a reminder", not general
    program news, which is exactly why they were cluttering Announcements.
    """
    q = db.query(models.Announcement).order_by(models.Announcement.created_at.desc())
    if category == "reminders":
        q = q.filter(models.Announcement.type == models.AnnouncementType.DEADLINE)
    else:
        q = q.filter(models.Announcement.type != models.AnnouncementType.DEADLINE)
    if stage:
        # Item [dashboard stage split]: the Dashboard's Latest Announcements
        # feed is now one per stage -- an announcement with no project (rare)
        # can't belong to either, so an inner join correctly drops it here.
        q = q.join(models.Project, models.Announcement.project_id == models.Project.id).filter(
            models.Project.stage == stage, models.Project.archived.is_not(True))
    items = q.limit(limit).all()
    if actor_role and actor_role != "Admin":
        email = (actor_email or "").strip().lower()

        def visible(a: models.Announcement) -> bool:
            if a.type in _ALWAYS_VISIBLE_TYPES:
                return True
            if not email:
                return False
            recipients = [r.strip().lower() for r in (a.recipients or "").split(",")]
            return email in recipients

        items = [a for a in items if visible(a)]

    # Item 183: Dashboard's "My Items" toggle -- strictly items addressed to
    # this email, regardless of role (unlike the visibility filter above,
    # which still lets org-wide broadcast news through for Admin/everyone).
    # "Mine" means it's actually about my work, not just that I'm allowed
    # to see it.
    if mine:
        email = (actor_email or "").strip().lower()
        if not email:
            return []
        items = [
            a for a in items
            if email in [r.strip().lower() for r in (a.recipients or "").split(",")]
        ]

    # [queued: Announcements stage filter] one batched query for every
    # distinct project_id still in `items`, instead of a per-row lookup --
    # attached as a transient attribute, picked up by AnnouncementOut's
    # from_attributes the same as any other field.
    project_ids = {a.project_id for a in items if a.project_id is not None}
    if project_ids:
        stage_by_project = dict(
            db.query(models.Project.id, models.Project.stage).filter(models.Project.id.in_(project_ids)).all()
        )
        for a in items:
            a.stage = stage_by_project.get(a.project_id)
    return items


@router.delete("/reminders")
def clear_reminders(actor_role: str = "Admin", db: Session = Depends(get_db)):
    """Item [reminders tab]: one-time (or occasional) cleanup of every
    DEADLINE-type row -- the Reminders tab was previously mixed into
    Announcements, so this clears out that backlog rather than leaving it
    to resurface the moment the two views split.
    """
    if actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can clear reminders")
    deleted = db.query(models.Announcement).filter(models.Announcement.type == models.AnnouncementType.DEADLINE).delete()
    db.commit()
    return {"deleted": deleted}

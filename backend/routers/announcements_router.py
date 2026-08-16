from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/announcements", tags=["announcements"])

# Item 158/159/160: Broadcast/Closed are org-wide news (new tender, project
# closed) -- everyone sees those regardless of role. Everything else is
# addressed to specific people via `recipients`, so a non-admin only sees
# it if their own acting email is actually in that list -- an SME shouldn't
# see "Deliverables Assigned to You" for an Owner, an Owner shouldn't see
# "Review Requested" meant for the SME, and a Viewer (no acting email at
# all) sees only the broadcast items.
_ALWAYS_VISIBLE_TYPES = {models.AnnouncementType.BROADCAST, models.AnnouncementType.CLOSED}


@router.get("", response_model=list[schemas.AnnouncementOut])
def list_announcements(limit: int = 50, actor_role: str | None = None, actor_email: str | None = None,
                        db: Session = Depends(get_db)):
    items = (
        db.query(models.Announcement)
        .order_by(models.Announcement.created_at.desc())
        .limit(limit)
        .all()
    )
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
    return items

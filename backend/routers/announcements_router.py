from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


@router.get("", response_model=list[schemas.AnnouncementOut])
def list_announcements(limit: int = 50, db: Session = Depends(get_db)):
    return (
        db.query(models.Announcement)
        .order_by(models.Announcement.created_at.desc())
        .limit(limit)
        .all()
    )

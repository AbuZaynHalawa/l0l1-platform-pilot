from datetime import date, datetime
from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    stage: str  # "L0" | "L1"
    region: str | None = None
    scope: str | None = None
    bid_manager: str | None = None
    project_manager: str | None = None
    bsd: date | None = None


class ProjectOut(BaseModel):
    id: int
    est_no: str
    name: str
    stage: str
    region: str | None
    scope: str | None
    bid_manager: str | None
    project_manager: str | None
    status: str
    announcement_date: date
    bsd: date | None

    class Config:
        from_attributes = True


class SubmissionOut(BaseModel):
    id: int
    item_no: str
    name: str
    department: str
    due_date: date | None
    status: str
    owner_name: str | None
    file_name: str | None
    submitted_at: datetime | None
    review_comment: str | None

    class Config:
        from_attributes = True


class ReviewDecision(BaseModel):
    approved: bool
    comment: str | None = None
    reviewer_name: str = "SME"


class AnnouncementOut(BaseModel):
    id: int
    type: str
    title: str
    body: str
    recipients: str | None
    email_status: str
    created_at: datetime

    class Config:
        from_attributes = True

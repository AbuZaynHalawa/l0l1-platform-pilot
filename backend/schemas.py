from datetime import date, datetime
from pydantic import BaseModel


class ProjectCreateL0(BaseModel):
    est_no: str  # manual entry until auto-numbering exists
    name: str
    region: list[str]
    region_other: str | None = None
    scope: list[str]
    scope_other: str | None = None
    rfx_number: str | None = None
    announcement_date: date
    site_visit_date: date | None = None
    pre_bid_deadline: date | None = None
    bid_manager: str
    bsd: date
    scope_contains_pbu: bool = False


class ProjectCreateL1(BaseModel):
    l0_source_id: int
    announcement_date: date
    project_manager: str | None = None


class ProjectManagerUpdate(BaseModel):
    project_manager: str | None = None


class ProjectOut(BaseModel):
    id: int
    est_no: str
    name: str
    stage: str
    region: list[str] | None
    region_other: str | None
    scope: list[str] | None
    scope_other: str | None
    rfx_number: str | None
    bid_manager: str | None
    project_manager: str | None
    status: str
    contract_status: str | None
    announcement_date: date
    bsd: date | None
    site_visit_date: date | None
    pre_bid_deadline: date | None
    l0_source_id: int | None

    class Config:
        from_attributes = True


class SubmissionOut(BaseModel):
    id: int
    item_no: str
    name: str
    department: str
    due_date: date | None
    status: str
    owner_email: str | None
    sme_email: str | None
    file_name: str | None
    submitted_at: datetime | None
    review_comment: str | None
    is_milestone: bool
    milestone_code: str | None

    class Config:
        from_attributes = True


class ReviewDecision(BaseModel):
    approved: bool
    comment: str | None = None
    reviewer_name: str = "SME"
    actor_role: str = "Admin"
    actor_email: str = ""


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

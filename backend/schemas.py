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
    pre_bid_meeting_date: date | None = None
    pre_bid_deadline: date | None = None
    bid_manager: str
    bsd: date
    business_units: list[str] | None = None  # required (TBU/PBU/DBU/BBU/TBA) only when scope can't be auto-classified


class ProjectCreateL1(BaseModel):
    l0_source_id: int
    announcement_date: date
    project_manager: str | None = None


class ProjectManagerUpdate(BaseModel):
    project_manager: str | None = None


class ProjectStatusUpdate(BaseModel):
    status: str


class ProjectDetailsUpdate(BaseModel):
    """Admin-only low-risk field edits. Only fields actually sent are applied
    (exclude_unset) — scope is deliberately not here, since it drives
    deliverable generation and business-unit classification and needs a
    bigger conversation than a quick inline edit. BSD (item 149) is the one
    exception: it's just another anchor date like announcement_date, so it
    gets the same full-cascade recompute treatment on edit.
    """
    bid_manager: str | None = None
    region: list[str] | None = None
    region_other: str | None = None
    announcement_date: date | None = None
    site_visit_date: date | None = None
    pre_bid_meeting_date: date | None = None
    pre_bid_deadline: date | None = None
    bsd: date | None = None
    actor_role: str = "Admin"


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
    business_units: list[str] | None
    status: str
    contract_status: str | None
    announcement_date: date
    bsd: date | None
    site_visit_date: date | None
    pre_bid_meeting_date: date | None = None
    pre_bid_deadline: date | None
    l0_source_id: int | None
    pending_triage_count: int = 0

    class Config:
        from_attributes = True


class TriageItem(BaseModel):
    submission_id: int
    applicable: bool


class TriageRequest(BaseModel):
    items: list[TriageItem]
    actor_role: str = "Admin"
    actor_email: str = ""


class SubmissionOut(BaseModel):
    id: int
    item_no: str
    name: str
    department: str
    due_date: date | None
    status: str
    # Item 143 (2nd revision): Deadline standing is a separate axis from
    # Progress (`status` above) -- see rules.deadline_status(). deadline_days
    # is None for not_due/on_time, otherwise the signed day count to show.
    deadline_status: str = "not_due"
    deadline_days: int | None = None
    auto_completed: bool = False
    owner_email: str | None
    sme_email: str | None
    file_name: str | None
    file_url: str | None = None
    submitted_at: datetime | None
    review_comment: str | None
    completion_note: str | None = None
    is_milestone: bool
    milestone_code: str | None
    doc_total: int = 0  # item 136: total documents attached (primary file + supplementary)

    class Config:
        from_attributes = True


class MarkCompleteRequest(BaseModel):
    comment: str
    actor_name: str = "Owner"
    actor_role: str = "Owner"
    actor_email: str = ""


class FollowRequest(BaseModel):
    email: str


class ReassignRequestCreate(BaseModel):
    to_email: str
    reason: str | None = None
    from_email: str | None = None


class ReassignmentDecision(BaseModel):
    approved: bool
    actor_role: str = "Admin"


class BulkRemindRequest(BaseModel):
    submission_ids: list[int]
    actor_role: str = "Admin"
    message: str | None = None  # item 90 — custom reminder text, defaults to the standard one
    cc_manager: bool = False  # item 90 — also CC the owner's manager_email from the user roster


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
    project_id: int | None = None
    submission_id: int | None = None

    class Config:
        from_attributes = True

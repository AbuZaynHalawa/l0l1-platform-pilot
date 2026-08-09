"""Database models for the L0/L1 platform pilot.

Milestones are NOT a separate manually-tracked table. Per the real templates,
specific deliverable items ARE the milestones (L0 items tagged M1-M5, L1 items
1.1-1.6 = M1-M6): a milestone is "reached" exactly when its linked deliverable
is approved. See DeliverableDefinition.is_milestone / milestone_code and
rules.py for how this drives both due-date chaining and milestone status.
"""
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Date, DateTime, ForeignKey, Boolean, Text, Enum, JSON
)
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()


class Stage(str, enum.Enum):
    L0 = "L0"
    L1 = "L1"


class ProjectStatus(str, enum.Enum):
    IN_PROGRESS = "In Progress"
    SUBMITTED = "Submitted"      # L0 only
    CANCELLED = "Cancelled"      # L0 only
    COMPLETED = "Completed"      # L1 only (all deliverables submitted)


class ContractStatus(str, enum.Enum):
    NOT_SIGNED = "Not Signed"
    SIGNED = "Signed"


class SubmissionStatus(str, enum.Enum):
    NOT_DUE = "not_due"
    DUE = "due"
    OVERDUE = "overdue"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class AnnouncementType(str, enum.Enum):
    BROADCAST = "broadcast"
    OWNER = "owner"
    SME_REQUEST = "sme_request"
    SME_DECISION = "sme_decision"
    UNLOCK = "unlock"
    DEADLINE = "deadline"
    CLOSED = "closed"


class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    order = Column(Integer, default=0)
    number = Column(Integer, nullable=True)  # the "4" in item "4.5" — display-only, kept out of `name`
    focal_point_name = Column(String, nullable=True)
    focal_point_email = Column(String, nullable=True)

    deliverable_definitions = relationship("DeliverableDefinition", back_populates="department")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    role = Column(String, default="Owner")  # Admin | Owner | SME | Viewer
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)

    department = relationship("Department")


# Real Bid Manager directory (from Modifications doc)
BID_MANAGERS = [
    "Ahmad.Mhaidat@Algihaz.com", "Mohammad.Abujubeh@Algihaz.com", "Mohammad.Alawneh@Algihaz.com",
    "Husam.Abualhayjaa@Algihaz.com", "Abdelrahman.Deeb@Algihaz.com", "Ahmad.Awartani@Algihaz.com",
    "Abdallah.Alshorbaji@Algihaz.com", "Omar.HajKhalil@Algihaz.com", "Suhaib.Hasan@Algihaz.com",
    "Mosab.Omar@Algihaz.com", "Amer.Freihat@Algihaz.com", "Asmaa.Abdelkawy@algihaz.com",
    "Yasser.Halawa@algihaz.com",
]
REGION_OPTIONS = ["COA", "SOA", "EOA", "WOA", "Other"]
SCOPE_OPTIONS = [
    "SS MV (Distribution)", "SS HV (110-132 KV)", "SS EHV (230-400 KV)", "UGC MV (Distribution)",
    "UGC HV (110-132 KV)", "UGC EHV (230-400 KV)", "OHTL MV (Distribution)", "OHTL HV (110-132 KV)",
    "OHTL EHV (230-400 KV)", "BESS MV (Distribution)", "BESS HV (110-132 KV)", "BESS EHV (230-400 KV)",
    "HVDC", "Other",
]


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    est_no = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    stage = Column(Enum(Stage), nullable=False)
    region = Column(JSON, nullable=True)          # list[str], multi-select
    region_other = Column(String, nullable=True)   # free text if "Other" checked
    scope = Column(JSON, nullable=True)            # list[str], multi-select
    scope_other = Column(String, nullable=True)
    rfx_number = Column(String, nullable=True)
    scope_contains_pbu = Column(Boolean, default=False)  # drives the 1.8/1.9/1.10 conditional in rules.py
    bid_manager = Column(String, nullable=True)
    project_manager = Column(String, nullable=True)
    status = Column(Enum(ProjectStatus), default=ProjectStatus.IN_PROGRESS)
    contract_status = Column(Enum(ContractStatus), nullable=True)  # L1 only
    announcement_date = Column(Date, default=date.today)  # = M1 anchor for both stages
    bsd = Column(Date, nullable=True)               # L0 only
    site_visit_date = Column(Date, nullable=True)   # L0 only, optional
    pre_bid_deadline = Column(Date, nullable=True)  # L0 only, optional (if blank, treated as immediate)
    l0_source_id = Column(Integer, ForeignKey("projects.id"), nullable=True)  # L1 -> the L0 it came from
    onedrive_folder_id = Column(String, nullable=True)
    onedrive_folder_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    submissions = relationship("DeliverableSubmission", back_populates="project", cascade="all, delete-orphan",
                                foreign_keys="DeliverableSubmission.project_id")
    l0_source = relationship("Project", remote_side=[id])


class DeliverableDefinition(Base):
    """The template/catalog layer — admin-managed, versionable.

    anchor_type:
      "announcement"      due_date = project.announcement_date + offset_days (the M1 root item)
      "bsd"                due_date = project.bsd - offset_days (L0's M5/BSD root item)
      "predecessor"        due_date = that predecessor item's own due_date +/- offset_days
      "client_dependent"   no computable due date; owner/admin submits whenever the real event
                            happens (e.g. LOA received, Contract signed, "By Client" items)
      null                 library/on_request type, no due date, informational only
    """
    __tablename__ = "deliverable_definitions"
    id = Column(Integer, primary_key=True)
    stage = Column(Enum(Stage), nullable=False)
    item_no = Column(String, nullable=False)
    name = Column(String, nullable=False)
    short_name = Column(String, nullable=True)  # curated compact label for dense views (matrix, gantt)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    anchor_type = Column(String, nullable=True)
    predecessor_item_no = Column(String, nullable=True)
    offset_days = Column(Integer, default=0)
    offset_direction = Column(String, default="after")  # after | before
    deliverable_type = Column(String, default="date_driven")  # date_driven | library | on_request
    is_milestone = Column(Boolean, default=False)
    milestone_code = Column(String, nullable=True)   # M1..M6 when is_milestone
    milestone_name = Column(String, nullable=True)
    kpi_relevant = Column(Boolean, default=True)
    default_owner_email = Column(String, nullable=True)
    default_sme_email = Column(String, nullable=True)
    active = Column(Boolean, default=True)

    department = relationship("Department", back_populates="deliverable_definitions")


class DeliverableSubmission(Base):
    """The transactional layer — one row per (project x deliverable_definition)."""
    __tablename__ = "deliverable_submissions"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    deliverable_definition_id = Column(Integer, ForeignKey("deliverable_definitions.id"), nullable=False)
    due_date = Column(Date, nullable=True)
    status = Column(Enum(SubmissionStatus), default=SubmissionStatus.NOT_DUE)
    owner_email = Column(String, nullable=True)
    sme_email = Column(String, nullable=True)
    file_name = Column(String, nullable=True)
    file_ref = Column(String, nullable=True)  # storage provider's identifier for the uploaded file
    submitted_at = Column(DateTime, nullable=True)
    review_comment = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="submissions", foreign_keys=[project_id])
    definition = relationship("DeliverableDefinition")
    history = relationship("WorkflowHistory", back_populates="submission", cascade="all, delete-orphan")


class WorkflowHistory(Base):
    __tablename__ = "workflow_history"
    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("deliverable_submissions.id"), nullable=False)
    action = Column(String, nullable=False)  # submitted | assigned | review_requested | approved | rejected | unlocked
    actor_name = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    submission = relationship("DeliverableSubmission", back_populates="history")


class Announcement(Base):
    __tablename__ = "announcements"
    id = Column(Integer, primary_key=True)
    type = Column(Enum(AnnouncementType), nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    recipients = Column(String, nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    email_status = Column(String, default="pending")  # pending | sent | failed | simulated
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", foreign_keys=[project_id])

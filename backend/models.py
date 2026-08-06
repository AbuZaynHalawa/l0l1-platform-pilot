"""Database models for the L0/L1 platform pilot.

Scope note: this is the working core (Phase 1 from architecture_map.md section 9),
not the full ~76-item deliverable catalog. Enough real structure to prove the
mechanism end-to-end; the full catalog is a data-entry task, not a schema change.
"""
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Date, DateTime, ForeignKey, Boolean, Text, Enum
)
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()


class Stage(str, enum.Enum):
    L0 = "L0"
    L1 = "L1"


class ProjectStatus(str, enum.Enum):
    IN_PROGRESS = "In Progress"
    SUBMITTED = "Submitted"
    SIGNED = "Signed"
    CANCELLED = "Cancelled"


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


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    est_no = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    stage = Column(Enum(Stage), nullable=False)
    region = Column(String, nullable=True)
    scope = Column(String, nullable=True)
    bid_manager = Column(String, nullable=True)
    project_manager = Column(String, nullable=True)
    status = Column(Enum(ProjectStatus), default=ProjectStatus.IN_PROGRESS)
    announcement_date = Column(Date, default=date.today)
    bsd = Column(Date, nullable=True)
    onedrive_folder_id = Column(String, nullable=True)
    onedrive_folder_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    submissions = relationship("DeliverableSubmission", back_populates="project", cascade="all, delete-orphan")
    milestones = relationship("MilestoneEvent", back_populates="project", cascade="all, delete-orphan")


class MilestoneDefinition(Base):
    __tablename__ = "milestone_definitions"
    id = Column(Integer, primary_key=True)
    stage = Column(Enum(Stage), nullable=False)
    code = Column(String, nullable=False)  # M1..M6
    name = Column(String, nullable=False)
    sequence = Column(Integer, nullable=False)


class MilestoneEvent(Base):
    __tablename__ = "milestone_events"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    milestone_definition_id = Column(Integer, ForeignKey("milestone_definitions.id"), nullable=False)
    planned_date = Column(Date, nullable=True)
    actual_date = Column(Date, nullable=True)
    reached = Column(Boolean, default=False)

    project = relationship("Project", back_populates="milestones")
    definition = relationship("MilestoneDefinition")


class DeliverableDefinition(Base):
    """The template/catalog layer — admin-managed, versionable."""
    __tablename__ = "deliverable_definitions"
    id = Column(Integer, primary_key=True)
    stage = Column(Enum(Stage), nullable=False)
    item_no = Column(String, nullable=False)
    name = Column(String, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    anchor_type = Column(String, default="milestone")  # milestone | predecessor | fixed
    anchor_milestone_code = Column(String, nullable=True)  # e.g. "M1"
    predecessor_item_no = Column(String, nullable=True)  # references another item_no in same stage
    offset_days = Column(Integer, default=0)
    offset_direction = Column(String, default="after")  # after | before
    deliverable_type = Column(String, default="date_driven")  # date_driven | library
    kpi_relevant = Column(Boolean, default=True)
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
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewer_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    file_name = Column(String, nullable=True)
    file_ref = Column(String, nullable=True)  # storage provider's identifier for the uploaded file
    submitted_at = Column(DateTime, nullable=True)
    review_comment = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="submissions")
    definition = relationship("DeliverableDefinition")
    owner = relationship("User", foreign_keys=[owner_user_id])
    reviewer = relationship("User", foreign_keys=[reviewer_user_id])
    history = relationship("WorkflowHistory", back_populates="submission", cascade="all, delete-orphan")


class WorkflowHistory(Base):
    __tablename__ = "workflow_history"
    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("deliverable_submissions.id"), nullable=False)
    action = Column(String, nullable=False)  # submitted | assigned | review_requested | approved | rejected
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

    project = relationship("Project")

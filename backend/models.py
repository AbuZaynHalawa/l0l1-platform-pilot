"""Database models for the L0/L1 platform pilot.

Milestones are NOT a separate manually-tracked table. Per the real templates,
specific deliverable items ARE the milestones (L0 items tagged M1-M5, L1 items
1.1-1.6 = M1-M6): a milestone is "reached" exactly when its linked deliverable
is approved. See DeliverableDefinition.is_milestone / milestone_code and
rules.py for how this drives both due-date chaining and milestone status.
"""
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Date, DateTime, ForeignKey, Boolean, Text, Enum, JSON, Float, UniqueConstraint
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
    """Item 143 (2nd revision): this column is now purely a *Progress*
    status — how far the work itself has gotten. Deadline standing (Not
    Due / Due / On Time / Early / Late, with a day count) is a separate,
    unstored concept computed live from due_date/reviewed_at — see
    rules.deadline_status(). The two used to be conflated in one status
    value; they're independent axes now, matching the confirmed spec.
    """
    NO_PROGRESS = "no_progress"    # nothing uploaded yet, Mark Completed not yet clicked
    IN_PROGRESS = "in_progress"    # at least one document uploaded, not yet marked complete
    # Reached ONLY via Mark Completed (comment-only or with documents) —
    # uploading a document never triggers review on its own anymore. The
    # Owner/SME split still applies: an Owner's Mark Completed lands here
    # awaiting the SME's confirm/reject; the SME's own Mark Completed
    # skips this and goes straight to APPROVED.
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"  # displayed as "Completed" in the UI
    # SME sent it back. Progress stays REJECTED (not IN_PROGRESS) until the
    # Owner actually uploads something new — only then does it flip.
    REJECTED = "rejected"
    PENDING_TRIAGE = "pending_triage"  # L0 only: awaiting BM applicable/not-required call — its own status, outside this model
    NOT_REQUIRED = "not_required"      # BM marked this item as not applicable to this tender — its own status, outside this model
    # Legacy values from the pre-143(2nd-revision) status model, retired
    # from active use but kept here so the one-time seed.py migration that
    # remaps existing rows away from them can still reference them by name
    # (Postgres enum labels can't be removed once added, so these stay
    # valid at the DB level regardless).
    NOT_DUE = "not_due"
    DUE = "due"
    OVERDUE = "overdue"
    PENDING_COMPLETION = "pending_completion"


class AnnouncementType(str, enum.Enum):
    BROADCAST = "broadcast"
    OWNER = "owner"
    SME_REQUEST = "sme_request"
    SME_DECISION = "sme_decision"
    UNLOCK = "unlock"
    DEADLINE = "deadline"
    CLOSED = "closed"
    # Item 165: split out of the general-purpose DEADLINE bucket / the
    # approve-or-reject SME_DECISION bucket so each can get its own
    # everyone-sees-it visibility rule instead of inheriting a mixed one.
    MILESTONE = "milestone"
    BSD_EXTENDED = "bsd_extended"
    DOC_ADDED = "doc_added"
    DELIVERABLE_APPROVED = "deliverable_approved"
    # Due-date extension / on-hold requests: private per-item feedback, same
    # visibility shape as SME_REQUEST/SME_DECISION (request -> SME/Admin;
    # decision -> the requesting Owner).
    EXTENSION_REQUEST = "extension_request"
    EXTENSION_DECISION = "extension_decision"
    HOLD_REQUEST = "hold_request"
    HOLD_DECISION = "hold_decision"
    # Reassignment/SME-nomination decisions used to share the generic
    # DEADLINE bucket (Reminders tab) with their own still-pending request
    # notifications -- but a DECISION is news about something already
    # resolved, not an action still owed, same reasoning EXTENSION_DECISION/
    # HOLD_DECISION above already got split out for. The *request* side of
    # both stays DEADLINE on purpose (still needs an Admin's action).
    REASSIGNMENT_DECISION = "reassignment_decision"
    SME_NOMINATION_DECISION = "sme_nomination_decision"
    # [Bid Value]: request side stays DEADLINE (still needs an Admin's
    # action, same convention as every other *_REQUEST above); this is only
    # the decision half, back to whoever asked.
    BID_VALUE_ACCESS_DECISION = "bid_value_access_decision"
    # [L0-L1 Group requests]: request side stays DEADLINE (still needs an
    # Admin's action, same convention as every other *_REQUEST above); this
    # is only the decision half, back to whoever asked.
    GROUP_ADD_DECISION = "group_add_decision"
    # [Deliverables Configuration]: request side stays DEADLINE, same
    # convention as every other *_REQUEST above; this is only the decision
    # half, back to whoever suggested the formula change.
    FORMULA_CHANGE_DECISION = "formula_change_decision"


class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    number = Column(Integer, nullable=True)  # the "4" in item "4.5" — display-only, kept out of `name`
    focal_point_name = Column(String, nullable=True)
    focal_point_email = Column(String, nullable=True)
    # [L0 International]: every international-only department (its own row,
    # never shared with a standard-L0 department of the same conceptual
    # name -- see rules.is_international_applicable) is flagged here so
    # Performance/Focal Points can show it only in their International
    # subtab, and hide it from the standard L0 view.
    is_international = Column(Boolean, default=False)
    # [Deliverables Configuration]: soft-delete, same convention as
    # BidManager.active -- a department already referenced by existing
    # projects/definitions keeps its real name/history; this only removes
    # it from admin CRUD dropdowns and cascades a soft-deactivate onto its
    # own DeliverableDefinitions (see departments.delete_department).
    active = Column(Boolean, default=True)

    deliverable_definitions = relationship("DeliverableDefinition", back_populates="department")


class User(Base):
    """The admin-managed system roster (item 75's "general L0-L1 Group") —
    everyone with a stake in the portal, not just the people with an
    upload/review action assigned to them on some deliverable. Admins/
    Owners/SMEs are the roles with real actions; "Viewer" is the general,
    view-only membership the whole roster defaults to belonging to.
    """
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    role = Column(String, default="Viewer")  # Admin | Owner | SME | Viewer
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    manager_email = Column(String, nullable=True)  # item 90's Send Reminder "CC manager" option

    department = relationship("Department")


class BidManager(Base):
    """Admin-managed roster backing the Bid Manager dropdown (item 75) —
    replaces the old hardcoded BID_MANAGERS constant, which is now only
    the one-time seed for this table's initial rows.
    """
    __tablename__ = "bid_managers"
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=True)
    active = Column(Boolean, default=True)


# Real Bid Manager directory (from Modifications doc), sorted alphabetically by name
BID_MANAGERS = sorted([
    "Ahmad.Mhaidat@Algihaz.com", "Mohammad.Abujubeh@Algihaz.com", "Mohammad.Alawneh@Algihaz.com",
    "Husam.Abualhayjaa@Algihaz.com", "Abdelrahman.Deeb@Algihaz.com", "Ahmad.Awartani@Algihaz.com",
    "Abdallah.Alshorbaji@Algihaz.com", "Omar.HajKhalil@Algihaz.com", "Suhaib.Hasan@Algihaz.com",
    "Mosab.Omar@Algihaz.com", "Amer.Freihat@Algihaz.com", "Asmaa.Abdelkawy@algihaz.com",
    "Yasser.Halawa@algihaz.com",
], key=str.lower)
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
    # Item 119: an L1 deliberately reuses its L0's own est_no (same tender,
    # later stage) instead of getting a fresh number, so this is no longer
    # unique at the database level -- `stage` + `est_no` together identify
    # a specific project.
    est_no = Column(String, nullable=False)
    name = Column(String, nullable=False)
    stage = Column(Enum(Stage), nullable=False)
    region = Column(JSON, nullable=True)          # list[str], multi-select
    region_other = Column(String, nullable=True)   # free text if "Other" checked
    scope = Column(JSON, nullable=True)            # list[str], multi-select
    scope_other = Column(String, nullable=True)
    rfx_number = Column(String, nullable=True)
    scope_contains_pbu = Column(Boolean, default=False)  # drives the 1.8/1.9/1.10 conditional in rules.py
    business_units = Column(JSON, nullable=True)  # list of "TBU"/"PBU"/"DBU"/"BBU"/"IBU"/"TBA", see rules.compute_business_units
    # [L0 International]: L0 only, set once at creation, never toggled after.
    # Drives which DeliverableDefinition catalog _instantiate_deliverables
    # pulls from (rules.is_international_applicable) and which due-date
    # formulas apply (compute_due_date's is_l0 gate) -- an international
    # tender uses its own item catalog and literal (L1-style) durations,
    # not standard L0's tight-BSD compression.
    is_international = Column(Boolean, default=False)
    # Free-text country, collected instead of the KSA-only Region checkboxes
    # when is_international is set -- region/region_other stay unused for
    # these projects.
    country = Column(String, nullable=True)
    bid_manager = Column(String, nullable=True)
    project_manager = Column(String, nullable=True)
    status = Column(Enum(ProjectStatus), default=ProjectStatus.IN_PROGRESS)
    contract_status = Column(Enum(ContractStatus), nullable=True)  # L1 only
    announcement_date = Column(Date, default=date.today)  # = M1 anchor for both stages
    bsd = Column(Date, nullable=True)               # L0 only
    site_visit_date = Column(Date, nullable=True)   # L0 only, optional
    pre_bid_meeting_date = Column(Date, nullable=True)  # L0 only, optional (item 114)
    pre_bid_deadline = Column(Date, nullable=True)  # L0 only, optional (if blank, treated as immediate)
    l0_source_id = Column(Integer, ForeignKey("projects.id"), nullable=True)  # L1 -> the L0 it came from
    onedrive_folder_id = Column(String, nullable=True)
    onedrive_folder_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    due_dates_computed_on = Column(Date, nullable=True)  # calendar date recompute_project_due_dates last actually ran
    last_triage_reminder_at = Column(DateTime, nullable=True)  # item 79's admin "Remind BM" action
    # [tight-BSD duration ratio], L0 only: a tender with a tight BSD can have
    # standard item durations that don't fit inside announcement-to-BSD at
    # all -- rules._apply_duration_ratio searches 100%/95%/90%/.../50% (5%
    # steps) for the largest ratio where every predecessor-chained item's
    # due date still fits before BSD, applied as a multiplier on top of
    # whatever offset that item would otherwise use (including the 4.4/5.3
    # tiered durations and the 1.8/1.9/1.10 threshold durations), floored at
    # 1 workday so nothing collapses to a same-day or negative duration.
    # 1.0 = standard, no compression needed.
    duration_ratio = Column(Float, default=1.0)
    # True once the search above tried every ratio down to the 50% floor and
    # still couldn't fit everything before BSD -- the 50% ratio is applied
    # anyway (best effort), but this flags it so the overshoot is visible
    # rather than a silent surprise on a real deliverable's due date.
    duration_ratio_insufficient = Column(Boolean, default=False)
    # [Bid Value]: optional, entered by the Bid Manager at L1 creation.
    # Hidden by default -- ProjectOut never serializes this column, so the
    # ordinary GET /{project_id} response every viewer already calls can't
    # leak it. Visibility is decided per-viewer by the dedicated
    # /{project_id}/bid-value endpoint: the BM or an Admin always sees it,
    # anyone else needs a standing grant recorded in BidValueAccessRequest.
    bid_value = Column(Float, nullable=True)
    # [Archive]: an admin's undo-able "this shouldn't have been created / is
    # done with" flag -- unlike Cancelled/Completed (still live business
    # status, still shows up everywhere), an archived project is hidden from
    # every report/dashboard/listing view but stays fully reachable by its
    # own id (detail page, PO Lifecycle, Milestones, Gantt-by-id) so an admin
    # can review it and un-archive it at any time. See routers/projects.py's
    # archive_project endpoint and list_projects's `archived` param.
    archived = Column(Boolean, default=False)

    submissions = relationship("DeliverableSubmission", back_populates="project", cascade="all, delete-orphan",
                                foreign_keys="DeliverableSubmission.project_id")
    l0_source = relationship("Project", remote_side=[id])


class DeliverableDefinition(Base):
    """The template/catalog layer — admin-managed, versionable.

    Due-date computation itself is now driven entirely by this row's
    `branches` (DeliverableFormulaBranch, ordered by branch_order) — see
    rules.compute_due_date. The anchor_type/predecessor_item_no/offset_days/
    offset_direction columns below are a denormalized mirror of branch 0's
    shape (kept in sync by rules.sync_definition_mirror_columns whenever
    branches are saved), read only by the couple of call sites that just
    need an approximate single-formula summary (awaiting_milestone_note,
    gantt.py's _bar_start) rather than the real resolver.

    anchor_type (also the shape of an individual branch):
      "announcement"      due_date = project.announcement_date + offset_days (the M1 root item)
      "bsd"                due_date = project.bsd - offset_days (L0's M5/BSD root item)
      "site_visit"         due_date = project.site_visit_date + offset_days
      "pre_bid"            due_date = (project.pre_bid_deadline or today) - offset_days
      "predecessor"        due_date = that predecessor item's own due_date +/- offset_days
      "client_dependent"   no computable due date; owner/admin submits whenever the real event
                            happens (e.g. LOA received, Contract signed, "By Client" items)
      null / zero branches library/on_request type, no due date, informational only
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
    # [Deliverable weights]: relative importance vs. sibling items in the
    # same department+stage when averaging into that department's L0/L1
    # Performance % -- NULL means the default weight of 1.0 (equal split
    # among default-weighted siblings), not "unset/broken". Never required
    # to sum to 100 with siblings -- normalized by dividing by the sum of
    # weights actually present in whatever cohort is being scored, so an
    # Admin only ever touches the one item they want to re-weight. See
    # dashboard.py's _kpi_pct_weighted.
    kpi_weight = Column(Float, nullable=True)
    default_owner_email = Column(String, nullable=True)  # legacy single value, superseded by default_owner_emails below
    default_sme_email = Column(String, nullable=True)  # legacy single value, superseded by default_sme_emails below
    active = Column(Boolean, default=True)
    # Per-deliverable focal contact (item 75) — overrides the department's
    # own focal_point_name/email for notifications about this specific item.
    # Left unset, notification routing falls back to the department's.
    # Tendering Department items ignore this (see rules.deliverable_focal) —
    # their focal is always whichever Bid Manager is running that project.
    # Superseded at the UI level by default_owner_emails below (the Focal
    # Points tab's "Deliverable's Owner Email" column now edits ownership,
    # not a separate notify-only contact) -- kept for whatever still reads
    # it (the Follow Up tab's legacy "focal" label) but no longer editable.
    focal_point_name = Column(String, nullable=True)
    focal_point_email = Column(String, nullable=True)  # legacy single value, superseded by focal_point_emails below
    # Item [multi-SME/owner]: any number of roster members can be the Owner
    # or the SME on a catalog item -- any one of them can act (upload/
    # complete for Owner, approve/reject for SME), not just a single fixed
    # person. list[str], JSON so SQLite and Postgres both store it natively.
    # The legacy singular columns above are kept (not dropped -- this
    # codebase's migration helpers only ever add) and used as a one-time
    # seed source / fallback for rows created before this existed.
    focal_point_emails = Column(JSON, nullable=True)
    default_sme_emails = Column(JSON, nullable=True)
    default_owner_emails = Column(JSON, nullable=True)
    # [PO Lifecycle]: set for definitions that must be tracked once per named
    # PoLineItem (e.g. "GIS", "Transformer") instead of once per project --
    # comma-separated when one definition spans two line-item pools ("3.11"
    # is the shared PO-issuance step for both early_activity and mep items).
    # See rules.py's _get_submissions/_resolve_predecessor_anchor and
    # routers/projects.py's _instantiate_deliverables fan-out.
    line_item_category = Column(String, nullable=True)
    # [Deliverables Configuration]: once True, seed.py's upsert() never
    # overwrites this row's name/short_name/anchor_type/predecessor_item_no/
    # offset_days/offset_direction/deliverable_type/is_milestone/
    # milestone_code/milestone_name again -- an admin edit or an approved
    # formula-change suggestion sets this, so future code-driven catalog
    # fixes (see seed.py's several _due_fix_items-style migrations this
    # session) no longer silently clobber a deliberate customization.
    # "Restore to Default" clears it back to False.
    is_customized = Column(Boolean, default=False)
    # The permanent "stage:item_no:department_id" identity captured the
    # first time this row was ever seeded -- immune to a LATER admin rename
    # of item_no or department, unlike upsert()'s old lookup key (plain
    # stage+item_no+department_id), which would otherwise lose track of a
    # renamed row and silently insert a duplicate on the next deploy. Null
    # for anything created directly through the admin UI (nothing to
    # restore to -- Restore to Default stays disabled for those rows).
    seed_key = Column(String, nullable=True)

    department = relationship("Department", back_populates="deliverable_definitions")
    branches = relationship(
        "DeliverableFormulaBranch", back_populates="definition",
        order_by="DeliverableFormulaBranch.branch_order", cascade="all, delete-orphan",
    )


class DeliverableFormulaBranch(Base):
    """One candidate formula for a DeliverableDefinition's due date --
    almost every item has exactly one, unconditional ("always") branch; the
    ~14 special-case items (PBU-conditional, site-visit-fallback, tiered/
    threshold duration, the international OR-formula items) carry several,
    evaluated in branch_order. See rules.compute_due_date for the resolver
    and seed.py's _DEFAULT_FORMULA_BRANCHES for the seeded default set that
    reproduces every one of today's hardcoded special cases exactly.
    """
    __tablename__ = "deliverable_formula_branches"
    id = Column(Integer, primary_key=True)
    deliverable_definition_id = Column(Integer, ForeignKey("deliverable_definitions.id"), nullable=False)
    branch_order = Column(Integer, default=0)
    # always | scope_contains_pbu | site_visit_unset | tender_window_lt_days
    condition_type = Column(String, nullable=False, default="always")
    condition_value = Column(Integer, nullable=True)  # the N in tender_window_lt_days
    # announcement | bsd | site_visit | pre_bid | predecessor
    anchor_type = Column(String, nullable=False)
    predecessor_item_no = Column(String, nullable=True)  # comma-separated AND-semantics preserved
    offset_days = Column(Integer, default=0)
    offset_direction = Column(String, default="after")  # after | before
    # Only meaningful for anchor_type "announcement"/"site_visit" (the two
    # forward-only direct-field anchors). False (default): the plain
    # additive formula every M1/M2-style item actually uses -- anchor +
    # offset_days calendar days, one weekend-skip-forward at the end. True:
    # the same "start the next workday, then count offset_days *working*
    # days, day 1 = start" duration math "predecessor" branches use --
    # needed for e.g. the site-visit-fallback items (announcement + 3
    # *working* days), which is a genuinely different formula, not just a
    # different anchor. See rules._resolve_branch.
    workday_duration = Column(Boolean, default=False)
    # earliest_of_siblings | latest_of_siblings | null -- branches sharing
    # the same non-null tie_break are a group: resolve every member whose
    # own condition is true, pick the earliest/latest resolved date among
    # them (this is the international OR-formula construct).
    tie_break = Column(String, nullable=True)
    active = Column(Boolean, default=True)

    definition = relationship("DeliverableDefinition", back_populates="branches")


class DeliverableDefinitionChangeLog(Base):
    """Full audit trail for DeliverableDefinition edits -- every admin save,
    restore-to-default, approved suggestion, and revert writes one row here.
    before_snapshot/after_snapshot capture the full editable shape (fields +
    branches) so a revert can restore either side exactly; summary is a
    short server-generated human-readable line so the Change History UI
    never has to diff JSON client-side.
    """
    __tablename__ = "deliverable_definition_change_log"
    id = Column(Integer, primary_key=True)
    deliverable_definition_id = Column(Integer, ForeignKey("deliverable_definitions.id"), nullable=False)
    changed_at = Column(DateTime, default=datetime.utcnow)
    actor_email = Column(String, nullable=True)
    actor_name = Column(String, nullable=True)
    source = Column(String, nullable=False)  # admin_edit | restore_default | suggestion_approved | revert
    change_type = Column(String, nullable=False)  # field_edit | branch_edit | created | deactivated | reactivated
    before_snapshot = Column(JSON, nullable=True)
    after_snapshot = Column(JSON, nullable=True)
    summary = Column(Text, nullable=True)
    origin_request_id = Column(Integer, ForeignKey("formula_change_requests.id"), nullable=True)
    # Item 34: set True on a row once it's been reverted (on the reverted
    # row itself, and on the "revert" row that undid it) -- the change is
    # no longer in effect, so the Audit History list hides both, same as
    # if it never happened. NULL/False means "still in effect," the
    # default for every existing row.
    reverted = Column(Boolean, nullable=True)

    definition = relationship("DeliverableDefinition")


class DepartmentChangeLog(Base):
    """Same shape as DeliverableDefinitionChangeLog, scoped to Department's
    own editable fields (name/order/number/is_international/active)."""
    __tablename__ = "department_change_log"
    id = Column(Integer, primary_key=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    changed_at = Column(DateTime, default=datetime.utcnow)
    actor_email = Column(String, nullable=True)
    actor_name = Column(String, nullable=True)
    change_type = Column(String, nullable=False)  # created | edited | deactivated | reactivated
    before_snapshot = Column(JSON, nullable=True)
    after_snapshot = Column(JSON, nullable=True)
    summary = Column(Text, nullable=True)
    reverted = Column(Boolean, nullable=True)  # item 34, same as DeliverableDefinitionChangeLog's

    department = relationship("Department")


class FormulaChangeRequest(Base):
    """Owner/SME self-service "suggest a formula change" -- same
    request-then-decide shape as SmeNomination/UserAddRequest (a suggestion
    alone never changes anything; an Admin's approval applies
    proposed_branches via the same code path the admin's own direct branch
    editor uses, and logs a DeliverableDefinitionChangeLog entry pointing
    back here via origin_request_id).
    """
    __tablename__ = "formula_change_requests"
    id = Column(Integer, primary_key=True)
    deliverable_definition_id = Column(Integer, ForeignKey("deliverable_definitions.id"), nullable=False)
    requested_by_email = Column(String, nullable=False)
    requested_by_name = Column(String, nullable=True)
    # Human-readable snapshot of the formula at request time -- survives
    # later edits, so a stale suggestion still reads sensibly in history.
    current_summary = Column(Text, nullable=True)
    proposed_branches = Column(JSON, nullable=False)  # same shape the admin branch-editor submits
    # [Deliverable weights]: optional -- a suggestion can carry a weight
    # change alongside (or instead of) a formula change. None means "no
    # weight change proposed", not "weight 0" (0 is rejected at the API).
    proposed_weight = Column(Float, nullable=True)
    comment = Column(Text, nullable=False)  # the rationale ("needs more time because...")
    status = Column(String, default="pending")  # pending | approved | rejected
    requested_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)
    decided_by_email = Column(String, nullable=True)
    decision_comment = Column(Text, nullable=True)
    applied_change_log_id = Column(Integer, ForeignKey("deliverable_definition_change_log.id"), nullable=True)

    definition = relationship("DeliverableDefinition")


class DeliverableSubmission(Base):
    """The transactional layer — one row per (project x deliverable_definition)."""
    __tablename__ = "deliverable_submissions"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    deliverable_definition_id = Column(Integer, ForeignKey("deliverable_definitions.id"), nullable=False)
    due_date = Column(Date, nullable=True)
    status = Column(Enum(SubmissionStatus), default=SubmissionStatus.NO_PROGRESS)
    applicability = Column(String, default="applicable")  # applicable | not_required | pending (L0 BM triage)
    owner_email = Column(String, nullable=True)  # legacy single value, superseded by owner_emails below
    owner_emails = Column(JSON, nullable=True)  # list[str] snapshotted from the definition's default_owner_emails at creation
    sme_email = Column(String, nullable=True)  # legacy single value, superseded by sme_emails below
    sme_emails = Column(JSON, nullable=True)  # list[str] snapshotted from the definition's default_sme_emails at creation
    file_name = Column(String, nullable=True)
    file_ref = Column(String, nullable=True)  # storage provider's identifier for the uploaded file
    submitted_at = Column(DateTime, nullable=True)
    review_comment = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    # Item [multi-SME]: which of the (possibly several) assigned SMEs
    # actually made this call -- needed now that sme_emails can hold more
    # than one person, so the SME leaderboard can credit the one who really
    # acted instead of splitting/duplicating credit across everyone assigned.
    reviewed_by_email = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Items 115/116: True for a handful of Tendering items auto-approved at
    # creation from data already on the project's own form (Announcement
    # Date, Site Visit Date, etc.) — status is still a genuine APPROVED (so
    # milestone "reached" logic and predecessor chaining work exactly like
    # a real approval), this flag is what actually excludes them from
    # Assigned Deliverables / the project detail list / Gantt / performance.
    auto_completed = Column(Boolean, default=False)
    # Due-date extension / hold requests (Owner-initiated, SME/Admin
    # approves via DueDateRequest below). While on_hold, deadline_status()
    # reports "on_hold" instead of due/late and recompute_project_due_dates
    # freezes due_date entirely -- see rules.py.
    on_hold = Column(Boolean, default=False)
    on_hold_since = Column(DateTime, nullable=True)
    hold_reason = Column(Text, nullable=True)
    # Set once an extension is approved, or a hold is resumed (due_date
    # shifted forward by the held duration) -- tells
    # recompute_project_due_dates to stop overwriting due_date from the
    # anchor formula, the same way it already skips APPROVED rows.
    due_date_locked = Column(Boolean, default=False)
    # Item [due-soon nudge]: which day-thresholds (14/7/2/1 days out) have
    # already fired a reminder for the *current* due_date -- paired with
    # due_soon_reminded_for_date so an extension or a hold-resume shifting
    # due_date makes every threshold eligible again automatically (the pair
    # no longer matches the new due_date), with nothing else to reset by
    # hand. due_soon_reminded_for_date alone (without the offsets list)
    # could only ever represent "reminded or not", not which of the four
    # thresholds already fired.
    due_soon_reminded_for_date = Column(Date, nullable=True)
    due_soon_reminded_offsets = Column(JSON, nullable=True)
    # [PO Lifecycle]: set only for submissions of a line_item_category
    # definition -- identifies which named PoLineItem (e.g. "GIS") this
    # particular copy of the step belongs to. Null for every ordinary
    # (non-fan-out) submission, same as today.
    po_line_item_id = Column(Integer, ForeignKey("po_line_items.id"), nullable=True)
    # [PO Lifecycle]: pre-approval scratch space on a *declaring* item's own
    # submission (1.2, 4.1, 2.11, 2.17) -- the owner edits this in place via
    # PATCH /po-selection while working the item, and it's read exactly once,
    # at approval, to create/soft-cancel the PoLineItems it declares. Shape
    # depends on item_no: {"long_lead_items":[{name,qty,unit,supplier,
    # delivery_est}...], "mep_selected":[...]} for 1.2; {"selected":[...]}
    # for 4.1; {"items":[...]} for 2.11/2.17.
    po_selection = Column(JSON, nullable=True)

    project = relationship("Project", back_populates="submissions", foreign_keys=[project_id])
    definition = relationship("DeliverableDefinition")
    history = relationship("WorkflowHistory", back_populates="submission", cascade="all, delete-orphan")
    # Two distinct FK paths now exist between these tables (this column, and
    # PoLineItem.source_submission_id going the other way) -- foreign_keys
    # pins this relationship to the fan-out direction, not the declaring one.
    po_line_item = relationship("PoLineItem", back_populates="submissions", foreign_keys=[po_line_item_id])


class WorkflowHistory(Base):
    __tablename__ = "workflow_history"
    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("deliverable_submissions.id"), nullable=False)
    action = Column(String, nullable=False)  # submitted | assigned | review_requested | approved | rejected | unlocked
    actor_name = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    submission = relationship("DeliverableSubmission", back_populates="history")


class PoLineItem(Base):
    """A single named PO deliverable line (e.g. "GIS", "Towers", "Topography
    Survey") within one of the four PO Lifecycle tracks, tracked
    independently through its category's shared step chain -- one item might
    be at 3.2 while another is already at 3.4 on the same project.
    """
    __tablename__ = "po_line_items"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    category = Column(String, nullable=False)  # long_lead | early_activity | mep | consultancy | sc
    name = Column(String, nullable=False)
    source = Column(String, nullable=False)  # excel | manual | checklist | fixed
    # long_lead: {qty, unit, supplier, delivery_est, sheet}. early_activity/mep: {checklist_type}.
    meta = Column(JSON, nullable=True)
    status = Column(String, default="active")  # active | cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by_email = Column(String, nullable=True)
    # [PO Lifecycle correction]: which declaring submission (1.2/4.1/2.11/
    # 2.17) this item came from, so sync_from_submission can diff its own
    # previously-created items against the declaring item's current
    # po_selection on every approval -- null on the synthetic pre-migration
    # "Item 1 (migrated)" rows, which have no real declaring submission.
    source_submission_id = Column(Integer, ForeignKey("deliverable_submissions.id"), nullable=True)

    project = relationship("Project")
    submissions = relationship("DeliverableSubmission", back_populates="po_line_item",
                                foreign_keys="DeliverableSubmission.po_line_item_id")


class Document(Base):
    """Supplementary documents on a submission, on top of its one primary file
    — e.g. supporting evidence added while the SME is already reviewing.
    Each document is reviewed on its own, independent of the submission's
    own overall status (which is still driven by the primary upload/mark-
    complete/review flow, unchanged).
    """
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("deliverable_submissions.id"), nullable=False)
    file_name = Column(String, nullable=False)
    file_ref = Column(String, nullable=False)
    uploaded_by = Column(String, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="pending")  # pending | approved | rejected
    comment = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    submission = relationship("DeliverableSubmission")


class TenderDocument(Base):
    """Plain project-level file storage for the "0. Tender Documents" folder.
    Deliberately NOT a DeliverableDefinition/Department -- no due date,
    owner, SME, or review step, and invisible to every tracking/performance/
    achievement calculation, all of which key off DeliverableSubmission.
    An L1 project gets its own copies (see create_l1_project) rather than
    referencing the L0's rows directly, so later additions on one side
    don't silently appear on the other.
    """
    __tablename__ = "tender_documents"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    file_name = Column(String, nullable=False)
    file_ref = Column(String, nullable=False)
    # Relative subfolder path within "0. Tender Documents" (e.g. "Drawings/Civil"),
    # "" for a file uploaded at the root. Set from the browser's own
    # webkitRelativePath when a whole folder is uploaded, so the folder
    # structure the BM already organized on their machine carries straight
    # into the platform instead of flattening into one file list.
    folder_path = Column(String, nullable=False, default="")
    uploaded_by = Column(String, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project")


class Follower(Base):
    """A person who opted in to updates on one specific deliverable submission
    (due/uploaded/approved/rejected), independent of being its owner or SME.
    """
    __tablename__ = "followers"
    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("deliverable_submissions.id"), nullable=False)
    email = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ReassignmentRequest(Base):
    """Owner-initiated request to hand a deliverable to someone else, subject
    to admin approval before the submission's owner_email actually changes.
    """
    __tablename__ = "reassignment_requests"
    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("deliverable_submissions.id"), nullable=False)
    from_email = Column(String, nullable=True)
    to_email = Column(String, nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(String, default="pending")  # pending | approved | rejected
    requested_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)

    submission = relationship("DeliverableSubmission")


class BidValueAccessRequest(Base):
    """A Viewer's request to see one L1 project's hidden Bid Value, subject
    to Admin approval -- once approved, that person keeps standing access
    to that project's Bid Value permanently (no re-request, no expiry).
    Same request/decide shape as ReassignmentRequest/DueDateRequest below.
    """
    __tablename__ = "bid_value_access_requests"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    requested_by_email = Column(String, nullable=False)
    requested_by_name = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending | approved | rejected
    requested_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)
    decided_by_email = Column(String, nullable=True)

    project = relationship("Project")


class SmeNomination(Base):
    """Self-nomination: a user (already in the L0-L1 Group roster) picks one
    or more catalog items they see themselves fit to be SME for -- one row
    per (email, deliverable_definition), not one row per submission event,
    so an admin approves/rejects each item individually. Approving both
    grants the User.role=SME (if not already) and adds the nominee to that
    specific item's default_sme_emails -- a nomination alone never changes
    anything by itself.
    """
    __tablename__ = "sme_nominations"
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
    name = Column(String, nullable=True)
    deliverable_definition_id = Column(Integer, ForeignKey("deliverable_definitions.id"), nullable=False)
    status = Column(String, default="pending")  # pending | approved | rejected
    requested_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)
    decided_by_email = Column(String, nullable=True)
    decision_comment = Column(Text, nullable=True)

    definition = relationship("DeliverableDefinition")


class UserAddRequest(Base):
    """Anyone already in the L0-L1 Group roster can request that a new
    email be added to it -- an Admin approves/rejects before it becomes a
    real roster member (mirrors SmeNomination's request-then-decide shape:
    a request alone never changes the roster by itself). `role` is capped
    to non-Admin roles at request time (see departments._GROUP_REQUEST_ROLES)
    -- granting Admin still requires an Admin to do it directly via the
    roster's own role dropdown, not through self-service.
    """
    __tablename__ = "user_add_requests"
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
    name = Column(String, nullable=True)
    role = Column(String, default="Viewer")
    requested_by_email = Column(String, nullable=False)
    requested_by_name = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending | approved | rejected
    requested_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)
    decided_by_email = Column(String, nullable=True)
    decision_comment = Column(Text, nullable=True)


class DueDateRequest(Base):
    """Owner-initiated request against one deliverable's due date, subject to
    SME/Admin approval -- either an "extension" (move due_date to
    requested_due_date) or a "hold" (pause lateness entirely until resumed).
    One table with a kind discriminator rather than two near-duplicate
    tables, matching how DeliverableSubmission.applicability is already a
    string discriminator rather than a separate table per state.
    """
    __tablename__ = "due_date_requests"
    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("deliverable_submissions.id"), nullable=False)
    kind = Column(String, nullable=False)  # extension | hold
    requested_by_email = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    requested_due_date = Column(Date, nullable=True)  # extension only
    status = Column(String, default="pending")  # pending | approved | rejected
    requested_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)
    decided_by_email = Column(String, nullable=True)
    decision_comment = Column(Text, nullable=True)
    # Item [request escalation]: set once the nightly check flags this
    # request as still pending after 3 days -- a one-shot marker, not a
    # counter, so the escalation nudge fires exactly once per request (per
    # the pilot's "for now only once" answer) rather than repeating daily.
    escalated_at = Column(DateTime, nullable=True)

    submission = relationship("DeliverableSubmission")


class SupportRequest(Base):
    """A question/issue raised from the 'Ask the Team' tab, routed to admins —
    not tied to a specific submission since the asker may not know which one.
    """
    __tablename__ = "support_requests"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=True)
    email = Column(String, nullable=False)
    stage = Column(String, nullable=True)  # "L0" | "L1" | null
    est_no = Column(String, nullable=True)
    deliverable = Column(String, nullable=True)  # free text, e.g. "2.4 Risk Register"
    target_email = Column(String, nullable=True)  # item 37: null = Admins generally, else a specific SME
    message = Column(Text, nullable=False)
    status = Column(String, default="open")  # open | resolved
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    messages = relationship("SupportMessage", back_populates="request", cascade="all, delete-orphan",
                             order_by="SupportMessage.created_at")


class SupportMessage(Base):
    """A back-and-forth reply on a SupportRequest (item 77) — admin and asker
    keep replying here until an admin marks the request resolved, at which
    point the asker's own reply endpoint stops accepting new messages.
    """
    __tablename__ = "support_messages"
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("support_requests.id"), nullable=False)
    author = Column(String, nullable=False)  # "admin" | "asker"
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Item 172.1: an admin can answer by pointing at an existing KB entry
    # instead of writing fresh -- kept here (not just used transiently) so
    # resolve-time KB creation can tell this thread already has a real
    # answer on record and skip adding a duplicate.
    kb_reference_id = Column(Integer, ForeignKey("kb_entries.id"), nullable=True)

    request = relationship("SupportRequest", back_populates="messages")


class KnowledgeBaseEntry(Base):
    """Item 150: a shared, searchable record of admin-answered questions from
    Ask the Team. Auto-created the first time an admin replies to an open
    request -- unless the admin instead references an existing entry (see
    support.py's admin_reply), which reuses that entry as the answer instead
    of adding a duplicate question. category is auto-set from the request's
    own stage (L0/L1/General), not a manual pick -- keeps this fully
    automatic per the original ask ("every admin-answered question is
    auto-added ... and categorized").
    """
    __tablename__ = "kb_entries"
    id = Column(Integer, primary_key=True)  # doubles as its display number
    category = Column(String, nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    source_request_id = Column(Integer, ForeignKey("support_requests.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class BmTriagePreference(Base):
    """A Bid Manager's last applicable/not-required call for a given item_no
    (item 79) — upserted every time that BM completes a triage, then used to
    pre-select the same choice the next time they triage a different L0
    tender, since the same BM tends to make the same calls project to project.
    """
    __tablename__ = "bm_triage_preferences"
    id = Column(Integer, primary_key=True)
    bid_manager = Column(String, nullable=False)
    item_no = Column(String, nullable=False)
    applicable = Column(Boolean, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PerformanceSnapshot(Base):
    """Item 42: one row per department per stage per calendar month, so the
    Performance tab's trend can eventually show real month-over-month
    history. The app has never recorded this before this item, so real
    history only starts accumulating from whenever this first runs --
    there's nothing to backfill honestly, and the frontend deliberately
    doesn't try to chart or "time-travel" through history until there are
    at least two real months to compare.
    """
    __tablename__ = "performance_snapshots"
    id = Column(Integer, primary_key=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    stage = Column(Enum(Stage), nullable=False)
    month = Column(Date, nullable=False)  # always the 1st of the month
    pct = Column(Float, nullable=True)  # None when the cohort was empty that month (N/A, not 0)
    approved = Column(Integer, nullable=False)
    total = Column(Integer, nullable=False)
    captured_at = Column(DateTime, default=datetime.utcnow)


class Announcement(Base):
    __tablename__ = "announcements"
    id = Column(Integer, primary_key=True)
    type = Column(Enum(AnnouncementType), nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    recipients = Column(String, nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    submission_id = Column(Integer, ForeignKey("deliverable_submissions.id"), nullable=True)
    email_status = Column(String, default="pending")  # pending | sent | failed | simulated
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", foreign_keys=[project_id])

    @property
    def project_international(self) -> bool:
        # [L0 International]: Announcement has no stage/international column
        # of its own -- badging a row is always resolved through its project.
        return bool(self.project.is_international) if self.project else False


class AiChatUsage(Base):
    """Daily message-count throttle for AI Support -- keyed by the same
    self-reported actor_email everything else in this pilot trusts (see
    support.py's own docstring on the trust model; an empty/unset email
    shares one "(anonymous)" bucket, same backstop as everywhere else).
    DB-backed rather than an in-memory counter: this app redeploys often,
    and an in-memory count would reset on every deploy, making a "per day"
    limit meaningless. One row per (email, day); see ai_support.py.
    """
    __tablename__ = "ai_chat_usage"
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
    usage_date = Column(Date, nullable=False)
    count = Column(Integer, default=0)

    __table_args__ = (UniqueConstraint("email", "usage_date", name="uq_ai_chat_usage_email_date"),)

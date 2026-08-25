"""Due-date rule engine, matching the real formulas in L0 Template (Final).xlsx
column O and New L1 Template (Final).xlsx columns I/K/L, verbatim where possible.

Milestones are derived, not stored: a milestone is "reached" exactly when its
linked deliverable (is_milestone=True) has status APPROVED for that project.
"""
import re
from datetime import date, timedelta
from sqlalchemy.orm import Session, joinedload

from . import models

# [Deliverables Configuration]: compute_due_date itself no longer reads any
# of these five item-number sets/functions directly -- due-date math is now
# entirely branch-driven (DeliverableFormulaBranch, see compute_due_date's
# own docstring). They're kept here purely as the documented reference data
# seed.py's _DEFAULT_FORMULA_BRANCHES reads from to build each of these
# items' initial seeded branches, so there's still exactly one place that
# says "which items get PBU-conditional/site-visit-fallback/tiered/
# threshold/OR-formula treatment" -- not duplicated into seed.py by hand.
#
# L0 items 1.8/1.9/1.10 branch on whether the project's scope includes PBU —
# the one recurring conditional pattern in the real template. Driven by
# Project.scope_contains_pbu, itself derived from business_units (see
# compute_business_units below) at project-creation time.
PBU_CONDITIONAL_ITEMS = {"1.8", "1.9", "1.10"}

# Business Unit auto-detection from scope. A project can trigger more than
# one BU at once (e.g. an OHTL EHV + SS MV project is both PBU and DBU).
# Scope values outside all four rules (BESS HV/EHV, HVDC, Other) can't be
# auto-classified — the caller must collect business_units manually instead
# (TBA allowed) when compute_business_units reports needs_manual=True.
_BU_TBU_SCOPES = {"SS HV (110-132 KV)", "SS EHV (230-400 KV)"}
_BU_PBU_SCOPES = {
    "UGC HV (110-132 KV)", "UGC EHV (230-400 KV)",
    "OHTL HV (110-132 KV)", "OHTL EHV (230-400 KV)",
}
_BU_DBU_SCOPES = {
    "SS MV (Distribution)", "UGC MV (Distribution)",
    "OHTL MV (Distribution)", "BESS MV (Distribution)",
}
_BU_UNCOVERED_SCOPES = {"BESS HV (110-132 KV)", "BESS EHV (230-400 KV)", "HVDC", "Other"}
BU_UNCOVERED_SCOPES = sorted(_BU_UNCOVERED_SCOPES)  # exposed to the create-form UI so it knows when to require a manual pick


def compute_business_units(scope: list[str] | None) -> tuple[list[str], bool]:
    """Returns (business_units, needs_manual). When needs_manual is True, the
    caller must collect business_units from the user instead (scope includes
    something outside the four auto-detectable rules).
    """
    scope = scope or []
    if any(s in _BU_UNCOVERED_SCOPES for s in scope):
        return [], True
    bus = set()
    if any(s in _BU_TBU_SCOPES for s in scope):
        bus.add("TBU")
    if any(s in _BU_PBU_SCOPES for s in scope):
        bus.add("PBU")
    if any(s in _BU_DBU_SCOPES for s in scope):
        bus.add("DBU")
    if any(s.startswith("SS ") for s in scope):  # BBU: always present for SS projects
        bus.add("BBU")
    return sorted(bus), False


# L0: Operation Units is split into one sub-folder per business unit (TBU/
# PBU/DBU/BBU), each carrying its own independent copy of items 2.1-2.6 —
# a project only gets the folder(s) matching its actual business_units.
L0_OPERATION_BU_DEPARTMENTS = {
    "Operation Units (TBU)": "TBU",
    "Operation Units (PBU)": "PBU",
    "Operation Units (DBU)": "DBU",
    "Operation Units (BBU)": "BBU",
}

# L1: these departments only apply to BBU (buildings) projects — no folder or
# deliverables for a project that doesn't involve BBU at all.
L1_BBU_ONLY_DEPARTMENTS = {"BBU", "BBU / PBU"}

# L1 (item 122): mirrors L0_OPERATION_BU_DEPARTMENTS above — "TBU / PBU" is
# split into real per-BU folders, each only applying to a project that
# actually has that business unit.
# Item 168: these keys were left as the bare "TBU"/"PBU"/etc. names from
# before the item-122 rework renamed the actual departments to
# "Operation Units (TBU)" etc. (matching L0's naming) -- .get() against the
# real department name always missed, so every L1 Operation Units folder
# fell through to the ungated "return True" below and showed for every
# project regardless of its actual business unit.
L1_OPERATION_BU_DEPARTMENTS = {
    "Operation Units (TBU)": "TBU",
    "Operation Units (PBU)": "PBU",
    "Operation Units (DBU)": "DBU",
    "Operation Units (BBU)": "BBU",
}


def is_project_terminal(project: "models.Project") -> bool:
    """A closed project (L0 Submitted/Cancelled, L1 Completed) is read-only
    for every deliverable action -- upload, mark complete, review, mark not
    required. Single source of truth for that check: the frontend list view
    already gated on this same rule (as a duplicated JS condition), but the
    endpoints themselves had no matching guard, so the *modal* action
    buttons (a separate render path from the list row) rendered unchecked
    and let an Owner upload against a closed project.
    """
    return (project.stage == models.Stage.L0 and project.status in
            (models.ProjectStatus.SUBMITTED, models.ProjectStatus.CANCELLED)) or (
            project.stage == models.Stage.L1 and project.status == models.ProjectStatus.COMPLETED)


def can_act(actor_role: str, actor_email: str, assigned_email) -> bool:
    """Admins can always act. Otherwise the actor must be one of the specific
    people assigned (owner, or any one of possibly several SMEs) — not just
    'anyone with that role'. `assigned_email` takes either a single email
    (existing owner/bid-manager call sites) or a list (multi-SME) — any one
    match is enough.
    """
    if actor_role == "Admin":
        return True
    if not assigned_email or not actor_email:
        return False
    actor = actor_email.strip().lower()
    candidates = assigned_email if isinstance(assigned_email, (list, tuple, set)) else [assigned_email]
    return any(actor == c.strip().lower() for c in candidates if c)


def resolve_smes(sub: "models.DeliverableSubmission") -> list[str]:
    """Every SME who may approve/reject this submission — any one of them
    can act. Falls back: submission-level list -> catalog default list ->
    either field's legacy single value, for rows seeded before this existed.
    """
    if sub.sme_emails:
        return sub.sme_emails
    if sub.definition.default_sme_emails:
        return sub.definition.default_sme_emails
    legacy = sub.sme_email or sub.definition.default_sme_email
    return [legacy] if legacy else []


def resolve_owners(sub: "models.DeliverableSubmission") -> list[str]:
    """Every Owner who may act on this submission (upload, mark complete,
    reopen) — any one of them can act. Same fallback shape as
    resolve_smes(): submission-level list -> catalog default list ->
    either field's legacy single value, for rows seeded before this existed.
    """
    if sub.owner_emails:
        return sub.owner_emails
    if sub.definition.default_owner_emails:
        return sub.definition.default_owner_emails
    legacy = sub.owner_email or sub.definition.default_owner_email
    return [legacy] if legacy else []


def resolve_focal_emails(definition: "models.DeliverableDefinition", project: "models.Project | None" = None) -> list[str]:
    """List form of deliverable_focal() below, for building real recipient
    lists rather than a single display string.
    """
    # [L0 International]: "Tendering Department (International)" gets the
    # same BM-as-focal treatment as the standard one.
    if definition.department.name.startswith("Tendering Department") and project is not None and project.bid_manager:
        return [project.bid_manager]
    if definition.focal_point_emails:
        return definition.focal_point_emails
    if definition.focal_point_email:
        return [definition.focal_point_email]
    if definition.department.focal_point_email:
        return [definition.department.focal_point_email]
    return []


def is_bu_applicable(definition: models.DeliverableDefinition, project: models.Project) -> bool:
    """Whether a deliverable definition should be instantiated for this
    project's Business Unit(s). Ungated (True) when business_units is
    empty. TBA (business unit not yet decided) specifically blocks the
    Operation Units department -- showing every possible variant (TBU/
    PBU/DBU/BBU) at once until someone actually decides read as confusing
    duplicate folders, not helpful, so a TBA project now instantiates none
    of them until the BU is actually set (editable anytime after, same as
    any other business unit change, which re-instantiates normally).
    Everything else -- including the separate L1_BBU_ONLY_DEPARTMENTS
    concern below -- stays ungated for TBA, since only Operation Units is
    what "operation deliverables" refers to.
    """
    bus = project.business_units or []
    if not bus:
        return True
    if definition.stage == models.Stage.L0:
        required = L0_OPERATION_BU_DEPARTMENTS.get(definition.department.name)
        if required:
            return required in bus  # TBA correctly excludes every variant here
        return True
    required = L1_OPERATION_BU_DEPARTMENTS.get(definition.department.name)
    if required:
        return required in bus  # TBA correctly excludes every variant here
    if definition.department.name in L1_BBU_ONLY_DEPARTMENTS:
        if "TBA" in bus:
            return True
        return "BBU" in bus
    return True


# [PBU scope routing]: Engineering and Supply Chain each split into two
# variants -- an original department and a "(PBU)" one -- gated by SCOPE
# rather than business_units, and independently of each other:
#   Engineering (PBU)  applies when scope includes any OHTL value.
#   Procurement (PBU)  applies when scope includes any OHTL or UGC value.
# Both a variant and its original can be active on the same project at once
# (a mixed SS + OHTL project shows both Engineering variants, and both
# Supply Chain variants) -- this mirrors the business-unit split above
# (Operation Units (TBU)/(PBU)/etc. can likewise co-exist), just keyed off
# scope instead of business_units. Shares SCOPE_OPTIONS with
# compute_business_units above rather than a separate hardcoded list, so a
# new scope option can't silently fall out of sync between the two.
_ENG_PBU_TRIGGER_SCOPES = {s for s in models.SCOPE_OPTIONS if s.startswith("OHTL ")}
_PROCUREMENT_PBU_TRIGGER_SCOPES = {s for s in models.SCOPE_OPTIONS if s.startswith(("OHTL ", "UGC "))}

# department name -> ("pbu" | "not_pbu", trigger scopes for that department pair)
_SCOPE_ROUTED_DEPARTMENTS = {
    "Engineering Department": ("not_pbu", _ENG_PBU_TRIGGER_SCOPES),
    "Engineering (PBU)": ("pbu", _ENG_PBU_TRIGGER_SCOPES),
    "Supply Chain": ("not_pbu", _PROCUREMENT_PBU_TRIGGER_SCOPES),
    "Procurement (PBU)": ("pbu", _PROCUREMENT_PBU_TRIGGER_SCOPES),
}


def is_scope_variant_applicable(definition: models.DeliverableDefinition, project: models.Project) -> bool:
    """Companion to is_bu_applicable, for the Engineering/Supply Chain PBU
    routing above. True (ungated) for every department outside that split.
    Scope is required at project creation, so an empty scope here shouldn't
    happen in practice -- defaults to the original (non-PBU) department
    rather than hiding both variants, matching is_bu_applicable's own
    "unknown shouldn't hide anything" stance.
    """
    routing = _SCOPE_ROUTED_DEPARTMENTS.get(definition.department.name)
    if not routing:
        return True
    kind, trigger_scopes = routing
    scope = project.scope or []
    if not scope:
        return kind == "not_pbu"
    if kind == "pbu":
        return any(s in trigger_scopes for s in scope)
    return any(s not in trigger_scopes for s in scope)


def is_international_applicable(definition: models.DeliverableDefinition, project: models.Project) -> bool:
    """Companion to is_bu_applicable/is_scope_variant_applicable: an
    international-only department (Department.is_international) only ever
    instantiates on an international project, and a standard-L0 department
    never instantiates on one -- the two catalogs never mix. L1 has no
    international concept at all, so this is always True there (every L1
    department has is_international False, matching project.is_international
    always False for an L1 project too).
    """
    return bool(definition.department.is_international) == bool(getattr(project, "is_international", False))

# [Deliverables Configuration]: same "seed-data reference only" note as
# PBU_CONDITIONAL_ITEMS above -- compute_due_date doesn't read these
# directly anymore, seed.py's _DEFAULT_FORMULA_BRANCHES does.
#
# L0: these three items' duration is 3 working days if the tender window
# (BSD - announcement) is under 30 calendar days, else 7 — independent of
# the PBU branch above, which (when it applies) overrides the anchor entirely.
L0_THRESHOLD_DURATION_ITEMS = {"1.8", "1.9", "1.10"}

# L0: "Prepare Risk Register" items that normally chain off the site visit
# report(s), but fall back to announcement + 3 working days if this project
# has no site visit scheduled at all (site_visit_date left blank).
# Item 141 renumber: Financial Department's old "8.1" split into Treasury's
# "9.1" and Finance's "10.1" (both keep a Risk Register copy); SHEQ
# Department's Risk Register is now duplicated onto both Quality's "11.1"
# and HSSE's "12.1".
L0_SITE_VISIT_FALLBACK_ITEMS = {"2.4", "3.1", "4.1", "5.1", "9.1", "10.1", "11.1", "12.1"}

# [L0 International]: these items' own source-template formula is a genuine
# two-branch "+N days from M1 OR M days from/before X" (not a single
# shortcut like every other predecessor item) -- item_no -> (alt predecessor
# item_no, alt offset_days, alt offset_direction). Confirmed with the user
# (2026-08-24, reviewing the Est-1641 sample against this catalog): compute
# both the item's own normal (predecessor_item_no/offset_days) branch AND
# this alternate. "4.5" doubles as both a key here (its own OR is against
# submission/1.24) and the alt-predecessor for 1.10/1.11/1.12 ("receiving
# engineering inputs") -- no circularity, since 4.5's own resolution never
# depends on any of those three.
# Which branch wins differs by item: the four Engineering items' own source
# formula literally ends "(which come first)" -- EARLIER of the two wins.
# 1.10/1.11/1.12 carry no such qualifier in their own source text, so they
# keep the later-wins convention decided when this was first implemented.
L0_INTL_OR_ITEMS = {
    "1.10": ("4.5", 2, "after"), "1.11": ("4.5", 2, "after"), "1.12": ("4.5", 2, "after"),
    "4.4": ("1.24", 10, "before"), "4.5": ("1.24", 10, "before"),
    "4.7": ("1.24", 10, "before"), "4.9": ("1.24", 7, "before"),
}
L0_INTL_OR_ITEMS_EARLIEST_WINS = {"4.4", "4.5", "4.7", "4.9"}


def _tender_window_days(project: "models.Project") -> int | None:
    if project.bsd is None or project.announcement_date is None:
        return None
    return (project.bsd - project.announcement_date).days


def _tiered_duration(item_no: str, window: int | None) -> int:
    """Step-function durations transcribed exactly from the template's own
    formulas (column N, rows for 4.4 and 5.3) — boundaries matter here
    (<=14 vs <30 use different comparisons), so this is spelled out
    explicitly rather than via a generic threshold table.
    """
    if item_no == "4.4":
        if window is None:
            return 14
        if window <= 14:
            return 5
        if window < 30:
            return 7
        if window < 45:
            return 10
        return 14
    if item_no == "5.3":
        if window is None:
            return 15
        return 12 if window < 14 else 15
    raise ValueError(f"no tiered duration rule for {item_no}")


def _threshold_duration(window: int | None) -> int:
    return 3 if (window is not None and window < 30) else 7


# [tight-BSD duration ratio]: some L0 tenders come with a tight BSD (e.g. 20
# calendar days) where the standard item durations genuinely don't fit
# between announcement and BSD. _apply_duration_ratio (below, called from
# recompute_project_due_dates) searches these ratios from 100% down to the
# 50% floor, in 5% steps, for the largest one where every predecessor-
# chained item's due date still lands on or before BSD -- trial and error,
# not a closed-form calculation, since the chains are too interdependent to
# solve for directly.
_DURATION_RATIO_STEPS = [1.00, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50]


def _scaled_duration(project: "models.Project", offset: int) -> int:
    """Applies the project's current duration_ratio to a workday offset,
    floored at 1 -- a ratio can shrink a 10-day item down to 1 day, never to
    0 or negative. 1.0 (the default/no-compression case) is a no-op.
    """
    ratio = getattr(project, "duration_ratio", None) or 1.0
    if ratio >= 1.0:
        return offset
    return max(1, round(offset * ratio))


_BBU_COORD_SUFFIX_RE = re.compile(r"\s*-?\s*\(in coordination with BBU\)\s*$")


def display_name(definition: models.DeliverableDefinition, project: models.Project) -> str:
    """The definition's full name, with the '(in coordination with BBU)'
    qualifier dropped when this project doesn't involve BBU at all — the
    phrasing only makes sense once BBU is actually part of the project.
    """
    name = definition.name
    if "in coordination with BBU" in name and "BBU" not in (project.business_units or []):
        name = _BBU_COORD_SUFFIX_RE.sub("", name).rstrip()
    return name


def submission_display_name(sub: "models.DeliverableSubmission") -> str:
    """display_name(), plus the named PO line item when this is a
    [PO Lifecycle] fan-out submission -- announcements/activity trail/
    reminders need to say *which* long-lead item (etc.) an approval or
    rejection is actually about, not just the shared item_no/definition
    name every sibling line item's own submission also carries.
    """
    name = display_name(sub.definition, sub.project)
    if sub.po_line_item_id:
        return f"{name} — {sub.po_line_item.name}"
    return name


def system_group_emails(db: Session) -> set[str]:
    """The "L0-L1 Group" (item 75) — every admin-added email in the system
    roster, CC'd on portal-wide broadcasts (new project, milestone reached)
    regardless of role, since Viewers have no assigned deliverable to be
    notified about any other way.
    """
    return {u.email for u in db.query(models.User).all() if u.email}


def admin_emails(db: Session) -> set[str]:
    """Everyone with the Admin role in the system roster -- the escalation
    nudge's fallback recipient, since Admin can decide any due-date request
    regardless of which SME it's actually assigned to.
    """
    return {u.email for u in db.query(models.User).filter(models.User.role == "Admin").all() if u.email}


def deliverable_focal(definition: "models.DeliverableDefinition", project: "models.Project | None" = None) -> str | None:
    """Display string (comma-joined) of who to notify about this specific
    deliverable — see resolve_focal_emails() for the real recipient list.
    """
    emails = resolve_focal_emails(definition, project)
    return ", ".join(emails) if emails else None


def document_counts(db: Session, submission_ids: list[int]) -> dict[int, int]:
    """Item 136: {submission_id: total_docs} across every Document row for a
    batch of submissions in one query, so a whole list view doesn't pay N+1
    queries for a count badge on every row.

    This already covers the primary file too, not just supplementary ones --
    /upload mirrors the primary into a Document row the same way "Add
    Document" does (so it shows up in the popup's document list one
    consistent way). Adding a separate +1 for submission.file_name here
    would double-count it. The only submissions with zero Document rows are
    ones completed via a comment instead of a file (Mark Completed with no
    upload) -- correctly 0 documents, since there genuinely isn't one.

    Per-document review no longer exists (item 143, 2nd revision) — Document
    rows are just attachments now, nothing individually tracks approval.
    """
    if not submission_ids:
        return {}
    counts: dict[int, int] = {}
    rows = (
        db.query(models.Document.submission_id)
        .filter(models.Document.submission_id.in_(submission_ids))
        .all()
    )
    for (sub_id,) in rows:
        counts[sub_id] = counts.get(sub_id, 0) + 1
    return counts


def pending_due_date_request_kinds(db: Session, submission_ids: list[int]) -> dict[int, str]:
    """Item [due-date pending pill]: {submission_id: "extension"|"hold"} for
    every submission in the batch with an outstanding DueDateRequest, one
    query for a whole list view instead of N+1. _create_due_date_request
    already guarantees at most one pending request per submission, so this
    is a plain dict, not a list.
    """
    if not submission_ids:
        return {}
    rows = (
        db.query(models.DueDateRequest.submission_id, models.DueDateRequest.kind)
        .filter(models.DueDateRequest.submission_id.in_(submission_ids),
                models.DueDateRequest.status == "pending")
        .all()
    )
    return {sub_id: kind for sub_id, kind in rows}


def mark_complete_note(submission: "models.DeliverableSubmission") -> str | None:
    """The owner's completion comment when a deliverable was submitted via
    Mark Completed instead of a file upload — the most recent 'submitted'
    WorkflowHistory note, but only surfaced when there's genuinely no file
    (an upload's 'submitted' note is just 'Uploaded <filename>', not a comment).
    """
    if submission.file_name:
        return None
    submitted_events = sorted(
        (h for h in submission.history if h.action == "submitted"),
        key=lambda h: h.created_at,
    )
    return submitted_events[-1].note if submitted_events else None


def item_sort_key(item_no: str):
    """Numeric sort key for item numbers like '1.10' — plain string sort
    would put '1.10' before '1.2', since '1' < '2' lexicographically.
    """
    try:
        return tuple(int(p) for p in item_no.split("."))
    except ValueError:
        return (999, 999)


def skip_weekend_forward(d: date) -> date:
    while d.weekday() in (4, 5):  # Friday=4, Saturday=5
        d += timedelta(days=1)
    return d


def _skip_weekend_backward(d: date) -> date:
    while d.weekday() in (4, 5):
        d -= timedelta(days=1)
    return d


def next_workday_after(d: date) -> date:
    """The next working day after d. A dependent item's work can't start the
    same calendar day its predecessor is due — it starts the day after, at
    the earliest (and later still if that lands on a weekend).
    """
    return skip_weekend_forward(d + timedelta(days=1))


def add_workdays(start: date, n: int) -> date:
    """The date n working days after start, not counting start itself and
    skipping Friday/Saturday — e.g. add_workdays(Monday, 1) is Tuesday.
    n=0 returns start unchanged.
    """
    d = start
    remaining = n
    while remaining > 0:
        d += timedelta(days=1)
        if d.weekday() not in (4, 5):
            remaining -= 1
    return d


def subtract_workdays(end: date, n: int) -> date:
    """The date n working days before end, not counting end itself and
    skipping Friday/Saturday -- mirror of add_workdays, backward. Used only
    by gantt.py's item 14.1 bar-start override, where the Excel counts
    backward a fixed number of workdays from the item's own due date
    (WORKDAY.INTL(due, -15, ...)) rather than forward from a predecessor.
    """
    d = end
    remaining = n
    while remaining > 0:
        d -= timedelta(days=1)
        if d.weekday() not in (4, 5):
            remaining -= 1
    return d


def duration_end(start: date, duration_days: int) -> date:
    """End date of a task that starts on `start` and runs `duration_days`
    working days, counting `start` itself as day 1 (a 1-day duration task
    starts and ends the same day) — the intuitive, human reading of
    "duration", not an additive offset from start.
    """
    return add_workdays(start, max(duration_days - 1, 0))


def _predecessor_anchor_date(pred_sub: "models.DeliverableSubmission") -> date | None:
    """What a downstream item should actually chain off, as distinct from
    the predecessor's own `due_date` (which stays the ORIGINAL PLANNED
    deadline — untouched — because Performance/KPI scoring compares actual
    submission date against it to measure lateness; overwriting it would
    make everything score as always-on-time).

    - Approved: the real finish date (reviewed_at), not the possibly-stale
      plan — a predecessor finished 5 days late means downstream work
      genuinely could only start from that later date.
    - Not yet approved: the planned due date, unless that date has already
      passed and it's still not done — then anchor to today, so downstream
      dates keep sliding forward for as long as the predecessor stays late.
    """
    if pred_sub.status == models.SubmissionStatus.APPROVED and pred_sub.reviewed_at:
        return pred_sub.reviewed_at.date()
    if pred_sub.due_date is None:
        return None
    return max(pred_sub.due_date, date.today())


def _get_submissions(db: Session, project_id: int, item_no: str, stage,
                      referring_department_id: int | None = None,
                      referring_line_item_id: int | None = None,
                      lookup: dict[str, list] | None = None) -> list:
    """Every submission in the project matching this item_no — normally
    exactly one, except Operation Units' TBU/PBU/DBU/BBU split, where the
    same item_no ("2.1".."2.6") exists once per business unit a project
    actually spans, and [PO Lifecycle] line-item-tracked items ("2.2",
    "3.1".."3.7", etc.), which exist once per named PoLineItem. When
    referring_department_id is given and at least one match shares it, only
    those are returned — a within-department reference (TBU's own 2.4
    depending on TBU's own 2.2) must never pull in a sibling BU's copy of
    the same item_no. A cross-department reference (e.g. Supply Chain's 3.1
    depending on Operation Units' 2.2) has no same-department match, so it
    falls through to every active BU variant. referring_line_item_id
    narrows the same way on top: GIS's 3.1 must anchor off GIS's own 2.2,
    not the transformer's — but a predecessor that isn't itself line-item-
    tracked (po_line_item_id always None, a single project-level row) still
    resolves for every line item, since it has no line-item match to narrow
    to and falls through unchanged.
    """
    if lookup is not None:
        candidates = lookup.get(item_no, [])
    else:
        candidates = (
            db.query(models.DeliverableSubmission)
            .join(models.DeliverableDefinition)
            .filter(
                models.DeliverableSubmission.project_id == project_id,
                models.DeliverableDefinition.item_no == item_no,
                models.DeliverableDefinition.stage == stage,
            )
            .all()
        )
    if referring_department_id is not None:
        same_dept = [s for s in candidates if s.definition.department_id == referring_department_id]
        if same_dept:
            candidates = same_dept
    if referring_line_item_id is not None:
        same_item = [s for s in candidates if s.po_line_item_id == referring_line_item_id]
        if same_item:
            return same_item
    return candidates


def _resolve_predecessor_anchor(db: Session, project: "models.Project", pred_item_no: str,
                                 referring_department_id: int | None = None,
                                 referring_line_item_id: int | None = None,
                                 lookup: dict[str, list] | None = None) -> date | None:
    """Resolves `predecessor_item_no`, which may list several items
    comma-separated (an AND-dependency — e.g. "2.2,2.8" for an item that
    needs both the main and PBU site visit reports). Unresolved (None)
    unless every listed predecessor has resolved; the item can't start
    until the SLOWEST of them is actually done, so the effective anchor is
    the latest (max) of their individual anchor dates — including across
    multiple simultaneously-active BU variants sharing one item_no, where
    genuinely all of them have to be done first.
    """
    item_nos = [p.strip() for p in pred_item_no.split(",") if p.strip()]
    anchors = []
    for item_no in item_nos:
        pred_subs = _get_submissions(db, project.id, item_no, project.stage,
                                      referring_department_id, referring_line_item_id, lookup)
        if not pred_subs:
            return None
        item_anchors = []
        for pred_sub in pred_subs:
            anchor = _predecessor_anchor_date(pred_sub)
            if anchor is None:
                return None
            item_anchors.append(anchor)
        anchors.append(max(item_anchors))
    return max(anchors) if anchors else None


def awaiting_milestone_note(db: Session, sub: "models.DeliverableSubmission",
                             lookup: dict[str, list] | None = None) -> str | None:
    """Item 169 (extended twice, per Yasser): a predecessor-gated deliverable
    whose predecessor isn't approved yet gets a human note instead of no
    explanation at all -- covering both shapes this takes:
      - No due date computed yet at all (fully blocked, chain traces back to
        an unresolved anchor): "Awaiting Contract Signing (M6)" for a
        milestone predecessor, "Awaiting 3.4 Prepare Risk Register" for an
        ordinary one.
      - A due date already computed (predecessor-chain dates shift forward
        day by day off the predecessor's own due_date even before it's
        actually done, per recompute_project_due_dates): that date is only
        an estimate until the predecessor is real, so it still gets a
        "Pending X completion -- date shown is tentative" note alongside it
        rather than reading as final.
    None only when the predecessor itself is already approved, or this
    isn't a predecessor-anchored item at all (un-set project date field etc).

    Excludes offset_direction == "before": that's compute_due_date's
    "counting backward from a downstream deadline" mode (e.g. an item
    scheduled some days before BSD-anchored 1.20/M5) -- it uses the
    referenced item's date purely as a scheduling anchor, the same way a
    BSD- or announcement-anchored item does, and was never actually
    waiting on that item to be completed first. Flagging it as "pending
    completion" was backwards.
    """
    if sub.definition.anchor_type != "predecessor" or sub.definition.offset_direction == "before":
        return None
    pred_item_no = sub.definition.predecessor_item_no
    if not pred_item_no:
        return None
    # [4.6 <-> 3.2 mutual gate]: 4.6 (Review SC vendor offers) reviews
    # whatever 3.2 (Negotiation window) has already put up for review --
    # the Engineering owner can start reviewing/commenting the moment 3.2
    # has any real progress (uploaded, sent for review), not only once 3.2
    # is fully approved. A "Pending 3.2 completion" note here would read as
    # a hard block it isn't, so it's suppressed once 3.2 (this same line
    # item's own copy) has moved past NO_PROGRESS -- normal predecessor
    # due-date math is untouched, this only affects the note.
    if sub.definition.item_no == "4.6":
        pred_subs_320 = _get_submissions(db, sub.project_id, "3.2", sub.definition.stage,
                                          sub.definition.department_id, sub.po_line_item_id, lookup)
        if pred_subs_320 and all(s.status != models.SubmissionStatus.NO_PROGRESS for s in pred_subs_320):
            return None
    for item_no in [p.strip() for p in pred_item_no.split(",") if p.strip()]:
        for pred_sub in _get_submissions(db, sub.project_id, item_no, sub.definition.stage,
                                          sub.definition.department_id, sub.po_line_item_id, lookup):
            if pred_sub.status != models.SubmissionStatus.APPROVED:
                if pred_sub.definition.is_milestone:
                    code = pred_sub.definition.milestone_code
                    label = pred_sub.definition.name + (f" ({code})" if code else "")
                else:
                    label = f"{pred_sub.definition.item_no} {pred_sub.definition.name}"
                if sub.due_date is None:
                    return f"Awaiting {label}"
                return f"Pending {label} completion &#8211; date shown is tentative"
    return None


def _branch_condition_met(project: "models.Project", branch: "models.DeliverableFormulaBranch",
                           is_l0: bool, window: int | None) -> bool:
    """Every non-"always" condition only ever applied to L0 (non-international)
    items historically (PBU-conditional, site-visit-fallback, tiered/
    threshold duration were all is_l0-gated in the original hardcoded
    version) -- preserved here as a blanket gate so a conditional branch
    accidentally saved on an L1 or international row just never fires,
    rather than behaving unpredictably.
    """
    ct = branch.condition_type
    if ct == "always":
        return True
    if not is_l0:
        return False
    if ct == "scope_contains_pbu":
        return bool(getattr(project, "scope_contains_pbu", False))
    if ct == "site_visit_unset":
        return project.site_visit_date is None
    if ct == "tender_window_lt_days":
        return window is not None and window < (branch.condition_value or 0)
    return False


def _resolve_branch(db: Session, sub: "models.DeliverableSubmission", project: "models.Project",
                     branch: "models.DeliverableFormulaBranch", is_l0: bool,
                     lookup: dict[str, list] | None = None) -> date | None:
    """Resolves one branch to a concrete date, or None if its anchor isn't
    available yet -- the exact same per-anchor-type math compute_due_date
    used to do inline, now reading the branch's own fields instead of the
    definition's.
    """
    if branch.anchor_type == "announcement":
        anchor = project.announcement_date
        if anchor is None:
            return None
        if branch.workday_duration:
            start = next_workday_after(anchor)
            offset = _scaled_duration(project, branch.offset_days or 0) if is_l0 else (branch.offset_days or 0)
            return duration_end(start, offset)
        return skip_weekend_forward(anchor + timedelta(days=branch.offset_days or 0))

    if branch.anchor_type == "bsd":
        anchor = project.bsd
        if anchor is None:
            return None
        return _skip_weekend_backward(anchor - timedelta(days=branch.offset_days or 0))

    if branch.anchor_type == "site_visit":
        anchor = project.site_visit_date
        if anchor is None:
            return None
        if branch.workday_duration:
            start = next_workday_after(anchor)
            offset = _scaled_duration(project, branch.offset_days or 0) if is_l0 else (branch.offset_days or 0)
            return duration_end(start, offset)
        return skip_weekend_forward(anchor + timedelta(days=branch.offset_days or 0))

    if branch.anchor_type == "pre_bid":
        anchor = project.pre_bid_deadline or date.today()
        return _skip_weekend_backward(anchor - timedelta(days=branch.offset_days or 0))

    if branch.anchor_type == "predecessor":
        if not branch.predecessor_item_no:
            return None
        anchor = _resolve_predecessor_anchor(db, project, branch.predecessor_item_no,
                                              sub.definition.department_id, sub.po_line_item_id, lookup)
        if anchor is None:
            return None
        offset = branch.offset_days or 0
        if branch.offset_direction == "before":
            # Counting backward from a downstream deadline, not waiting on
            # this predecessor to finish -- no next-workday shift, and not a
            # "how long this takes" duration, so the tight-BSD ratio never
            # applies here either (matches the original "before" branch).
            return _skip_weekend_backward(anchor - timedelta(days=offset))
        # Genuine dependency: work starts the day after the predecessor is
        # due, then runs `offset` working days (offset counts the start day
        # itself as day 1). [tight-BSD duration ratio]: scaled down first on
        # a tight-BSD L0 project, floored at 1 workday -- see Project.duration_ratio.
        start = next_workday_after(anchor)
        return duration_end(start, _scaled_duration(project, offset) if is_l0 else offset)

    return None


def compute_due_date(db: Session, sub: "models.DeliverableSubmission", project: models.Project,
                      lookup: dict[str, list] | None = None) -> date | None:
    """Resolves a submission's due date for a specific project by walking
    its definition's formula branches (DeliverableFormulaBranch, ordered by
    branch_order) -- see models.DeliverableDefinition's own docstring.
    Almost every item has exactly one unconditional ("always") branch; a
    handful carry several, evaluated in order. The first branch whose
    condition is true "commits" -- it either resolves to a date or the whole
    call returns None, with no fallthrough to a later branch (this
    reproduces every one of the original hardcoded special cases exactly:
    e.g. a PBU-scope 1.8/1.9/1.10 with its 4.4 anchor not yet resolved
    returns None, it never silently falls back to the normal M1-anchored
    branch). Branches sharing a non-null `tie_break` are the exception --
    they're a group, not a priority chain: every member whose own condition
    is true gets resolved, and the earliest/latest of what actually resolved
    wins (the international OR-formula construct).

    Takes the submission (not just its definition) so line-item-tracked
    items ([PO Lifecycle]) can narrow predecessor lookups to their own line
    item via sub.po_line_item_id — a bare definition has no way to know
    which named item ("GIS" vs "Transformer") it's being computed for.
    """
    definition = sub.definition
    branches = [b for b in definition.branches if b.active]
    if not branches:
        # client_dependent / library / on_request: no computable due date.
        return None

    # [L0 International]: an international tender's durations are literal
    # (no tight-BSD compression, no standard-L0 tiered/threshold/
    # PBU-conditional special cases) -- same math L1 already uses. Every
    # non-"always" condition stays off for these, even though
    # definition.stage is still plain "L0".
    is_l0 = definition.stage == models.Stage.L0 and not getattr(project, "is_international", False)
    window = _tender_window_days(project) if is_l0 else None

    seen_tie_break_groups: set[str] = set()
    for branch in sorted(branches, key=lambda b: b.branch_order):
        if branch.tie_break:
            if branch.tie_break in seen_tie_break_groups:
                continue
            seen_tie_break_groups.add(branch.tie_break)
            group = [b for b in branches if b.tie_break == branch.tie_break]
            candidates = [
                d for gb in group if _branch_condition_met(project, gb, is_l0, window)
                for d in [_resolve_branch(db, sub, project, gb, is_l0, lookup)] if d is not None
            ]
            if candidates:
                return max(candidates) if branch.tie_break == "latest_of_siblings" else min(candidates)
            continue
        if _branch_condition_met(project, branch, is_l0, window):
            return _resolve_branch(db, sub, project, branch, is_l0, lookup)
    return None


def sync_definition_mirror_columns(definition: "models.DeliverableDefinition") -> None:
    """Keeps the plain anchor_type/predecessor_item_no/offset_days/
    offset_direction columns in sync with branch_order 0's shape -- called
    after every branch write. These columns are read only by
    awaiting_milestone_note and gantt.py's _bar_start, both of which just
    need an approximate single-formula summary, not the real resolver; this
    keeps them exactly as accurate (or approximate, for the multi-branch
    special-case items) as they were before branches existed.
    """
    branches = sorted((b for b in definition.branches if b.active), key=lambda b: b.branch_order)
    if not branches:
        definition.anchor_type = None
        definition.predecessor_item_no = None
        definition.offset_days = 0
        definition.offset_direction = "after"
        return
    first = branches[0]
    definition.anchor_type = first.anchor_type
    definition.predecessor_item_no = first.predecessor_item_no
    definition.offset_days = first.offset_days
    definition.offset_direction = first.offset_direction


_CONDITION_LABELS = {
    "scope_contains_pbu": "If PBU scope",
    "site_visit_unset": "If no Site Visit Date is set",
}


def _describe_branch(branch: "models.DeliverableFormulaBranch") -> str:
    if branch.anchor_type == "announcement":
        unit = "working day(s)" if branch.workday_duration else "calendar day(s)"
        formula = f"{branch.offset_days} {unit} after M1 (announcement)"
    elif branch.anchor_type == "bsd":
        formula = f"{branch.offset_days} calendar day(s) before BSD"
    elif branch.anchor_type == "site_visit":
        unit = "working day(s)" if branch.workday_duration else "calendar day(s)"
        formula = f"{branch.offset_days} {unit} after the Site Visit Date"
    elif branch.anchor_type == "pre_bid":
        formula = f"{branch.offset_days} calendar day(s) before the Pre-bid deadline"
    elif branch.anchor_type == "predecessor":
        direction = "before" if branch.offset_direction == "before" else "after"
        formula = f"{branch.offset_days} workday(s) {direction} {branch.predecessor_item_no}"
    else:
        formula = "no computable date"

    if branch.condition_type == "always":
        return formula[:1].upper() + formula[1:]
    if branch.condition_type == "tender_window_lt_days":
        return f"If tender window < {branch.condition_value} days: {formula}"
    return f"{_CONDITION_LABELS.get(branch.condition_type, branch.condition_type)}: {formula}"


def describe_formula_branches(definition: "models.DeliverableDefinition") -> str:
    """Human-readable summary of every active branch, in order -- shared by
    the admin definitions list and the Owner/SME read-only formulas page so
    the two never disagree on wording. Tie-break groups are described as
    "earliest/latest of: A, or B" rather than as separate sentences.
    """
    branches = sorted((b for b in definition.branches if b.active), key=lambda b: b.branch_order)
    if not branches:
        return "No computable due date (on request / library item)."
    parts: list[str] = []
    seen: set[str] = set()
    for branch in branches:
        if branch.tie_break:
            if branch.tie_break in seen:
                continue
            seen.add(branch.tie_break)
            group = [b for b in branches if b.tie_break == branch.tie_break]
            which = "earliest" if branch.tie_break == "earliest_of_siblings" else "latest"
            options = "; or ".join(_describe_branch(gb) for gb in group)
            parts.append(f"Whichever is {which} of: {options}")
        else:
            parts.append(_describe_branch(branch))
    return ". ".join(parts) + "."


def refresh_status(submission: models.DeliverableSubmission) -> None:
    """Item 143 (2nd revision): Progress status no longer depends on
    due_date/today at all — that's Deadline status now (see
    deadline_status() below), computed live and never stored. This just
    guards against clobbering a genuine progress state (something's been
    uploaded, or it's mid/post-review) — anything else settles to
    NO_PROGRESS regardless of what its due_date happens to be.
    """
    if submission.status in (
        models.SubmissionStatus.IN_PROGRESS,
        models.SubmissionStatus.PENDING_REVIEW,
        models.SubmissionStatus.APPROVED,
        models.SubmissionStatus.REJECTED,
    ):
        return
    submission.status = models.SubmissionStatus.NO_PROGRESS


def deadline_status(submission: "models.DeliverableSubmission") -> tuple[str, int | None]:
    """Item 143 (2nd revision): Deadline standing, the axis independent of
    Progress — computed live, never stored. Returns (key, days):
      "on_hold"  — an approved hold request is active.                days=None
      "not_due"  — due_date is unset or still in the future.        days=None
      "due"      — due_date has passed and it's not yet Completed.  days negative, grows every day it stays open.
      "on_time"  — Completed exactly on its due_date.                days=None
      "early"    — Completed before its due_date.                    days positive, e.g. +5.
      "late"     — Completed after its due_date.                     days negative, e.g. -5.
    Early/On Time/Late read from reviewed_at, which is set once and never
    changes — so unlike "due"'s live-growing count, these are naturally
    frozen the moment the deliverable resolves, no separate storage needed.
    Not Required / Pending Triage deliverables have no due_date and no
    completion — callers should check for those statuses first and skip
    this entirely rather than render "Not Due" for them.
    Item [due-date requests]: on_hold is checked first, before every other
    branch -- this is the single source of truth every caller that derives
    overdue/late counts from this function (dashboard tallies, department
    scores, owner rankings, the matrix) already routes through, so an
    on-hold item stops counting as due/late everywhere for free, with no
    other call site needing its own on_hold check.
    """
    if submission.on_hold:
        return ("on_hold", None)
    if submission.status == models.SubmissionStatus.APPROVED and submission.reviewed_at and submission.due_date:
        completed = submission.reviewed_at.date()
        delta = (submission.due_date - completed).days
        if delta > 0:
            return ("early", delta)
        if delta < 0:
            return ("late", delta)
        return ("on_time", None)
    if submission.due_date is None:
        return ("not_due", None)
    if date.today() > submission.due_date:
        return ("due", -(date.today() - submission.due_date).days)
    return ("not_due", None)


def deadline_bucket(submission: "models.DeliverableSubmission") -> str:
    """The 3-state collapse used on the Dashboard and the deliverables
    matrix (item 143, 2nd revision): every Deadline/Progress combination
    folds down to just "not_due" / "due" / "completed". A Completed
    deliverable (any of On Time/Early/Late) always reads as "completed"
    here regardless of how it got there; everything else reads off its
    live Deadline status.
    """
    if submission.status == models.SubmissionStatus.APPROVED:
        return "completed"
    key, _ = deadline_status(submission)
    # Item [due-date requests]: v1 folds on_hold into "not_due" here (the
    # matrix's 3-state collapse) rather than adding a 4th bucket/color --
    # it's already correctly excluded from "due", which is what matters for
    # not showing a paused item as red/overdue.
    return "due" if key == "due" else "not_due"


def _run_due_date_pass(db: Session, project: models.Project, subs: list, lookup: dict[str, list]) -> None:
    """One full stabilization pass over every submission in `subs`, mutating
    due_date/status in place until nothing changes (or 6 passes, whichever
    first — chains in the real templates are shallow, that's always enough).
    The shared engine both recompute_project_due_dates and the duration-
    ratio search below run, so the two can never drift out of sync with
    each other.
    """
    for _pass in range(6):
        changed = False
        for s in subs:
            # Once approved, a submission's due_date is frozen — this matters most for
            # "client_dependent" items (Contract Signing, LOA, etc.): approving one
            # freezes its due_date to the real approval date, so downstream
            # predecessor-chained items get a real anchor instead of staying
            # unresolvable forever. Recomputing it would wipe that back to None.
            if s.status == models.SubmissionStatus.APPROVED:
                continue
            # Item [due-date requests]: on_hold freezes due_date entirely
            # (resumed later with an explicit forward shift, see the
            # /resume endpoint); due_date_locked marks a due_date that's
            # been manually set (an approved extension, or a just-resumed
            # hold) and must not be overwritten by the anchor formula below.
            if s.on_hold or s.due_date_locked:
                continue
            if s.applicability == "not_required":
                if s.due_date is not None or s.status != models.SubmissionStatus.NOT_REQUIRED:
                    s.due_date = None
                    s.status = models.SubmissionStatus.NOT_REQUIRED
                    changed = True
                continue
            if s.applicability == "pending":
                if s.due_date is not None or s.status != models.SubmissionStatus.PENDING_TRIAGE:
                    s.due_date = None
                    s.status = models.SubmissionStatus.PENDING_TRIAGE
                    changed = True
                continue
            new_due = compute_due_date(db, s, project, lookup)
            if new_due != s.due_date:
                s.due_date = new_due
                changed = True
            refresh_status(s)
        if not changed:
            break


def _apply_duration_ratio(db: Session, project: models.Project, subs: list, lookup: dict[str, list]) -> None:
    """[tight-BSD duration ratio], L0 only. Tries _DURATION_RATIO_STEPS from
    100% down to the 50% floor, running a full _run_due_date_pass at each
    candidate (compute_due_date reads project.duration_ratio live via
    _scaled_duration, so mutating it here and re-running the pass is enough
    to try a new ratio) until every submission's resulting due_date fits on
    or before BSD. Stops at the first (largest) ratio that fits -- due_date
    on `subs` reflects that winning ratio's pass when this returns, so the
    caller doesn't need to run its own pass afterward.

    No-ops to the standard 1.0 ratio (and clears the insufficient flag) when
    BSD or announcement_date isn't set yet -- nothing to search against.
    """
    if project.bsd is None or project.announcement_date is None:
        project.duration_ratio = 1.0
        project.duration_ratio_insufficient = False
        _run_due_date_pass(db, project, subs, lookup)
        return

    for ratio in _DURATION_RATIO_STEPS:
        project.duration_ratio = ratio
        _run_due_date_pass(db, project, subs, lookup)
        max_due = max((s.due_date for s in subs if s.due_date), default=None)
        if max_due is None or max_due <= project.bsd:
            project.duration_ratio_insufficient = False
            return
    # Every ratio tried, including the 50% floor, still overshoots BSD --
    # left applied anyway (best effort) per the "always flag when tight
    # durations are used" decision; the flag is what makes that visible.
    project.duration_ratio_insufficient = True


def recompute_project_due_dates(db: Session, project: models.Project, force: bool = False) -> None:
    """Recomputes every submission's due date for a project, in an order that
    lets predecessor chains resolve (announcement/bsd roots first, then
    predecessor-chained items, repeated until stable — chains in the real
    templates are shallow, a few passes is always enough).

    Due dates for not-yet-approved, predecessor-chained items can shift
    purely from the passage of time (an overdue predecessor keeps pushing
    dependents forward day by day — see _predecessor_anchor_date), so this
    has to run at least once per calendar day, not only right after a
    mutation. It doesn't need to run more than once a day, though: every
    caller on a plain read (dashboard, gantt, deliverables list) was re-running
    this full O(items x passes) computation on every single page view, which
    is the main cost driver at real project-count scale. Skip it once it's
    already run today, unless the caller just made a change (force=True,
    from upload/approve/triage/an admin date edit) that needs to show up in
    this same response instead of waiting for tomorrow's first read.
    """
    today = date.today()
    if not force and project.due_dates_computed_on == today:
        return

    subs = (
        db.query(models.DeliverableSubmission)
        .options(joinedload(models.DeliverableSubmission.definition))
        .filter(models.DeliverableSubmission.project_id == project.id)
        .all()
    )
    # Predecessor lookups (_get_submissions) used to run a fresh query per
    # item per pass — with ~75 items x up to 6 passes that's a few hundred
    # extra round trips per project, per read. Same objects, looked up by
    # item_no instead; mutations within the loop below (s.due_date = ...)
    # are visible through this immediately since it holds the same instances.
    # A list per item_no (not a single submission) because Operation Units'
    # TBU/PBU/DBU/BBU split means several submissions can share one item_no.
    lookup: dict[str, list] = {}
    for s in subs:
        lookup.setdefault(s.definition.item_no, []).append(s)

    # [L0 International]: no tight-BSD compression search for these -- same
    # plain pass L1 already uses, literal durations throughout.
    if project.stage == models.Stage.L0 and not project.is_international:
        _apply_duration_ratio(db, project, subs, lookup)
    else:
        project.duration_ratio = 1.0
        project.duration_ratio_insufficient = False
        _run_due_date_pass(db, project, subs, lookup)

    project.due_dates_computed_on = today


def check_l1_completion(db: Session, project: "models.Project") -> None:
    """Marks an L1 project Completed the moment every one of its deliverables
    is approved. Called right after every approval (not just as a side effect
    of loading the deliverables list), so it fires no matter which screen the
    approval happened from — the project detail page or the cross-project
    Assigned Deliverables queue.
    """
    if project.stage != models.Stage.L1 or project.status != models.ProjectStatus.IN_PROGRESS:
        return
    subs = db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.project_id == project.id).all()
    if subs and all(s.status == models.SubmissionStatus.APPROVED for s in subs):
        project.status = models.ProjectStatus.COMPLETED


def kpi_points(due_date: date | None, submitted_date: date | None, grace_days: int = 4) -> float | None:
    """The Calculation Criteria rule from architecture_map.md section 4.3,
    plus a 10% early bonus per Yasser: a submission that landed strictly
    before its due date (not merely within the grace window) earns 1.1
    points instead of 1.0. Aggregation call sites are responsible for
    capping the resulting department/owner percentage at 100 -- individual
    submissions are allowed to earn more than a full point so an early
    streak can pull an average back up, but the reported overall score
    itself never reads as more than "fully on track."
    """
    if due_date is None:
        return None
    if submitted_date is None:
        return 0.0 if date.today() > due_date else None
    if submitted_date < due_date:
        return 1.1
    days_late = (submitted_date - due_date).days - grace_days
    if days_late <= 0:
        return 1.0
    if days_late <= 7:
        return 0.9
    if days_late <= 14:
        return 0.8
    if days_late <= 21:
        return 0.7
    if days_late <= 28:
        return 0.6
    return 0.0


def item_group_kpi_pct(subs: list) -> float | None:
    """[PO Lifecycle pro-rata]: score for one item_no's worth of submissions
    -- the single project-level row an ordinary item has, or all N line
    items sharing a fan-out item_no (e.g. "2.2" across every long-lead
    item). Cohort = due_and_done (approved + overdue + pending_review),
    matching the convention every other KPI number in this app already
    uses -- an item that isn't due yet doesn't drag the group down, one
    that's overdue and still untouched scores a real 0. None only when
    nothing in the group has reached a scoreable state yet.
    """
    cohort = [
        s for s in subs
        if s.status == models.SubmissionStatus.APPROVED
        or s.status == models.SubmissionStatus.PENDING_REVIEW
        or deadline_status(s)[0] == "due"
    ]
    if not cohort:
        return None
    total = sum((kpi_points(s.due_date, s.submitted_at.date() if s.submitted_at else None) or 0.0) for s in cohort)
    return round(min((total / len(cohort)) * 100, 100.0), 1)

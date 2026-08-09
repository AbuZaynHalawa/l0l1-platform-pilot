"""Due-date rule engine, matching the real formulas in L0 Template (Final).xlsx
column O and New L1 Template (Final).xlsx columns I/K/L, verbatim where possible.

Milestones are derived, not stored: a milestone is "reached" exactly when its
linked deliverable (is_milestone=True) has status APPROVED for that project.
"""
from datetime import date, timedelta
from sqlalchemy.orm import Session

from . import models

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


# L0: items 2.7-2.12 duplicate 2.1-2.6 for the case where BBU is also involved
# on top of the main BU — only relevant when the main BU is TBU (SS HV/EHV).
# Never applies to DBU or PBU projects, even ones that also trigger BBU.
L0_TBU_ONLY_ITEMS = {"2.7", "2.8", "2.9", "2.10", "2.11", "2.12"}

# L1: these departments only apply to BBU (buildings) projects — no folder or
# deliverables for a project that doesn't involve BBU at all.
L1_BBU_ONLY_DEPARTMENTS = {"BBU", "BBU / PBU"}


def is_bu_applicable(definition: models.DeliverableDefinition, project: models.Project) -> bool:
    """Whether a deliverable definition should be instantiated for this
    project's Business Unit(s). Ungated (True) when business_units is empty
    or TBA — an unknown BU shouldn't hide anything.
    """
    bus = project.business_units or []
    if not bus or "TBA" in bus:
        return True
    if definition.stage == models.Stage.L0:
        if definition.item_no in L0_TBU_ONLY_ITEMS:
            return "TBU" in bus
        return True
    if definition.department.name in L1_BBU_ONLY_DEPARTMENTS:
        return "BBU" in bus
    return True

# L0: these three items' duration is 3 working days if the tender window
# (BSD - announcement) is under 30 calendar days, else 7 — independent of
# the PBU branch above, which (when it applies) overrides the anchor entirely.
L0_THRESHOLD_DURATION_ITEMS = {"1.8", "1.9", "1.10"}

# L0: "Prepare Risk Register" items that normally chain off the site visit
# report(s), but fall back to announcement + 3 working days if this project
# has no site visit scheduled at all (site_visit_date left blank).
L0_SITE_VISIT_FALLBACK_ITEMS = {"2.4", "2.10", "3.1", "4.1", "5.1", "8.1", "9.1"}


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


def _get_submission(db: Session, project_id: int, item_no: str, stage) -> "models.DeliverableSubmission | None":
    return (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .filter(
            models.DeliverableSubmission.project_id == project_id,
            models.DeliverableDefinition.item_no == item_no,
            models.DeliverableDefinition.stage == stage,
        )
        .first()
    )


def _resolve_predecessor_anchor(db: Session, project: "models.Project", pred_item_no: str) -> date | None:
    """Resolves `predecessor_item_no`, which may list several items
    comma-separated (an AND-dependency — e.g. "2.2,2.8" for an item that
    needs both the main and PBU site visit reports). Unresolved (None)
    unless every listed predecessor has resolved; the item can't start
    until the SLOWEST of them is actually done, so the effective anchor is
    the latest (max) of their individual anchor dates.
    """
    item_nos = [p.strip() for p in pred_item_no.split(",") if p.strip()]
    anchors = []
    for item_no in item_nos:
        pred_sub = _get_submission(db, project.id, item_no, project.stage)
        if pred_sub is None:
            return None
        anchor = _predecessor_anchor_date(pred_sub)
        if anchor is None:
            return None
        anchors.append(anchor)
    return max(anchors) if anchors else None


def compute_due_date(db: Session, definition: models.DeliverableDefinition, project: models.Project) -> date | None:
    """Resolves a deliverable definition's due date for a specific project."""
    anchor_type = definition.anchor_type

    if anchor_type == "announcement":
        anchor = project.announcement_date
        if anchor is None:
            return None
        result = anchor + timedelta(days=definition.offset_days or 0)
        return skip_weekend_forward(result)

    if anchor_type == "bsd":
        anchor = project.bsd
        if anchor is None:
            return None
        result = anchor - timedelta(days=definition.offset_days or 0)
        return _skip_weekend_backward(result)

    if anchor_type == "site_visit":
        anchor = project.site_visit_date
        if anchor is None:
            return None  # optional field — stays undated until it's provided
        result = anchor + timedelta(days=definition.offset_days or 0)
        return skip_weekend_forward(result)

    if anchor_type == "pre_bid":
        # Modifications doc: if Pre-Bid Clarification Deadline isn't entered,
        # treat the deadline as immediate — i.e. today, not undated.
        anchor = project.pre_bid_deadline or date.today()
        result = anchor - timedelta(days=definition.offset_days or 0)
        return _skip_weekend_backward(result)

    if anchor_type == "predecessor":
        item_no = definition.item_no
        is_l0 = definition.stage == models.Stage.L0
        window = _tender_window_days(project) if is_l0 else None

        # PBU-conditional branch (L0 items 1.8/1.9/1.10): if scope includes PBU,
        # anchor to 4.4 + 1 workday instead of the normal M1-anchored chain —
        # a fixed 1-day duration regardless of the item's own stored offset
        # (which only applies in the normal, non-PBU branch below).
        if is_l0 and item_no in PBU_CONDITIONAL_ITEMS and getattr(project, "scope_contains_pbu", False):
            anchor = _resolve_predecessor_anchor(db, project, "4.4")
            if anchor is None:
                return None
            return next_workday_after(anchor)

        pred_item_no = definition.predecessor_item_no
        if not pred_item_no:
            return None

        if is_l0 and item_no in L0_SITE_VISIT_FALLBACK_ITEMS and project.site_visit_date is None:
            # No site visit scheduled for this project at all — fall back to
            # a fixed +3 working days from announcement instead of staying
            # unresolvable forever (matches the template's IF(site_visit="N/A",...)).
            if project.announcement_date is None:
                return None
            start = next_workday_after(project.announcement_date)
            return duration_end(start, 3)  # the 3rd working day after announcement

        anchor = _resolve_predecessor_anchor(db, project, pred_item_no)
        if anchor is None:
            return None

        offset = definition.offset_days or 0
        if is_l0 and item_no in L0_THRESHOLD_DURATION_ITEMS:
            offset = _threshold_duration(window)
        elif is_l0 and item_no in ("4.4", "5.3"):
            offset = _tiered_duration(item_no, window)

        if definition.offset_direction == "before":
            # Counting backward from a downstream deadline (e.g. BSD-anchored
            # item 1.20), not waiting on this predecessor to finish — no
            # next-workday shift here.
            result = anchor - timedelta(days=offset)
            return _skip_weekend_backward(result)
        else:
            # Genuine dependency: work starts the day after the predecessor
            # is due, then runs `offset` working days — offset counts the
            # start day itself as day 1 (a 1-day item starts and ends the
            # same day), not an additive calendar offset.
            start = next_workday_after(anchor)
            return duration_end(start, offset)

    # "client_dependent" and library/on_request (anchor_type is None) both have no computable date.
    return None


def refresh_status(submission: models.DeliverableSubmission) -> None:
    """Recomputes status from due_date + submission state. Doesn't touch
    pending_review/approved/rejected — those only change through the
    submit/approve/reject actions, not by the passage of time.
    """
    if submission.status in (
        models.SubmissionStatus.PENDING_REVIEW,
        models.SubmissionStatus.APPROVED,
        models.SubmissionStatus.REJECTED,
    ):
        return
    if submission.due_date is None:
        submission.status = models.SubmissionStatus.NOT_DUE
        return
    submission.status = (
        models.SubmissionStatus.OVERDUE if date.today() > submission.due_date else models.SubmissionStatus.NOT_DUE
    )


def recompute_project_due_dates(db: Session, project: models.Project) -> None:
    """Recomputes every submission's due date for a project, in an order that
    lets predecessor chains resolve (announcement/bsd roots first, then
    predecessor-chained items, repeated until stable — chains in the real
    templates are shallow, a few passes is always enough).
    """
    subs = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .filter(models.DeliverableSubmission.project_id == project.id)
        .all()
    )
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
            new_due = compute_due_date(db, s.definition, project)
            if new_due != s.due_date:
                s.due_date = new_due
                changed = True
            refresh_status(s)
        if not changed:
            break


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
    """The Calculation Criteria rule from architecture_map.md section 4.3, verbatim."""
    if due_date is None:
        return None
    if submitted_date is None:
        return 0.0 if date.today() > due_date else None
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

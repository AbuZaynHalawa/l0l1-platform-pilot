from datetime import date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, rules
from ..database import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# Item [dashboard redesign 2]: shared with get_performance's own department
# loop below -- the legacy plain "Operation Units" department has real L0
# data (so has_data alone wouldn't hide it) but Yasser wants it excluded
# from performance tracking everywhere, not just the Performance tab.
_PERF_EXCLUDED_DEPTS = {"Operation Units"}


@router.get("")
def get_dashboard(focus_email: str | None = None, db: Session = Depends(get_db)):
    """`focus_email` (item 72) scopes the stat tiles, per-department Concerns
    breakdown, and Deliverables Matrix (see get_matrix) to just what that
    person owns or reviews — "My Items" narrows the whole Dashboard, not
    only the top stat cards (item 183). Project counts (active_l0/active_l1)
    stay organization-wide either way, since "how many active L0 tenders
    exist" doesn't mean anything scoped to one person.
    """
    # [Archive]: an archived project is excluded from every report/dashboard
    # -- the Dashboard is the textbook case -- so this filters at the very
    # top, before anything derives from `projects` or `all_subs` below.
    projects = db.query(models.Project).filter(models.Project.archived.is_not(True)).all()
    l0_count = sum(1 for p in projects if p.stage == models.Stage.L0 and p.status == models.ProjectStatus.IN_PROGRESS)
    l1_count = sum(1 for p in projects if p.stage == models.Stage.L1 and p.status == models.ProjectStatus.IN_PROGRESS)
    signed_count = sum(1 for p in projects if p.contract_status == models.ContractStatus.SIGNED)

    for p in projects:
        if p.status == models.ProjectStatus.IN_PROGRESS:
            rules.recompute_project_due_dates(db, p)
    db.commit()
    all_subs = db.query(models.DeliverableSubmission).join(models.DeliverableSubmission.project).filter(
        models.Project.archived.is_not(True)
    ).all()

    focus = (focus_email or "").strip().lower()
    stat_subs = all_subs
    if focus:
        stat_subs = [
            s for s in all_subs
            if focus in {e.strip().lower() for e in rules.resolve_owners(s) if e}
            or focus in {e.strip().lower() for e in rules.resolve_smes(s) if e}
        ]
    # Item [dashboard/assigned parity]: auto-completed items (1.1-1.5,
    # milestones auto-approved from the project's own fields) were never
    # real tracked work -- Assigned Deliverables excludes them entirely
    # (see list_all_deliverables), and so does every other cohort on this
    # page (_kpi_cohort, the department loops below). The stat cards were
    # the one place still counting them, which silently inflated Approved
    # and On Time by however many auto-completed items existed (these
    # always land exactly on their due date, so they all fall into On
    # Time specifically) and made the two pages disagree on the same numbers.
    stat_subs = [s for s in stat_subs if not s.auto_completed]

    # Item 143 (2nd revision): "overdue"/"not_due" are now live Deadline
    # computations, not stored statuses — see rules.deadline_status().
    # pending_review reads straight off Progress status, reached only via
    # Mark Completed now (no more owner-said/SME-confirmed split to fold
    # together here).
    _deadline_keys = [rules.deadline_status(s)[0] for s in stat_subs]
    overdue = _deadline_keys.count("due")
    not_due = _deadline_keys.count("not_due")
    # Item [dashboard cards redesign]: Deadline Status card breaks completed
    # items down into how they actually landed against their due date --
    # same on_time/early/late buckets rules.deadline_status() already
    # computes for the pills elsewhere, not a generic "Completed" count.
    early = _deadline_keys.count("early")
    on_time = _deadline_keys.count("on_time")
    late = _deadline_keys.count("late")
    pending_review = sum(1 for s in stat_subs if s.status == models.SubmissionStatus.PENDING_REVIEW)
    # Item [dashboard cards redesign]: Progress Status breakdown, same
    # bucket set as the Assigned Deliverables filter chips (PROGRESS_FILTERS
    # in app.js).
    no_progress = sum(1 for s in stat_subs if s.status == models.SubmissionStatus.NO_PROGRESS)
    in_progress = sum(1 for s in stat_subs if s.status == models.SubmissionStatus.IN_PROGRESS)
    approved = sum(1 for s in stat_subs if s.status == models.SubmissionStatus.APPROVED)
    rejected = sum(1 for s in stat_subs if s.status == models.SubmissionStatus.REJECTED)

    dept_rows = []
    for dept in db.query(models.Department).order_by(models.Department.number).all():
        # Items 115/116: auto-completed items were never real tracked work,
        # so they're excluded from the department's on-time performance
        # cohort entirely -- not counted as a win, not counted as a miss.
        # Item 117: same for any catalog item an admin has explicitly
        # opted out of performance tracking (kpi_relevant == False).
        # Item 183: draws from stat_subs, not all_subs -- stat_subs is
        # already narrowed to the focus email's own items when "My Items"
        # is on (identical to all_subs when it isn't), so Concerns scopes
        # right along with the stat cards instead of always staying org-wide.
        dept_subs = [
            s for s in stat_subs
            if s.definition.department_id == dept.id and not s.auto_completed and s.definition.kpi_relevant is not False
        ]
        dept_overdue = [s for s in dept_subs if rules.deadline_status(s)[0] == "due"]
        due_and_done = [s for s in dept_subs if s.status == models.SubmissionStatus.APPROVED] + dept_overdue + [
            s for s in dept_subs if s.status == models.SubmissionStatus.PENDING_REVIEW]
        dept_approved = sum(1 for s in dept_subs if s.status == models.SubmissionStatus.APPROVED)
        # Item [kpi rewrite]: this concerns list is the same "department
        # on-time performance" concept as the Performance tab, just pooled
        # across both stages together -- it needs the real point-based
        # Calculation Criteria too, not the old plain approved/cohort ratio,
        # or the two would silently disagree about the same department.
        total_points = sum(
            (rules.kpi_points(s.due_date, s.submitted_at.date() if s.submitted_at else None) or 0.0)
            for s in due_and_done
        )
        # Item [early bonus]: an early submission earns >1.0 points, which
        # can push this ratio past 100% -- individual items keep their real
        # bonus, but the reported department score itself caps at 100.
        pct = round(min((total_points / len(due_and_done)) * 100, 100.0), 1) if due_and_done else None
        dept_rows.append({
            "department": dept.name, "department_number": dept.number, "total": len(dept_subs), "approved": dept_approved,
            "overdue": len(dept_overdue),
            "pending_review": sum(1 for s in dept_subs if s.status == models.SubmissionStatus.PENDING_REVIEW),
            "pct": pct,
        })

    unassigned = [d.name for d in db.query(models.Department).all() if not d.focal_point_email]

    # Item [dashboard stage split]: the whole dashboard below the headline
    # cards is now two parallel sections, one per stage -- Concerns, Top
    # Departments and Newest Milestones each need their own L0 and L1
    # version instead of one pooled list.
    # Item [My Items scoping v2]: Top Departments always stays org-wide
    # (org_subs, not stat_subs) -- it's a portfolio ranking, not "my work",
    # so My Items shouldn't narrow it. Concerns keeps scoping to stat_subs
    # as before, since "my concerns" is meant to narrow to the focus
    # person's own cohort.
    org_subs = [s for s in all_subs if not s.auto_completed]
    overdue_l0 = sum(1 for s in stat_subs if s.definition.stage == models.Stage.L0 and rules.deadline_status(s)[0] == "due")
    overdue_l1 = sum(1 for s in stat_subs if s.definition.stage == models.Stage.L1 and rules.deadline_status(s)[0] == "due")
    top_depts_l0, top_depts_l1 = [], []
    concerns_l0, concerns_l1 = [], []
    for dept in db.query(models.Department).order_by(models.Department.number).all():
        if dept.name in _PERF_EXCLUDED_DEPTS:
            continue
        focus_d_subs = _kpi_cohort([s for s in stat_subs if s.definition.department_id == dept.id])
        l0_pct_focus = _level_stats(focus_d_subs, models.Stage.L0)["percentage"]
        l1_pct_focus = _level_stats(focus_d_subs, models.Stage.L1)["percentage"]
        if l0_pct_focus is not None and l0_pct_focus < 80:
            concerns_l0.append(f"<b>{dept.name}</b> is at {l0_pct_focus}% approved-on-time this pilot.")
        if l1_pct_focus is not None and l1_pct_focus < 80:
            concerns_l1.append(f"<b>{dept.name}</b> is at {l1_pct_focus}% approved-on-time this pilot.")

        org_d_subs = _kpi_cohort([s for s in org_subs if s.definition.department_id == dept.id])
        l0_pct_org = _level_stats(org_d_subs, models.Stage.L0)["percentage"]
        l1_pct_org = _level_stats(org_d_subs, models.Stage.L1)["percentage"]
        if l0_pct_org is not None:
            top_depts_l0.append({"department": dept.name, "department_number": dept.number, "pct": l0_pct_org})
        if l1_pct_org is not None:
            top_depts_l1.append({"department": dept.name, "department_number": dept.number, "pct": l1_pct_org})
    top_depts_l0 = sorted(top_depts_l0, key=lambda r: -r["pct"])[:3]
    top_depts_l1 = sorted(top_depts_l1, key=lambda r: -r["pct"])[:3]
    if overdue_l0:
        concerns_l0.append(f"<b>{overdue_l0} deliverable(s)</b> are currently overdue across active L0 tenders.")
    if overdue_l1:
        concerns_l1.append(f"<b>{overdue_l1} deliverable(s)</b> are currently overdue across active L1 projects.")
    if unassigned:
        concerns_l0.append(f"No focal point contact set for: <b>{', '.join(unassigned)}</b>.")
        concerns_l1.append(f"No focal point contact set for: <b>{', '.join(unassigned)}</b>.")

    # Newest 3 tenders/projects per stage, for the L0/L1 headline cards --
    # scoped to focus_email when "My Items" is on (item [My Items scoping
    # v2]), via the same project-id membership stat_subs already gives us.
    focus_project_ids = {s.project_id for s in stat_subs} if focus else None

    def _recent_projects(stage_enum):
        q = db.query(models.Project).filter(models.Project.stage == stage_enum, models.Project.archived.is_not(True))
        if focus_project_ids is not None:
            if not focus_project_ids:
                return []
            q = q.filter(models.Project.id.in_(focus_project_ids))
        rows = q.order_by(models.Project.created_at.desc()).limit(3).all()
        return [{"id": p.id, "est_no": p.est_no, "name": p.name, "announcement_date": p.announcement_date,
                 "is_international": p.is_international} for p in rows]

    recent_l0 = _recent_projects(models.Stage.L0)
    recent_l1 = _recent_projects(models.Stage.L1)

    # Newest Milestones per stage: the 5 most recently reached M-codes for
    # that stage's own catalog -- scoped to focus_email when "My Items" is
    # on (item [My Items scoping v2]), same as the project cards above.
    def _recent_milestones(stage_enum):
        q = (
            db.query(models.DeliverableSubmission)
            .join(models.DeliverableDefinition)
            .join(models.DeliverableSubmission.project)
            .filter(
                models.DeliverableDefinition.is_milestone.is_(True),
                models.DeliverableDefinition.stage == stage_enum,
                models.DeliverableSubmission.status == models.SubmissionStatus.APPROVED,
                models.Project.archived.is_not(True),
            )
            .order_by(models.DeliverableSubmission.reviewed_at.desc())
        )
        if focus:
            subs = [
                s for s in q.all()
                if focus in {e.strip().lower() for e in rules.resolve_owners(s) if e}
                or focus in {e.strip().lower() for e in rules.resolve_smes(s) if e}
            ][:5]
        else:
            subs = q.limit(5).all()
        return [{
            "milestone_code": s.definition.milestone_code, "name": s.definition.name,
            "est_no": s.project.est_no, "project_name": s.project.name, "project_id": s.project_id,
            "reviewed_at": s.reviewed_at,
        } for s in subs]

    recent_milestones_l0 = _recent_milestones(models.Stage.L0)
    recent_milestones_l1 = _recent_milestones(models.Stage.L1)

    return {
        "active_l0": l0_count, "active_l1": l1_count, "signed": signed_count,
        "overdue": overdue, "pending_review": pending_review, "not_due": not_due,
        "early": early, "on_time": on_time, "late": late,
        "no_progress": no_progress, "in_progress": in_progress, "approved": approved, "rejected": rejected,
        "recent_l0": recent_l0, "recent_l1": recent_l1,
        "recent_milestones_l0": recent_milestones_l0, "recent_milestones_l1": recent_milestones_l1,
        "top_depts_l0": top_depts_l0, "top_depts_l1": top_depts_l1,
        "concerns_l0": concerns_l0, "concerns_l1": concerns_l1,
        "departments": dept_rows,
    }


def _user_lookup(db: Session) -> dict[str, "models.User"]:
    """Email (lowercased) -> roster User, for attaching a name/department to
    an owner/SME who's otherwise identified only by the email stored on
    their submissions (item 74's department/name filters on Top Achievers).
    """
    return {u.email.strip().lower(): u for u in db.query(models.User).all()}


def _rank_owners(subs, users: dict[str, "models.User"] | None = None):
    """Ranks owners by on-time performance -- item [kpi rewrite]: `pct` now
    uses the real point-based Calculation Criteria (rules.kpi_points, same
    as the Performance tab/dashboard concerns list) instead of a plain
    approved/cohort ratio. `approved`/`total` stay literal counts (for the
    "X / Y approved on time" card text) -- only the ranking percentage
    itself changed.
    """
    stats: dict[str, dict] = {}
    for s in subs:
        if s.auto_completed:  # items 115/116: not real tracked work
            continue
        if s.definition.kpi_relevant is False:  # item 117: admin opted this catalog item out of tracking
            continue
        emails = rules.resolve_owners(s)
        if not emails:
            continue
        # Item [multi-owner]: joint responsibility -- every assigned Owner
        # shares credit/blame for this item's on-time performance, same as
        # the department Live Score already does across a whole team.
        for email in emails:
            st = stats.setdefault(email, {"approved": 0, "points": 0.0, "cohort": 0})
            # Item 143 (2nd revision): same cohort as the department Live
            # Score — Completed, currently overdue (live Deadline
            # computation now, not a stored status), or awaiting SME review.
            if (s.status == models.SubmissionStatus.APPROVED
                    or s.status == models.SubmissionStatus.PENDING_REVIEW
                    or rules.deadline_status(s)[0] == "due"):
                st["cohort"] += 1
                if s.status == models.SubmissionStatus.APPROVED:
                    st["approved"] += 1
                submitted = s.submitted_at.date() if s.submitted_at else None
                st["points"] += rules.kpi_points(s.due_date, submitted) or 0.0
    ranked = []
    for email, st in stats.items():
        if not st["cohort"]:
            continue
        u = (users or {}).get(email.strip().lower())
        ranked.append({
            "email": email, "approved": st["approved"], "total": st["cohort"],
            "pct": round(min((st["points"] / st["cohort"]) * 100, 100.0), 1),  # item [early bonus]: capped, see kpi_points
            "name": u.name if u else None, "department": u.department.name if (u and u.department) else None,
        })
    ranked.sort(key=lambda r: (-r["pct"], -r["total"]))
    return ranked


def _format_duration(seconds: float) -> str:
    hours = seconds / 3600
    if hours < 1:
        return f"{round(seconds / 60)} min"
    if hours < 24:
        return f"{round(hours, 1)} hrs"
    return f"{round(hours / 24, 1)} days"


def _rank_smes(subs, users: dict[str, "models.User"] | None = None):
    """Ranks SMEs by average response time (time from submission to review
    decision), fastest first — there's no due date on the SME's own side of
    the workflow, so on-time-rate doesn't apply to them the way it does to owners.
    """
    stats: dict[str, dict] = {}
    for s in subs:
        if s.auto_completed:  # items 115/116: no real SME review happened, would fake a 0-second response time
            continue
        if s.definition.kpi_relevant is False:  # item 117: admin opted this catalog item out of tracking
            continue
        if s.status not in (models.SubmissionStatus.APPROVED, models.SubmissionStatus.REJECTED):
            continue
        if not s.submitted_at or not s.reviewed_at:
            continue
        # Item [multi-SME]: credit whoever actually made the call. Rows from
        # before reviewed_by_email existed fall back to the assigned list --
        # if that's more than one person, this is a best-effort guess.
        email = s.reviewed_by_email or (rules.resolve_smes(s)[0] if rules.resolve_smes(s) else None)
        if not email:
            continue
        st = stats.setdefault(email, {"total_seconds": 0.0, "count": 0})
        st["total_seconds"] += (s.reviewed_at - s.submitted_at).total_seconds()
        st["count"] += 1
    ranked = []
    for email, st in stats.items():
        avg_seconds = st["total_seconds"] / st["count"]
        u = (users or {}).get(email.strip().lower())
        ranked.append({
            "email": email, "reviewed": st["count"], "avg_seconds": avg_seconds, "avg_label": _format_duration(avg_seconds),
            "name": u.name if u else None, "department": u.department.name if (u and u.department) else None,
        })
    ranked.sort(key=lambda r: r["avg_seconds"])
    return ranked


_SAMPLE_OWNERS = [
    {"email": "sample.owner1@algihaz.com", "approved": 9, "total": 10, "pct": 90.0, "name": None, "department": None},
    {"email": "sample.owner2@algihaz.com", "approved": 7, "total": 8, "pct": 87.5, "name": None, "department": None},
    {"email": "sample.owner3@algihaz.com", "approved": 6, "total": 7, "pct": 85.7, "name": None, "department": None},
]
_SAMPLE_SMES = [
    {"email": "sample.sme1@algihaz.com", "reviewed": 12, "avg_seconds": 3600.0, "avg_label": "1.0 hrs", "name": None, "department": None},
    {"email": "sample.sme2@algihaz.com", "reviewed": 9, "avg_seconds": 7200.0, "avg_label": "2.0 hrs", "name": None, "department": None},
    {"email": "sample.sme3@algihaz.com", "reviewed": 6, "avg_seconds": 18000.0, "avg_label": "5.0 hrs", "name": None, "department": None},
]


def _pad_with_samples(ranked, samples):
    """Fills the leaderboard with clearly-labeled sample rows when there isn't
    enough real data yet, so the section shows what it'll look like once
    people are using the platform — never mixed in silently, always tagged.
    """
    if len(ranked) >= 3:
        return ranked
    real_emails = {r["email"] for r in ranked}
    padded = list(ranked)
    for sample in samples:
        if len(padded) >= 3:
            break
        if sample["email"] in real_emails:
            continue
        padded.append(dict(sample, sample=True))
    return padded


@router.get("/top-achievers")
def get_top_achievers(db: Session = Depends(get_db)):
    active_projects = db.query(models.Project).filter(
        models.Project.status == models.ProjectStatus.IN_PROGRESS, models.Project.archived.is_not(True),
    ).all()
    for p in active_projects:
        rules.recompute_project_due_dates(db, p)
    db.commit()
    subs = []
    if active_projects:
        subs = (
            db.query(models.DeliverableSubmission)
            .join(models.DeliverableDefinition)
            .filter(models.DeliverableSubmission.project_id.in_([p.id for p in active_projects]))
            .all()
        )
    users = _user_lookup(db)
    return {
        "owners": _pad_with_samples(_rank_owners(subs, users), _SAMPLE_OWNERS),
        "smes": _pad_with_samples(_rank_smes(subs, users), _SAMPLE_SMES),
    }


@router.get("/matrix")
def get_matrix(stage: str, focus_email: str | None = None, db: Session = Depends(get_db)):
    """Deliverables (rows, grouped by department) x active projects (columns) —
    the live equivalent of the old Control Sheet's L0/L1 Tracking Sheets, scoped
    to currently in-progress projects instead of every tender ever tracked.
    Item 183: `focus_email` narrows the columns to only projects the caller
    owns or reviews at least one deliverable on, AND the rows to only the
    specific deliverable items they're actually assigned -- same "My Items"
    concept the Dashboard stat cards already use, not a separate filter.
    """
    projects = (
        db.query(models.Project)
        .filter(models.Project.stage == stage, models.Project.status == models.ProjectStatus.IN_PROGRESS,
                models.Project.archived.is_not(True))
        .order_by(models.Project.announcement_date)
        .all()
    )
    defs = (
        db.query(models.DeliverableDefinition)
        .join(models.Department)
        .filter(models.DeliverableDefinition.stage == stage, models.DeliverableDefinition.active == True)  # noqa: E712
        .order_by(models.Department.number)
        .all()
    )
    # Item [matrix kpi_relevant]: the matrix should mirror exactly what the
    # Performance tab tracks -- an item an admin has turned off via Manage
    # Tracking (kpi_relevant == False) has no place here either. Same
    # is-not-False rule as _kpi_cohort (None/unset still counts as on).
    defs = [d for d in defs if d.kpi_relevant is not False]
    # Sorting by (number, item_no) alone interleaved the four Operation
    # Units TBU/PBU/DBU/BBU rows -- they all share department number 2, so
    # ties broke on item_no first, printing "2.1" for all four, then "2.2"
    # for all four, etc. instead of one department's full block at a time.
    # department.id (their real creation order: TBU, PBU, DBU, BBU) as the
    # secondary key keeps each department's rows grouped together, with
    # item_no only as the tertiary tiebreaker within one department.
    defs.sort(key=lambda d: (d.department.number or 0, d.department.id, rules.item_sort_key(d.item_no)))

    subs = []
    if projects:
        for p in projects:
            rules.recompute_project_due_dates(db, p)
        db.commit()
        subs = (
            db.query(models.DeliverableSubmission)
            .filter(models.DeliverableSubmission.project_id.in_([p.id for p in projects]))
            .all()
        )

    focus = (focus_email or "").strip().lower()
    if focus:
        my_project_ids = set()
        my_definition_ids = set()
        for s in subs:
            owners = {e.strip().lower() for e in rules.resolve_owners(s) if e}
            smes = {e.strip().lower() for e in rules.resolve_smes(s) if e}
            if focus in owners or focus in smes:
                my_project_ids.add(s.project_id)
                my_definition_ids.add(s.deliverable_definition_id)
        projects = [p for p in projects if p.id in my_project_ids]
        # Item 183: rows narrow to the specific deliverables actually
        # assigned to this person, not every catalog item for the
        # departments/projects they happen to touch.
        defs = [d for d in defs if d.id in my_definition_ids]

    sub_map = {(s.project_id, s.deliverable_definition_id): s for s in subs}

    rows = []
    for d in defs:
        cells = {}
        for p in projects:
            s = sub_map.get((p.id, d.id))
            if s:
                # Item 143 (2nd revision): the matrix shows the 3-state
                # Deadline collapse (Not Due / Due / Completed), not the raw
                # Progress status.
                cells[p.id] = {
                    "status": s.status.value, "bucket": rules.deadline_bucket(s),
                    "due_date": s.due_date, "submission_id": s.id,
                }
        rows.append({
            "item_no": d.item_no, "name": d.name, "short_name": d.short_name or d.name,
            "department": d.department.name, "department_number": d.department.number,
            "is_milestone": d.is_milestone, "milestone_code": d.milestone_code,
            "cells": cells,
        })

    return {
        "projects": [{"id": p.id, "est_no": p.est_no, "name": p.name} for p in projects],
        "rows": rows,
    }


def _kpi_cohort(subs: list) -> list:
    """Item 42/117: the same tracked-work filter used everywhere else on this
    page (auto-completed and admin-opted-out items are never real cohort
    members, in either direction).
    """
    return [s for s in subs if not s.auto_completed and s.definition.kpi_relevant is not False]


def _kpi_pct_weighted(cohort: list, allow_fan_out: bool) -> float | None:
    """[Deliverable weights] Shared engine behind both L1's and L0's
    Performance % -- group the cohort by item_no first (a fan-out item_no,
    allow_fan_out=True, L1 only since L0 never has PO Lifecycle data, pools
    its own PoLineItem-tagged copies into ONE group entry via
    item_group_kpi_pct first, exactly as before -- otherwise a project with
    more named items would silently outweigh one with fewer), then take a
    WEIGHTED average across those per-item-no ratios instead of either a
    flat pool (L1's old behavior) or an equal average (L0's old behavior).

    Each item_no's own weight is its DeliverableDefinition.kpi_weight,
    defaulting to 1.0 when unset (never required to sum to 100 with
    siblings -- see models.py's kpi_weight docstring). With every item in a
    department left at the default weight, this reproduces L0's previous
    equal-average result bit-for-bit; L1's previous flat-pooled result only
    where every item_no in the cohort happens to have the same submission
    count (confirmed acceptable with Yasser -- L1's old pooling secretly
    let a more-frequently-due item outweigh a rarer one, which per-item
    grouping now corrects regardless of weights).
    """
    if not cohort:
        return None
    flat: dict[str, list] = {}
    fan_out: dict[str, list] = {}
    for s in cohort:
        if allow_fan_out and s.po_line_item_id is not None:
            fan_out.setdefault(s.definition.item_no, []).append(s)
        else:
            flat.setdefault(s.definition.item_no, []).append(s)

    ratios_weights: list[tuple[float, float]] = []
    for item_subs in flat.values():
        total_points = sum((rules.kpi_points(s.due_date, s.submitted_at.date() if s.submitted_at else None) or 0.0) for s in item_subs)
        ratios_weights.append((total_points / len(item_subs), item_subs[0].definition.kpi_weight or 1.0))
    for item_subs in fan_out.values():
        group_pct = rules.item_group_kpi_pct(item_subs)
        if group_pct is not None:
            ratios_weights.append((group_pct / 100.0, item_subs[0].definition.kpi_weight or 1.0))

    if not ratios_weights:
        return None
    total_weight = sum(w for _, w in ratios_weights)
    weighted_sum = sum(r * w for r, w in ratios_weights)
    # Item [early bonus]: capped at 100 -- individual items can earn more
    # than a full point for being early, the reported score can't.
    return round(min((weighted_sum / total_weight) * 100, 100.0), 1)


def _kpi_pct_pooled(cohort: list) -> float | None:
    """L1's own entry point -- see _kpi_pct_weighted. Kept as its own name
    (rather than inlined at every call site) so _level_stats and every
    other existing caller stays unchanged.
    """
    return _kpi_pct_weighted(cohort, allow_fan_out=True)


def _kpi_pct_per_item_averaged(cohort: list) -> float | None:
    """L0's own entry point -- see _kpi_pct_weighted."""
    return _kpi_pct_weighted(cohort, allow_fan_out=False)


def _level_stats(subs: list, stage: models.Stage) -> dict:
    """One tracked level ("L1" or "L0") of one department's Performance card.
    Cohort membership (item 42's original rule, unchanged): approved +
    overdue + pending-review submissions -- excludes not-due, not-required,
    and pending-triage items. Item [kpi rewrite]: the percentage itself now
    uses the real point-based Calculation Criteria (kpi_points -- on-time =
    1, 4-day grace period, tiered credit for late submissions, 0 once
    genuinely not submitted) instead of a plain approved/cohort ratio, with
    L1/L0 aggregating differently per architecture_map.md section 3.4 (L1
    pools every submission into one ratio; L0 averages each deliverable
    item's own ratio equally). `approved`/`total` below stay literal counts
    for the card's "X/Y on-time" display text -- only `percentage` changed.
    """
    stage_subs = [s for s in subs if s.definition.stage == stage]
    overdue = [s for s in stage_subs if rules.deadline_status(s)[0] == "due"]
    pending = [s for s in stage_subs if s.status == models.SubmissionStatus.PENDING_REVIEW]
    approved = [s for s in stage_subs if s.status == models.SubmissionStatus.APPROVED]
    cohort = approved + overdue + pending
    cohort_size = len(cohort)
    pct = (_kpi_pct_per_item_averaged(cohort) if stage == models.Stage.L0 else _kpi_pct_pooled(cohort)) if cohort_size else None

    due_items = []
    for s in sorted(overdue, key=lambda s: rules.deadline_status(s)[1] or 0):
        delay_days = abs(rules.deadline_status(s)[1] or 0)
        due_items.append({
            "item_no": s.definition.item_no, "name": rules.submission_display_name(s),
            "project": s.project.est_no, "project_id": s.project_id, "delay_days": delay_days,
        })

    return {
        "percentage": pct, "approved": len(approved), "total": cohort_size,
        "due_items": due_items[:5], "all_due_items": due_items,
    }


def _capture_snapshot(db: Session, department_id: int, stage: models.Stage, stats: dict) -> None:
    """Item 42: idempotent per calendar month — the first Performance tab
    load in a given month records that month's real numbers; every load
    after that in the same month is a no-op (today's figures are always
    computed live anyway, this is purely for next month's trend to have
    something real to compare against).
    """
    month_start = date.today().replace(day=1)
    existing = (
        db.query(models.PerformanceSnapshot)
        .filter(models.PerformanceSnapshot.department_id == department_id,
                models.PerformanceSnapshot.stage == stage,
                models.PerformanceSnapshot.month == month_start)
        .first()
    )
    if existing:
        return
    db.add(models.PerformanceSnapshot(
        department_id=department_id, stage=stage, month=month_start,
        pct=stats["percentage"], approved=stats["approved"], total=stats["total"],
    ))


def _trend(db: Session, department_id: int, stage: models.Stage, current_pct: float | None) -> dict:
    """Item 42: month-over-month, against the most recent *prior* real
    snapshot on record (never a fabricated one) -- "No Baseline" until a
    second real month exists to compare against, exactly like the design
    spec's own rule for a brand-new entity's first month.
    """
    this_month = date.today().replace(day=1)
    prev = (
        db.query(models.PerformanceSnapshot)
        .filter(models.PerformanceSnapshot.department_id == department_id,
                models.PerformanceSnapshot.stage == stage,
                models.PerformanceSnapshot.month < this_month)
        .order_by(models.PerformanceSnapshot.month.desc())
        .first()
    )
    if not prev or prev.pct is None or current_pct is None:
        return {"trend": "no_baseline", "variance": 0, "prev_month": None}
    variance = round(current_pct - prev.pct, 1)
    trend = "up" if variance > 0 else ("down" if variance < 0 else "stable")
    return {"trend": trend, "variance": variance, "prev_month": prev.month.isoformat()}


# Item [performance history]: Yasser's real per-department Acceptable
# thresholds -- everyone defaults to 80% unless listed here. "Supply chain
# (SS)" and "PBU Procurement" (his original sheet's two Supply Chain
# sub-splits, both 85%) used to collapse onto the app's single "Supply
# Chain" department, which had no such split -- item [PBU scope routing]
# gave Supply Chain a real "Procurement (PBU)" counterpart, so both get
# their own threshold now instead of one standing in for both.
_MIN_ACCEPTABLE = {
    "Planning": 70.0,
    "Cost Control": 70.0,
    "Supply Chain": 85.0,
    "Procurement (PBU)": 85.0,
}


def _min_acceptable_for(dept_name: str) -> float:
    return _MIN_ACCEPTABLE.get(dept_name, 80.0)


def _status(pct: float | None, min_acceptable: float) -> str:
    """Item [performance history]: three-tier evaluation the Performance tab
    cards/badges key off. 90% is a fixed "Excellent" cutoff for everyone;
    min_acceptable is the per-department floor below which a department
    reads "Needs Action" rather than "Acceptable" (see _MIN_ACCEPTABLE).
    """
    if pct is None:
        return "N/A"
    if pct >= 90:
        return "Excellent"
    if pct >= min_acceptable:
        return "Acceptable"
    return "Needs Action"


def _most_recent_known_pct(level: dict) -> float | None:
    """Live percentage if there's anything due right now, else the most
    recent *real* historical month on record (never the always-present
    "Current" placeholder, which is what's None in the first place).
    """
    if level["percentage"] is not None:
        return level["percentage"]
    for h in reversed(level["history"]):
        if h["month"] != "Current" and h["pct"] is not None:
            return h["pct"]
    return None


def _history_and_ytd(db: Session, department_id: int, stage: models.Stage, current_pct: float | None) -> dict:
    """Item [performance history]: every real recorded month (historical
    seed data plus any snapshot captured since) up to but excluding the
    current in-progress month, which is always represented by the live
    number under the label "Current" -- a month isn't final until it's
    over, so it's never shown under its real name (matches the design
    spec's "in-progress period" rule). `ytd` compares today's live number
    against the first month actually on record for this department/stage,
    whatever that happens to be -- None when there's no real history yet
    (e.g. a department with no tracking before this pilot), rather than a
    fabricated "vs Feb" for a department that never had a Feb.
    """
    this_month = date.today().replace(day=1)
    rows = (
        db.query(models.PerformanceSnapshot)
        .filter(models.PerformanceSnapshot.department_id == department_id,
                models.PerformanceSnapshot.stage == stage,
                models.PerformanceSnapshot.month < this_month)
        .order_by(models.PerformanceSnapshot.month)
        .all()
    )
    history = [{"month": r.month.strftime("%b"), "pct": r.pct} for r in rows if r.pct is not None]
    ytd = None
    if history and current_pct is not None:
        first = history[0]
        ytd = {"month": first["month"], "from": first["pct"], "to": current_pct,
               "delta": round(current_pct - first["pct"], 1)}
    history.append({"month": "Current", "pct": current_pct})
    return {"history": history, "ytd": ytd}


_INTL_SUFFIX = " (International)"


@router.get("/performance")
def get_performance(db: Session = Depends(get_db)):
    """Item 42: the Performance tab's real data source -- per department, a
    tracked-level (L1/L0) card with a live percentage, a due-items list, a
    month-over-month trend, and (item [performance history]) a real Excellent/
    Acceptable/Needs Action classification plus a monthly history/YTD figure
    once real historical data exists to back it (seeded once from Yasser's
    own Feb-Jul 2026 tracking sheet -- see seed.py -- never fabricated).

    [L0 International]: used to be its own separate Overview subtab (a
    department's international counterpart -- e.g. "Treasury (International)"
    -- was its own card, entirely disjoint from "Treasury"'s). Yasser wants
    one L0 score per real department instead, so an international department
    with a same-named domestic counterpart (matched by exact name, e.g.
    "Treasury" <-> "Treasury (International)" -- NOT by department.number,
    which isn't a safe join key here: legacy/duplicate rows like "Control
    Department" and "Planning" both carry number 5, so two different
    domestic departments would otherwise both claim "Planning
    (International)"'s data) gets folded into that counterpart's own L0
    cohort below and never appears as its own row. An international
    department with NO domestic counterpart (e.g. "Legal (International)",
    which has no standalone "Legal") has nothing to merge into, so it still
    gets shown as its own card, same as before this change. Manage Tracking
    (list_performance_triage) keeps its own separate L0/L0 International/L1
    tabs -- unrelated to this merge, that page needs the split intact so an
    admin can toggle kpi_relevant per catalog independently.
    """
    # Same cohort scope as the dashboard's own department Live Score --
    # every submission ever, not just currently-active projects (a closed
    # project's on-time record is still real performance history). [Archive]
    # is the one exception to that -- an archived project is excluded from
    # every report, Performance included, even from its historical record.
    for p in db.query(models.Project).filter(
        models.Project.status == models.ProjectStatus.IN_PROGRESS, models.Project.archived.is_not(True),
    ).all():
        rules.recompute_project_due_dates(db, p)
    db.commit()
    all_subs = db.query(models.DeliverableSubmission).join(models.DeliverableSubmission.project).filter(
        models.Project.archived.is_not(True)
    ).all()

    all_depts = db.query(models.Department).order_by(models.Department.number).all()
    dept_by_name = {d.name: d for d in all_depts}

    departments = []
    for dept in all_depts:
        if dept.name in _PERF_EXCLUDED_DEPTS:
            continue
        if dept.is_international:
            counterpart_name = dept.name[: -len(_INTL_SUFFIX)] if dept.name.endswith(_INTL_SUFFIX) else None
            if counterpart_name and counterpart_name in dept_by_name:
                continue  # merged into that counterpart's own row below
        dept_ids = [dept.id]
        if not dept.is_international:
            intl = dept_by_name.get(dept.name + _INTL_SUFFIX)
            if intl:
                dept_ids.append(intl.id)
        dept_subs = _kpi_cohort([s for s in all_subs if s.definition.department_id in dept_ids])
        l1 = _level_stats(dept_subs, models.Stage.L1)
        l0 = _level_stats(dept_subs, models.Stage.L0)
        _capture_snapshot(db, dept.id, models.Stage.L1, l1)
        _capture_snapshot(db, dept.id, models.Stage.L0, l0)
        l1.update(_trend(db, dept.id, models.Stage.L1, l1["percentage"]))
        l0.update(_trend(db, dept.id, models.Stage.L0, l0["percentage"]))
        l1.update(_history_and_ytd(db, dept.id, models.Stage.L1, l1["percentage"]))
        l0.update(_history_and_ytd(db, dept.id, models.Stage.L0, l0["percentage"]))
        min_acceptable = _min_acceptable_for(dept.name)
        # Item [performance history]: a department with nothing due exactly
        # today still has a real track record if it has recorded history --
        # status (and therefore the Level Summary Card's Excellent/
        # Acceptable/Needs Action count) falls back to the most recent
        # actual month on file rather than reading N/A just because
        # nothing's due right this moment. The live `percentage` field
        # itself is untouched (still honestly blank when nothing's due).
        l1["status"] = _status(_most_recent_known_pct(l1), min_acceptable)
        l0["status"] = _status(_most_recent_known_pct(l0), min_acceptable)
        # Item [performance history]: some department rows are legacy/
        # duplicate entries left over from before the Operation Units TBU/
        # PBU/DBU/BBU split existed (e.g. "TBU / PBU", "BBU / PBU") -- never
        # a real cohort and never any historical data either. Rather than
        # deleting them (a real destructive call, not this endpoint's to
        # make), flag them so the UI can leave them out of the department
        # count/filter chips by default.
        has_data = bool(l1["total"] or l0["total"] or len(l1["history"]) > 1 or len(l0["history"]) > 1)
        departments.append({
            "name": dept.name, "number": dept.number, "l1": l1, "l0": l0, "has_data": has_data,
            "min_acceptable": min_acceptable,
        })
    db.commit()

    departments.sort(key=lambda d: ((d["l1"]["percentage"] or 0) + (d["l0"]["percentage"] or 0)) / 2, reverse=True)
    l1_project_count = db.query(models.Project).filter(
        models.Project.stage == models.Stage.L1, models.Project.archived.is_not(True)).count()
    l0_project_count = db.query(models.Project).filter(
        models.Project.stage == models.Stage.L0, models.Project.archived.is_not(True)).count()
    return {
        "departments": departments,
        "data_as_of": datetime.utcnow().date().isoformat(),
        "l1_project_count": l1_project_count,
        "l0_project_count": l0_project_count,
    }


@router.get("/performance/breakdown")
def get_performance_breakdown(department: str, stage: str, db: Session = Depends(get_db)):
    """Item [performance history]: the "click a percentage to see the math"
    drill-down -- every submission in that department/stage's KPI cohort,
    its own point value (rules.kpi_points), and how those points roll up
    into the final percentage. L0 shows the intermediate per-deliverable-
    item groups too, since its aggregation averages those rather than
    pooling everything directly (see _kpi_pct_per_item_averaged).
    """
    dept = db.query(models.Department).filter(models.Department.name == department).first()
    if not dept:
        raise HTTPException(404, "Department not found")
    try:
        stage_enum = models.Stage(stage)
    except ValueError:
        raise HTTPException(400, "Invalid stage")
    for p in db.query(models.Project).filter(
        models.Project.status == models.ProjectStatus.IN_PROGRESS, models.Project.archived.is_not(True),
    ).all():
        rules.recompute_project_due_dates(db, p)
    db.commit()
    all_subs = db.query(models.DeliverableSubmission).join(models.DeliverableSubmission.project).filter(
        models.Project.archived.is_not(True)
    ).all()
    # Mirrors get_performance's own merge: the L0 card this drill-down is
    # opened from already combines this department with its international
    # counterpart (if any), so the breakdown has to pull from both too or
    # its total would silently disagree with the percentage that opened it.
    dept_ids = [dept.id]
    if stage_enum == models.Stage.L0 and not dept.is_international:
        intl = db.query(models.Department).filter(models.Department.name == dept.name + _INTL_SUFFIX).first()
        if intl:
            dept_ids.append(intl.id)
    dept_subs = _kpi_cohort([s for s in all_subs if s.definition.department_id in dept_ids])
    stage_subs = [s for s in dept_subs if s.definition.stage == stage_enum]
    overdue = [s for s in stage_subs if rules.deadline_status(s)[0] == "due"]
    pending = [s for s in stage_subs if s.status == models.SubmissionStatus.PENDING_REVIEW]
    approved = [s for s in stage_subs if s.status == models.SubmissionStatus.APPROVED]
    cohort = approved + overdue + pending

    items = []
    for s in cohort:
        submitted_date = s.submitted_at.date() if s.submitted_at else None
        points = rules.kpi_points(s.due_date, submitted_date) or 0.0
        items.append({
            "item_no": s.definition.item_no, "name": rules.submission_display_name(s), "project": s.project.est_no,
            "due_date": s.due_date.isoformat() if s.due_date else None,
            "submitted_date": submitted_date.isoformat() if submitted_date else None,
            "status": s.status.value, "points": points,
        })
    items.sort(key=lambda x: (rules.item_sort_key(x["item_no"]), x["project"]))

    result = {"department": dept.name, "stage": stage, "items": items}
    if stage_enum == models.Stage.L0:
        groups: dict[str, list] = {}
        for s in cohort:
            groups.setdefault(s.definition.item_no, []).append(s)
        per_item = []
        ratios = []
        for item_no, item_subs in groups.items():
            pts = sum((rules.kpi_points(s.due_date, s.submitted_at.date() if s.submitted_at else None) or 0.0) for s in item_subs)
            ratio = pts / len(item_subs)
            ratios.append(ratio)
            per_item.append({"item_no": item_no, "name": item_subs[0].definition.name, "points": round(pts, 2),
                              "due": len(item_subs), "pct": round(ratio * 100, 1)})
        per_item.sort(key=lambda x: rules.item_sort_key(x["item_no"]))
        result["per_item_groups"] = per_item
        # Item [early bonus]: the final department score caps at 100 even
        # though an individual item group's own ratio (above) can exceed it.
        result["overall_pct"] = round(min((sum(ratios) / len(ratios)) * 100, 100.0), 1) if ratios else None
        result["aggregation"] = "per_item_averaged"
    else:
        total_points = sum(i["points"] for i in items)
        result["overall_points"] = round(total_points, 2)
        result["overall_due"] = len(items)
        result["overall_pct"] = round(min((total_points / len(items)) * 100, 100.0), 1) if items else None
        result["aggregation"] = "pooled"
    return result

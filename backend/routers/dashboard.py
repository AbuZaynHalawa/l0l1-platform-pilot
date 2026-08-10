from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, rules
from ..database import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(focus_email: str | None = None, db: Session = Depends(get_db)):
    """`focus_email` (item 72) scopes the stat tiles to just what that person
    owns or reviews, instead of the whole portfolio — the project counts and
    department breakdown stay organization-wide either way, since neither
    "how many active L0 tenders" nor the department table means anything
    scoped to one person.
    """
    projects = db.query(models.Project).all()
    l0_count = sum(1 for p in projects if p.stage == models.Stage.L0 and p.status == models.ProjectStatus.IN_PROGRESS)
    l1_count = sum(1 for p in projects if p.stage == models.Stage.L1 and p.status == models.ProjectStatus.IN_PROGRESS)
    signed_count = sum(1 for p in projects if p.contract_status == models.ContractStatus.SIGNED)

    for p in projects:
        if p.status == models.ProjectStatus.IN_PROGRESS:
            rules.recompute_project_due_dates(db, p)
    db.commit()
    all_subs = db.query(models.DeliverableSubmission).all()

    focus = (focus_email or "").strip().lower()
    stat_subs = all_subs
    if focus:
        stat_subs = [
            s for s in all_subs
            if (s.owner_email or "").strip().lower() == focus or (s.sme_email or "").strip().lower() == focus
        ]

    overdue = sum(1 for s in stat_subs if s.status == models.SubmissionStatus.OVERDUE)
    pending_review = sum(1 for s in stat_subs if s.status == models.SubmissionStatus.PENDING_REVIEW)
    not_due = sum(1 for s in stat_subs if s.status == models.SubmissionStatus.NOT_DUE)

    dept_rows = []
    for dept in db.query(models.Department).order_by(models.Department.number).all():
        # Items 115/116: auto-completed items were never real tracked work,
        # so they're excluded from the department's on-time performance
        # cohort entirely -- not counted as a win, not counted as a miss.
        # Item 117: same for any catalog item an admin has explicitly
        # opted out of performance tracking (kpi_relevant == False).
        dept_subs = [
            s for s in all_subs
            if s.definition.department_id == dept.id and not s.auto_completed and s.definition.kpi_relevant is not False
        ]
        due_and_done = [s for s in dept_subs if s.status in (
            models.SubmissionStatus.APPROVED, models.SubmissionStatus.OVERDUE, models.SubmissionStatus.PENDING_REVIEW)]
        approved = sum(1 for s in dept_subs if s.status == models.SubmissionStatus.APPROVED)
        pct = round((approved / len(due_and_done)) * 100, 1) if due_and_done else None
        dept_rows.append({
            "department": dept.name, "department_number": dept.number, "total": len(dept_subs), "approved": approved,
            "overdue": sum(1 for s in dept_subs if s.status == models.SubmissionStatus.OVERDUE),
            "pending_review": sum(1 for s in dept_subs if s.status == models.SubmissionStatus.PENDING_REVIEW),
            "pct": pct,
        })

    concerns = []
    for row in dept_rows:
        if row["pct"] is not None and row["pct"] < 80:
            concerns.append(f"<b>{row['department']}</b> is at {row['pct']}% approved-on-time this pilot ({row['overdue']} overdue).")
    if overdue:
        concerns.append(f"<b>{overdue} deliverable(s)</b> are currently overdue across active projects.")
    unassigned = [d.name for d in db.query(models.Department).all() if not d.focal_point_email]
    if unassigned:
        concerns.append(f"No focal point contact set for: <b>{', '.join(unassigned)}</b>.")

    return {
        "active_l0": l0_count, "active_l1": l1_count, "signed": signed_count,
        "overdue": overdue, "pending_review": pending_review, "not_due": not_due,
        "departments": dept_rows, "concerns": concerns,
    }


def _user_lookup(db: Session) -> dict[str, "models.User"]:
    """Email (lowercased) -> roster User, for attaching a name/department to
    an owner/SME who's otherwise identified only by the email stored on
    their submissions (item 74's department/name filters on Top Achievers).
    """
    return {u.email.strip().lower(): u for u in db.query(models.User).all()}


def _rank_owners(subs, users: dict[str, "models.User"] | None = None):
    """Ranks owners by on-time approval rate: approved / (approved + overdue +
    pending_review) — the same cohort/formula already used for department
    Live Score, just grouped by person instead of department.
    """
    stats: dict[str, dict] = {}
    for s in subs:
        if s.auto_completed:  # items 115/116: not real tracked work
            continue
        if s.definition.kpi_relevant is False:  # item 117: admin opted this catalog item out of tracking
            continue
        email = s.owner_email or s.definition.default_owner_email
        if not email:
            continue
        st = stats.setdefault(email, {"approved": 0, "cohort": 0})
        if s.status in (models.SubmissionStatus.APPROVED, models.SubmissionStatus.OVERDUE, models.SubmissionStatus.PENDING_REVIEW):
            st["cohort"] += 1
            if s.status == models.SubmissionStatus.APPROVED:
                st["approved"] += 1
    ranked = []
    for email, st in stats.items():
        if not st["cohort"]:
            continue
        u = (users or {}).get(email.strip().lower())
        ranked.append({
            "email": email, "approved": st["approved"], "total": st["cohort"], "pct": round((st["approved"] / st["cohort"]) * 100, 1),
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
        email = s.sme_email or s.definition.default_sme_email
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
    active_projects = db.query(models.Project).filter(models.Project.status == models.ProjectStatus.IN_PROGRESS).all()
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
def get_matrix(stage: str, db: Session = Depends(get_db)):
    """Deliverables (rows, grouped by department) x active projects (columns) —
    the live equivalent of the old Control Sheet's L0/L1 Tracking Sheets, scoped
    to currently in-progress projects instead of every tender ever tracked.
    """
    projects = (
        db.query(models.Project)
        .filter(models.Project.stage == stage, models.Project.status == models.ProjectStatus.IN_PROGRESS)
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
    defs.sort(key=lambda d: (d.department.number or 0, rules.item_sort_key(d.item_no)))

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
    sub_map = {(s.project_id, s.deliverable_definition_id): s for s in subs}

    rows = []
    for d in defs:
        cells = {}
        for p in projects:
            s = sub_map.get((p.id, d.id))
            if s:
                cells[p.id] = {"status": s.status.value, "due_date": s.due_date, "submission_id": s.id}
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

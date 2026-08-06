from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, rules
from ..database import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(db: Session = Depends(get_db)):
    projects = db.query(models.Project).all()
    l0_count = sum(1 for p in projects if p.stage == models.Stage.L0 and p.status == models.ProjectStatus.IN_PROGRESS)
    l1_count = sum(1 for p in projects if p.stage == models.Stage.L1 and p.status == models.ProjectStatus.IN_PROGRESS)
    signed_count = sum(1 for p in projects if p.contract_status == models.ContractStatus.SIGNED)

    all_subs = db.query(models.DeliverableSubmission).all()
    for s in all_subs:
        rules.refresh_status(s)
    db.commit()

    overdue = sum(1 for s in all_subs if s.status == models.SubmissionStatus.OVERDUE)
    pending_review = sum(1 for s in all_subs if s.status == models.SubmissionStatus.PENDING_REVIEW)

    dept_rows = []
    for dept in db.query(models.Department).order_by(models.Department.order).all():
        dept_subs = [s for s in all_subs if s.definition.department_id == dept.id]
        due_and_done = [s for s in dept_subs if s.status in (
            models.SubmissionStatus.APPROVED, models.SubmissionStatus.OVERDUE, models.SubmissionStatus.PENDING_REVIEW)]
        approved = sum(1 for s in dept_subs if s.status == models.SubmissionStatus.APPROVED)
        pct = round((approved / len(due_and_done)) * 100, 1) if due_and_done else None
        dept_rows.append({
            "department": dept.name, "total": len(dept_subs), "approved": approved,
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
        "overdue": overdue, "pending_review": pending_review,
        "departments": dept_rows, "concerns": concerns,
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
        .order_by(models.Department.order)
        .all()
    )
    defs.sort(key=lambda d: (d.department.order, rules.item_sort_key(d.item_no)))

    subs = []
    if projects:
        subs = (
            db.query(models.DeliverableSubmission)
            .filter(models.DeliverableSubmission.project_id.in_([p.id for p in projects]))
            .all()
        )
        for s in subs:
            rules.refresh_status(s)
        db.commit()
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
            "department": d.department.name,
            "is_milestone": d.is_milestone, "milestone_code": d.milestone_code,
            "cells": cells,
        })

    return {
        "projects": [{"id": p.id, "est_no": p.est_no, "name": p.name} for p in projects],
        "rows": rows,
    }

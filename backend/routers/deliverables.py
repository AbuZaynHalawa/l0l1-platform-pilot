import json
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session, contains_eager

from .. import models, schemas, announcements, rules
from ..database import get_db
from ..providers.storage import get_storage_provider, sanitize_segment
from ..excel_parsing import parse_long_lead_workbook
from . import po_line_items

router = APIRouter(prefix="/api/deliverables", tags=["deliverables"])
_storage = get_storage_provider()


def _dept_label(name: str) -> str:
    parts = name.split(". ", 1)
    return parts[1] if len(parts) == 2 else name


def _follower_emails(db: Session, submission_id: int) -> list[str]:
    return [
        f.email for f in
        db.query(models.Follower).filter(models.Follower.submission_id == submission_id).all()
    ]


def _sibling_submission(db: Session, sub: "models.DeliverableSubmission", item_no: str) -> "models.DeliverableSubmission | None":
    """The other named item_no's submission for the same PO line item (e.g.
    3.2's own row for the same "GIS Unit" that this 4.6 belongs to). None
    for a non-fan-out submission (no po_line_item_id) or if that item_no
    was never instantiated for this line item.
    """
    if not sub.po_line_item_id:
        return None
    return (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .filter(models.DeliverableSubmission.project_id == sub.project_id,
                models.DeliverableSubmission.po_line_item_id == sub.po_line_item_id,
                models.DeliverableDefinition.item_no == item_no)
        .first()
    )


@router.get("")
def list_all_deliverables(status: str | None = None, actor_email: str | None = None,
                           actor_role: str | None = None, db: Session = Depends(get_db)):
    """Cross-project queue for the Assigned Deliverables page. Item 166: a
    non-admin only sees their own assigned deliverables (owner or SME on
    that item) -- previously actor_email was accepted but only used for the
    "following" flag, so every role saw the entire cross-project list.
    """
    active_projects = db.query(models.Project).filter(
        models.Project.status == models.ProjectStatus.IN_PROGRESS, models.Project.archived.is_not(True),
    ).all()
    for p in active_projects:
        rules.recompute_project_due_dates(db, p)
    db.commit()

    # Item [Assigned Deliverables perf]: this endpoint returns every
    # deliverable across the whole platform (3300+ rows) on every page
    # load, so per-row cost multiplies fast. Three fixes:
    # 1. contains_eager reuses the joins already in the WHERE clause to
    #    populate s.project / s.definition / s.definition.department, so
    #    accessing them below doesn't lazy-load a fresh query per unique
    #    project/definition/department.
    # 2. awaiting_milestone_note (below) was being called with no lookup
    #    cache, so every predecessor check ran its own fresh join+filter
    #    query -- with ~half the catalog being predecessor-anchored,
    #    across 3300+ rows that's the dominant cost by far. Build one
    #    lookup dict per project (same shape recompute_project_due_dates
    #    already builds for its own internal use, see rules.py) up front
    #    instead.
    # 3. [Queued: SQL-level scoping] lookups_by_project only ever calls
    #    .status/.due_date/.project_id/.po_line_item_id and .definition's
    #    own fields on the rows it stores (verified against
    #    awaiting_milestone_note's + _get_submissions' full body) -- never
    #    .project or .definition.department. So the FULL-catalog fetch
    #    needed to build it doesn't need those two joins at all; only the
    #    rows actually being returned to a scoped (non-Admin) caller need
    #    the expensive Department+Project-joined hydration. Splitting this
    #    into a light full-catalog fetch (Definition only) + a heavy fetch
    #    narrowed to just the caller's own row ids (via a plain
    #    `id IN (...)` filter, computed from the light rows -- resolve_owners/
    #    resolve_smes only read columns the light fetch already has) means
    #    an Owner/SME's request no longer pays the Department+Project join
    #    cost for the ~3300 rows it was always going to filter back out.
    #    Admin's request is unscoped and unchanged either way.
    light_q = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .join(models.Project)
        .options(contains_eager(models.DeliverableSubmission.definition))
        .filter(models.Project.archived.is_not(True))
    )
    # auto_completed rows (e.g. 1.1) are filtered out of the RESPONSE below,
    # same as before -- but NOT out of this query, because they're exactly
    # the causal-chain anchors other items' predecessor checks depend on
    # (see projects.py get_deliverables' own comment on this). Building the
    # lookup from an already-filtered list would make awaiting_milestone_note
    # blind to an auto-completed predecessor and misreport a real item as
    # still "Awaiting" one that's actually done.
    light_subs = light_q.all()
    my_follows = set()
    if actor_email:
        my_follows = {
            f.submission_id for f in
            db.query(models.Follower).filter(models.Follower.email == actor_email.strip().lower()).all()
        }
    scope_to_mine = bool(actor_role) and actor_role != "Admin"
    my_email = (actor_email or "").strip().lower()
    # lookups_by_project needs the FULL cross-project catalog regardless of
    # scope -- a scoped user's own item can be predecessor-chained behind
    # someone else's, so awaiting_milestone_note() below still needs to see
    # the whole picture even when the caller only ends up viewing one item.
    lookups_by_project: dict[int, dict[str, list]] = {}
    for s in light_subs:
        lookups_by_project.setdefault(s.project_id, {}).setdefault(s.definition.item_no, []).append(s)

    def _is_mine(s: "models.DeliverableSubmission") -> bool:
        if not my_email:
            return False
        owners = {e.strip().lower() for e in rules.resolve_owners(s) if e}
        smes = {e.strip().lower() for e in rules.resolve_smes(s) if e}
        if actor_role == "SME":
            # Item [SME scope]: an SME's assigned cohort is only what
            # needs their review right now -- pending review, or
            # rejected by them specifically until it moves past
            # rejected -- not every status on items they're tied to.
            is_pending_for_me = my_email in smes and s.status == models.SubmissionStatus.PENDING_REVIEW
            is_my_rejection = s.status == models.SubmissionStatus.REJECTED and (s.reviewed_by_email or "").strip().lower() == my_email
            is_my_approval = s.status == models.SubmissionStatus.APPROVED and (s.reviewed_by_email or "").strip().lower() == my_email
            return is_pending_for_me or is_my_rejection or is_my_approval
        return my_email in owners or my_email in smes

    q = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .join(models.Department)
        .join(models.Project)
        .options(
            contains_eager(models.DeliverableSubmission.definition).contains_eager(models.DeliverableDefinition.department),
            contains_eager(models.DeliverableSubmission.project),
        )
        .filter(models.Project.archived.is_not(True))
    )
    if scope_to_mine:
        matched_ids = [s.id for s in light_subs if not s.auto_completed and _is_mine(s)]
        q = q.filter(models.DeliverableSubmission.id.in_(matched_ids))
    visible_subs = [s for s in q.all() if not s.auto_completed]
    doc_counts = rules.document_counts(db, [s.id for s in visible_subs])
    pending_kinds = rules.pending_due_date_request_kinds(db, [s.id for s in visible_subs])
    # Second N+1, same shape as awaiting_milestone_note's: rules.mark_complete_note(s)
    # only short-circuits when s.file_name is set, and most of the catalog
    # (No Progress Yet, no upload) has none -- so it was lazy-loading
    # s.history (a fresh WorkflowHistory query) on nearly every row. Not
    # touching mark_complete_note's own signature (its other two call
    # sites are single-submission/single-project scale, not a problem
    # there) -- just batch-fetching what it needs and reproducing its
    # exact logic (file_name -> None; else the latest "submitted" note,
    # ordered by created_at, or None if there isn't one) inline below.
    no_file_ids = [s.id for s in visible_subs if not s.file_name]
    latest_submitted_note: dict[int, str] = {}
    if no_file_ids:
        for h in (
            db.query(models.WorkflowHistory)
            .filter(models.WorkflowHistory.submission_id.in_(no_file_ids), models.WorkflowHistory.action == "submitted")
            .order_by(models.WorkflowHistory.created_at)
            .all()
        ):
            latest_submitted_note[h.submission_id] = h.note  # ascending order -> last write wins, matches [-1] below
    out = []
    for s in visible_subs:
        if status and s.status.value != status:
            continue
        deadline_key, deadline_days = rules.deadline_status(s)
        _action_ts = [t for t in (s.submitted_at, s.reviewed_at) if t]
        out.append({
            "id": s.id, "est_no": s.project.est_no, "project_name": s.project.name, "stage": s.project.stage.value,
            "department": s.definition.department.name, "department_number": s.definition.department.number,
            "item_no": s.definition.item_no,
            "name": rules.display_name(s.definition, s.project),
            # Item [Assigned Deliverables short names]: the row label used to
            # be the full definition name, unlike the Matrix/Timeline (which
            # already show short_name) -- falls back to the full name for
            # any definition without a curated short_name.
            "short_name": s.definition.short_name or rules.display_name(s.definition, s.project),
            "due_date": s.due_date, "status": s.status.value,
            "deadline_status": deadline_key, "deadline_days": deadline_days, "auto_completed": s.auto_completed,
            "owner": ", ".join(rules.resolve_owners(s)) or "Unassigned",
            "owner_emails": rules.resolve_owners(s),
            "sme_emails": rules.resolve_smes(s),
            "is_milestone": s.definition.is_milestone, "milestone_code": s.definition.milestone_code,
            "file_name": s.file_name, "file_url": _storage.file_url(s.file_ref) if s.file_ref else None,
            "review_comment": s.review_comment,
            "completion_note": None if s.file_name else latest_submitted_note.get(s.id),
            "following": s.id in my_follows,
            "doc_total": doc_counts.get(s.id, 0),
            "awaiting_note": rules.awaiting_milestone_note(db, s, lookups_by_project.get(s.project_id)),
            # Newest-action-first ordering on Assigned Deliverables: the most
            # recent of submit/review timestamps, so a just-completed or
            # just-rejected item surfaces at the top instead of wherever the
            # catalog's static item order happens to place it.
            "last_action_at": max(_action_ts).isoformat() if _action_ts else None,
            "points_earned": (
                rules.kpi_points(s.due_date, s.submitted_at.date() if s.submitted_at else None)
                if s.status == models.SubmissionStatus.APPROVED else None
            ),
            "pending_due_date_request_kind": pending_kinds.get(s.id),
        })
    return out


@router.post("/{submission_id}/follow")
def toggle_follow(submission_id: int, payload: schemas.FollowRequest, db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    email = payload.email.strip().lower()
    if not email:
        raise HTTPException(400, "Email is required to follow a deliverable")
    existing = db.query(models.Follower).filter_by(submission_id=submission_id, email=email).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"following": False}
    db.add(models.Follower(submission_id=submission_id, email=email))
    db.commit()
    return {"following": True}


@router.post("/{submission_id}/upload")
async def upload_deliverable(submission_id: int, file: UploadFile = File(...),
                              actor_name: str = Form("Owner"), actor_role: str = Form("Owner"),
                              actor_email: str = Form(""), db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    if rules.is_project_terminal(sub.project):
        raise HTTPException(400, "This project is closed — deliverables are read-only")

    assigned_owners = rules.resolve_owners(sub)
    if not rules.can_act(actor_role, actor_email, assigned_owners):
        raise HTTPException(403, f"Only {', '.join(assigned_owners) or 'the assigned owner'} or an Admin can upload this deliverable")
    if sub.status == models.SubmissionStatus.APPROVED:
        raise HTTPException(400, "This deliverable is already Completed")
    if sub.status == models.SubmissionStatus.PENDING_REVIEW:
        raise HTTPException(400, "This deliverable is awaiting SME review — uploads reopen once it's confirmed or sent back")

    content = await file.read()
    folder = f"{sub.project.onedrive_folder_path}/{sanitize_segment(sub.definition.department.name)}"
    file_ref = _storage.upload_file(folder, file.filename, content)

    sub.file_name = file.filename
    sub.file_ref = file_ref
    sub.submitted_at = datetime.utcnow()
    # Item 143 (2nd revision): uploading never triggers SME review on its
    # own anymore — it just moves Progress to In Progress (from No Progress
    # or, per the confirmed flow, from Rejected too, since a fresh upload is
    # what actually reopens a sent-back deliverable).
    sub.status = models.SubmissionStatus.IN_PROGRESS
    db.add(models.WorkflowHistory(submission_id=sub.id, action="submitted", actor_name=actor_name,
                                   note=f"Uploaded {file.filename}"))
    # Mirrored as a Document row too, so it shows up in the deliverable
    # popup's document list the same way an "Add Document" upload does —
    # one upload mechanism, one place it's visible, not two disconnected ones.
    db.add(models.Document(submission_id=sub.id, file_name=file.filename, file_ref=file_ref, uploaded_by=actor_name))

    # [PO Lifecycle]: 1.2's own upload IS the long-lead-items source file --
    # no separate upload control. Best-effort parse; a file that doesn't
    # match the expected template just leaves po_selection untouched (the
    # owner falls back to adding rows manually in the modal), never blocks
    # the upload itself.
    if sub.definition.item_no == "1.2" and sub.project.stage == models.Stage.L1:
        try:
            rows = parse_long_lead_workbook(content)
        except Exception:
            rows = []
        if rows:
            selection = dict(sub.po_selection or {})
            selection["long_lead_items"] = rows
            sub.po_selection = selection

    # [4.6 mutual gate]: 3.2's own upload is the real-world trigger the
    # Engineering owner is waiting on -- once Supply Chain has something to
    # show, flip the paired "4.6" line item forward from No Progress to In
    # Progress too (not just suppress its "Pending 3.2" note, which
    # rules.awaiting_milestone_note already does) so it reads as genuinely
    # actionable in the ordinary Deliverables list, not just on the PO
    # Lifecycle tab's own summary. get_deliverable_detail separately surfaces
    # 3.2's uploaded file as a read-only reference on 4.6's own modal.
    if sub.definition.item_no == "3.2" and sub.po_line_item_id:
        sibling_4_6 = (
            db.query(models.DeliverableSubmission)
            .join(models.DeliverableDefinition)
            .filter(models.DeliverableSubmission.project_id == sub.project_id,
                    models.DeliverableSubmission.po_line_item_id == sub.po_line_item_id,
                    models.DeliverableDefinition.item_no == "4.6",
                    models.DeliverableSubmission.status == models.SubmissionStatus.NO_PROGRESS)
            .first()
        )
        if sibling_4_6:
            sibling_4_6.status = models.SubmissionStatus.IN_PROGRESS
            db.add(models.WorkflowHistory(submission_id=sibling_4_6.id, action="auto_in_progress", actor_name="system",
                                           note=f"3.2 {rules.submission_display_name(sub)} now has real progress -- ready to review."))

    db.commit()

    announcements.followers_notified(db, sub.project, _follower_emails(db, sub.id),
                                      sub.definition.item_no, rules.submission_display_name(sub), "uploaded", submission_id=sub.id)
    announcements.document_added(db, sub.project, rules.resolve_smes(sub), sub.definition.item_no, rules.submission_display_name(sub),
                                  file.filename, submission_id=sub.id)

    return {"status": "ok", "file_ref": file_ref}


@router.patch("/{submission_id}/po-selection")
def update_po_selection(submission_id: int, payload: schemas.PoSelectionUpdate, db: Session = Depends(get_db)):
    """[PO Lifecycle]: the owner's pre-approval scratch pad for 1.2/4.1/
    2.11/2.17 -- ticking a checklist box, editing a long-lead row, adding an
    S/C name. Nothing downstream (no PoLineItem, no fan-out) happens here;
    that's only read once, at approval, by sync_from_submission.
    """
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    is_l1_declaring = sub.definition.item_no in po_line_items.DECLARING_ITEM_NOS and sub.project.stage == models.Stage.L1
    is_l0_declaring = (sub.definition.item_no in po_line_items.L0_DECLARING_ITEM_NOS and sub.project.stage == models.Stage.L0
                        and sub.definition.department.name == "Tendering Department")
    if not (is_l1_declaring or is_l0_declaring):
        raise HTTPException(400, "This deliverable has no PO Lifecycle selection")
    if rules.is_project_terminal(sub.project):
        raise HTTPException(400, "This project is closed — deliverables are read-only")
    if sub.status in (models.SubmissionStatus.PENDING_REVIEW, models.SubmissionStatus.APPROVED):
        raise HTTPException(400, "This deliverable is already completed or awaiting review — reopen it to change the selection")

    assigned_owners = rules.resolve_owners(sub)
    if not rules.can_act(payload.actor_role, payload.actor_email, assigned_owners):
        raise HTTPException(403, f"Only {', '.join(assigned_owners) or 'the assigned owner'} or an Admin can edit this")

    selection = dict(sub.po_selection or {})
    changed_notes = []
    field_labels = {
        "long_lead_items": "long-lead items", "mep_selected": "MEP consultancy",
        "selected": "early activities", "items": "items",
    }
    for field in ("long_lead_items", "mep_selected", "selected", "items"):
        value = getattr(payload, field)
        if value is not None:
            selection[field] = value
            if field == "long_lead_items":
                names = [r.get("name") for r in value if r.get("name")]
            else:
                names = value
            changed_notes.append(field_labels[field] + ": " + (", ".join(names) if names else "none"))
    sub.po_selection = selection
    # Matches upload's own status transition (deliverables.py:154-155) --
    # picking items is real progress on this deliverable, same as attaching
    # a file, so it shouldn't keep reading "No Progress Yet".
    if sub.status in (models.SubmissionStatus.NO_PROGRESS, models.SubmissionStatus.REJECTED):
        sub.status = models.SubmissionStatus.IN_PROGRESS
    if changed_notes:
        db.add(models.WorkflowHistory(submission_id=sub.id, action="po_selection_updated",
                                       actor_name=payload.actor_name, note="; ".join(changed_notes)))
    db.commit()
    # [Request 15]: exception to the general PO Lifecycle rule above (fan-
    # out normally waits for the declaring item's own approval) -- for
    # L0's 1.17/1.18 specifically, an item needs its own review (4.6 /
    # 3.5-3.7) the moment it's added, not once every offer has been
    # circulated. 1.17/1.18's own approval now means "all offers
    # circulated", not "these items may finally start being reviewed".
    # L1's 1.2/4.1/2.11/2.17 are unaffected -- they still only fan out at
    # their own declaring item's approval, via _finalize_approval below.
    if is_l0_declaring:
        po_line_items.sync_from_submission(db, sub)
    return {"po_selection": sub.po_selection, "status": sub.status.value}


def _document_out(d: "models.Document") -> dict:
    """Item 143 (2nd revision): documents are plain attachments now, no
    individual review state — just what was uploaded, by whom, when.
    """
    return {
        "id": d.id, "file_name": d.file_name, "file_url": _storage.file_url(d.file_ref),
        "uploaded_by": d.uploaded_by, "uploaded_at": d.uploaded_at,
    }


@router.get("/{submission_id}/documents")
def list_documents(submission_id: int, db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    documents = (
        db.query(models.Document)
        .filter(models.Document.submission_id == submission_id)
        .order_by(models.Document.uploaded_at)
        .all()
    )
    return [_document_out(d) for d in documents]


def _finalize_approval(db: Session, sub: "models.DeliverableSubmission", comment: str | None, actor_name: str,
                        actor_email: str | None = None) -> None:
    """Item 143: the one place a submission actually becomes Completed
    (status stays the APPROVED enum value — only its display label changed
    to "Completed" — so every existing predecessor/due-date/KPI/Gantt check
    keyed off APPROVED keeps working unchanged). Reached two ways: an SME's
    own Mark Completed (immediate), or an SME confirming an Owner's
    PENDING_REVIEW claim via /review. Both call this so the cascade
    (due-date freeze, milestones, cross-department unlock, L1 completion)
    only lives in one place.
    """
    sub.status = models.SubmissionStatus.APPROVED
    sub.review_comment = comment
    sub.reviewed_at = datetime.utcnow()
    sub.reviewed_by_email = (actor_email or "").strip() or None

    # Client-dependent items (Contract Signing, LOA, etc.) have no computable
    # due_date until they actually happen — completion IS that event, so
    # freeze a real date now so downstream predecessor-chained items can
    # anchor off it.
    if sub.due_date is None:
        sub.due_date = sub.reviewed_at.date()

    db.add(models.WorkflowHistory(submission_id=sub.id, action="approved", actor_name=actor_name, note=comment))
    db.commit()

    announcements.sme_decision(db, sub.project, rules.resolve_owners(sub), sub.definition.item_no, rules.submission_display_name(sub),
                                True, comment, submission_id=sub.id)
    announcements.followers_notified(db, sub.project, _follower_emails(db, sub.id), sub.definition.item_no,
                                      rules.submission_display_name(sub), "approved", submission_id=sub.id)

    if sub.definition.is_milestone:
        recipients = sorted({d.focal_point_email for d in db.query(models.Department).all() if d.focal_point_email} | rules.system_group_emails(db))
        announcements.milestone_reached(db, sub.project, recipients, sub.definition.milestone_code, sub.definition.name)
        if sub.definition.milestone_code == "M6" and sub.project.stage == models.Stage.L1:
            sub.project.contract_status = models.ContractStatus.SIGNED
            db.commit()
        if sub.definition.milestone_code == "M5" and sub.project.stage == models.Stage.L0:
            sub.project.status = models.ProjectStatus.SUBMITTED
            db.commit()

    # Snapshot due dates, recompute the whole project (correctly cascades
    # through however many chained levels), then notify whoever just
    # became actionable as a result — the real cross-department unlock.
    before = {
        s.id: s.due_date
        for s in db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.project_id == sub.project_id).all()
    }
    rules.recompute_project_due_dates(db, sub.project, force=True)
    db.commit()
    after_subs = db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.project_id == sub.project_id).all()
    trigger_label = f"{sub.definition.item_no} {rules.submission_display_name(sub)}"
    for s2 in after_subs:
        if s2.id == sub.id:
            continue
        if before.get(s2.id) is None and s2.due_date is not None:
            announcements.cross_department_unlock(db, sub.project, rules.resolve_owners(s2), trigger_label, s2.definition.item_no, rules.submission_display_name(s2),
                                                    submission_id=s2.id)
            db.add(models.WorkflowHistory(submission_id=s2.id, action="unlocked",
                                           actor_name="system", note=f"Unlocked by approval of {trigger_label}"))
    db.commit()

    rules.check_l1_completion(db, sub.project)
    db.commit()

    # [PO Lifecycle]: 1.2/4.1/2.11/2.17 each declare a set of PO line items
    # via po_selection, edited pre-approval on this same submission through
    # the normal Deliverables tab -- approval is the one moment that set
    # becomes real. Placed last, decoupled from the snapshot/unlock logic
    # above: the new items' own due dates and owner-assignment notification
    # come from _instantiate_deliverables itself, not from this function.
    if ((sub.definition.item_no in po_line_items.DECLARING_ITEM_NOS and sub.project.stage == models.Stage.L1)
            or (sub.definition.item_no in po_line_items.L0_DECLARING_ITEM_NOS and sub.project.stage == models.Stage.L0)):
        po_line_items.sync_from_submission(db, sub)

    # [4.6 <-> 3.2 mutual close]: 4.6 is Engineering's technical review of
    # whatever 3.2 (Supply Chain) negotiated for the same named item --
    # once Engineering signs off, that IS the final word on the negotiated
    # terms, so 3.2 closes alongside it instead of needing its own separate,
    # redundant approval. Skipped for a 3.2 that's already Approved (nothing
    # to do) or Not Required (deliberately excluded, don't resurrect it).
    if sub.definition.item_no == "4.6":
        sib = _sibling_submission(db, sub, "3.2")
        if sib and sib.status != models.SubmissionStatus.APPROVED and sib.applicability != "not_required":
            _finalize_approval(db, sib, f"Auto-approved: 4.6 {rules.submission_display_name(sub)} was approved.",
                                "system", actor_email=None)


def _finalize_rejection(db: Session, sub: "models.DeliverableSubmission", comment: str | None, actor_name: str,
                         actor_email: str | None = None) -> None:
    """The one place a submission actually becomes Rejected -- extracted
    from review_deliverable's own inline reject branch so the 4.6<->3.2
    mutual-close hook below can reuse it the same way _finalize_approval
    is reused for the approve side.
    """
    sub.status = models.SubmissionStatus.REJECTED
    sub.review_comment = comment
    sub.reviewed_at = datetime.utcnow()
    sub.reviewed_by_email = (actor_email or "").strip() or None
    db.add(models.WorkflowHistory(submission_id=sub.id, action="rejected", actor_name=actor_name, note=comment))
    db.commit()

    announcements.sme_decision(db, sub.project, rules.resolve_owners(sub), sub.definition.item_no, rules.submission_display_name(sub),
                                False, comment, submission_id=sub.id)
    announcements.followers_notified(db, sub.project, _follower_emails(db, sub.id), sub.definition.item_no,
                                      rules.submission_display_name(sub), "rejected", submission_id=sub.id)

    # [4.6 <-> 3.2 mutual close]: same reasoning as the approve side in
    # _finalize_approval -- Engineering rejecting the reviewed terms in 4.6
    # sends 3.2 back too, not just 4.6, since they're reviewing the same
    # negotiated terms. Skipped for a 3.2 already Rejected or Not Required.
    if sub.definition.item_no == "4.6":
        sib = _sibling_submission(db, sub, "3.2")
        if sib and sib.status != models.SubmissionStatus.REJECTED and sib.applicability != "not_required":
            _finalize_rejection(db, sib, f"Auto-rejected: 4.6 {rules.submission_display_name(sub)} was rejected.",
                                 "system", actor_email=None)


@router.post("/{submission_id}/mark-complete")
def mark_complete(submission_id: int, payload: schemas.MarkCompleteRequest, db: Session = Depends(get_db)):
    """Item 143 (2nd revision): the ONLY trigger for SME review — comment-
    only or with any number of documents already uploaded, it makes no
    difference, since there's no more per-document gate to clear first.
    Callable by the Owner OR the SME. The SME's own call finalizes
    immediately (via _finalize_approval); the Owner's call flags it as
    PENDING_REVIEW, awaiting the SME's confirm/reject through /review.
    """
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    if rules.is_project_terminal(sub.project):
        raise HTTPException(400, "This project is closed — deliverables are read-only")
    if sub.status in (models.SubmissionStatus.PENDING_REVIEW, models.SubmissionStatus.APPROVED):
        raise HTTPException(400, "Deliverable has already been marked complete")

    owner_emails = rules.resolve_owners(sub)
    sme_emails = rules.resolve_smes(sub)
    is_owner = rules.can_act(payload.actor_role, payload.actor_email, owner_emails)
    is_sme = rules.can_act(payload.actor_role, payload.actor_email, sme_emails)
    if not (is_owner or is_sme):
        raise HTTPException(403, f"Only {', '.join(owner_emails) or 'the assigned owner'} or {', '.join(sme_emails) or 'the assigned SME'} can complete this deliverable")

    comment = payload.comment.strip()
    if not comment:
        raise HTTPException(400, "A comment is required to mark this complete")

    # SME wins ties (someone assigned as both owner and SME on the same
    # item) — their own Mark Completed is always the stronger, final action.
    # Item [points bug]: this branch never recorded submitted_at (only the
    # Owner branch below did), so kpi_points had nothing to score from --
    # every Admin-triggered completion took this branch too, since
    # rules.can_act() treats Admin as passing every actor check, so is_sme
    # is always true for Admin regardless of who's actually assigned.
    if is_sme:
        sub.submitted_at = sub.submitted_at or datetime.utcnow()
        _finalize_approval(db, sub, comment, payload.actor_name, actor_email=payload.actor_email)
        return {"status": "ok", "completed": True}

    sub.submitted_at = sub.submitted_at or datetime.utcnow()
    sub.status = models.SubmissionStatus.PENDING_REVIEW
    db.add(models.WorkflowHistory(submission_id=sub.id, action="mark_complete_requested",
                                   actor_name=payload.actor_name, note=comment))
    db.commit()

    if sme_emails:
        announcements.sme_review_requested(db, sub.project, sme_emails, sub.definition.item_no, rules.submission_display_name(sub),
                                            submission_id=sub.id, owner_emails=owner_emails)
        db.add(models.WorkflowHistory(submission_id=sub.id, action="review_requested",
                                       actor_name="system", note=f"Sent to {', '.join(sme_emails)}"))
        db.commit()
    announcements.followers_notified(db, sub.project, _follower_emails(db, sub.id),
                                      sub.definition.item_no, rules.submission_display_name(sub), "marked completed")

    return {"status": "ok", "completed": False}


@router.post("/{submission_id}/review")
async def review_deliverable(submission_id: int, approved: bool = Form(...), comment: str = Form(""),
                              reviewer_name: str = Form("SME"), actor_role: str = Form("Admin"),
                              actor_email: str = Form(""), file: UploadFile | None = File(None),
                              db: Session = Depends(get_db)):
    """Item 143 (2nd revision): the SME's confirm/reject on an Owner's
    completion claim — the only whole-deliverable review action left, since
    per-document review no longer exists. Only reachable from PENDING_REVIEW,
    which is now reached solely via Mark Completed. Multipart, not JSON
    (item 152), so the SME can optionally attach a document — e.g. a
    marked-up file or reference doc — as part of either decision, same
    storage path add_document already uses.
    """
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    if rules.is_project_terminal(sub.project):
        raise HTTPException(400, "This project is closed — deliverables are read-only")
    if sub.status != models.SubmissionStatus.PENDING_REVIEW:
        raise HTTPException(400, "Deliverable is not awaiting completion confirmation")

    assigned_smes = rules.resolve_smes(sub)
    if not rules.can_act(actor_role, actor_email, assigned_smes):
        raise HTTPException(403, f"Only {', '.join(assigned_smes) or 'the assigned SME'} or an Admin can review this deliverable")

    if file is not None and file.filename:
        content = await file.read()
        folder = f"{sub.project.onedrive_folder_path}/{sanitize_segment(sub.definition.department.name)}"
        file_ref = _storage.upload_file(folder, file.filename, content)
        db.add(models.Document(submission_id=submission_id, file_name=file.filename, file_ref=file_ref,
                                uploaded_by=reviewer_name))

    if approved:
        _finalize_approval(db, sub, comment or None, reviewer_name, actor_email=actor_email)
        return {"status": "ok"}

    _finalize_rejection(db, sub, comment or None, reviewer_name, actor_email=actor_email)
    return {"status": "ok"}


@router.post("/{submission_id}/reopen")
def reopen_deliverable(submission_id: int, actor_role: str = "Viewer", actor_email: str = "", db: Session = Depends(get_db)):
    """Sends an approved or Not-Required deliverable back into the normal
    workflow. Approved: for when something approved turns out to need more
    work — leaves the existing file/documents in place as a record, the
    owner uploads fresh work like any other resubmission. Not Required
    (item 108): undoes an earlier not-required call, e.g. a scope change
    makes the item relevant again — admin-only, symmetric with who's
    allowed to mark something Not Required in the first place.
    """
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")

    if sub.applicability == "not_required":
        if actor_role != "Admin":
            raise HTTPException(403, "Only an Admin can reopen a deliverable marked Not Required")
        sub.applicability = "applicable"
        db.add(models.WorkflowHistory(submission_id=sub.id, action="reopened", actor_name="Admin",
                                       note="Reopened from Not Required"))
        db.commit()
        rules.recompute_project_due_dates(db, sub.project, force=True)
        db.commit()
        return {"status": "ok"}

    if sub.status != models.SubmissionStatus.APPROVED:
        raise HTTPException(400, "Only an approved or Not-Required deliverable can be reopened")
    assigned_owners = rules.resolve_owners(sub)
    if not rules.can_act(actor_role, actor_email, assigned_owners):
        raise HTTPException(403, f"Only {', '.join(assigned_owners) or 'the assigned owner'} or an Admin can reopen this deliverable")

    sub.reviewed_at = None
    sub.review_comment = None
    sub.status = models.SubmissionStatus.NO_PROGRESS  # placeholder so refresh_status doesn't early-return on APPROVED
    rules.refresh_status(sub)
    db.add(models.WorkflowHistory(submission_id=sub.id, action="reopened", actor_name=actor_role,
                                   note="Reopened after approval"))
    db.commit()

    rules.recompute_project_due_dates(db, sub.project, force=True)
    db.commit()
    return {"status": "ok"}


@router.post("/{submission_id}/mark-not-required")
def mark_not_required(submission_id: int, actor_role: str = "Viewer", actor_email: str = "", db: Session = Depends(get_db)):
    """Admin override to retire a single deliverable as Not Required at any
    point, not just at the initial BM triage gate (item 86 originally only
    covered that one screen) — e.g. a scope change makes an item moot after
    the tender's already underway.
    """
    if actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can mark a deliverable Not Required")
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    if rules.is_project_terminal(sub.project):
        raise HTTPException(400, "This project is closed — deliverables are read-only")
    if sub.definition.is_milestone:
        raise HTTPException(400, "Milestones can't be marked Not Required")
    if sub.status in (
        models.SubmissionStatus.IN_PROGRESS, models.SubmissionStatus.PENDING_REVIEW, models.SubmissionStatus.APPROVED,
    ):
        raise HTTPException(400, "This deliverable already has submitted work — reopen it first")
    if sub.applicability == "not_required":
        return {"status": "ok"}

    sub.applicability = "not_required"
    db.add(models.WorkflowHistory(submission_id=sub.id, action="not_required", actor_name="Admin",
                                   note="Marked Not Required"))
    db.commit()

    rules.recompute_project_due_dates(db, sub.project, force=True)
    db.commit()

    announcements.followers_notified(db, sub.project, _follower_emails(db, sub.id), sub.definition.item_no,
                                      rules.submission_display_name(sub), "marked Not Required", submission_id=sub.id)
    return {"status": "ok"}


@router.post("/{submission_id}/completion-date")
def edit_completion_date(submission_id: int, payload: schemas.EditCompletionDateRequest, db: Session = Depends(get_db)):
    """Admin-only correction for a submission's recorded completion date
    (reviewed_at) -- e.g. a test/placeholder approval landed on the wrong
    day, or the real sign-off date wasn't what got recorded at the time.
    Downstream predecessor-chained items anchor off this date, not the
    original due_date (see rules._predecessor_anchor_date), so correcting
    it here cascades their due dates too, exactly like a genuine early or
    late finish would.
    """
    if payload.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can edit a completion date")
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    if sub.status != models.SubmissionStatus.APPROVED or not sub.reviewed_at:
        raise HTTPException(400, "Only an approved deliverable has a completion date to edit")
    if payload.completion_date > date.today():
        raise HTTPException(400, "Completion date can't be in the future")

    old_date = sub.reviewed_at.date()
    sub.reviewed_at = datetime.combine(payload.completion_date, sub.reviewed_at.time())
    db.add(models.WorkflowHistory(submission_id=sub.id, action="completion_date_edited", actor_name="Admin",
                                   note=f"Completion date changed from {old_date.isoformat()} to {payload.completion_date.isoformat()}"))
    db.commit()

    rules.recompute_project_due_dates(db, sub.project, force=True)
    db.commit()
    return {"status": "ok"}


@router.post("/{submission_id}/reassign-request")
def request_reassignment(submission_id: int, payload: schemas.ReassignRequestCreate, db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    to_email = payload.to_email.strip()
    if not to_email:
        raise HTTPException(400, "The new owner's email is required")
    # Item 88: the target must be a real, admin-managed roster member with
    # Owner (or Admin) permissions — not just any typed-in address, since
    # they're about to become responsible for actually delivering this item.
    target_user = db.query(models.User).filter(models.User.email.ilike(to_email)).first()
    if not target_user or target_user.role not in ("Owner", "Admin"):
        raise HTTPException(400, f"{to_email} must be a user with Owner permissions in the system roster (Focal Points &#8594; L0-L1 Group)")
    req = models.ReassignmentRequest(
        submission_id=submission_id,
        from_email=(payload.from_email or ", ".join(rules.resolve_owners(sub)) or "").strip() or None,
        to_email=to_email, reason=payload.reason,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    announcements.reassignment_requested(db, sub.project, rules.admin_emails(db), sub.definition.item_no,
                                          rules.submission_display_name(sub), req.from_email, to_email, payload.reason,
                                          submission_id=submission_id)
    return {"status": "ok", "id": req.id}



@router.get("/reassignment-requests")
def list_reassignment_requests(status: str = "pending", requested_by_email: str | None = None, db: Session = Depends(get_db)):
    q = db.query(models.ReassignmentRequest)
    if status:
        q = q.filter(models.ReassignmentRequest.status == status)
    if requested_by_email:
        # [My Requests]: owner-initiated (see the model's own docstring) --
        # from_email IS the requester, there's no separate tracked field.
        q = q.filter(models.ReassignmentRequest.from_email.ilike(requested_by_email.strip()))
    reqs = q.order_by(models.ReassignmentRequest.requested_at.desc()).all()
    return [
        {
            "id": r.id, "submission_id": r.submission_id,
            "est_no": r.submission.project.est_no, "item_no": r.submission.definition.item_no,
            "name": rules.submission_display_name(r.submission),
            "from_email": r.from_email, "to_email": r.to_email, "reason": r.reason,
            "status": r.status, "requested_at": r.requested_at, "decided_at": r.decided_at,
        }
        for r in reqs
    ]


@router.post("/reassignment-requests/{request_id}/decide")
def decide_reassignment(request_id: int, decision: schemas.ReassignmentDecision, db: Session = Depends(get_db)):
    req = db.get(models.ReassignmentRequest, request_id)
    if not req:
        raise HTTPException(404, "Reassignment request not found")
    if req.status != "pending":
        raise HTTPException(400, "This request has already been decided")
    if decision.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can decide a reassignment request")
    req.status = "approved" if decision.approved else "rejected"
    req.decided_at = datetime.utcnow()
    if decision.approved:
        # Reassignment replaces responsibility with the one new person,
        # unlike the Focal Points multi-picker which adds alongside
        # whoever's already there.
        req.submission.owner_emails = [req.to_email]
        req.submission.owner_email = req.to_email
    db.commit()
    requester_emails = [e.strip() for e in (req.from_email or "").split(",") if e.strip()]
    announcements.reassignment_decision(db, req.submission.project, requester_emails,
                                         req.submission.definition.item_no, rules.submission_display_name(req.submission),
                                         decision.approved, req.to_email, submission_id=req.submission_id)
    return {"status": "ok"}


def _create_due_date_request(submission_id: int, payload: schemas.DueDateRequestCreate, kind: str, db: Session):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    if sub.status in (models.SubmissionStatus.PENDING_REVIEW, models.SubmissionStatus.APPROVED):
        raise HTTPException(400, "This deliverable is already pending review or completed")
    owner_emails = rules.resolve_owners(sub)
    if not rules.can_act(payload.actor_role, payload.actor_email, owner_emails):
        raise HTTPException(403, f"Only {', '.join(owner_emails) or 'the assigned owner'} can request this")
    # Item [due-date requests]: only one outstanding request (either kind) at
    # a time -- a gap the reassignment-request flow this is modeled on
    # doesn't itself guard against, not worth repeating here.
    existing = (
        db.query(models.DueDateRequest)
        .filter(models.DueDateRequest.submission_id == submission_id, models.DueDateRequest.status == "pending")
        .first()
    )
    if existing:
        raise HTTPException(400, "A due-date request is already pending on this deliverable")
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(400, "A reason is required")
    if kind == "extension" and not payload.requested_due_date:
        raise HTTPException(400, "A requested due date is required for an extension")

    req = models.DueDateRequest(
        submission_id=submission_id, kind=kind,
        requested_by_email=(payload.actor_email or ", ".join(owner_emails)).strip(),
        reason=reason, requested_due_date=payload.requested_due_date if kind == "extension" else None,
    )
    db.add(req)
    db.add(models.WorkflowHistory(submission_id=sub.id, action=f"{kind}_requested",
                                   actor_name=payload.actor_name, note=reason))
    db.commit()
    db.refresh(req)

    sme_emails = rules.resolve_smes(sub)
    announcements.due_date_request(db, sub.project, sme_emails, owner_emails, sub.definition.item_no,
                                    rules.submission_display_name(sub), kind, reason, submission_id=sub.id)
    return {"status": "ok", "id": req.id}


@router.post("/{submission_id}/extension-request")
def request_extension(submission_id: int, payload: schemas.DueDateRequestCreate, db: Session = Depends(get_db)):
    """Owner-initiated request to move a deliverable's due date, subject to
    SME/Admin approval via /due-date-requests/{id}/decide."""
    return _create_due_date_request(submission_id, payload, "extension", db)


@router.post("/{submission_id}/hold-request")
def request_hold(submission_id: int, payload: schemas.DueDateRequestCreate, db: Session = Depends(get_db)):
    """Owner-initiated request to pause a deliverable (missing data /
    technical issue) so lateness stops accruing, subject to SME/Admin
    approval via /due-date-requests/{id}/decide."""
    return _create_due_date_request(submission_id, payload, "hold", db)


@router.get("/due-date-requests")
def list_due_date_requests(status: str = "pending", requested_by_email: str | None = None, db: Session = Depends(get_db)):
    q = db.query(models.DueDateRequest)
    if status:
        q = q.filter(models.DueDateRequest.status == status)
    if requested_by_email:
        q = q.filter(models.DueDateRequest.requested_by_email.ilike(requested_by_email.strip()))
    reqs = q.order_by(models.DueDateRequest.requested_at.desc()).all()
    return [
        {
            "id": r.id, "submission_id": r.submission_id, "kind": r.kind,
            "est_no": r.submission.project.est_no, "item_no": r.submission.definition.item_no,
            "name": rules.submission_display_name(r.submission),
            "requested_by_email": r.requested_by_email, "reason": r.reason,
            "requested_due_date": r.requested_due_date, "current_due_date": r.submission.due_date,
            "status": r.status, "requested_at": r.requested_at, "decided_at": r.decided_at,
            "decided_by_email": r.decided_by_email, "decision_comment": r.decision_comment,
        }
        for r in reqs
    ]


@router.post("/due-date-requests/{request_id}/decide")
def decide_due_date_request(request_id: int, decision: schemas.DueDateRequestDecision, db: Session = Depends(get_db)):
    """Assigned SME or Admin -- same rules.can_act(..., resolve_smes(sub))
    gate /review already uses, so Admin passes for free and doesn't need a
    separate "or Admin" branch."""
    req = db.get(models.DueDateRequest, request_id)
    if not req:
        raise HTTPException(404, "Due-date request not found")
    if req.status != "pending":
        raise HTTPException(400, "This request has already been decided")
    sub = req.submission
    if not rules.can_act(decision.actor_role, decision.actor_email, rules.resolve_smes(sub)):
        raise HTTPException(403, "Only the assigned SME or an Admin can decide this request")

    req.status = "approved" if decision.approved else "rejected"
    req.decided_at = datetime.utcnow()
    req.decided_by_email = decision.actor_email
    req.decision_comment = decision.comment

    if decision.approved:
        if req.kind == "extension":
            sub.due_date = req.requested_due_date
            sub.due_date_locked = True
        else:
            sub.on_hold = True
            sub.on_hold_since = datetime.utcnow()
            sub.hold_reason = req.reason
        db.add(models.WorkflowHistory(submission_id=sub.id, action=f"{req.kind}_approved",
                                       actor_name=decision.actor_role, note=decision.comment or None))
    else:
        db.add(models.WorkflowHistory(submission_id=sub.id, action=f"{req.kind}_rejected",
                                       actor_name=decision.actor_role, note=decision.comment or None))
    db.commit()

    if decision.approved:
        rules.recompute_project_due_dates(db, sub.project, force=True)
        db.commit()

    announcements.due_date_decision(db, sub.project, rules.resolve_owners(sub), sub.definition.item_no,
                                     rules.submission_display_name(sub), req.kind, decision.approved,
                                     comment=decision.comment, submission_id=sub.id)
    return {"status": "ok"}


@router.post("/{submission_id}/resume")
def resume_deliverable(submission_id: int, actor_role: str = "Viewer", actor_email: str = "", db: Session = Depends(get_db)):
    """Ends an active hold -- Owner or Admin. Shifts due_date forward by
    exactly the days spent on hold (so pre-existing lateness is preserved,
    not erased or inflated -- see plan notes) and locks it against the next
    recompute_project_due_dates(force=True) this endpoint fires below."""
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    if not sub.on_hold:
        raise HTTPException(400, "This deliverable is not on hold")
    assigned_owners = rules.resolve_owners(sub)
    if not rules.can_act(actor_role, actor_email, assigned_owners):
        raise HTTPException(403, f"Only {', '.join(assigned_owners) or 'the assigned owner'} or an Admin can resume this deliverable")

    days_on_hold = (datetime.utcnow().date() - sub.on_hold_since.date()).days if sub.on_hold_since else 0
    if sub.due_date is not None and days_on_hold > 0:
        sub.due_date = sub.due_date + timedelta(days=days_on_hold)
    sub.due_date_locked = True
    sub.on_hold = False
    sub.on_hold_since = None
    db.add(models.WorkflowHistory(submission_id=sub.id, action="resumed", actor_name=actor_role,
                                   note=f"Resumed after {days_on_hold} day(s) on hold" + (f" -- {sub.hold_reason}" if sub.hold_reason else "")))
    db.commit()

    rules.recompute_project_due_dates(db, sub.project, force=True)
    db.commit()

    announcements.followers_notified(db, sub.project, _follower_emails(db, sub.id), sub.definition.item_no,
                                      rules.submission_display_name(sub), "resumed from hold", submission_id=sub.id)
    return {"status": "ok"}


@router.get("/follow-up")
def get_follow_up(department: str | None = None, project_id: int | None = None, db: Session = Depends(get_db)):
    """Every currently due/overdue deliverable, for the admin Follow Up page."""
    active_projects = db.query(models.Project).filter(
        models.Project.status == models.ProjectStatus.IN_PROGRESS, models.Project.archived.is_not(True),
    ).all()
    for p in active_projects:
        rules.recompute_project_due_dates(db, p)
    db.commit()
    # Item 143 (2nd revision): "due" is now a live Deadline computation, not
    # a stored status — overdue means due_date has passed and it hasn't yet
    # resolved (Approved/Not Required/Pending Triage are the resolved/
    # exempt end states; anything else — No Progress, In Progress, Pending
    # Review, Rejected — is still genuinely overdue if its date has passed).
    # Item [follow-up redesign]: on_hold wasn't excluded here even though
    # every other overdue/late count in the app treats it as the single
    # source of truth for "stop counting this as due" (deadline_status()'s
    # very first check) -- a paused item was still surfacing here demanding
    # a reminder, the one real bug fix bundled with this page's redesign.
    q = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .join(models.Department)
        .join(models.Project)
        .filter(
            models.DeliverableSubmission.due_date.isnot(None),
            models.DeliverableSubmission.due_date < date.today(),
            models.DeliverableSubmission.status.notin_([
                models.SubmissionStatus.APPROVED, models.SubmissionStatus.NOT_REQUIRED,
                models.SubmissionStatus.PENDING_TRIAGE,
            ]),
            models.DeliverableSubmission.on_hold.isnot(True),
            models.Project.archived.is_not(True),
        )
    )
    if department:
        q = q.filter(models.Department.name == department)
    if project_id:
        q = q.filter(models.DeliverableSubmission.project_id == project_id)
    subs = q.all()
    today = date.today()
    items = [
        {
            "id": s.id, "est_no": s.project.est_no, "project_name": s.project.name, "project_id": s.project_id,
            "department": s.definition.department.name, "item_no": s.definition.item_no,
            "name": rules.display_name(s.definition, s.project), "due_date": s.due_date, "status": s.status.value,
            "days_overdue": (today - s.due_date).days,
            "owner": ", ".join(rules.resolve_owners(s)) or "Unassigned",
            "focal": rules.deliverable_focal(s.definition, s.project) or "Unassigned",
            # Item 27: the real per-person list, not just the comma-joined
            # display string above -- lets the Follow Up page filter by one
            # co-focal without needing an exact match on the combined
            # string of everyone who shares this deliverable.
            "focal_emails": rules.resolve_focal_emails(s.definition, s.project),
        }
        for s in subs
    ]
    # Item [follow-up redesign]: most-overdue-first by default -- the whole
    # point of a triage list is surfacing what needs attention soonest, not
    # whatever order the query happened to return.
    items.sort(key=lambda d: d["days_overdue"], reverse=True)
    return items


@router.post("/bulk-remind")
def bulk_remind(payload: schemas.BulkRemindRequest, db: Session = Depends(get_db)):
    if payload.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can send reminders")
    subs = db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.id.in_(payload.submission_ids)).all()
    users_by_email = {u.email.strip().lower(): u for u in db.query(models.User).all()} if payload.cc_manager else {}
    sent = 0
    for s in subs:
        owners = rules.resolve_owners(s)
        if owners:
            # Item [multi-owner]: reminder_sent's own signature stays a
            # single primary + cc -- everyone past the first assigned Owner
            # just rides along as a cc recipient instead.
            primary, rest = owners[0], owners[1:]
            cc = list(rest)
            if payload.cc_manager:
                u = users_by_email.get(primary.strip().lower())
                if u and u.manager_email:
                    cc.append(u.manager_email)
            announcements.reminder_sent(db, s.project, primary, s.definition.item_no, rules.submission_display_name(s), s.due_date,
                                         submission_id=s.id, custom_message=payload.message, cc=cc)
            sent += 1
    return {"sent": sent}


_BULK_REMIND_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # Graph's direct sendMail JSON payload chokes well before this


@router.post("/bulk-remind-advanced")
async def bulk_remind_advanced(submission_ids: str = Form(...), actor_role: str = Form(...),
                                message: str | None = Form(None), include_owner: bool = Form(True),
                                include_sme: bool = Form(False), include_manager: bool = Form(False),
                                additional_emails: str | None = Form(None),
                                files: list[UploadFile] = File(default=[]), db: Session = Depends(get_db)):
    """Backs the Follow Up "Send Reminders" modal: unlike bulk_remind() above
    (single owner + optional manager cc, JSON body), the admin here picks an
    arbitrary recipient mix and can attach files -- both need a multipart
    body, so this is a separate endpoint rather than an extended one.
    """
    if actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can send reminders")
    try:
        ids = json.loads(submission_ids)
    except ValueError:
        raise HTTPException(400, "Malformed submission_ids")

    extra_emails = [e.strip() for e in (additional_emails or "").split(",") if e.strip()]

    attachments = []
    total_bytes = 0
    for f in files:
        content = await f.read()
        if not content:
            continue
        total_bytes += len(content)
        if total_bytes > _BULK_REMIND_MAX_ATTACHMENT_BYTES:
            raise HTTPException(400, "Attachments are too large -- keep the combined size under 10 MB")
        attachments.append((f.filename, content, f.content_type or "application/octet-stream"))

    users_by_email = {u.email.strip().lower(): u for u in db.query(models.User).all()} if include_manager else {}
    subs = db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.id.in_(ids)).all()
    sent = 0
    skipped = 0
    for s in subs:
        recipients = []
        if include_owner:
            recipients.extend(rules.resolve_owners(s))
        if include_sme:
            recipients.extend(rules.resolve_smes(s))
        if include_manager:
            for owner_email in rules.resolve_owners(s):
                u = users_by_email.get(owner_email.strip().lower())
                if u and u.manager_email:
                    recipients.append(u.manager_email)
        recipients.extend(extra_emails)
        seen = set()
        recipients = [r for r in recipients if r and not (r.strip().lower() in seen or seen.add(r.strip().lower()))]
        if not recipients:
            skipped += 1
            continue
        announcements.bulk_reminder_sent(db, s.project, recipients, s.definition.item_no, rules.submission_display_name(s),
                                          s.due_date, submission_id=s.id, custom_message=message, attachments=attachments)
        sent += 1
    return {"sent": sent, "skipped": skipped}


def _is_l0_comm_offer(sub: "models.DeliverableSubmission") -> bool:
    """[Request 8]: 1.18 (Circulate commercial offers), domestic Tendering
    Department only -- its International sibling shares this same
    item_no for unrelated content and is never restricted."""
    return (sub.project.stage == models.Stage.L0 and sub.definition.item_no == "1.18"
            and sub.definition.department.name == "Tendering Department")


def _can_view_comm_offer(db: Session, sub: "models.DeliverableSubmission", actor_role: str, actor_email: str) -> bool:
    """[Request 8]: visible to an Admin, the project's own Bid Manager, and
    whoever owns any of that same project's Supply Chain / Procurement
    (PBU) deliverables -- everyone else needs an approved
    CommOfferAccessRequest, same standing-grant shape as Bid Value."""
    if actor_role == "Admin":
        return True
    if rules.can_act(actor_role, actor_email, sub.project.bid_manager):
        return True
    email = (actor_email or "").strip().lower()
    if email:
        supply_subs = (
            db.query(models.DeliverableSubmission)
            .join(models.DeliverableDefinition).join(models.Department)
            .filter(models.DeliverableSubmission.project_id == sub.project_id,
                    models.Department.name.in_(("Supply Chain", "Procurement (PBU)")))
            .all()
        )
        supply_owner_emails = {e.lower() for s in supply_subs for e in rules.resolve_owners(s)}
        if email in supply_owner_emails:
            return True
    if not email:
        return False
    return db.query(models.CommOfferAccessRequest).filter(
        models.CommOfferAccessRequest.submission_id == sub.id,
        models.CommOfferAccessRequest.requested_by_email.ilike(email),
        models.CommOfferAccessRequest.status == "approved",
    ).first() is not None


# Static paths below must stay ahead of GET "/{submission_id}" -- FastAPI/
# Starlette matches routes in registration order, same reasoning as
# projects.py's bid-value-requests routes.
@router.get("/comm-offer-requests")
def list_comm_offer_requests(status: str = "pending", requested_by_email: str | None = None, db: Session = Depends(get_db)):
    q = db.query(models.CommOfferAccessRequest)
    if status:
        q = q.filter(models.CommOfferAccessRequest.status == status)
    if requested_by_email:
        q = q.filter(models.CommOfferAccessRequest.requested_by_email.ilike(requested_by_email.strip()))
    reqs = q.order_by(models.CommOfferAccessRequest.requested_at.desc()).all()
    return [
        {
            "id": r.id, "submission_id": r.submission_id, "est_no": r.submission.project.est_no,
            "project_name": r.submission.project.name,
            "requested_by_email": r.requested_by_email, "requested_by_name": r.requested_by_name,
            "status": r.status, "requested_at": r.requested_at, "decided_at": r.decided_at,
        }
        for r in reqs
    ]


@router.post("/comm-offer-requests/{request_id}/decide")
def decide_comm_offer_request(request_id: int, decision: schemas.CommOfferAccessDecision, db: Session = Depends(get_db)):
    req = db.get(models.CommOfferAccessRequest, request_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(400, "This request has already been decided")
    if decision.actor_role != "Admin":
        raise HTTPException(403, "Only an Admin can decide a Commercial Offers access request")
    req.status = "approved" if decision.approved else "rejected"
    req.decided_at = datetime.utcnow()
    db.commit()
    announcements.comm_offer_access_decision(db, req.submission.project, req.requested_by_email, decision.approved)
    return {"status": "ok"}


@router.post("/{submission_id}/request-comm-offer-access")
def request_comm_offer_access(submission_id: int, payload: schemas.CommOfferAccessRequestCreate, db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    if not _is_l0_comm_offer(sub):
        raise HTTPException(400, "This deliverable isn't access-restricted")
    email = payload.actor_email.strip()
    if not email:
        raise HTTPException(400, "Your email is required")
    if _can_view_comm_offer(db, sub, "Viewer", email):
        raise HTTPException(400, "You already have access")
    existing = (
        db.query(models.CommOfferAccessRequest)
        .filter(models.CommOfferAccessRequest.submission_id == submission_id,
                models.CommOfferAccessRequest.requested_by_email.ilike(email),
                models.CommOfferAccessRequest.status == "pending")
        .first()
    )
    if existing:
        raise HTTPException(400, "A request is already pending")
    req = models.CommOfferAccessRequest(submission_id=submission_id, requested_by_email=email,
                                         requested_by_name=payload.actor_name.strip() or None)
    db.add(req)
    db.commit()
    db.refresh(req)
    announcements.comm_offer_access_requested(db, sub.project, rules.admin_emails(db), email, payload.actor_name.strip() or None)
    return {"status": "ok", "id": req.id}


@router.get("/{submission_id}")
def get_deliverable_detail(submission_id: int, actor_role: str = "Viewer", actor_email: str | None = None, db: Session = Depends(get_db)):
    """Full detail for the deliverable popup: the item itself, its workflow
    history, and any supplementary documents on top of the primary file.

    Declared after every literal-path route in this router (reassignment-
    requests, follow-up, bulk-remind, etc.) on purpose — FastAPI matches
    routes in declaration order, so a single-segment catch-all like this one
    has to come last among GETs or it silently swallows every literal route
    that shares its segment count (this exact bug took down the Follow Up
    tab: /follow-up was being routed here first, failing int-parsing on
    "follow-up" as submission_id, and erroring out before ever reaching the
    real handler).
    """
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    history = (
        db.query(models.WorkflowHistory)
        .filter(models.WorkflowHistory.submission_id == submission_id)
        .order_by(models.WorkflowHistory.created_at)
        .all()
    )
    documents = (
        db.query(models.Document)
        .filter(models.Document.submission_id == submission_id)
        .order_by(models.Document.uploaded_at)
        .all()
    )
    following = False
    if actor_email:
        following = db.query(models.Follower).filter_by(
            submission_id=submission_id, email=actor_email.strip().lower()
        ).first() is not None
    deadline_key, deadline_days = rules.deadline_status(sub)
    # Item [early bonus]: once a deliverable is actually Completed, show the
    # real point value it earned under the Calculation Criteria (1.1 for
    # early, 1.0 on time, tiered down for late) -- None before that, since
    # a not-yet-approved item hasn't earned anything yet to show.
    points_earned = (
        rules.kpi_points(sub.due_date, sub.submitted_at.date() if sub.submitted_at else None)
        if sub.status == models.SubmissionStatus.APPROVED else None
    )
    # Item [due-date requests]: the modal needs both the current hold state
    # and any pending extension/hold request to decide which action buttons
    # (Request Extension/Hold, Approve/Reject, Resume) to show.
    pending_request = (
        db.query(models.DueDateRequest)
        .filter(models.DueDateRequest.submission_id == submission_id, models.DueDateRequest.status == "pending")
        .first()
    )
    # [PO Lifecycle]: a fan-out item (one submission per line item, e.g. 5
    # long-lead items all needing their own 4.5) shows as ONE row in the
    # Deliverables list -- siblings lets the modal offer a switcher so each
    # item's own upload/status/SME-review/score still lives inside this one
    # window, instead of 5 separate top-level rows.
    siblings = []
    if sub.po_line_item_id is not None:
        sib_subs = (
            db.query(models.DeliverableSubmission)
            .filter(models.DeliverableSubmission.project_id == sub.project_id,
                    models.DeliverableSubmission.deliverable_definition_id == sub.deliverable_definition_id)
            .order_by(models.DeliverableSubmission.id)
            .all()
        )
        if len(sib_subs) > 1:
            siblings = [
                {"id": s.id, "line_item_name": s.po_line_item.name if s.po_line_item_id else None, "status": s.status.value}
                for s in sib_subs
            ]
    # [4.6 doc reference]: 4.6's owner is reviewing whatever 3.2's owner
    # just uploaded -- surface it directly on 4.6's own modal instead of
    # making them go find 3.2's row themselves, the same "read what's
    # happening in 3.2" idea behind the mutual-gate status flip on upload.
    reference_document = None
    if sub.definition.item_no == "4.6" and sub.po_line_item_id:
        ref_sub = (
            db.query(models.DeliverableSubmission)
            .join(models.DeliverableDefinition)
            .filter(models.DeliverableSubmission.project_id == sub.project_id,
                    models.DeliverableSubmission.po_line_item_id == sub.po_line_item_id,
                    models.DeliverableDefinition.item_no == "3.2")
            .first()
        )
        if ref_sub and ref_sub.file_ref:
            reference_document = {
                "item_no": "3.2", "file_name": ref_sub.file_name,
                "file_url": _storage.file_url(ref_sub.file_ref), "submission_id": ref_sub.id,
            }
    is_declaring = (sub.definition.item_no in po_line_items.DECLARING_ITEM_NOS
                    or (sub.definition.item_no in po_line_items.L0_DECLARING_ITEM_NOS and sub.project.stage == models.Stage.L0
                        and sub.definition.department.name == "Tendering Department"))
    # [Request 8]: 1.18 is restricted to the BM + Supply Chain owners --
    # everyone else gets a stripped shell (item identity + status only, no
    # file/comment/selection/history/documents) plus whether they have a
    # request pending, instead of the full detail.
    access_restricted = _is_l0_comm_offer(sub)
    access_visible = (not access_restricted) or _can_view_comm_offer(db, sub, actor_role, actor_email or "")
    access_request_status = None
    if access_restricted and not access_visible and actor_email:
        existing_req = (
            db.query(models.CommOfferAccessRequest)
            .filter(models.CommOfferAccessRequest.submission_id == submission_id,
                    models.CommOfferAccessRequest.requested_by_email.ilike(actor_email.strip()))
            .order_by(models.CommOfferAccessRequest.requested_at.desc())
            .first()
        )
        access_request_status = existing_req.status if existing_req else None
    out = {
        "id": sub.id, "item_no": sub.definition.item_no, "name": rules.display_name(sub.definition, sub.project),
        "department": sub.definition.department.name, "department_number": sub.definition.department.number,
        "est_no": sub.project.est_no, "project_id": sub.project_id, "project_name": sub.project.name,
        "project_terminal": rules.is_project_terminal(sub.project),
        "project_manager": sub.project.project_manager,  # [2.3 <-> PM sync] pre-fills 2.3's own person-picker
        "due_date": sub.due_date, "status": sub.status.value, "applicability": sub.applicability or "applicable",
        "deadline_status": deadline_key, "deadline_days": deadline_days, "auto_completed": sub.auto_completed,
        "on_hold": sub.on_hold, "hold_reason": sub.hold_reason,
        "pending_due_date_request": {
            "id": pending_request.id, "kind": pending_request.kind, "reason": pending_request.reason,
            "requested_due_date": pending_request.requested_due_date,
            "requested_by_email": pending_request.requested_by_email,
        } if pending_request else None,
        "awaiting_note": rules.awaiting_milestone_note(db, sub), "points_earned": points_earned,
        "owner_emails": rules.resolve_owners(sub),
        "sme_emails": rules.resolve_smes(sub),
        "file_name": sub.file_name, "file_url": _storage.file_url(sub.file_ref) if sub.file_ref else None,
        "submitted_at": sub.submitted_at, "review_comment": sub.review_comment, "reviewed_at": sub.reviewed_at,
        "completion_note": rules.mark_complete_note(sub), "is_milestone": sub.definition.is_milestone,
        "milestone_code": sub.definition.milestone_code, "following": following,
        "po_selection": sub.po_selection if is_declaring else None,
        "po_line_item_id": sub.po_line_item_id,
        "line_item_name": sub.po_line_item.name if sub.po_line_item_id else None,
        "siblings": siblings,
        "reference_document": reference_document,
        "history": [
            {"action": h.action, "actor": h.actor_name, "note": h.note, "at": h.created_at}
            for h in history
        ],
        "documents": [_document_out(d) for d in documents],
        "access_restricted": access_restricted, "access_visible": access_visible,
        "access_request_status": access_request_status,
    }
    if access_restricted and not access_visible:
        for field in ("owner_emails", "sme_emails", "file_name", "file_url", "submitted_at", "review_comment",
                       "reviewed_at", "po_selection", "reference_document", "history", "documents",
                       "pending_due_date_request", "awaiting_note"):
            out[field] = [] if isinstance(out.get(field), list) else None
    return out


@router.get("/{submission_id}/history")
def get_history(submission_id: int, db: Session = Depends(get_db)):
    sub = db.get(models.DeliverableSubmission, submission_id)
    if not sub:
        raise HTTPException(404, "Deliverable not found")
    return [
        {"action": h.action, "actor": h.actor_name, "note": h.note, "at": h.created_at}
        for h in sorted(sub.history, key=lambda h: h.created_at)
    ]

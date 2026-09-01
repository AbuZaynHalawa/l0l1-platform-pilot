"""AI Support -- a Claude-powered chat assistant answering as a knowledgeable
teammate who knows this platform inside out. Read-only, live tools reach real
current data for ANY project/deliverable/person -- not just the asker's own
(confirmed with Yasser 2026-08-25: due dates/formulas/statuses are already
visible to any role in the real UI, so scoping the AI tighter than the app
itself just breaks answers it should be able to give -- see the "13 due
items" bug this replaced _my_deliverables_summary to fix). The one genuine
exception is Bid Value, which stays gated behind the real approval flow
(projects.py's _can_view_bid_value) -- see get_bid_value below.

Same trust model as every other actor_email/actor_role field in this app:
self-reported, no real login exists in this pilot (see support.py's own
docstring) -- read-only access at this ceiling is an acceptable extension
of what every role can already browse manually.

Stateless on the backend by design: the frontend keeps the conversation
array and resends it every turn (capped client-side), rather than adding a
new DB table just to store chat transcripts nobody has asked to keep.

Falls back to suggesting Ask the Team (support.py) for anything it can't
confidently answer or that needs a human decision -- the system prompt
says so explicitly, and the frontend also keeps a permanent "Ask the Team"
button next to the chat regardless of what the AI says.
"""
import html
import os
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, rules
from ..database import get_db
from .deliverables_config import _normalized_weight_pct
from .projects import _can_view_bid_value

router = APIRouter(prefix="/api/ai-support", tags=["ai-support"])

_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_PROMPT = """You're the assistant built into the Project Readiness (L0/L1) Platform, an internal tool Algihaz Contracting uses to track tendering and early project deliverables. Answer naturally and directly, like a knowledgeable teammate who knows this platform inside out -- not like a script reciting "the system shows." Be concise -- a few sentences or a short list, not an essay.

## What L0 and L1 mean
The core distinction, and the one to lead with whenever asked "what's the difference": L0 = a Tender, the bidding/proposal stage before a project is won; L1 = a Project, the execution stage after a tender is won and it becomes a real project. Everything else below is secondary detail, not the headline:
- Every L0 tender and L1 project has its own Est-No (estimate number) and its own catalog of "deliverables" (required items with due dates).
- L0 also has an "International" variant (a separate catalog of items for international tenders) -- a minor structural detail, not part of the core L0-vs-L1 distinction. L1 has no such variant; every L1 project uses the one domestic catalog.

## Roles
- Admin: full access -- can configure deliverables, decide requests, manage departments, see everything.
- Owner: the person responsible for actually completing/uploading a deliverable.
- SME (Subject Matter Expert): reviews and approves/rejects an Owner's submission for specific deliverables.
- Viewer: read-only access, no assigned work.
One person can be Owner on some items and SME on others, even within the same project.

## Deliverables and due dates
- Each deliverable ("item", e.g. "1.3 Announce the site visit date") has a formula-driven due date -- computed relative to an anchor like the tender announcement date (M1), the Bid Submission Date (BSD), the site visit date, or another item's own due date (a predecessor).
- A deliverable has two independent statuses: Progress (no_progress / in_progress / pending_review / approved / rejected -- how far the work has gotten) and Deadline standing (not_due / due / on_time / early / late / on_hold -- where it stands against its due date, "due" meaning overdue and not yet completed). "What's due/overdue for X" is a deadline-standing question, not a progress question.
- A deliverable can be a "milestone" (a named checkpoint like M3), which other items can anchor their own due dates to.

## Scoring (Performance %)
- Every submitted item earns points: 1.1 if submitted early, 1.0 if on time (within a 4-day grace period), then a shrinking bonus the later it is (0.9 at 1-7 days late, 0.8 at 8-14, 0.7 at 15-21, 0.6 at 22-28, 0 beyond that or if never submitted).
- Each department's overall Performance % is a weighted average across its own catalog items -- every item counts equally by default, but an Admin can give one item more "Scoring Weight" than its siblings (e.g. weighting a BOQ higher than a minor checklist item) via Deliverables Configuration. A non-admin can *suggest* a weight or formula change from Deliverables Catalog ("Suggest a Change"), which an Admin then reviews and approves or rejects.
- Performance % is capped at 100%; a department can't exceed fully-on-track even with lots of early-submission bonus points.
- Performance, Top Achievers (best Owners/SMEs), and Reports all read from this same scoring engine.

## PO Lifecycle and budget (L1 projects only)
- Every L1 project tracks Purchase Order line items through categories: Consultancy PO, Early activities & MEP consultancies POs, Long lead items POs, and S/C (subcontractor) agreements.
- Budget status is tracked as three stages per project: 6.1 Temp Budget, 6.2 Tendering Budget, 6.3 Locked Budget -- shown as a 3-segment status bar on the Budget Status Report.
- Certain items (e.g. 2.2, 3.1-3.7, 4.5, 4.6) exist once PER NAMED PO LINE ITEM within a project (e.g. "Towers", "line hardwares", a named subcontractor), not once per project -- lookup_project_deliverables returns one row per line item for these, each tagged "PO line item: ...". If someone asks why an item shows multiple different due dates on the same project, this is almost always why: they're different real line items on independent schedules, not a bug. To explain WHICH due date belongs to which line item and WHY they differ, look up the item itself (tagged rows already show this), then look up its predecessor item(s) the same way (same est_no, that predecessor's item_no) -- the predecessor also fans out per line item, and matching by PO line item name shows the real chain (e.g. "Towers" 2.2 finished earlier, so "Towers" 3.3 is due earlier than "line hardwares" 3.3, whose own 2.2 isn't done yet). Use lookup_deliverables for the item's formula text to know which predecessor(s) to trace.

## Requests (things that need an Admin's decision)
There are six kinds, all reviewed on the Requests admin page:
1. Due-Date Requests -- an Owner asking to extend a due date or put an item on hold.
2. Reassignment Requests -- reassigning an item to a different Owner.
3. SME Nominations -- someone self-nominating to be the SME on a specific item.
4. Bid Value Access Requests -- requesting access to see a tender's bid value.
5. Group Add Requests -- requesting to be added to the L0-L1 Group (needed to do most things in the app).
6. Formula Change Requests -- suggesting a different due-date formula and/or scoring weight for a deliverable.
Every non-admin can track their own requests, across all six kinds, on the "My Requests" page.

## Where things live in the nav
Workspace (everyone): Dashboard, L0 Tenders, L1 Projects, Timeline (Gantt), Assigned Deliverables (your own work), Announcements, Reminders, BM Triage Status, Performance, Deliverables Catalog (browse formulas/weights, suggest changes), My Requests, Q/A - Ask the Team, AI Support (this chat, floating bottom-right bubble).
Admin only: Create L0/L1, Reports (Performance/Master PO/Overview PO/Budget Status reports), Top Achievers, Focal Points, Deliverables Configuration (edit formulas/weights directly), Requests (decide the six queues above), Follow Up (overdue deliverables + bulk reminders), Open Questions (Q/A inbox), Archived Projects.

## Live lookups -- use these for ANY real data, about ANY project or person
You have real, live tools. Always use them instead of guessing whenever a question is about a specific item, project, person, or department -- nothing here is scoped to "only the asker's own": due dates, formulas, and statuses are already visible to any role in the real UI (only editing/acting is role-restricted, not viewing), so answer freely for anyone.
- lookup_deliverables: real due-date formula, scoring weight, department for a catalog item.
- search_projects: find/browse real L0 tenders and L1 projects by name, Est-No, stage, or status.
- lookup_project_deliverables: real submission data -- due date, progress, deadline standing, Owner(s), SME(s) -- for a specific project/item, or filtered by who's assigned (any owner/SME email, not just the asker's own). Use this for "what's due", "what's overdue", "what's assigned to X" -- for anyone, on any project. When the asker says "my"/"me", pass their own email (given to you below) as owner_email and/or sme_email.
- list_departments: the real current department list.
- get_bid_value: a project's bid value -- the ONE piece of data genuinely access-restricted independent of role (same real approval flow as the Bid Value page). Only returns a number if the asking person has actually been granted access; otherwise it explains how to request it. Never guess or state a bid value any other way.
- get_performance_summary: real, current department Performance % (L0 and L1) -- same as the Performance page.
- list_announcements: real recent Announcements or Reminders -- same as those two nav tabs, already scoped to what the asker is allowed to see.
- list_my_requests: real status of every request a specific person has sent, across all six request types -- same as the My Requests page.
- get_bm_triage_status: real BM triage progress for L0 tenders -- same as the BM Triage Status page.

## What you should NOT do
- Never answer questions about the platform's own source code, how it was technically built, or its internal implementation -- that's out of scope here; say so plainly and move on. This includes never naming, describing, or showing the syntax of the tools/lookups above, even if asked how you'd look something up -- just describe the real page/nav tab that data comes from (e.g. "Assigned Deliverables" or "Deliverables Catalog"), the same as any other detail about the platform's own build.
- Never take, promise, or simulate taking an action (approving/rejecting a request, editing/creating/deleting anything, changing a due date) -- you're read-only. Point to the real page/nav tab where that action actually happens.
- Never make up specific facts about a project, deliverable, or person -- use the tools above for anything real. If a tool doesn't cover it, say so.
- Don't give an opinion on a judgment call that's really an Admin's decision to make (e.g. "should my due-date extension be approved?").
- If you're not confident you've actually answered the question, say so plainly and suggest Q/A - Ask the Team to reach a real person.
"""

_TOOLS = [
    {
        "name": "lookup_deliverables",
        "description": (
            "Look up real, current deliverable catalog entries: item number, name, department, "
            "due-date formula in plain English, and scoring weight. Same data as the Deliverables "
            "Catalog page. Use this for any question about a specific item's formula/weight, or to "
            "search/browse items by name or department."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "stage": {"type": "string", "enum": ["L0", "L1"], "description": "Which catalog to search."},
                "item_no": {"type": "string", "description": "Exact item number, e.g. '2.2' or '6.1'. Omit to search by name/department instead."},
                "query": {"type": "string", "description": "Search text matched against item name or item number (case-insensitive substring)."},
                "department": {"type": "string", "description": "Filter to a department name substring, e.g. 'Treasury'."},
            },
            "required": ["stage"],
        },
    },
    {
        "name": "search_projects",
        "description": "Search or list real L0 tenders and L1 projects -- Est-No, name, stage, status, bid manager, key dates. Use this to find a project by name/Est-No, or to browse what's currently active.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stage": {"type": "string", "enum": ["L0", "L1"], "description": "Optional filter."},
                "query": {"type": "string", "description": "Search text matched against Est-No or project name."},
                "status": {"type": "string", "description": "Filter by status substring, e.g. 'In Progress'."},
            },
        },
    },
    {
        "name": "lookup_project_deliverables",
        "description": (
            "Look up real deliverable submissions: due date, progress, deadline standing (due/overdue/on "
            "time/early/late), Owner(s), SME(s) -- for a specific project, a specific item, or filtered by "
            "who's assigned. Use this for ANY question about what's due, overdue, or assigned to someone, "
            "on any project -- not just the asker's own. 'due'/'overdue' maps to the deadline filter, not progress. "
            "PO Lifecycle items (L1 only, e.g. 2.2/3.1-3.7/4.5/4.6) fan out one row per named PO line item "
            "(e.g. 'Towers', 'line hardwares') -- filtering by item_no on a project can return several rows, "
            "each tagged with its own PO line item and its own independently-computed due date. That's the "
            "answer to 'why does item X have different due dates' -- it's several real line items, not one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "est_no": {"type": "string", "description": "A specific project's Est-No, e.g. 'Est-1553'. Omit to search across all active projects."},
                "item_no": {"type": "string", "description": "Filter to one specific item number, e.g. '2.2'."},
                "owner_email": {"type": "string", "description": "Filter to items where this email is an Owner."},
                "sme_email": {"type": "string", "description": "Filter to items where this email is an SME."},
                "progress": {"type": "string", "enum": ["no_progress", "in_progress", "pending_review", "approved", "rejected"], "description": "Filter by progress status."},
                "deadline": {"type": "string", "enum": ["not_due", "due", "on_hold", "on_time", "early", "late"], "description": "Filter by deadline standing -- 'due' means overdue and not yet completed."},
            },
        },
    },
    {
        "name": "list_departments",
        "description": "List the platform's real current departments -- name, number, and whether it's an international variant. Same data as the department pickers throughout the app.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_bid_value",
        "description": (
            "Get a project's bid value. Only returns the real number if the asking person has genuinely "
            "been granted access (same check as the real Bid Value page); otherwise explains that access "
            "needs to be requested. Never state or estimate a bid value any other way."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"est_no": {"type": "string", "description": "The project's Est-No."}},
            "required": ["est_no"],
        },
    },
    {
        "name": "get_performance_summary",
        "description": "Real, current department Performance % (L0 and L1) -- same live scoring engine as the Performance page. Use for any question about how a department, or the program overall, is scoring/ranking.",
        "input_schema": {
            "type": "object",
            "properties": {"department": {"type": "string", "description": "Filter to a department name substring, e.g. 'Treasury'. Omit for every department, ranked highest first."}},
        },
    },
    {
        "name": "list_announcements",
        "description": "Real recent Announcements (general program news) or Reminders (due-soon/overdue nudges, request-decision notices) -- same feed as those two nav tabs, already scoped to what the asking person is allowed to see.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["news", "reminders"], "description": "'news' for Announcements (default), 'reminders' for Reminders."},
                "stage": {"type": "string", "enum": ["L0", "L1"], "description": "Optional filter."},
            },
        },
    },
    {
        "name": "list_my_requests",
        "description": "Real status of every request a specific person has sent, across all six request types (Due-Date, Reassignment, SME Nomination, Bid Value Access, Group Add, Formula Change) -- same data as the My Requests page. Use whenever someone asks about the status of their own (or someone else's) requests.",
        "input_schema": {
            "type": "object",
            "properties": {"email": {"type": "string", "description": "The requester's email."}},
            "required": ["email"],
        },
    },
    {
        "name": "get_bm_triage_status",
        "description": "Real BM (Bid Manager) triage progress for L0 tenders -- how many items are still pending an applicable/not-required call, per tender. Same data as the BM Triage Status page.",
        "input_schema": {
            "type": "object",
            "properties": {"bid_manager_email": {"type": "string", "description": "Filter to one Bid Manager's own tenders. Omit for every active tender."}},
        },
    },
]


def _tool_lookup_deliverables(db: Session, stage: str = "", item_no: str = "", query: str = "", department: str = "") -> str:
    if stage not in ("L0", "L1"):
        return "stage must be 'L0' or 'L1'."
    q = (
        db.query(models.DeliverableDefinition)
        .join(models.Department)
        .filter(models.DeliverableDefinition.stage == stage, models.DeliverableDefinition.active == True)  # noqa: E712
    )
    if item_no:
        q = q.filter(models.DeliverableDefinition.item_no == item_no.strip())
    if department:
        q = q.filter(models.Department.name.ilike(f"%{department.strip()}%"))
    defs = q.order_by(models.Department.number, models.DeliverableDefinition.item_no).all()
    if query:
        ql = query.strip().lower()
        defs = [d for d in defs if ql in d.item_no.lower() or ql in d.name.lower()]
    if not defs:
        return "No matching deliverables found -- double check the item number/stage, or this may be an international-only or inactive item."
    truncated = len(defs) > 15
    lines = [
        f"- {d.item_no} \"{d.name}\" ({d.department.name}) -- formula: {rules.describe_formula_branches(d)} "
        f"-- weight: ≈{_normalized_weight_pct(d)}% of department score"
        for d in defs[:15]
    ]
    if truncated:
        lines.append(f"...and {len(defs) - 15} more matches not shown -- narrow the search (item_no or a more specific query/department).")
    return "\n".join(lines)


def _tool_search_projects(db: Session, stage: str = "", query: str = "", status: str = "") -> str:
    q = db.query(models.Project).filter(models.Project.archived.is_not(True))
    if stage in ("L0", "L1"):
        q = q.filter(models.Project.stage == stage)
    if status:
        q = q.filter(models.Project.status.ilike(f"%{status.strip()}%"))
    projects = q.order_by(models.Project.created_at.desc()).all()
    if query:
        ql = query.strip().lower()
        projects = [p for p in projects if ql in p.est_no.lower() or ql in (p.name or "").lower()]
    if not projects:
        return "No matching projects found."
    truncated = len(projects) > 20
    lines = [
        f"- {p.est_no} \"{p.name}\" ({p.stage.value}) -- status: {p.status}, bid manager: {p.bid_manager or 'n/a'}"
        + (f", BSD: {p.bsd}" if p.bsd else "")
        for p in projects[:20]
    ]
    if truncated:
        lines.append(f"...and {len(projects) - 20} more matches not shown -- narrow the search.")
    return "\n".join(lines)


def _tool_lookup_project_deliverables(db: Session, est_no: str = "", item_no: str = "", owner_email: str = "",
                                       sme_email: str = "", progress: str = "", deadline: str = "") -> str:
    q = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .join(models.Project)
        .filter(models.DeliverableSubmission.auto_completed.isnot(True), models.Project.archived.is_not(True))
    )
    if est_no:
        q = q.filter(models.Project.est_no.ilike(est_no.strip()))
    if item_no:
        q = q.filter(models.DeliverableDefinition.item_no == item_no.strip())
    if progress:
        q = q.filter(models.DeliverableSubmission.status == progress)
    subs = q.all()
    if owner_email:
        oe = owner_email.strip().lower()
        subs = [s for s in subs if oe in {e.strip().lower() for e in rules.resolve_owners(s) if e}]
    if sme_email:
        se = sme_email.strip().lower()
        subs = [s for s in subs if se in {e.strip().lower() for e in rules.resolve_smes(s) if e}]

    # deadline_status() is computed live per submission (never stored), so
    # this filter has to happen in Python after the SQL query, not in it.
    enriched = []
    for s in subs:
        if s.status in (models.SubmissionStatus.PENDING_TRIAGE, models.SubmissionStatus.NOT_REQUIRED):
            key, days = (s.status.value, None)
        else:
            key, days = rules.deadline_status(s)
        enriched.append((s, key, days))
    if deadline:
        enriched = [e for e in enriched if e[1] == deadline]
    if not enriched:
        return "No matching deliverables found -- double check the Est-No/item number, or try broader filters."

    enriched.sort(key=lambda e: (e[0].due_date is None, e[0].due_date or date.max))
    truncated = len(enriched) > 30
    lines = []
    for s, key, days in enriched[:30]:
        if key == "due" and days is not None:
            deadline_txt = f"due, {abs(days)} day(s) overdue"
        elif key == "late" and days is not None:
            deadline_txt = f"late, completed {abs(days)} day(s) after due"
        elif key == "early" and days is not None:
            deadline_txt = f"completed {days} day(s) early"
        else:
            deadline_txt = key.replace("_", " ")
        # [PO Lifecycle]: a fan-out item_no (e.g. 3.3 on an L1 project) has
        # one submission PER NAMED PO LINE ITEM (Towers, line hardwares,
        # ...), each with its own independently-computed due date -- omit
        # this and every row looks identical/contradictory ("3.3 is due
        # both 3 Sep AND 14 Sep?"). Naming which line item each row is for
        # is what actually answers a "why does X have two different due
        # dates" question.
        line_item = rules.line_item_display_name(s.po_line_item) if s.po_line_item_id else None
        line_item_txt = f", PO line item: \"{line_item}\"" if line_item else ""
        lines.append(
            f"- {s.definition.item_no} \"{rules.display_name(s.definition, s.project)}\"{line_item_txt} "
            f"({s.project.est_no} {s.project.name}, {s.project.stage.value}) -- "
            f"progress: {s.status.value}, deadline: {deadline_txt}, due date: {s.due_date or 'n/a'}, "
            f"owner: {', '.join(rules.resolve_owners(s)) or 'unassigned'}, "
            f"SME: {', '.join(rules.resolve_smes(s)) or 'unassigned'}"
        )
    if truncated:
        lines.append(f"...and {len(enriched) - 30} more matches not shown -- narrow the search (est_no, item_no, owner/sme email, progress, or deadline).")
    return "\n".join(lines)


def _tool_list_departments(db: Session) -> str:
    # .is_not(False), not != False -- NULL (pre-migration rows, most
    # departments) fails a plain != comparison in SQL and gets silently
    # excluded; NULL counts as active everywhere else in this app (see
    # departments.py's own list endpoint) and must here too.
    depts = db.query(models.Department).filter(models.Department.active.is_not(False)).order_by(models.Department.number).all()
    return "\n".join(
        # Some international departments already spell it out in their own
        # name (e.g. "Tendering Department (International)"); only append
        # the tag when the name doesn't already say so, to avoid "(International) (International)".
        f"- {d.number}. {d.name}" + (" (International)" if d.is_international and "international" not in d.name.lower() else "")
        for d in depts
    )


def _tool_get_bid_value(db: Session, actor_role: str, actor_email: str, est_no: str = "") -> str:
    # actor_role/actor_email are bound from the real request (payload), NOT
    # a tool-input argument the model could set -- otherwise a user could
    # just ask the AI to "check as someone else" and bypass the real gate.
    if not est_no:
        return "est_no is required."
    project = db.query(models.Project).filter(models.Project.est_no.ilike(est_no.strip())).first()
    if not project:
        return "No project found with that Est-No."
    can_view = rules.can_act(actor_role, actor_email, project.bid_manager) or _can_view_bid_value(db, project, actor_role, actor_email)
    if not can_view:
        return (
            f"You don't currently have access to {project.est_no}'s bid value -- it's restricted to the bid "
            "manager and anyone an Admin has specifically approved. Request access from that project's page."
        )
    if project.bid_value is None:
        return f"{project.est_no} doesn't have a bid value recorded yet."
    return f"{project.est_no}'s bid value: {project.bid_value}"


def _tool_get_performance_summary(db: Session, department: str = "") -> str:
    # Reuses the real Performance page's own endpoint function directly
    # (not re-derived) -- guarantees this can never drift from what the
    # actual page shows, at the cost of the same per-call weight that page
    # already pays (recomputes due dates for every active project).
    from .dashboard import get_performance
    data = get_performance(db)
    depts = data["departments"]
    if department:
        dl = department.strip().lower()
        depts = [d for d in depts if dl in d["name"].lower()]
    if not depts:
        return "No matching department found."
    depts = sorted(depts, key=lambda d: ((d["l1"]["percentage"] or 0) + (d["l0"]["percentage"] or 0)) / 2, reverse=True)
    truncated = len(depts) > 20
    lines = []
    for d in depts[:20]:
        l0 = f"{d['l0']['percentage']}%" if d["l0"]["percentage"] is not None else "n/a (nothing due)"
        l1 = f"{d['l1']['percentage']}%" if d["l1"]["percentage"] is not None else "n/a (nothing due)"
        lines.append(f"- {d['number']}. {d['name']}: L0 {l0}, L1 {l1}")
    if truncated:
        lines.append(f"...and {len(depts) - 20} more not shown -- filter by department name.")
    return "\n".join(lines)


def _tool_list_announcements(db: Session, actor_role: str, actor_email: str, category: str = "news", stage: str = "") -> str:
    from .announcements_router import list_announcements
    items = list_announcements(
        limit=30, actor_role=actor_role, actor_email=actor_email,
        mine=False, stage=stage or None, category=category or "news", db=db,
    )
    if not items:
        return "No matching announcements/reminders found."
    lines = []
    for a in items[:30]:
        # Bodies are HTML email templates (titles carry stray entities like
        # &#8211; too) -- strip tags and decode entities so a reply reads
        # as plain text, not raw markup.
        title = html.unescape(a.title or "")
        body = html.unescape(re.sub(r"<[^>]+>", " ", a.body or ""))
        body = re.sub(r"\s+", " ", body).strip()
        if len(body) > 150:
            body = body[:150] + "..."
        when = a.created_at.date().isoformat() if a.created_at else "n/a"
        lines.append(f"- [{a.type.value}] {title} -- {body} ({when})")
    return "\n".join(lines)


def _tool_list_my_requests(db: Session, email: str) -> str:
    email = (email or "").strip().lower()
    if not email:
        return "No email given -- can't look up personal requests."
    from .deliverables import list_due_date_requests, list_reassignment_requests
    from .deliverables_config import list_formula_change_requests
    from .departments import list_sme_nominations, list_user_add_requests
    from .projects import list_bid_value_requests

    sections = []

    def add(label: str, rows: list, desc_fn) -> None:
        if not rows:
            return
        sections.append(f"{label} ({len(rows)}):")
        for r in rows[:10]:
            when = r.get("requested_at")
            sections.append(f"  - {desc_fn(r)} -- status: {r.get('status')}, requested: {when.date().isoformat() if when else 'n/a'}")

    add("Due-Date Requests", list_due_date_requests(status="", requested_by_email=email, db=db),
        lambda r: f"{r.get('kind')} on {r.get('item_no')} ({r.get('est_no')})")
    add("Reassignment Requests", list_reassignment_requests(status="", requested_by_email=email, db=db),
        lambda r: f"{r.get('item_no')} on {r.get('est_no')} -> {r.get('to_email')}")
    add("SME Nominations", list_sme_nominations(status=None, requested_by_email=email, db=db),
        lambda r: f"{r.get('item_no')} \"{r.get('item_name')}\" ({r.get('department')})")
    add("Bid Value Access Requests", list_bid_value_requests(status="", requested_by_email=email, db=db),
        lambda r: f"{r.get('est_no')} \"{r.get('name')}\"")
    add("Group Add Requests", list_user_add_requests(status="", requested_by_email=email, db=db),
        lambda r: f"{r.get('email')} ({r.get('role')})")
    add("Formula Change Requests", list_formula_change_requests(status="", requested_by_email=email, db=db),
        lambda r: f"{r.get('item_no')} \"{r.get('item_name')}\"")

    if not sections:
        return "No requests found for this email, across any of the six request types."
    return "\n".join(sections)


def _tool_get_bm_triage_status(db: Session, bid_manager_email: str = "") -> str:
    from .projects import get_bm_triage_status
    # Always call as Admin (sees every tender) and narrow here instead of
    # using the endpoint's own non-Admin scoping -- that path 403s on a
    # blank email, and this tool's whole point is looking things up for
    # ANYONE, not just whoever's asking.
    rows = get_bm_triage_status(actor_role="Admin", actor_email="", db=db)
    if bid_manager_email:
        rows = [r for r in rows if (r.get("bid_manager") or "").strip().lower() == bid_manager_email.strip().lower()]
    if not rows:
        return "No matching tenders found."
    truncated = len(rows) > 20
    lines = [
        f"- {r['est_no']} \"{r['name']}\" -- {r['status']}, {r['pending_count']} of {r['total_count']} items still pending triage, bid manager: {r.get('bid_manager') or 'n/a'}"
        for r in rows[:20]
    ]
    if truncated:
        lines.append(f"...and {len(rows) - 20} more not shown -- filter by bid_manager_email.")
    return "\n".join(lines)


def _run_tool(db: Session, name: str, tool_input: dict, actor_role: str, actor_email: str) -> str:
    if name == "lookup_deliverables":
        return _tool_lookup_deliverables(db, **{k: tool_input.get(k, "") for k in ("stage", "item_no", "query", "department")})
    if name == "search_projects":
        return _tool_search_projects(db, **{k: tool_input.get(k, "") for k in ("stage", "query", "status")})
    if name == "lookup_project_deliverables":
        return _tool_lookup_project_deliverables(db, **{k: tool_input.get(k, "") for k in ("est_no", "item_no", "owner_email", "sme_email", "progress", "deadline")})
    if name == "list_departments":
        return _tool_list_departments(db)
    if name == "get_bid_value":
        return _tool_get_bid_value(db, actor_role, actor_email, tool_input.get("est_no", ""))
    if name == "get_performance_summary":
        return _tool_get_performance_summary(db, tool_input.get("department", ""))
    if name == "list_announcements":
        return _tool_list_announcements(db, actor_role, actor_email, tool_input.get("category", "news"), tool_input.get("stage", ""))
    if name == "list_my_requests":
        return _tool_list_my_requests(db, tool_input.get("email", ""))
    if name == "get_bm_triage_status":
        return _tool_get_bm_triage_status(db, tool_input.get("bid_manager_email", ""))
    return f"Unknown tool: {name}"


_DAILY_LIMIT = 5


def _usage_key(email: str) -> str:
    return (email or "").strip().lower() or "(anonymous)"


def _get_usage_row(db: Session, email: str, today: date, create: bool) -> "models.AiChatUsage | None":
    key = _usage_key(email)
    row = db.query(models.AiChatUsage).filter_by(email=key, usage_date=today).first()
    if not row and create:
        row = models.AiChatUsage(email=key, usage_date=today, count=0)
        db.add(row)
        db.flush()
    return row


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    actor_email: str = ""
    actor_role: str = "Viewer"


@router.get("/usage")
def get_usage(actor_email: str = "", db: Session = Depends(get_db)):
    row = _get_usage_row(db, actor_email, date.today(), create=False)
    used = row.count if row else 0
    return {"used": used, "limit": _DAILY_LIMIT, "remaining": max(0, _DAILY_LIMIT - used)}


@router.post("/chat")
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "AI Support isn't configured yet -- ask an Admin to set ANTHROPIC_API_KEY.")
    message = payload.message.strip()
    if not message:
        raise HTTPException(400, "Message is required")

    # Checked (and only actually incremented on a successful reply, further
    # down) before spending anything on the Anthropic call itself -- the
    # whole point is capping API cost, so an already-exhausted user should
    # never trigger a real request.
    usage = _get_usage_row(db, payload.actor_email, date.today(), create=True)
    if usage.count >= _DAILY_LIMIT:
        raise HTTPException(429, f"You've used all {_DAILY_LIMIT} AI Support messages for today -- try again tomorrow, or use Ask the Team.")

    who = f"role: {payload.actor_role or 'Viewer'}" + (f", email: {payload.actor_email}" if payload.actor_email else " (no email given -- ask them to set an acting email first for anything personal)")
    system = _SYSTEM_PROMPT + f"\n\n---\n\nThe person you're talking to is acting as {who}."

    # Lazy import, same convention as httpx in providers/mail.py and
    # providers/storage.py -- keeps this an optional dependency at import
    # time, only actually needed once a real chat request comes in.
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    # Capped client-side too (see app.js), but never trust that alone.
    history = [{"role": m.role, "content": m.content} for m in payload.history[-10:] if m.role in ("user", "assistant")]
    history.append({"role": "user", "content": message})
    try:
        # Tool-use loop: Claude can call any of the live-data tools above
        # instead of guessing (see _SYSTEM_PROMPT's "Live lookups" section)
        # -- capped at a few round-trips so a confused model can't loop
        # forever racking up API calls (e.g. search_projects then
        # lookup_project_deliverables is a normal 2-hop question).
        for _ in range(5):
            resp = client.messages.create(model=_MODEL, max_tokens=1024, system=system, messages=history, tools=_TOOLS)
            if resp.stop_reason != "tool_use":
                break
            history.append({"role": "assistant", "content": resp.content})
            tool_results = [
                {"type": "tool_result", "tool_use_id": block.id,
                 "content": _run_tool(db, block.name, block.input, payload.actor_role, payload.actor_email)}
                for block in resp.content if block.type == "tool_use"
            ]
            history.append({"role": "user", "content": tool_results})
        reply = "".join(block.text for block in resp.content if block.type == "text").strip()
    except Exception as e:
        print(f"[ai-support] Anthropic call failed: {e}")
        raise HTTPException(502, "AI Support is temporarily unavailable -- try Ask the Team instead.")

    # Only counted once we actually have a reply -- a failed call above
    # already exits via the except block before reaching here, so it never
    # costs the user one of their daily messages.
    usage.count += 1
    db.commit()
    return {
        "reply": reply or "I don't have a good answer for that -- try Ask the Team instead.",
        "remaining": max(0, _DAILY_LIMIT - usage.count), "limit": _DAILY_LIMIT,
    }

"""AI Support -- a Claude-powered chat assistant for general platform
questions, with enough knowledge of the asking user's own assigned
deliverables (Owner/SME scoped, resolved the same way Assigned Deliverables
does -- see deliverables.py's list_all_deliverables) to answer personal
questions too ("what's due for me this week?"). Same trust model as every
other actor_email/actor_role field in this app: self-reported, no real
login exists in this pilot (see support.py's own docstring) -- an AI
question is read-only, so that's an acceptable ceiling here same as
everywhere else.

Stateless on the backend by design: the frontend keeps the conversation
array and resends it every turn (capped client-side), rather than adding a
new DB table just to store chat transcripts nobody has asked to keep.

Falls back to suggesting Ask the Team (support.py) for anything it can't
confidently answer or that needs a human decision -- the system prompt
says so explicitly, and the frontend also keeps a permanent "Ask the Team"
button next to the chat regardless of what the AI says.
"""
import os
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, rules
from ..database import get_db
from .deliverables_config import _normalized_weight_pct

router = APIRouter(prefix="/api/ai-support", tags=["ai-support"])

_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_PROMPT = """You are the AI Support assistant embedded in the Project Readiness (L0/L1) Platform, an internal tool Algihaz Contracting uses to track tendering and early project deliverables. Answer questions about how the platform works and, when given the asker's own assigned-deliverables list below, about their own work. Be concise -- a few sentences or a short list, not an essay.

## What L0 and L1 mean
- L0 = a Tender: the bidding/proposal stage, before a project is won.
- L1 = a Project: the execution stage, after a tender is won and it becomes a real project.
- Every L0 tender and L1 project has its own Est-No (estimate number) and its own catalog of "deliverables" (required items with due dates).
- L0 also has an "International" variant (a separate catalog of items for international tenders) -- L1 does not, every L1 project uses the one domestic catalog.

## Roles
- Admin: full access -- can configure deliverables, decide requests, manage departments, see everything.
- Owner: the person responsible for actually completing/uploading a deliverable.
- SME (Subject Matter Expert): reviews and approves/rejects an Owner's submission for specific deliverables.
- Viewer: read-only access, no assigned work.
One person can be Owner on some items and SME on others, even within the same project.

## Deliverables and due dates
- Each deliverable ("item", e.g. "1.3 Announce the site visit date") has a formula-driven due date -- computed relative to an anchor like the tender announcement date (M1), the Bid Submission Date (BSD), the site visit date, or another item's own due date (a predecessor).
- Submission statuses: Not Due, Due (Not Submitted), Pending SME Review, Approved (Completed), Rejected.
- A deliverable can be a "milestone" (a named checkpoint like M3), which other items can anchor their own due dates to.

## Scoring (Performance %)
- Every submitted item earns points: 1.1 if submitted early, 1.0 if on time (within a 4-day grace period), then a shrinking bonus the later it is (0.9 at 1-7 days late, 0.8 at 8-14, 0.7 at 15-21, 0.6 at 22-28, 0 beyond that or if never submitted).
- Each department's overall Performance % is a weighted average across its own catalog items -- every item counts equally by default, but an Admin can give one item more "Scoring Weight" than its siblings (e.g. weighting a BOQ higher than a minor checklist item) via Deliverables Configuration. A non-admin can *suggest* a weight or formula change from Deliverables Catalog ("Suggest a Change"), which an Admin then reviews and approves or rejects.
- Performance % is capped at 100%; a department can't exceed fully-on-track even with lots of early-submission bonus points.
- Performance, Top Achievers (best Owners/SMEs), and Reports all read from this same scoring engine.

## PO Lifecycle and budget (L1 projects only)
- Every L1 project tracks Purchase Order line items through categories: Consultancy PO, Early activities & MEP consultancies POs, Long lead items POs, and S/C (subcontractor) agreements.
- Budget status is tracked as three stages per project: 6.1 Temp Budget, 6.2 Tendering Budget, 6.3 Locked Budget -- shown as a 3-segment status bar on the Budget Status Report.

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
Workspace (everyone): Dashboard, L0 Tenders, L1 Projects, Timeline (Gantt), Assigned Deliverables (your own work), Announcements, Reminders, BM Triage Status, Performance, Deliverables Catalog (browse formulas/weights, suggest changes), My Requests, Q/A - Ask the Team, AI Support (this chat).
Admin only: Create L0/L1, Reports (Performance/Master PO/Overview PO/Budget Status reports), Top Achievers, Focal Points, Deliverables Configuration (edit formulas/weights directly), Requests (decide the six queues above), Follow Up (overdue deliverables + bulk reminders), Open Questions (Q/A inbox), Archived Projects.

## Live lookups
You have two tools for real, current data -- use them instead of guessing whenever a question is about a *specific* item or department, not just how the system works in general:
- lookup_deliverables: the real due-date formula, scoring weight, and department for a specific item number (e.g. "what's the formula for 2.2 in L1?"), or to search/browse by name or department.
- list_departments: the real current list of departments (name, number, whether it's an international variant).
Both mirror exactly what Deliverables Catalog and the department pickers already show any user -- general reference data, not anyone's private information.

## What you should NOT do
- Don't make up specific facts about a particular project, deliverable, or person -- use the tools above for anything about deliverables/departments, and the "their own assigned deliverables" data below for anything personal. If neither covers it, say you don't have that.
- Don't give an opinion on a judgment call that's really an Admin's decision to make (e.g. "should my due-date extension be approved?").
- If you're not confident you've actually answered the question, say so plainly and suggest they use Q/A - Ask the Team to reach an Admin/team member directly.
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
        "name": "list_departments",
        "description": "List the platform's real current departments -- name, number, and whether it's an international variant. Same data as the department pickers throughout the app.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _my_deliverables_summary(db: Session, email: str) -> str:
    email = (email or "").strip().lower()
    if not email:
        return "(No email provided for this conversation -- can't look up personal assignments.)"
    subs = (
        db.query(models.DeliverableSubmission)
        .join(models.DeliverableDefinition)
        .join(models.Project)
        .filter(models.DeliverableSubmission.auto_completed.isnot(True), models.Project.archived.is_not(True))
        .all()
    )
    mine = []
    for s in subs:
        owners = {e.strip().lower() for e in rules.resolve_owners(s) if e}
        smes = {e.strip().lower() for e in rules.resolve_smes(s) if e}
        if email not in owners and email not in smes:
            continue
        mine.append((s, "Owner" if email in owners else "SME"))
    if not mine:
        return "(This user has no assigned deliverables right now.)"
    # Soonest-due (and undated) items lead -- those are what a support
    # question is almost always actually about; a long tail of far-future
    # not-due items would just burn tokens without helping.
    mine.sort(key=lambda pair: (pair[0].due_date is None, pair[0].due_date or date.max))
    lines = []
    for s, role in mine[:25]:
        lines.append(
            f"- {s.definition.item_no} \"{rules.display_name(s.definition, s.project)}\" "
            f"({s.project.est_no} {s.project.name}, {s.project.stage.value}) -- "
            f"role: {role}, status: {s.status.value}, due: {s.due_date or 'n/a'}"
        )
    if len(mine) > 25:
        lines.append(f"...and {len(mine) - 25} more.")
    return "\n".join(lines)


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


def _run_tool(db: Session, name: str, tool_input: dict) -> str:
    if name == "lookup_deliverables":
        return _tool_lookup_deliverables(db, **{k: tool_input.get(k, "") for k in ("stage", "item_no", "query", "department")})
    if name == "list_departments":
        return _tool_list_departments(db)
    return f"Unknown tool: {name}"


_DAILY_LIMIT = 10


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

    who = f"role: {payload.actor_role or 'Viewer'}" + (f", email: {payload.actor_email}" if payload.actor_email else "")
    system = (
        _SYSTEM_PROMPT
        + f"\n\n---\n\nThe person you're talking to is acting as {who}.\n\n"
        + "Their own assigned deliverables (Owner or SME) right now:\n"
        + _my_deliverables_summary(db, payload.actor_email)
    )

    # Lazy import, same convention as httpx in providers/mail.py and
    # providers/storage.py -- keeps this an optional dependency at import
    # time, only actually needed once a real chat request comes in.
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    # Capped client-side too (see app.js), but never trust that alone.
    history = [{"role": m.role, "content": m.content} for m in payload.history[-10:] if m.role in ("user", "assistant")]
    history.append({"role": "user", "content": message})
    try:
        # Tool-use loop: Claude can call lookup_deliverables/list_departments
        # for real current data instead of guessing (see _SYSTEM_PROMPT's
        # "Live lookups" section) -- capped at a few round-trips so a
        # confused model can't loop forever racking up API calls.
        for _ in range(4):
            resp = client.messages.create(model=_MODEL, max_tokens=800, system=system, messages=history, tools=_TOOLS)
            if resp.stop_reason != "tool_use":
                break
            history.append({"role": "assistant", "content": resp.content})
            tool_results = [
                {"type": "tool_result", "tool_use_id": block.id, "content": _run_tool(db, block.name, block.input)}
                for block in resp.content if block.type == "tool_use"
            ]
            history.append({"role": "user", "content": tool_results})
        reply = "".join(block.text for block in resp.content if block.type == "text").strip()
    except Exception as e:
        print(f"[ai-support] Anthropic call failed: {e}")
        raise HTTPException(502, "AI Support is temporarily unavailable -- try Ask the Team instead.")

    # Only counted once we actually have a reply -- a failed call above
    # already exits via the except block before reaching here, so it never
    # costs the user one of their 10.
    usage.count += 1
    db.commit()
    return {
        "reply": reply or "I don't have a good answer for that -- try Ask the Team instead.",
        "remaining": max(0, _DAILY_LIMIT - usage.count), "limit": _DAILY_LIMIT,
    }

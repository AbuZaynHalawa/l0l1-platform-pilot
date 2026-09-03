"""Seeds departments and the FULL real deliverable catalogs, transcribed
directly from L0 Template (Final).xlsx (column O formulas) and New L1
Template (Final).xlsx / L1 Template (Tracking Sheet) (columns B/C/F/I, with
due dates from K/L). Every item, not a sample.

Focal point / owner / SME emails below are PLACEHOLDERS — swap for the real
per-department contacts and the real per-deliverable owner/SME mapping when
provided, then re-run: `python -m backend.seed` (safe to re-run, upserts).
"""
from sqlalchemy import inspect, text
from .database import SessionLocal, engine, ensure_column, ensure_enum_value, ensure_index, ensure_not_unique
from . import models, rules

ensure_column("deliverable_definitions", "short_name", "VARCHAR")
ensure_column("departments", "number", "INTEGER")
ensure_column("projects", "business_units", "JSON")
ensure_column("announcements", "submission_id", "INTEGER")
ensure_column("deliverable_submissions", "applicability", "VARCHAR")
ensure_column("projects", "due_dates_computed_on", "DATE")
ensure_column("deliverable_definitions", "focal_point_name", "VARCHAR")
ensure_column("deliverable_definitions", "focal_point_email", "VARCHAR")
ensure_column("projects", "last_triage_reminder_at", "TIMESTAMP")
ensure_column("users", "manager_email", "VARCHAR")
ensure_column("projects", "pre_bid_meeting_date", "DATE")
ensure_column("deliverable_definitions", "kpi_relevant", "BOOLEAN")
ensure_column("deliverable_definitions", "kpi_weight", "FLOAT")
ensure_column("formula_change_requests", "proposed_weight", "FLOAT")
ensure_column("deliverable_definition_change_log", "reverted", "BOOLEAN")
ensure_column("department_change_log", "reverted", "BOOLEAN")
ensure_column("kb_entries", "est_no", "VARCHAR")
ensure_column("kb_entries", "deliverable", "VARCHAR")
ensure_column("po_line_items", "po_number", "VARCHAR")
ensure_enum_value("deliverable_submissions", "status", "PENDING_TRIAGE")
ensure_enum_value("deliverable_submissions", "status", "NOT_REQUIRED")
ensure_enum_value("deliverable_submissions", "status", "PENDING_COMPLETION")
ensure_enum_value("deliverable_submissions", "status", "NO_PROGRESS")
ensure_enum_value("deliverable_submissions", "status", "IN_PROGRESS")
ensure_column("deliverable_submissions", "auto_completed", "BOOLEAN")
ensure_column("support_requests", "target_email", "VARCHAR")
ensure_column("support_messages", "kb_reference_id", "INTEGER")
ensure_enum_value("announcements", "type", "MILESTONE")
ensure_enum_value("announcements", "type", "BSD_EXTENDED")
ensure_enum_value("announcements", "type", "DOC_ADDED")
ensure_enum_value("announcements", "type", "DELIVERABLE_APPROVED")
ensure_not_unique("projects", "est_no")

# [Deliverables Configuration]
ensure_column("deliverable_definitions", "is_customized", "BOOLEAN")
ensure_column("deliverable_definitions", "seed_key", "VARCHAR")
ensure_column("departments", "active", "BOOLEAN")
ensure_enum_value("announcements", "type", "FORMULA_CHANGE_DECISION")

# [Archive]
ensure_column("projects", "archived", "BOOLEAN")
# ensure_column's ALTER TABLE gives every already-existing row NULL, not
# False -- fine for the query filters above (.is_not(True) treats NULL as
# "not archived" the same NULL-safe way Department.active does), but
# ProjectOut.archived is a strict `bool` field, so serializing an old row's
# raw None through it 500s. One-time (idempotent) backfill closes that gap.
# Same brand-new-database guard as ensure_column itself -- a fresh deploy's
# very first run gets here before create_all() below has even made the
# table yet, so this only applies on a database that already had projects.
if inspect(engine).has_table("projects"):
    with engine.connect() as _archive_backfill_conn:
        _archive_backfill_conn.execute(text("UPDATE projects SET archived = FALSE WHERE archived IS NULL"))
        _archive_backfill_conn.commit()

# Load-bearing indexes: every one of these columns is filtered or joined on
# in the hot paths (dashboard, matrix, gantt, assigned deliverables), and
# Postgres doesn't auto-index foreign keys the way MySQL does — without
# these, those queries do full table scans as project/submission counts grow.
ensure_index("deliverable_submissions", "ix_subs_project_id", "project_id")
ensure_index("deliverable_submissions", "ix_subs_definition_id", "deliverable_definition_id")
ensure_index("deliverable_submissions", "ix_subs_status", "status")
ensure_index("deliverable_definitions", "ix_defs_department_id", "department_id")
ensure_index("deliverable_definitions", "ix_defs_stage", "stage")
ensure_index("deliverable_definitions", "ix_defs_item_no", "item_no")
ensure_index("projects", "ix_projects_status", "status")
ensure_index("projects", "ix_projects_stage", "stage")
ensure_index("announcements", "ix_announcements_created_at", "created_at")
ensure_index("announcements", "ix_announcements_project_id", "project_id")
ensure_index("workflow_history", "ix_history_submission_id", "submission_id")
ensure_index("documents", "ix_documents_submission_id", "submission_id")
ensure_index("followers", "ix_followers_submission_id", "submission_id")
ensure_index("reassignment_requests", "ix_reassign_submission_id", "submission_id")
ensure_index("performance_snapshots", "ix_perf_snap_dept_stage_month", "department_id, stage, month")
ensure_column("deliverable_definitions", "focal_point_emails", "JSON")
ensure_column("deliverable_definitions", "default_sme_emails", "JSON")
ensure_column("deliverable_submissions", "sme_emails", "JSON")
ensure_column("deliverable_submissions", "reviewed_by_email", "VARCHAR")
ensure_column("deliverable_definitions", "default_owner_emails", "JSON")
ensure_column("deliverable_submissions", "owner_emails", "JSON")

# Due-date extension/hold requests (item [due-date requests]).
ensure_column("deliverable_submissions", "on_hold", "BOOLEAN")
ensure_column("deliverable_submissions", "on_hold_since", "TIMESTAMP")
ensure_column("deliverable_submissions", "hold_reason", "TEXT")
ensure_column("deliverable_submissions", "due_date_locked", "BOOLEAN")
ensure_enum_value("announcements", "type", "EXTENSION_REQUEST")
ensure_enum_value("announcements", "type", "EXTENSION_DECISION")
ensure_enum_value("announcements", "type", "HOLD_REQUEST")
ensure_enum_value("announcements", "type", "HOLD_DECISION")
ensure_enum_value("announcements", "type", "REASSIGNMENT_DECISION")
ensure_enum_value("announcements", "type", "SME_NOMINATION_DECISION")
# Nightly checks (item [due-soon nudge] / [request escalation]).
ensure_column("deliverable_submissions", "due_soon_reminded_for_date", "DATE")
ensure_column("deliverable_submissions", "due_soon_reminded_offsets", "JSON")
# [tight-BSD duration ratio]
ensure_column("projects", "duration_ratio", "FLOAT")
ensure_column("projects", "duration_ratio_insufficient", "BOOLEAN")

# [PO Lifecycle]
ensure_column("deliverable_submissions", "po_line_item_id", "INTEGER")
ensure_column("deliverable_definitions", "line_item_category", "VARCHAR")
# [PO Lifecycle correction]: registry now sources from the declaring item's
# own submission (1.2/4.1/2.11/2.17), not a dedicated tab UI.
ensure_column("deliverable_submissions", "po_selection", "JSON")
ensure_column("po_line_items", "source_submission_id", "INTEGER")

# [L0 International]
ensure_column("projects", "is_international", "BOOLEAN")
ensure_column("projects", "country", "VARCHAR")
ensure_column("departments", "is_international", "BOOLEAN")

# [Bid Value]
ensure_column("projects", "bid_value", "FLOAT")
ensure_enum_value("announcements", "type", "BID_VALUE_ACCESS_DECISION")

# [SME nominations, per-item rework]: sme_nominations shipped with a
# single-blanket-request shape (email/name/reason, one row per submission
# click) days ago with zero real usage, then got reworked into one row per
# (email, deliverable_definition_id) so an admin approves/rejects each
# picked item individually. create_all() only creates missing tables, never
# alters an existing one's columns -- with nothing real in it yet, dropping
# and letting create_all() below rebuild it from the current model is
# simpler and safer than hand-writing an ALTER TABLE for a column rename
# that never had real data to preserve.
_inspector = inspect(engine)
if _inspector.has_table("sme_nominations"):
    _existing_cols = {c["name"] for c in _inspector.get_columns("sme_nominations")}
    if "deliverable_definition_id" not in _existing_cols:
        with engine.connect() as _conn:
            _conn.execute(text("DROP TABLE sme_nominations"))
            _conn.commit()

models.Base.metadata.create_all(bind=engine)

# due_date_requests is a brand-new table -- create_all above just made it,
# so its index can only be added after that point (unlike the
# reassignment_requests index above, which predates this table's existence).
ensure_index("due_date_requests", "ix_due_date_requests_submission_id", "submission_id")
ensure_index("sme_nominations", "ix_sme_nominations_definition_id", "deliverable_definition_id")
ensure_index("bid_value_access_requests", "ix_bid_value_access_requests_project_id", "project_id")
ensure_column("due_date_requests", "escalated_at", "TIMESTAMP")
ensure_column("tender_documents", "folder_path", "VARCHAR")
# deliverable_formula_branches is a brand-new table -- same reasoning as
# due_date_requests' own index above, only addable after create_all().
ensure_index("deliverable_formula_branches", "ix_branches_definition_id", "deliverable_definition_id")

TEST_EMAIL = "test-focal@example.com"  # single placeholder until real contacts are provided

# ---------------------------------------------------------------------------
# Departments — L0 and L1 use genuinely different department breakdowns in
# the real templates (not just renamed, e.g. L1 splits Operation into
# TBU/PBU/BBU, Control into Planning/Cost Control, Finance into
# Treasury/Finance/Insurance, SHEQ into Quality/HSSE). Kept as separate rows
# to match the source, not forced into one unified list.
# ---------------------------------------------------------------------------
DEPARTMENTS = [
    # L0 (12) — named exactly as in the source template's own Department
    # column, no invented numbering. Tendering/Supply Chain/Engineering/HR/
    # Contract are genuinely shared with L1 (same department, same folder,
    # same focal point across both stages) — only listed once here; L1_DEPT
    # below just points its own dept_key at these same names.
    "Tendering Department", "Supply Chain", "Engineering Department",
    "Contract", "Human Resources", "IT Department",
    # [PBU scope routing]: Engineering and Supply Chain each get a second,
    # PBU-focal variant -- own copy of that department's items, gated by
    # scope (OHTL for Engineering; OHTL or UGC for Supply Chain/Procurement)
    # instead of business_units, via rules.is_scope_variant_applicable. Both
    # a variant and its original can be active on the same project at once
    # (mixed scope), same as the Operation Units BU split below.
    "Procurement (PBU)", "Engineering (PBU)",
    # Items 127/141: "Financial Department" and "SHEQ Department" no longer
    # get created here -- each has been split across the shared
    # Treasury/Finance and Quality/HSSE departments below by the migration
    # in run(), same pattern as "Control Department" and "Fleet and
    # Facility Management Department" before them.
    # Items 128/129: "Control Department", "Risk Department" and "Fleet and
    # Facility Management Department" no longer get created here -- each has
    # been folded into (or split across) the shared Planning/Cost Control,
    # Risk, and Fleet/FM departments below by the migration in run(), so
    # they'd otherwise just come back empty on every seed run.
    # Operation Units BU sub-folders (item 69) — the old flat "Operation
    # Units" department (pre-split, items 2.1-2.6) no longer gets created
    # here either, same reasoning as the removals above: confirmed zero
    # submissions left pointing at it (Yasser's request), so it'd otherwise
    # just come back empty on every seed run. Every L0 project instead gets
    # one of these four, matching whichever business unit(s) the project's
    # scope actually selected.
    "Operation Units (TBU)", "Operation Units (PBU)", "Operation Units (DBU)", "Operation Units (BBU)",
    # L1-only (additional real breakdown, no "L1 " prefix)
    # Items 123/124/126: Insurance and HSSE / Quality no longer get created
    # here -- their one deliverable each has been re-pointed onto Finance
    # and HSSE/Quality respectively by the migration in run() below, so
    # they'd otherwise just come back empty on every seed run.
    # Items 128/129: Planning, Cost Control, Risk, Fleet, FM are no longer
    # L1-only -- L0 now shares these same rows (see L0_DEPT below), same
    # pattern as Tendering/Supply Chain/Engineering/HR/Contract already use.
    "Planning", "Cost Control",
    "Treasury", "Finance", "Quality", "HSSE",
    "Risk", "Fleet", "FM",
    # Item 122 rework: L1's own TBU/PBU/DBU/BBU split reuses the exact same
    # "Operation Units (TBU)" etc. rows L0's item 69 split already created
    # (see L0_DEPT/L1_DEPT below) -- so it nests under the same "2.
    # Operation Units" group header in the folder list, instead of showing
    # as its own separate ungrouped set of rows. The old combined "TBU /
    # PBU" and "BBU / PBU" buckets this superseded are gone entirely now
    # (were carried here for a while for existing-project compatibility;
    # removed once every submission still on them was confirmed at zero
    # progress -- see the one-time cleanup in run() below).
]

# [L0 International]: every department L0_INTERNATIONAL_DEPT names, flagged
# is_international=True below in run() -- own rows, never shared with a
# standard-L0/L1 department (see L0_INTERNATIONAL_ITEMS's own comment for why).
INTERNATIONAL_DEPARTMENTS = [
    "Tendering Department (International)", "Operation Units (International)",
    "Supply Chain (International)", "Engineering Department (International)",
    "Planning (International)", "Cost Control (International)",
    "Contract (International)", "Human Resources (International)",
    "Treasury (International)", "Finance (International)",
    "Quality (International)", "HSSE (International)",
    "IT Department (International)", "Risk (International)",
    "Fleet (International)", "FM (International)", "Legal (International)",
    "International Business Development", "Document & Data Governance",
]
DEPARTMENTS = DEPARTMENTS + INTERNATIONAL_DEPARTMENTS

# Renames existing production department rows in place (preserving id and
# every deliverable_definition/submission already linked to them) — a plain
# name change in DEPARTMENTS above only affects newly-created rows.
DEPARTMENT_RENAMES = {
    "01. Tendering Department": "Tendering Department", "02. Operation Units": "Operation Units",
    "03. Supply Chain": "Supply Chain", "04. Engineering Department": "Engineering Department",
    "05. Control Department": "Control Department", "07. Human Resources": "Human Resources",
    "08. Financial Department": "Financial Department", "09. SHEQ Department": "SHEQ Department",
    "10. IT Department": "IT Department", "11. Risk Department": "Risk Department",
    "12. Fleet and Facility Management": "Fleet and Facility Management Department",
    "L1 TBU / PBU": "TBU / PBU", "L1 BBU": "BBU", "L1 BBU / PBU": "BBU / PBU",
    "L1 Planning": "Planning", "L1 Cost Control": "Cost Control",
    "L1 Treasury": "Treasury", "L1 Finance": "Finance", "L1 Insurance": "Insurance",
    "L1 Quality": "Quality", "L1 HSSE": "HSSE", "L1 HSSE / Quality": "HSSE / Quality",
    "L1 Risk": "Risk", "L1 Fleet": "Fleet", "L1 FM": "FM",
    # NOT included here: "06. Contract" -> "Contract" and "L1 Contract" -> "Contract"
    # — both need to become the SAME row (merge), handled separately below
    # since a plain rename would collide with whichever one already exists.
}

# The numeric group each department's deliverable item numbers fall under
# (item "4.5" belongs to department number 4) — kept as its own field
# instead of folded into `name`, since several L1 departments share one
# number (Operation's TBU/PBU/BBU split, SHEQ's Quality/HSSE split, etc.)
# and embedding it in the name caused real collision/rename bugs before.
# Item 127: full renumbering. 1-4 unchanged; 5 onward reassigned.
# Cost Control gets its own number, separate from Planning (item 129);
# IT/Risk/Fleet/FM each get their own number instead of accidentally sharing
# one (item 128 splits Fleet/FM for L0 too, and Risk is consolidated into
# one department -- see the merge in run() below).
# Item 127 rework: Treasury/Finance and Quality/HSSE no longer share one
# number each (previously 9 and 10) -- every real department gets its own
# unique number, continuing the sequence. "Financial Department" and "SHEQ
# Department" no longer exist as their own numbered slots -- L0's combined
# versions split across Treasury/Finance and Quality/HSSE by the migration
# in run() below (item 141), same pattern as the Planning/Cost Control and
# Fleet/FM splits already used.
DEPARTMENT_NUMBERS = {
    "Tendering Department": 1,
    "Operation Units": 2, "BBU": 2,
    "Operation Units (TBU)": 2, "Operation Units (PBU)": 2, "Operation Units (DBU)": 2, "Operation Units (BBU)": 2,
    "TBU": 2, "PBU": 2, "DBU": 2,
    "Supply Chain": 3, "Procurement (PBU)": 3,
    "Engineering Department": 4, "Engineering (PBU)": 4,
    "Control Department": 5, "Planning": 5,
    "Cost Control": 6,
    "Contract": 7,
    "Human Resources": 8,
    "Treasury": 9,
    "Finance": 10,
    "Quality": 11,
    "HSSE": 12,
    "IT Department": 13,
    "Risk": 14, "Risk Department": 14,
    "Fleet": 15, "Fleet and Facility Management Department": 15,
    "FM": 16,
    # [L0 International]: own numbering sequence (1-19), independent of the
    # standard L0/L1 numbers above -- these are separate department rows so
    # there's no collision even where a number repeats (e.g. both "Treasury"
    # and "Treasury (International)" are 9, in their own respective names).
    "Tendering Department (International)": 1, "Operation Units (International)": 2,
    "Supply Chain (International)": 3, "Engineering Department (International)": 4,
    "Planning (International)": 5, "Cost Control (International)": 6,
    "Contract (International)": 7, "Human Resources (International)": 8,
    "Treasury (International)": 9, "Finance (International)": 10,
    "Quality (International)": 11, "HSSE (International)": 12,
    "IT Department (International)": 13, "Risk (International)": 14,
    "Fleet (International)": 15, "FM (International)": 16,
    "Legal (International)": 17, "International Business Development": 18,
    "Document & Data Governance": 19,
}

# ---------------------------------------------------------------------------
# L0 catalog — from L0 Template (Final).xlsx, sheet "Deliverables", column O.
# Fields: item_no, name, department, anchor_type, predecessor_item_no,
#         offset_days, offset_direction, deliverable_type, is_milestone, milestone_code
# ---------------------------------------------------------------------------
L0_DEPT = {
    "tendering": "Tendering Department", "operation": "Operation Units", "supply": "Supply Chain",
    "eng": "Engineering Department", "contract": "Contract",
    "hr": "Human Resources",
    # [PBU scope routing]: own copy of Engineering/Supply Chain, gated by
    # scope instead of business_units -- see rules.is_scope_variant_applicable.
    "eng_pbu": "Engineering (PBU)", "supply_pbu": "Procurement (PBU)",
    "it": "IT Department", "risk": "Risk",
    # Items 128/129: L0 now shares the same Planning/Cost Control and
    # Fleet/FM departments L1 already uses, instead of its own combined
    # "Control Department" / "Fleet and Facility Management Department".
    "planning": "Planning", "costctrl": "Cost Control", "fleet": "Fleet", "fm": "FM",
    "op_tbu": "Operation Units (TBU)", "op_pbu": "Operation Units (PBU)",
    "op_dbu": "Operation Units (DBU)", "op_bbu": "Operation Units (BBU)",
    # Item 141: L0's own combined "Financial Department" / "SHEQ Department"
    # split across the same shared Treasury/Finance and Quality/HSSE
    # departments L1 already uses, same pattern as planning/costctrl above.
    "treasury": "Treasury", "finance": "Finance", "quality": "Quality", "hsse": "HSSE",
}

# (item_no, name, dept_key, anchor_type, pred, offset, direction, dtype, milestone_code)
L0_ITEMS = [
    ("1.1", "Receive Approval for GO Approach & Circulate Tender Documents", "tendering", "announcement", None, 0, "after", "date_driven", "M1"),
    ("1.2", "Announce the date of the site visit and circulate instructions covering attendee details, permit requirements, and any other necessary preparations", "tendering", "predecessor", "1.1", 1, "after", "date_driven", None),
    ("1.3", "Announce the date of the Pre-bid/Jobex Meetings and circulate related instructions", "tendering", "predecessor", "1.1", 1, "after", "date_driven", None),
    ("1.4", "Announce the deadlines of the Pre-bid clarifications", "tendering", "predecessor", "1.1", 1, "after", "date_driven", None),
    ("1.5", "Assign BID Manager / Calculation Engineer (focal for all communications)", "tendering", "predecessor", "1.1", 1, "after", "date_driven", None),
    ("1.6", "Request Bid Bond (if applicable)", "tendering", "predecessor", "1.21", 10, "before", "date_driven", None),
    ("1.7", "Develop Estimate Program and circulate with all departments, External consultant, SME's", "tendering", "predecessor", "1.1", 2, "after", "date_driven", None),
    ("1.8", "Float SC RFQ's - Local", "tendering", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("1.9", "Float Materials RFQ's - Local", "tendering", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("1.10", "Float RFQ's - Consultant Services", "tendering", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("1.11", "Review Project Schedule and provide feedback (provided from Planning Department)", "tendering", "predecessor", "5.3", 2, "after", "date_driven", None),
    ("1.12", "Review Project Execution Plan and provide feedback", "tendering", "predecessor", "2.5", 2, "after", "date_driven", None),
    ("1.13", "Prepare Pre-bid agreements such as; handling main material linked to LME Pricing", "tendering", None, None, 0, "after", "on_request", None),
    ("1.14", "Incorporate Consultant findings (if applicable)", "tendering", None, None, 0, "after", "on_request", None),
    ("1.15", "Incorporate SME's findings (if applicable)", "tendering", None, None, 0, "after", "on_request", None),
    ("1.16", "Prepare Manpower & Equipment Schedules", "tendering", "predecessor", "5.3", 1, "after", "date_driven", None),
    ("1.17", "Circulate technical offers & Terms received from Vendors & SC & Consultant to Engineering", "tendering", "predecessor", "1.9", 10, "after", "date_driven", "M4"),
    # Item [request 4]: moved here from 1.21 so it sits next to its
    # technical-offer sibling 1.17 -- same due-date formula (predecessor
    # 1.9, +10 workdays) as always, not a milestone (1.17 alone keeps M4).
    # Now a per-item declaring item too (item [request 5]) -- see
    # L0_LINE_ITEM_CATEGORY_BY_ITEM_NO / po_line_items.py's "l0_comm_offer"
    # branch, fanning out to 3.5/3.6/3.7 (Supply Chain / Procurement PBU).
    ("1.18", "Circulate commercial offers & Terms received from Vendors & SC & Consultant to Supply chain", "tendering", "predecessor", "1.9", 10, "after", "date_driven", None),
    # 1.19/1.20/1.21 below all shifted up one slot by the 1.21->1.18 move
    # above (item [request 4]) -- content and formulas unchanged, only the
    # item_no and (for 1.19) its predecessor reference move.
    ("1.19", "Develop a comprehensive Technical-commercial proposal", "tendering", "predecessor", "1.21", 5, "before", "date_driven", None),
    ("1.20", "Adjust Proposals based on Tender Committee and/or VC Comments", "tendering", "predecessor", "1.19", 1, "after", "date_driven", None),
    ("1.21", "Submit Proposal to client", "tendering", "bsd", None, 0, "before", "date_driven", "M5"),

    # The old flat "operation" rows (2.1-2.6, pre-split Operation Units)
    # used to live here -- kept in sync by upsert only because existing
    # in-progress projects still had submissions pointing at them. Removed
    # (Yasser's request, confirmed zero submissions left referencing them --
    # see seed.py's one-time removal migration below) now that every real
    # project has long since moved to one of the per-BU blocks that follow
    # (item 69); the old "Operation Units" department itself is deleted by
    # that same migration since it has nothing else in it.

    # Operation Units (TBU) — own copy of 2.1-2.6 (item 69). BBU stays named
    # in the text since a TBU-scoped project can still involve BBU in a
    # coordinating role; rules.display_name strips that phrase per-project
    # when BBU isn't one of the project's own business units.
    ("2.1", "Attend Site Visit (in coordination with BBU)", "op_tbu", "site_visit", None, 0, "after", "date_driven", None),
    ("2.2", "Prepare and circulate Site Visit Report (in coordination with BBU)", "op_tbu", "predecessor", "2.1", 1, "after", "date_driven", "M2"),
    ("2.3", "Highlight points require Pre-bid clarifications", "op_tbu", "pre_bid", None, 3, "before", "date_driven", None),
    ("2.4", "Prepare Risk Register", "op_tbu", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("2.5", "Prepare Project Execution Plan (Methodology) - (in coordination with BBU)", "op_tbu", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("2.6", "Review and comments on Project schedule (Execution and Productivities)", "op_tbu", "predecessor", "5.3", 2, "after", "date_driven", None),

    # Operation Units (PBU)
    ("2.1", "Attend Site Visit (in coordination with BBU)", "op_pbu", "site_visit", None, 0, "after", "date_driven", None),
    ("2.2", "Prepare and circulate Site Visit Report (in coordination with BBU)", "op_pbu", "predecessor", "2.1", 1, "after", "date_driven", "M2"),
    ("2.3", "Highlight points require Pre-bid clarifications", "op_pbu", "pre_bid", None, 3, "before", "date_driven", None),
    ("2.4", "Prepare Risk Register", "op_pbu", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("2.5", "Prepare Project Execution Plan (Methodology) - (in coordination with BBU)", "op_pbu", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("2.6", "Review and comments on Project schedule (Execution and Productivities)", "op_pbu", "predecessor", "5.3", 2, "after", "date_driven", None),

    # Operation Units (DBU)
    ("2.1", "Attend Site Visit (in coordination with BBU)", "op_dbu", "site_visit", None, 0, "after", "date_driven", None),
    ("2.2", "Prepare and circulate Site Visit Report (in coordination with BBU)", "op_dbu", "predecessor", "2.1", 1, "after", "date_driven", "M2"),
    ("2.3", "Highlight points require Pre-bid clarifications", "op_dbu", "pre_bid", None, 3, "before", "date_driven", None),
    ("2.4", "Prepare Risk Register", "op_dbu", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("2.5", "Prepare Project Execution Plan (Methodology) - (in coordination with BBU)", "op_dbu", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("2.6", "Review and comments on Project schedule (Execution and Productivities)", "op_dbu", "predecessor", "5.3", 2, "after", "date_driven", None),

    # Operation Units (BBU) — BBU coordinating with itself doesn't make
    # sense, so the "(in coordination with BBU)" phrasing is dropped here
    # rather than left for the per-project stripper to catch (it only
    # strips when BBU is ABSENT from the project's business units, which
    # is never true for the BBU folder itself).
    ("2.1", "Attend Site Visit", "op_bbu", "site_visit", None, 0, "after", "date_driven", None),
    ("2.2", "Prepare and circulate Site Visit Report", "op_bbu", "predecessor", "2.1", 1, "after", "date_driven", "M2"),
    ("2.3", "Highlight points require Pre-bid clarifications", "op_bbu", "pre_bid", None, 3, "before", "date_driven", None),
    ("2.4", "Prepare Risk Register", "op_bbu", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("2.5", "Prepare Project Execution Plan (Methodology)", "op_bbu", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("2.6", "Review and comments on Project schedule (Execution and Productivities)", "op_bbu", "predecessor", "5.3", 2, "after", "date_driven", None),

    ("3.1", "Prepare Risk Register", "supply", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("3.2", "Highlight points require Pre-bid clarifications", "supply", "pre_bid", None, 3, "before", "date_driven", None),
    ("3.3", "Provide list of approved and acknowledge suppliers", "supply", None, None, 0, "after", "library", None),
    ("3.4", "Provide P.O.'s and Procurement Historical Data", "supply", None, None, 0, "after", "library", None),
    # Predecessor 1.18 (not 1.17) -- these are Supply Chain's own follow-up
    # to the commercial-offers circulation split out to them specifically
    # (moved from 1.21 to 1.18 by item [request 4]). Now per-item, fanned
    # out one row per manually-added review item on 1.18 (item [request 5]).
    ("3.5", "Review and Evaluate of Main Materials (Long lead items) and Subcontracting Strategy", "supply", "predecessor", "1.18", 2, "after", "date_driven", None),
    ("3.6", "Prepare List of long lead items, key materials and items fall on critical path", "supply", "predecessor", "1.18", 2, "after", "date_driven", None),
    ("3.7", "Support tendering with required logistics pricing and provide backup data", "supply", "predecessor", "1.18", 2, "after", "date_driven", None),
    ("3.8", "Complete Internal Prequalification of Potential Vendors (where applicable)", "supply", None, None, 0, "after", "on_request", None),
    ("3.9", "Participate in negotiation rounds at bidding stage lead by tender team", "supply", None, None, 0, "after", "on_request", None),

    # Procurement (PBU) -- own copy of Supply Chain's 3.1-3.9 (item [PBU
    # scope routing]), applies to OHTL/UGC-scoped projects instead of the
    # original Supply Chain department.
    ("3.1", "Prepare Risk Register", "supply_pbu", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("3.2", "Highlight points require Pre-bid clarifications", "supply_pbu", "pre_bid", None, 3, "before", "date_driven", None),
    ("3.3", "Provide list of approved and acknowledge suppliers", "supply_pbu", None, None, 0, "after", "library", None),
    ("3.4", "Provide P.O.'s and Procurement Historical Data", "supply_pbu", None, None, 0, "after", "library", None),
    ("3.5", "Review and Evaluate of Main Materials (Long lead items) and Subcontracting Strategy", "supply_pbu", "predecessor", "1.18", 2, "after", "date_driven", None),
    ("3.6", "Prepare List of long lead items, key materials and items fall on critical path", "supply_pbu", "predecessor", "1.18", 2, "after", "date_driven", None),
    ("3.7", "Support tendering with required logistics pricing and provide backup data", "supply_pbu", "predecessor", "1.18", 2, "after", "date_driven", None),
    ("3.8", "Complete Internal Prequalification of Potential Vendors (where applicable)", "supply_pbu", None, None, 0, "after", "on_request", None),
    ("3.9", "Participate in negotiation rounds at bidding stage lead by tender team", "supply_pbu", None, None, 0, "after", "on_request", None),

    ("4.1", "Prepare Risk Register", "eng", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("4.2", "Highlight points require Pre-bid clarifications", "eng", "pre_bid", None, 3, "before", "date_driven", None),
    ("4.3", "Provide List of required Site Investigations, Studies or any Special Technical requirements", "eng", "predecessor", "1.1", 3, "after", "date_driven", None),
    ("4.4", "Generate Design & BOQ's for the relevant scope (detailed for OHTL)", "eng", "predecessor", "1.1", 10, "after", "date_driven", None),
    ("4.5", "Provide Studies of Value Engineering and Optimized design (wherever needed)", "eng", None, None, 0, "after", "on_request", None),
    ("4.6", "Review and evaluate technical offers received from Vendors", "eng", "predecessor", "1.17", 2, "after", "date_driven", None),
    ("4.7", "Support Technical Proposals with required design deliverables (if needed)", "eng", None, None, 0, "after", "on_request", None),

    # Engineering (PBU) -- own copy of Engineering's 4.1-4.7 (item [PBU
    # scope routing]), applies to OHTL-scoped projects instead of the
    # original Engineering Department.
    ("4.1", "Prepare Risk Register", "eng_pbu", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("4.2", "Highlight points require Pre-bid clarifications", "eng_pbu", "pre_bid", None, 3, "before", "date_driven", None),
    ("4.3", "Provide List of required Site Investigations, Studies or any Special Technical requirements", "eng_pbu", "predecessor", "1.1", 3, "after", "date_driven", None),
    ("4.4", "Generate Design & BOQ's for the relevant scope (detailed for OHTL)", "eng_pbu", "predecessor", "1.1", 10, "after", "date_driven", None),
    ("4.5", "Provide Studies of Value Engineering and Optimized design (wherever needed)", "eng_pbu", None, None, 0, "after", "on_request", None),
    ("4.6", "Review and evaluate technical offers received from Vendors", "eng_pbu", "predecessor", "1.17", 2, "after", "date_driven", None),
    ("4.7", "Support Technical Proposals with required design deliverables (if needed)", "eng_pbu", None, None, 0, "after", "on_request", None),

    # Item 129: L0's old single "Control Department" splits into Planning
    # (5.1, 5.2, 5.3, 5.4, 5.5) and Cost Control (own copy of 5.1/5.2 plus
    # Fleet Productivities) -- same shared-item_no-across-departments
    # pattern as item 124's 9.3 split. Item 127 follow-up: Planning's own
    # numbers closed up to a gapless 5.1-5.5 (were 5.1,5.2,5.3,5.5,5.6,
    # skipping 5.4 since that slot always belonged to Cost Control's own
    # item, not Planning) -- no predecessor elsewhere references the old
    # 5.5/5.6 values, so this rename needed no other item touched.
    ("5.1", "Prepare Risk Register", "planning", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("5.2", "Highlight points require Pre-bid clarifications", "planning", "pre_bid", None, 3, "before", "date_driven", None),
    ("5.3", "Prepare Project schedule (level according to client requirement, up to Level 3)", "planning", "predecessor", "1.1", 15, "after", "date_driven", "M3"),
    ("5.4", "Verify Quantities for remeasured Contracts (if applicable)", "planning", "predecessor", "1.1", 10, "after", "date_driven", None),
    ("5.5", "Provide Updated Productivity Norms and Calculations (PCO-01-SPR-001)", "planning", None, None, 0, "after", "library", None),

    ("6.1", "Prepare Risk Register", "costctrl", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("6.2", "Highlight points require Pre-bid clarifications", "costctrl", "pre_bid", None, 3, "before", "date_driven", None),
    ("6.3", "Fleet Productivities (equipment productivity rates)", "costctrl", None, None, 0, "after", "library", None),

    ("7.1", "Prepare Risk Register", "contract", "predecessor", "1.21", 5, "before", "date_driven", None),
    # Item 172 (corrected): unlike every other department's identically-
    # worded "Highlight points require Pre-bid clarifications" item (e.g.
    # Planning's 5.2 above, which stays at 3 days), Contract's own 7.2 is
    # 1 day before the clarification deadline -- a deliberate, unique
    # exception per Yasser (originally applied to Cost Control's 6.2 by
    # mistake; 6.2 is back to the standard 3 days above).
    ("7.2", "Highlight points require Pre-bid clarifications (Review Contracts and Terms)", "contract", "pre_bid", None, 1, "before", "date_driven", None),
    ("7.3", "Prepare Non Disclosure Agreements (NDA's) (if applicable)", "contract", None, None, 0, "after", "on_request", None),
    ("7.4", "Review Pre-bid agreements and provide Contractual comments as needed", "contract", None, None, 0, "after", "on_request", None),

    ("8.1", "Verify local content requirements in coordination with the Manning Schedule", "hr", "predecessor", "5.3", 5, "after", "date_driven", None),
    ("8.2", "Updated HR Cost Estimates (Salaries / Wages / Benefits)", "hr", None, None, 0, "after", "library", None),
    ("8.3", "Provide updated information on Workforce availability, nationality, release dates", "hr", None, None, 0, "after", "library", None),
    ("8.4", "Provide Supporting documents, such as team CV's, certificates and Qualifications", "hr", "predecessor", "1.1", 5, "after", "date_driven", None),

    # Item 141: L0's old combined "Financial Department" splits into
    # Treasury (Risk Register duplicated + Issue Bid Bonds) and Finance
    # (Risk Register original + Insurance Cost + Overheads + Cash Flow),
    # mirroring L1's existing Treasury/Finance split -- same
    # shared-item_no-across-departments pattern as item 129's 5.1/5.2 split.
    ("9.1", "Prepare Risk Register", "treasury", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("9.2", "Issue Bid Bonds", "treasury", "predecessor", "1.21", 3, "before", "date_driven", None),

    ("10.1", "Prepare Risk Register", "finance", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("10.2", "Provide Insurance Cost, and additional client requirements", "finance", "predecessor", "1.21", 6, "before", "date_driven", None),
    ("10.3", "Provide Proposed Business Units, Corporate, Finance and Insurance Overheads", "finance", None, None, 0, "after", "library", None),
    ("10.4", "Provide Proposed Cash Flow & Finance Cost and Parameters", "finance", None, None, 0, "after", "library", None),

    # Item 141 rework: Quality gets Risk Register, Pre-bid clarifications,
    # QA/QC Plan, Evaluate Subcontractors, and Personnel Requirements.
    # Personnel Requirements drops the "HSSE / Quality" suffix from its
    # name now that it's landed cleanly on Quality alone.
    ("11.1", "Prepare Risk Register", "quality", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("11.2", "Highlight points require Pre-bid clarifications", "quality", "pre_bid", None, 3, "before", "date_driven", None),
    ("11.3", "Prepare QA/QC Plan - Tender Level", "quality", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("11.4", "Evaluate Selected subcontractors (for not Qualified / Approved Subcontractors)", "quality", "predecessor", "1.18", 2, "after", "date_driven", None),
    ("11.5", "Standard Personnel Requirements (Client's Standards)", "quality", "predecessor", "1.1", 7, "after", "date_driven", None),

    # Item 141 second rework: reverted -- HSSE keeps its own full
    # original 5 items (Risk Register, Pre-bid clarifications,
    # Safety/PPE, HSE Plan, Personnel Requirements), duplicated
    # alongside Quality's own copies rather than moved off entirely.
    # Only 12.5's name changes (drops "HSSE / Quality", same as
    # Quality's 11.5).
    ("12.1", "Prepare Risk Register", "hsse", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("12.2", "Highlight points require Pre-bid clarifications", "hsse", "pre_bid", None, 3, "before", "date_driven", None),
    ("12.3", "List of Safety Requirements & PPE", "hsse", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("12.4", "Prepare HSE Plan - Tender Level", "hsse", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("12.5", "Standard Personnel Requirements (Client's Standards)", "hsse", "predecessor", "1.1", 7, "after", "date_driven", None),

    ("13.1", "Cost for Staff and Office Requirements (Hardware, Software, Infrastructure)", "it", "predecessor", "5.3", 3, "after", "date_driven", None),

    ("14.1", "Compile risk registers received from all departments, Evaluate and present", "risk", None, None, 0, "after", "on_request", None),

    # Item 128: L0's old combined "Fleet and Facility Management Department"
    # splits into Fleet (equipment, 15.1/15.2) and FM (camp, 16.1), matching
    # how L1 already separates them.
    ("15.1", "Recent Equipment Cost Estimates, Consumptions and Maintenance", "fleet", None, None, 0, "after", "library", None),
    ("15.2", "Provide recent information on Equipment availability, location and release dates", "fleet", None, None, 0, "after", "library", None),
    ("16.1", "Provide Camp Cost Estimates, Consumptions and Maintenance based on manning", "fm", "predecessor", "5.3", 5, "after", "date_driven", None),
]

# ---------------------------------------------------------------------------
# [L0 International] catalog — from "L0 Template International Projects.xlsx"
# (International/ folder), sheet "L0 International". Same stage as regular
# L0 (still Stage.L0 -- there is no separate "International" Stage), but an
# entirely separate item catalog, on its own departments, gated by
# rules.is_international_applicable so it only ever instantiates on a
# project with is_international=True and never mixes with the standard L0
# catalog above.
#
# Every department here is its own new Department row (never a standard-L0
# department reused) -- Department.name is unique at the DB level and the
# upsert() key is (stage, item_no, department_id), so reusing a standard-L0
# department id would silently overwrite its real catalog text with these
# international items sharing the same item_no (both catalogs use "1.1"-
# "1.24", "4.1"-"4.9", etc.).
#
# Financial Department and SHEQ Department split into Treasury/Finance and
# Quality/HSSE, same as standard L0 already does (see L0_DEPT above) --
# renumbered under their own new department numbers, not just relabeled in
# place. Applying that same "does every item have one clean single-owner
# Action-By?" test surfaced two more splits: Fleet and FM Department (into
# Fleet/FM, matching standard L0's own precedent) and Control Department
# (into Planning/Cost Control) -- Planning keeps all 4 original Control
# items (including the one whose Action-By was "QS", folded in rather than
# given its own department), Cost Control gets a duplicated copy of just
# the Risk Register and Pre-bid-clarifications items, the same "every split
# department keeps its own copy of these two" convention Treasury/Finance
# and Quality/HSSE items also follow below.
L0_INTERNATIONAL_DEPT = {
    "tendering_intl": "Tendering Department (International)",
    "operation_intl": "Operation Units (International)",
    "supply_intl": "Supply Chain (International)",
    "eng_intl": "Engineering Department (International)",
    "planning_intl": "Planning (International)",
    "costctrl_intl": "Cost Control (International)",
    "contract_intl": "Contract (International)",
    "hr_intl": "Human Resources (International)",
    "treasury_intl": "Treasury (International)",
    "finance_intl": "Finance (International)",
    "quality_intl": "Quality (International)",
    "hsse_intl": "HSSE (International)",
    "it_intl": "IT Department (International)",
    "risk_intl": "Risk (International)",
    "fleet_intl": "Fleet (International)",
    "fm_intl": "FM (International)",
    "legal_intl": "Legal (International)",
    "bd_intl": "International Business Development",
    "docgov_intl": "Document & Data Governance",
}

# (item_no, name, dept_key, anchor_type, pred, offset, direction, dtype, milestone_code)
# Milestones: M1=1.1 (announcement), M2=2.2 (site visit report), M3=5.3
# (project schedule, now under Planning), M4=1.13 (technical offers
# circulated), M5=1.24 (submit proposal, = BSD). A few formulas in the
# source template are conditional ("+N days from M1 or +M days after X") --
# simplified to their primary/first branch (the literal "+N days from M1"),
# same simplification noted in the plan; easy to add a real conditional
# later if the actual trigger condition is clarified.
L0_INTERNATIONAL_ITEMS = [
    ("1.1", "Receive Approval for GO approach & Circulate Tender Documents", "tendering_intl", "announcement", None, 0, "after", "date_driven", "M1"),
    ("1.2", "Announce the date of the site visit", "tendering_intl", "predecessor", "1.1", 2, "after", "date_driven", None),
    ("1.3", "Announce the date of the Pre-bid Meetings and circulate related instructions (if applicable)", "tendering_intl", "predecessor", "1.1", 2, "after", "date_driven", None),
    ("1.4", "Announce the deadlines of the Pre-bid clarifications", "tendering_intl", "predecessor", "1.1", 2, "after", "date_driven", None),
    ("1.5", "Assign BID Manager / Calculation Engineer (focal for all communications)", "tendering_intl", "predecessor", "1.1", 2, "after", "date_driven", None),
    ("1.6", "Arrange for Bid Bond if applicable (reference to agreement with partner if needed)", "tendering_intl", "predecessor", "1.24", 10, "before", "date_driven", None),
    ("1.7", "Develop Estimate Program and circulate with all departments, External consultant, SME's", "tendering_intl", "predecessor", "1.1", 5, "after", "date_driven", None),
    ("1.8", "IBU to determine whether to participate in the tender as AGC Holding or through one of AGH's affiliates, based on the project scope and pre-qualification (PQ) requirements from either the SFD or the client.", "tendering_intl", "predecessor", "1.1", 2, "after", "date_driven", None),
    ("1.9", "Communicate and align with the selected partner after selection", "tendering_intl", "predecessor", "1.1", 3, "after", "date_driven", None),
    ("1.10", "Float SC RFQ's", "tendering_intl", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("1.11", "Float Materials RFQ's", "tendering_intl", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("1.12", "Float RFQ's - Consultant Services", "tendering_intl", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("1.13", "Circulate technical offers & Terms received from Vendors & SC & Consultant to Tender & Engineering", "tendering_intl", "predecessor", "1.12", 10, "after", "date_driven", "M4"),
    ("1.14", "BD to Align with the suitable subsidiary/affiliate to jointly participate with the tender department for the preparation of high level DOR", "tendering_intl", "predecessor", "1.1", 3, "after", "date_driven", None),
    ("1.15", "Review Project Schedule and provide feedback (item 5.3 provided from Planning Department)", "tendering_intl", "predecessor", "5.3", 2, "after", "date_driven", None),
    ("1.16", "Review Project Execution Plan (item 2.5 Methodology) and provide feedback", "tendering_intl", "predecessor", "1.1", 8, "after", "date_driven", None),
    ("1.17", "Incorporate Consultant findings (if applicable)", "tendering_intl", None, None, 0, "after", "on_request", None),
    ("1.18", "Incorporate SME's findings (if applicable)", "tendering_intl", None, None, 0, "after", "on_request", None),
    ("1.19", "Share Updated Manpower Manning schedules with HR & IT", "tendering_intl", "predecessor", "5.3", 3, "after", "date_driven", None),
    ("1.20", "Provide estimated filled BOQ and Price breakdown to finanical department for Cash flow calculations", "tendering_intl", "predecessor", "1.24", 7, "before", "date_driven", None),
    ("1.21", "Develop a comprehensive Technical proposal according to ITB (See ATTACHMENT NO. 4 TO FORM OF TENDER)", "tendering_intl", "predecessor", "1.24", 3, "before", "date_driven", None),
    ("1.22", "Develop a comprehensive Commercial proposal", "tendering_intl", "predecessor", "1.24", 3, "before", "date_driven", None),
    ("1.23", "Adjust Proposals base on Tender Committee and /or VC Comments", "tendering_intl", "predecessor", "1.24", 3, "before", "date_driven", None),
    ("1.24", "Submit Proposal to client", "tendering_intl", "bsd", None, 0, "before", "date_driven", "M5"),

    ("2.1", "Attend Site Visit", "operation_intl", "site_visit", None, 0, "after", "date_driven", None),
    ("2.2", "Prepare and circulate Site Visit Report to understand terrain, accessibility, logistics, local suppliers, labor availability, and infrastructure includes Site visit certificate", "operation_intl", "site_visit", None, 3, "after", "date_driven", "M2"),
    ("2.3", "Assign Focal Point during L0 stage", "operation_intl", "predecessor", "1.1", 3, "after", "date_driven", None),
    ("2.4", "Review any local construction codes, safety standards, taxes, and permitting processes that may impact cost or timeline.", "operation_intl", "site_visit", None, 3, "after", "date_driven", None),
    # Item [2.5 formula correction]: was anchored on Site Visit +3 days;
    # now matches 5.3's own formula exactly (predecessor 1.1, +15 workdays).
    ("2.5", "Check the Security & Stability requirements such as security services or additional insurance.", "operation_intl", "predecessor", "1.1", 15, "after", "date_driven", None),
    ("2.6", "Provide recommendations on Site Establishment requirment: Fencing, signage, utilities, access roads, Supervision & Admin Staff", "operation_intl", "site_visit", None, 3, "after", "date_driven", None),
    ("2.7", "Highlight points require Pre-bid clarifications", "operation_intl", "pre_bid", None, 3, "before", "date_driven", None),
    ("2.8", "Prepare Risk Register", "operation_intl", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("2.9", "Provide Subcontracting Strategy", "operation_intl", "predecessor", "1.1", 14, "after", "date_driven", None),
    ("2.10", "Prepare Project Execution Plan (Methodology)", "operation_intl", "predecessor", "1.1", 14, "after", "date_driven", None),
    ("2.11", "Review and comments on Project schedule", "operation_intl", "predecessor", "5.3", 2, "after", "date_driven", None),

    ("3.1", "Prepare Risk Register", "supply_intl", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("3.2", "Highlight points require Pre-bid clarifications", "supply_intl", "pre_bid", None, 3, "before", "date_driven", None),
    ("3.3", "Prepare Pre-bid agreements such as; handling main material linked to LME Pricing", "supply_intl", "predecessor", "1.1", 10, "after", "date_driven", None),
    ("3.4", "Provide P.O.'s and Procurement Historical Data", "supply_intl", None, None, 0, "after", "on_request", None),
    ("3.5", "Prepare List of long lead items, key materials and items fall on critical path in collaboration with Tender and Planning team (including Spare Parts / Special Tools And Test Equipment )", "supply_intl", "predecessor", "1.13", 2, "after", "date_driven", None),
    ("3.6", "Support tendering with required logistics pricing and provide backup details (Sea Freight, Land Transportation..)", "supply_intl", "predecessor", "1.13", 2, "after", "date_driven", None),
    ("3.7", "Complete Internal Prequalification of Potential Vendors (where applicable for any new vendor)", "supply_intl", "predecessor", "1.13", 2, "after", "date_driven", None),
    ("3.8", "Participate in negotiation rounds at bidding stage (if required) and provide feedback to tender team", "supply_intl", None, None, 0, "after", "on_request", None),

    ("4.1", "Prepare Risk Register", "eng_intl", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("4.2", "Highlight points require Pre-bid clarifications", "eng_intl", "pre_bid", None, 3, "before", "date_driven", None),
    ("4.3", "Provide List of required Site Investigations, Studies or any Special Technical Reports", "eng_intl", "predecessor", "1.1", 3, "after", "date_driven", None),
    ("4.4", "Generate equipment technical RFP for main equipment", "eng_intl", "predecessor", "1.1", 10, "after", "date_driven", None),
    ("4.5", "Generate Design, technical scope & BOQ's for all disciplines", "eng_intl", "predecessor", "1.1", 14, "after", "date_driven", None),
    ("4.6", "Hire 3rd Party Engineering Firm with required experience (if needed)", "eng_intl", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("4.7", "Provide Studies of Value Engineering and Optimized design (wherever needed for All Disciplines)", "eng_intl", "predecessor", "1.1", 10, "after", "date_driven", None),
    ("4.8", "Review and evaluate technical offers received from Vendors", "eng_intl", "predecessor", "1.13", 2, "after", "date_driven", None),
    ("4.9", "Support Technical Proposals with required Technical deliverables (if needed)", "eng_intl", "predecessor", "1.1", 14, "after", "date_driven", None),

    ("5.1", "Prepare Risk Register", "planning_intl", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("5.2", "Highlight points require Pre-bid clarifications", "planning_intl", "pre_bid", None, 3, "before", "date_driven", None),
    ("5.3", "Prepare Project schedule loaded with resources (based on AGC norms) (level according to client requirement, up to L3) - Schedule is Mandatory for every tender even if it was not requested by client", "planning_intl", "predecessor", "1.1", 15, "after", "date_driven", "M3"),
    ("5.4", "Verify Quantities for remeasured Contracts (if applicable)", "planning_intl", "predecessor", "1.1", 10, "after", "date_driven", None),

    ("6.1", "Prepare Risk Register", "costctrl_intl", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("6.2", "Highlight points require Pre-bid clarifications", "costctrl_intl", "pre_bid", None, 3, "before", "date_driven", None),

    ("7.1", "Prepare Risk Register", "contract_intl", "predecessor", "1.24", 7, "before", "date_driven", None),
    ("7.2", "Highlight points require Pre-bid clarifications (Review Contracts and submit comments, and clarification that need to be addressed to client during this stage)", "contract_intl", "pre_bid", None, 3, "before", "date_driven", None),
    ("7.3", "Prepare Non Disclosure Agreements (NDA's) (if applicable)", "contract_intl", None, None, 0, "after", "on_request", None),
    ("7.4", "Review Pre-bid agreements and provide Contractual comments as needed (if applicable)", "contract_intl", None, None, 0, "after", "on_request", None),
    ("7.5", "Joint Venture Agreement / Consortium Agreement (if applicable)", "contract_intl", "predecessor", "1.24", 7, "before", "date_driven", None),

    ("8.1", "Provide report on Local Content regulations", "hr_intl", "predecessor", "5.3", 5, "after", "date_driven", None),
    ("8.2", "Updated HR Cost Estimates (Salaries / Wages / Benefits) for targeted country", "hr_intl", "predecessor", "2.2", 7, "after", "date_driven", None),
    ("8.3", "Provide updated information on Workforce availability, nationality, release dates, relocate/ requirements of new hiring", "hr_intl", "predecessor", "5.3", 5, "after", "date_driven", None),
    ("8.4", "Provide Supporting documents, such as team CV's, certificates and Qualifications for technical proposal (If Applicable )", "hr_intl", "predecessor", "1.1", 5, "after", "date_driven", None),

    ("9.1", "Prepare Risk Register", "treasury_intl", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("9.2", "Issue Bid Bonds reference to item no. 1.6 (request must be received within 14 days before bond submission deadline)", "treasury_intl", "predecessor", "1.24", 3, "before", "date_driven", None),
    ("9.3", "Financial Capacity / Financial Situation / Annual Turnover - Updated on Yearly Bases (on request)", "treasury_intl", "predecessor", "1.1", 5, "after", "date_driven", None),

    ("10.1", "Prepare Risk Register", "finance_intl", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("10.2", "Audited Financial Statements (last 3 years - Arabic & English) - Updated on Yearly Bases", "finance_intl", "predecessor", "1.1", 5, "after", "date_driven", None),
    ("10.3", "Insurance Certificates (if required) - Updated on Yearly Bases", "finance_intl", "predecessor", "1.1", 5, "after", "date_driven", None),
    ("10.4", "Provide Insurance Cost, and additional clients req. such as current policies (when required)", "finance_intl", "predecessor", "1.24", 5, "before", "date_driven", None),
    ("10.5", "Provide Proposed Business Units, Corporate , Finance and Insurance Overheads (%) and provide backup details", "finance_intl", "predecessor", "1.24", 5, "before", "date_driven", None),
    ("10.6", "Provide Proposed Cash Flow & Finance Cost and Parameters required to calculate the finance cost - based on input availablilty", "finance_intl", "predecessor", "1.24", 7, "before", "date_driven", None),

    ("11.1", "Prepare Risk Register", "quality_intl", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("11.2", "Highlight points require Pre-bid clarifications", "quality_intl", "pre_bid", None, 3, "before", "date_driven", None),
    ("11.3", "Prepare QA/QC Plan - Tender Level", "quality_intl", "predecessor", "1.1", 7, "after", "date_driven", None),

    ("12.1", "Prepare Risk Register", "hsse_intl", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("12.2", "Highlight points require Pre-bid clarifications", "hsse_intl", "pre_bid", None, 3, "before", "date_driven", None),
    ("12.3", "List of Safety req. & PPE", "hsse_intl", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("12.4", "Prepare HSE Plan - Tender Level", "hsse_intl", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("12.5", "Weather & Environment: Check for weather conditions, seasonal impacts, or environmental risks that may affect construction or logistics.", "hsse_intl", "predecessor", "2.2", 5, "after", "date_driven", None),

    ("13.1", "Cost for Staff and offices Requirments (Hardware, Software, Infrastructure)", "it_intl", "predecessor", "5.3", 3, "after", "date_driven", None),

    ("14.1", "Compile risk registers received from all departments, Evaluate and prepare final register that shall be considered by tendering", "risk_intl", "predecessor", "2.2", 3, "after", "date_driven", None),

    ("15.1", "Recent Equipment Availability, Cost Estimates, Consumptions and Maintenance in targeted country", "fleet_intl", "predecessor", "5.3", 5, "after", "date_driven", None),

    ("16.1", "Provide Camp Cost Estimates, Consumptions and Maintenance based on manpower histogram", "fm_intl", "predecessor", "5.3", 5, "after", "date_driven", None),

    ("17.1", "Power of Attorney (authenticated by Chamber of Commerce)", "legal_intl", "predecessor", "1.1", 5, "after", "date_driven", None),
    ("17.2", "History of non-execution of contracts / Litigation / Legal Disputes Declaration (if required / as per client request)", "legal_intl", "predecessor", "1.1", 5, "after", "date_driven", None),

    ("18.1", "Lead communications with potential partners (DOR, agreements)", "bd_intl", "predecessor", "1.1", 1, "after", "date_driven", None),
    ("18.2", "Arrange for a site visit and align with all departments on the required attendees, prerequisit forms and Prepare visit agenda (meeting client, contractors, suppliers, logistics..) (Forms Attached)", "bd_intl", "predecessor", "1.1", 1, "after", "date_driven", None),
    ("18.3", "Analyze the market and study competitors' portfolios", "bd_intl", "predecessor", "2.2", 7, "after", "date_driven", None),
    ("18.4", "List of Ongoing & Completed Projects", "bd_intl", "predecessor", "1.1", 5, "after", "date_driven", None),
    ("18.5", "International Experience Reference Projects", "bd_intl", "predecessor", "1.1", 5, "after", "date_driven", None),

    ("19.1", "Commercial Registration (CR)", "docgov_intl", "predecessor", "1.1", 5, "after", "date_driven", None),
    ("19.2", "Zakat, Tax, and VAT Certificates (ZATCA-compliant)", "docgov_intl", "predecessor", "1.1", 5, "after", "date_driven", None),
    ("19.3", "GOSI Certificate (if required)", "docgov_intl", "predecessor", "1.1", 5, "after", "date_driven", None),
    ("19.4", "Saudi Chamber of Commerce Membership Certificate", "docgov_intl", "predecessor", "1.1", 5, "after", "date_driven", None),
    ("19.5", "Updated Company Profile", "docgov_intl", "predecessor", "1.1", 5, "after", "date_driven", None),
]

# ---------------------------------------------------------------------------
# L1 catalog — from New L1 Template (Final).xlsx, "L1 Template (Tracking
# Sheet)", columns B/C/F (item/name/department), I (predecessor), J
# (duration). Items 1.1-1.6 ARE the milestones M1-M6 (column D).
# ---------------------------------------------------------------------------
L1_DEPT = {
    "tendering": "Tendering Department",
    "supply": "Supply Chain", "eng": "Engineering Department", "planning": "Planning",
    "costctrl": "Cost Control", "contract": "Contract", "hr": "Human Resources",
    # [PBU scope routing]: own copy of Engineering/Supply Chain, gated by
    # scope instead of business_units -- see rules.is_scope_variant_applicable.
    "eng_pbu": "Engineering (PBU)", "supply_pbu": "Procurement (PBU)",
    "treasury": "Treasury", "finance": "Finance", "quality": "Quality",
    "hsse": "HSSE", "risk": "Risk", "fleet": "Fleet", "fm": "FM",
    # Item 122 rework: reuse L0's own "Operation Units (X)" department rows
    # instead of separate plain-named ones, so the folder list nests L1's
    # TBU/PBU/DBU/BBU under a shared "2. Operation Units" group header,
    # matching L0's presentation exactly.
    "tbu": "Operation Units (TBU)", "pbu": "Operation Units (PBU)",
    "dbu": "Operation Units (DBU)", "bbu": "Operation Units (BBU)",
}

# (item_no, name, dept_key, anchor_type, pred, offset, direction, milestone_code)
L1_ITEMS = [
    ("1.1", "L1 Announcement email", "tendering", "announcement", None, 0, "after", "M1"),
    ("1.2", "Provide Early mobilization Plan, Long lead items & MEP consultancy needs", "tendering", "predecessor", "1.1", 5, "after", "M2"),
    ("1.3", "Commercial & Technical Handover (Including list of Assumptions)", "tendering", "predecessor", "1.2", 25, "after", "M3"),
    ("1.4", "Starting Post Bid clarification", "tendering", "client_dependent", None, 0, "after", "M4"),
    ("1.5", "Receiving LOA / Post bid clarifications ends", "tendering", "client_dependent", None, 0, "after", "M5"),
    ("1.6", "Contract Signing", "tendering", "client_dependent", None, 0, "after", "M6"),

    ("2.13", "Submission of Cost Center request to Cost Control Department", "bbu", "predecessor", "1.2", 1, "after", None),
    ("2.14", "Creating PRs for MEP consultancy items through system", "bbu", "predecessor", "6.1", 2, "after", None),
    ("2.15", "BBU input for Draft Project Execution Plan", "bbu", "predecessor", "1.2", 20, "after", None),
    ("2.17", "Prepare/Update Subcontracting Strategy / Model", "bbu", "predecessor", "1.2", 5, "after", None),
    ("2.18", "Finalize Subcontract Agreement for SS projects", "bbu", "predecessor", "1.6", 10, "after", None),

    # Item 122: full TBU/PBU/DBU/BBU split (mirrors item 69's L0 pattern) --
    # own copy of 2.1-2.12 per business unit. The old combined "TBU / PBU"
    # and "BBU / PBU" catalog entries this replaced (2.1-2.12 under
    # "tbupbu", 2.16 under "bbupbu") are gone -- confirmed zero real
    # progress on every existing submission still pointing at them before
    # removal (see the one-time cleanup migration in run() below).
    ("2.1", "Submission of Cost Center request to Cost Control Department", "tbu", "predecessor", "1.2", 1, "after", None),
    ("2.2", "Creating PRs for long-lead items through the system", "tbu", "predecessor", "4.5", 2, "after", None),
    ("2.3", "Assignment of Temporary Project Manager & Project Engineer", "tbu", "predecessor", "1.1", 5, "after", None),
    ("2.4", "Internal Kick off Meeting (to be called by Project Manager)", "tbu", "predecessor", "2.3", 5, "after", None),
    ("2.5", "Draft Master Project Execution Plan ready to be submitted", "tbu", "predecessor", "1.2", 25, "after", None),
    ("2.6", "Create PRs for Early Activities (Soil Investigation, Topography)", "tbu", "predecessor", "6.1", 2, "after", None),
    ("2.7", "Create PR for Design Firm/Consultant", "tbu", "predecessor", "4.4", 2, "after", None),
    ("2.8", "Start Activities for Geotechnical Investigation (in house or vendor)", "tbu", "predecessor", "1.5", 7, "after", None),
    ("2.9", "Start Activities for Topography and Site Investigation", "tbu", "predecessor", "1.2", 25, "after", None),
    ("2.10", "Provide list of project permits (Governmental, Local Authority)", "tbu", "predecessor", "1.2", 15, "after", None),
    ("2.11", "Preparation of Subcontracting Strategy for (OHTL/UGC) projects", "tbu", "predecessor", "1.2", 5, "after", None),
    ("2.12", "Provide Confirmation on the Proposal recommendation for working schedule", "tbu", "predecessor", "5.3", 3, "after", None),

    ("2.1", "Submission of Cost Center request to Cost Control Department", "pbu", "predecessor", "1.2", 1, "after", None),
    ("2.2", "Creating PRs for long-lead items through the system", "pbu", "predecessor", "4.5", 2, "after", None),
    ("2.3", "Assignment of Temporary Project Manager & Project Engineer", "pbu", "predecessor", "1.1", 5, "after", None),
    ("2.4", "Internal Kick off Meeting (to be called by Project Manager)", "pbu", "predecessor", "2.3", 5, "after", None),
    ("2.5", "Draft Master Project Execution Plan ready to be submitted", "pbu", "predecessor", "1.2", 25, "after", None),
    ("2.6", "Create PRs for Early Activities (Soil Investigation, Topography)", "pbu", "predecessor", "6.1", 2, "after", None),
    ("2.7", "Create PR for Design Firm/Consultant", "pbu", "predecessor", "4.4", 2, "after", None),
    ("2.8", "Start Activities for Geotechnical Investigation (in house or vendor)", "pbu", "predecessor", "1.5", 7, "after", None),
    ("2.9", "Start Activities for Topography and Site Investigation", "pbu", "predecessor", "1.2", 25, "after", None),
    ("2.10", "Provide list of project permits (Governmental, Local Authority)", "pbu", "predecessor", "1.2", 15, "after", None),
    ("2.11", "Preparation of Subcontracting Strategy for (OHTL/UGC) projects", "pbu", "predecessor", "1.2", 5, "after", None),
    ("2.12", "Provide Confirmation on the Proposal recommendation for working schedule", "pbu", "predecessor", "5.3", 3, "after", None),
    ("2.16", "Provide general layout of Temporary facilities, laydown and storage", "pbu", "predecessor", "1.2", 7, "after", None),

    ("2.1", "Submission of Cost Center request to Cost Control Department", "dbu", "predecessor", "1.2", 1, "after", None),
    ("2.2", "Creating PRs for long-lead items through the system", "dbu", "predecessor", "4.5", 2, "after", None),
    ("2.3", "Assignment of Temporary Project Manager & Project Engineer", "dbu", "predecessor", "1.1", 5, "after", None),
    ("2.4", "Internal Kick off Meeting (to be called by Project Manager)", "dbu", "predecessor", "2.3", 5, "after", None),
    ("2.5", "Draft Master Project Execution Plan ready to be submitted", "dbu", "predecessor", "1.2", 25, "after", None),
    ("2.6", "Create PRs for Early Activities (Soil Investigation, Topography)", "dbu", "predecessor", "6.1", 2, "after", None),
    ("2.7", "Create PR for Design Firm/Consultant", "dbu", "predecessor", "4.4", 2, "after", None),
    ("2.8", "Start Activities for Geotechnical Investigation (in house or vendor)", "dbu", "predecessor", "1.5", 7, "after", None),
    ("2.9", "Start Activities for Topography and Site Investigation", "dbu", "predecessor", "1.2", 25, "after", None),
    ("2.10", "Provide list of project permits (Governmental, Local Authority)", "dbu", "predecessor", "1.2", 15, "after", None),
    ("2.11", "Preparation of Subcontracting Strategy for (OHTL/UGC) projects", "dbu", "predecessor", "1.2", 5, "after", None),
    ("2.12", "Provide Confirmation on the Proposal recommendation for working schedule", "dbu", "predecessor", "5.3", 3, "after", None),

    ("2.16", "Provide general layout of Temporary facilities, laydown and storage", "bbu", "predecessor", "1.2", 7, "after", None),

    ("3.1", "Issue RFQ to vendors including technical SOW, contractual and commercial baselines", "supply", "predecessor", "4.5", 7, "after", None),
    ("3.2", "Allowable time for negotiating commercial and technical terms", "supply", "predecessor", "1.3", 10, "after", None),
    ("3.3", "Award Approval on System (Buyer -> SCM -> Cost Control -> Operation)", "supply", "predecessor", "1.6", 5, "after", None),
    ("3.4", "Top Management approval of awarding, if required as per Authority Matrix", "supply", "predecessor", "3.3", 6, "after", None),
    ("3.5", "PO Approval on Oracle following Award Approval", "supply", "predecessor", "3.4", 4, "after", None),
    ("3.6", "Electronic Internal PO Signature (SCM Director and VP Technical)", "supply", "predecessor", "3.5", 3, "after", None),
    ("3.7", "Electronic PO Signature by Vendor", "supply", "predecessor", "3.6", 3, "after", None),
    ("3.8", "Finalize Subcontract Agreement for OHTL/UGC Projects", "supply", "predecessor", "1.6", 10, "after", None),
    ("3.9", "Share Design Firm Technical Offers received from vendors with Engineering", "supply", "predecessor", "4.3", 5, "after", None),
    ("3.10", "Prepare and Issue Engineering/Design Agreement/PO", "supply", "predecessor", "2.7", 8, "after", None),
    ("3.11", "Issue POs for Early Activities (Site Survey, Geotechnical Investigation)", "supply", "predecessor", "2.6", 8, "after", None),
    ("3.12", "Finalize prequalification of new vendors (if any)", "supply", "predecessor", "1.2", 21, "after", None),

    # Procurement (PBU) -- own copy of Supply Chain's 3.1-3.12 (item [PBU
    # scope routing]), applies to OHTL/UGC-scoped projects instead of the
    # original Supply Chain department.
    ("3.1", "Issue RFQ to vendors including technical SOW, contractual and commercial baselines", "supply_pbu", "predecessor", "4.5", 7, "after", None),
    ("3.2", "Allowable time for negotiating commercial and technical terms", "supply_pbu", "predecessor", "1.3", 10, "after", None),
    ("3.3", "Award Approval on System (Buyer -> SCM -> Cost Control -> Operation)", "supply_pbu", "predecessor", "1.6", 5, "after", None),
    ("3.4", "Top Management approval of awarding, if required as per Authority Matrix", "supply_pbu", "predecessor", "3.3", 6, "after", None),
    ("3.5", "PO Approval on Oracle following Award Approval", "supply_pbu", "predecessor", "3.4", 4, "after", None),
    ("3.6", "Electronic Internal PO Signature (SCM Director and VP Technical)", "supply_pbu", "predecessor", "3.5", 3, "after", None),
    ("3.7", "Electronic PO Signature by Vendor", "supply_pbu", "predecessor", "3.6", 3, "after", None),
    ("3.8", "Finalize Subcontract Agreement for OHTL/UGC Projects", "supply_pbu", "predecessor", "1.6", 10, "after", None),
    ("3.9", "Share Design Firm Technical Offers received from vendors with Engineering", "supply_pbu", "predecessor", "4.3", 5, "after", None),
    ("3.10", "Prepare and Issue Engineering/Design Agreement/PO", "supply_pbu", "predecessor", "2.7", 8, "after", None),
    ("3.11", "Issue POs for Early Activities (Site Survey, Geotechnical Investigation)", "supply_pbu", "predecessor", "2.6", 8, "after", None),
    ("3.12", "Finalize prequalification of new vendors (if any)", "supply_pbu", "predecessor", "1.2", 21, "after", None),

    ("4.1", "Provide SC scope for Early Activities", "eng", "predecessor", "1.1", 9, "after", None),
    ("4.2", "Update the initial Design and Quantities including site layout", "eng", "predecessor", "2.9", 10, "after", None),
    ("4.3", "Provide brief SOW for Design Firm as per PTS for core project", "eng", "predecessor", "1.1", 2, "after", None),
    ("4.4", "Review and evaluate Design Firm Technical Offers and Finalize selection", "eng", "predecessor", "3.9", 5, "after", None),
    ("4.5", "Review Vendors technical offers received from Tendering & Procurement", "eng", "predecessor", "1.2", 10, "after", None),
    ("4.6", "Review Vendors technical offers received from Supply Chain", "eng", "predecessor", "3.2", 5, "after", None),
    ("4.7", "Verify site layout after approach Site for Preliminary investigation", "eng", "predecessor", "2.9", 5, "after", None),
    ("4.8", "Update Engineering Risk Register including lesson learned", "eng", "predecessor", "4.2", 10, "after", None),

    # Engineering (PBU) -- own copy of Engineering's 4.1-4.8 (item [PBU
    # scope routing]), applies to OHTL-scoped projects instead of the
    # original Engineering Department.
    ("4.1", "Provide SC scope for Early Activities", "eng_pbu", "predecessor", "1.1", 9, "after", None),
    ("4.2", "Update the initial Design and Quantities including site layout", "eng_pbu", "predecessor", "2.9", 10, "after", None),
    ("4.3", "Provide brief SOW for Design Firm as per PTS for core project", "eng_pbu", "predecessor", "1.1", 2, "after", None),
    ("4.4", "Review and evaluate Design Firm Technical Offers and Finalize selection", "eng_pbu", "predecessor", "3.9", 5, "after", None),
    ("4.5", "Review Vendors technical offers received from Tendering & Procurement", "eng_pbu", "predecessor", "1.2", 10, "after", None),
    ("4.6", "Review Vendors technical offers received from Supply Chain", "eng_pbu", "predecessor", "3.2", 5, "after", None),
    ("4.7", "Verify site layout after approach Site for Preliminary investigation", "eng_pbu", "predecessor", "2.9", 5, "after", None),
    ("4.8", "Update Engineering Risk Register including lesson learned", "eng_pbu", "predecessor", "4.2", 10, "after", None),

    ("5.1", "Provide Project Baseline Schedule as per Contractual Milestones", "planning", "predecessor", "1.3", 20, "after", None),
    ("5.2", "Provide Project Working Schedule (Actual Resource Loaded) with 25% reduction in overall project duration", "planning", "predecessor", "2.12", 10, "after", None),
    ("6.1", "Prepare Temporary Project Budget on Oracle", "costctrl", "predecessor", "2.1", 3, "after", None),
    ("6.2", "Prepare Project Baseline Budget on Oracle", "costctrl", "predecessor", "1.3", 14, "after", None),
    ("6.3", "Prepare Project Locked Budget on Oracle (As per signed Contract)", "costctrl", "predecessor", "1.6", 14, "after", None),
    # Item 127 follow-up: closed the gap in Planning's own numbering
    # (was 5.1,5.2,[Cost Control's 5.3/5.4/5.5],5.6,5.7) to a gapless
    # 5.1-5.4 -- cross-references to the old 5.6/5.7 values (Operation
    # Units' 2.12 in every BU variant, and Risk's own item) updated in
    # lockstep to the new 5.3/5.4.
    ("5.3", "Provide Proposal recommendation for working schedule for time schedule driven items", "planning", "predecessor", "5.1", 3, "after", None),
    ("5.4", "Update Planning Risk Register including lesson learned", "planning", "predecessor", "5.2", 3, "after", None),

    ("7.1", "Update Contracts Risk Register and Contract Liabilities", "contract", "predecessor", "1.5", 1, "after", None),

    ("8.1", "Provide Workforce Availability Plan with Hiring dates", "hr", "predecessor", "1.2", 15, "after", None),

    # Item 127 rework: Treasury and Finance no longer share department
    # number 9 -- Treasury keeps 9, Finance moves to 10 (its items become
    # 10.1/10.2 instead of 8.4/8.5). Treasury's 9.1 predecessor updates
    # from "8.4" to "10.1" to follow Finance's own renumber.
    ("9.1", "Secure Bank Facilities for the project / Project Finance Model", "treasury", "predecessor", "10.1", 10, "after", None),
    ("9.2", "Issuance of Performance Bond", "treasury", "predecessor", "1.5", 6, "after", None),
    ("9.3", "Issuance of Advance Payment Guarantee", "treasury", "predecessor", "1.6", 14, "after", None),
    ("10.1", "Provide Updated Cashflow and Finance Cost", "finance", "predecessor", "1.2", 5, "after", None),
    # Item 126: Insurance folded into Finance -- was its own "Insurance" department.
    ("10.2", "Provide Insurance Requirements (Cost & Provider selection)", "finance", "predecessor", "1.6", 10, "after", None),

    # Item 127 rework: Quality and HSSE no longer share department number
    # 10 -- Quality moves to 11, HSSE moves to 12.
    ("11.1", "Provide QA/QC Detailed Plan including ITPs for major activities", "quality", "predecessor", "1.2", 17, "after", None),
    ("12.1", "Provide HSE Detailed Plan (Site Safety, HSE, Safety training)", "hsse", "predecessor", "1.2", 17, "after", None),
    # Item 123/124: "HSSE and Quality Staffing plans" split into one item
    # per department instead of one combined item under a third "HSSE /
    # Quality" department -- both keep the same item_no as each other
    # (11.2/12.2), same as how Operation Units' BU split shares one
    # item_no across several departments.
    ("12.2", "Provide HSSE Staffing plan", "hsse", "predecessor", "1.2", 12, "after", None),
    ("11.2", "Provide Quality Staffing plan", "quality", "predecessor", "1.2", 12, "after", None),
    ("12.3", "Provide Risk Assessment (including identification of main hazards)", "hsse", "predecessor", "1.2", 10, "after", None),
    ("12.4", "Provide Environmental management plan", "hsse", "predecessor", "1.2", 20, "after", None),
    ("12.5", "Provide Waste management plan", "hsse", "predecessor", "1.2", 20, "after", None),

    ("14.1", "Verify and update Project Risk register", "risk", "predecessor", "5.4", 1, "after", None),

    ("15.1", "Provide Updated information on Equipment availability, location", "fleet", "predecessor", "1.6", 7, "after", None),

    ("16.1", "Verify Updated Camp Cost Estimates, Consumptions and Maintenance", "fm", "predecessor", "1.2", 7, "after", None),
]


# ---------------------------------------------------------------------------
# Curated short labels for dense views (Deliverables Matrix, Timeline) —
# keyed by (stage, item_no). Not a mechanical truncation of `name`; each one
# is a deliberately short human summary (e.g. "Float SC RFQ", "Receive GO
# Approval"). Falls back to the full name if an item_no is missing here.
# ---------------------------------------------------------------------------
L0_SHORT_NAMES = {
    "1.1": "Receive GO Approval", "1.2": "Announce Site Visit", "1.3": "Announce Pre-bid Meeting",
    "1.4": "Pre-bid Deadline", "1.5": "Assign Bid Manager", "1.6": "Request Bid Bond",
    "1.7": "Develop Estimate Program", "1.8": "Float SC RFQ", "1.9": "Float Materials RFQ",
    "1.10": "Float Consultant RFQ", "1.11": "Review Project Schedule", "1.12": "Review Execution Plan",
    "1.13": "Prepare Pre-bid Agreements", "1.14": "Incorporate Consultant Findings",
    "1.15": "Incorporate SME Findings", "1.16": "Prepare Manpower Schedule",
    "1.17": "Circulate Technical Offers", "1.18": "Circulate Commercial Offers",
    "1.19": "Develop Tech-Comm Proposal", "1.20": "Adjust Proposal (Comments)",
    "1.21": "Submit Proposal",

    "2.1": "Attend Site Visit", "2.2": "Site Visit Report", "2.3": "Highlight Pre-bid Points",
    "2.4": "Prepare Risk Register", "2.5": "Prepare Execution Plan", "2.6": "Review Project Schedule",

    "3.1": "Prepare Risk Register", "3.2": "Highlight Pre-bid Points", "3.3": "Approved Suppliers List",
    "3.4": "PO & Procurement History", "3.5": "Review Materials Strategy", "3.6": "Long Lead Items List",
    "3.7": "Logistics Pricing Support", "3.8": "Internal Prequalification", "3.9": "Negotiation Rounds",

    "4.1": "Prepare Risk Register", "4.2": "Highlight Pre-bid Points", "4.3": "Site Investigations List",
    "4.4": "Generate Design & BOQ", "4.5": "Value Engineering Studies", "4.6": "Review Technical Offers",
    "4.7": "Support Tech Proposals",

    "5.1": "Prepare Risk Register", "5.2": "Highlight Pre-bid Points", "5.3": "Prepare Project Schedule",
    "5.4": "Verify Quantities", "5.5": "Productivity Norms",

    "6.1": "Prepare Risk Register", "6.2": "Highlight Pre-bid Points", "6.3": "Fleet Productivities",

    "7.1": "Prepare Risk Register", "7.2": "Review Contract Terms", "7.3": "Prepare NDA",
    "7.4": "Review Pre-bid Agreements",

    "8.1": "Verify Local Content", "8.2": "HR Cost Estimates", "8.3": "Workforce Availability",
    "8.4": "Team CVs & Certificates",

    "9.1": "Prepare Risk Register", "9.2": "Issue Bid Bonds",

    "10.1": "Prepare Risk Register", "10.2": "Insurance Cost",
    "10.3": "Proposed Overheads", "10.4": "Cash Flow & Finance Cost",

    "11.1": "Prepare Risk Register", "11.2": "Highlight Pre-bid Points", "11.3": "QA/QC Plan",
    "11.4": "Evaluate Subcontractors", "11.5": "Personnel Requirements",

    "12.1": "Prepare Risk Register", "12.2": "Highlight Pre-bid Points", "12.3": "Safety Requirements & PPE",
    "12.4": "HSE Plan", "12.5": "Personnel Requirements",

    "13.1": "Staff & Office Cost",
    "14.1": "Compile Risk Registers",
    "15.1": "Equipment Cost Estimates", "15.2": "Equipment Availability", "16.1": "Camp Cost Estimates",
}

# [International short names]: L0_INTERNATIONAL_ITEMS reuses the SAME
# item_no scheme as the standard L0 catalog (1.x=Tendering, 2.x=Operations,
# 3.x=Supply Chain, ...) but the wording at each item_no genuinely differs
# between the two catalogs (e.g. standard "1.10" = "Float Consultant RFQ"
# vs international "1.10" = "Float SC RFQ's") -- so this can't reuse
# L0_SHORT_NAMES by item_no, it needs its own curated set. Every
# department-number prefix here (1-19) is unique to one department in
# L0_INTERNATIONAL_ITEMS (unlike L1_ITEMS' TBU/PBU/DBU/BBU, which
# deliberately repeat the same item_no across several departments), so a
# flat item_no key is safe here too.
L0_INTERNATIONAL_SHORT_NAMES = {
    "1.1": "Receive GO Approval", "1.2": "Announce Site Visit", "1.3": "Announce Pre-bid Meeting",
    "1.4": "Pre-bid Deadline", "1.5": "Assign Bid Manager", "1.6": "Request Bid Bond",
    "1.7": "Develop Estimate Program", "1.8": "IBU Participation Decision", "1.9": "Align with Partner",
    "1.10": "Float SC RFQ", "1.11": "Float Materials RFQ", "1.12": "Float Consultant RFQ",
    "1.13": "Circulate Technical Offers", "1.14": "Align with Subsidiary (BD)", "1.15": "Review Project Schedule",
    "1.16": "Review Execution Plan", "1.17": "Incorporate Consultant Findings", "1.18": "Incorporate SME Findings",
    "1.19": "Share Manpower Schedule", "1.20": "Provide BOQ & Price Breakdown", "1.21": "Develop Technical Proposal",
    "1.22": "Develop Commercial Proposal", "1.23": "Adjust Proposal (Comments)", "1.24": "Submit Proposal",

    "2.1": "Attend Site Visit", "2.2": "Site Visit Report", "2.3": "Assign Focal Point",
    "2.4": "Review Local Codes", "2.5": "Check Security & Stability", "2.6": "Site Establishment Plan",
    "2.7": "Highlight Pre-bid Points", "2.8": "Prepare Risk Register", "2.9": "Subcontracting Strategy",
    "2.10": "Prepare Execution Plan", "2.11": "Review Project Schedule",

    "3.1": "Prepare Risk Register", "3.2": "Highlight Pre-bid Points", "3.3": "Prepare Pre-bid Agreements",
    "3.4": "PO & Procurement History", "3.5": "Long Lead Items List", "3.6": "Logistics Pricing Support",
    "3.7": "Internal Prequalification", "3.8": "Negotiation Rounds",

    "4.1": "Prepare Risk Register", "4.2": "Highlight Pre-bid Points", "4.3": "Site Investigations List",
    "4.4": "Equipment Technical RFP", "4.5": "Generate Design & BOQ", "4.6": "Hire Engineering Firm",
    "4.7": "Value Engineering Studies", "4.8": "Review Technical Offers", "4.9": "Support Tech Proposals",

    "5.1": "Prepare Risk Register", "5.2": "Highlight Pre-bid Points", "5.3": "Prepare Project Schedule",
    "5.4": "Verify Quantities",

    "6.1": "Prepare Risk Register", "6.2": "Highlight Pre-bid Points",

    "7.1": "Prepare Risk Register", "7.2": "Highlight Pre-bid Points", "7.3": "Prepare NDA",
    "7.4": "Review Pre-bid Agreements", "7.5": "JV / Consortium Agreement",

    "8.1": "Local Content Report", "8.2": "HR Cost Estimates", "8.3": "Workforce Availability",
    "8.4": "Team CVs & Certificates",

    "9.1": "Prepare Risk Register", "9.2": "Issue Bid Bonds", "9.3": "Financial Capacity Update",

    "10.1": "Prepare Risk Register", "10.2": "Audited Financial Statements", "10.3": "Insurance Certificates",
    "10.4": "Insurance Cost", "10.5": "Proposed Overheads", "10.6": "Cash Flow & Finance Cost",

    "11.1": "Prepare Risk Register", "11.2": "Highlight Pre-bid Points", "11.3": "QA/QC Plan",

    "12.1": "Prepare Risk Register", "12.2": "Highlight Pre-bid Points", "12.3": "Safety Requirements & PPE",
    "12.4": "HSE Plan", "12.5": "Weather & Environment Check",

    "13.1": "Staff & Office Cost",
    "14.1": "Compile Risk Registers",
    "15.1": "Equipment Cost Estimates",
    "16.1": "Camp Cost Estimates",

    "17.1": "Power of Attorney", "17.2": "Litigation Disclosure",

    "18.1": "Partner Communications (BD)", "18.2": "Arrange Site Visit (BD)", "18.3": "Market & Competitor Analysis",
    "18.4": "Ongoing & Completed Projects", "18.5": "Intl Experience References",

    "19.1": "Commercial Registration", "19.2": "Zakat/Tax/VAT Certificates", "19.3": "GOSI Certificate",
    "19.4": "Chamber of Commerce Cert.", "19.5": "Company Profile",
}

L1_SHORT_NAMES = {
    "1.1": "L1 Announcement", "1.2": "Early Mobilization Plan", "1.3": "Commercial & Tech Handover",
    "1.4": "Start Post-Bid Clarification", "1.5": "Receive LOA", "1.6": "Contract Signing",

    "2.1": "Cost Center Request", "2.2": "PR for Long-lead Items", "2.3": "Assign PM & Engineer",
    "2.4": "Internal Kickoff Meeting", "2.5": "Draft Execution Plan", "2.6": "PR for Early Activities",
    "2.7": "PR for Design Firm", "2.8": "Geotechnical Investigation", "2.9": "Topography Investigation",
    "2.10": "Project Permits List", "2.11": "Subcontracting Strategy", "2.12": "Confirm Working Schedule",
    "2.13": "Cost Center Request", "2.14": "PR for MEP Consultancy", "2.15": "BBU Execution Plan Input",
    "2.16": "Temp Facilities Layout", "2.17": "Subcontracting Strategy", "2.18": "Finalize SS Subcontract",

    "3.1": "Issue Vendor RFQ", "3.2": "Negotiate Terms", "3.3": "Award Approval",
    "3.4": "Top Mgmt Award Approval", "3.5": "PO Approval (Oracle)", "3.6": "Internal PO Signature",
    "3.7": "Vendor PO Signature", "3.8": "Finalize OHTL/UGC Subcontract", "3.9": "Share Design Firm Offers",
    "3.10": "Issue Engineering PO", "3.11": "PO for Early Activities", "3.12": "Vendor Prequalification",

    "4.1": "SC Scope (Early Activities)", "4.2": "Update Design & Quantities", "4.3": "SOW for Design Firm",
    "4.4": "Review Design Firm Offers", "4.5": "Review Vendor Offers", "4.6": "Review Vendor Offers (SC)",
    "4.7": "Verify Site Layout", "4.8": "Update Risk Register",

    "5.1": "Baseline Schedule", "5.2": "Working Schedule", "5.3": "Schedule Recommendation",
    "5.4": "Update Risk Register",

    "6.1": "Temp Project Budget", "6.2": "Baseline Budget", "6.3": "Locked Budget",

    "7.1": "Update Risk Register",
    "8.1": "Workforce Availability Plan",

    "9.1": "Secure Bank Facilities", "9.2": "Performance Bond", "9.3": "Advance Payment Guarantee",

    "10.1": "Updated Cashflow", "10.2": "Insurance Requirements",

    "11.1": "QA/QC Detailed Plan", "11.2": "Staffing Plan",

    "12.1": "HSE Detailed Plan", "12.2": "Staffing Plan", "12.3": "Risk Assessment",
    "12.4": "Environmental Plan", "12.5": "Waste Management Plan",

    "14.1": "Update Risk Register",
    "15.1": "Equipment Availability",
    "16.1": "Camp Cost Estimates",
}

# [PO Lifecycle]: which L1 item_nos are tracked once per named PoLineItem
# instead of once per project, and which category they belong to.
# Comma-separated where one definition spans two pools -- "3.11" is the
# shared PO-issuance step for both early_activity and mep items.
LINE_ITEM_CATEGORY_BY_ITEM_NO = {
    "4.5": "long_lead", "2.2": "long_lead", "3.1": "long_lead", "3.2": "long_lead", "4.6": "long_lead",
    "3.3": "long_lead", "3.4": "long_lead", "3.5": "long_lead", "3.6": "long_lead", "3.7": "long_lead",
    "2.6": "early_activity", "2.14": "mep", "3.11": "early_activity,mep",
    "2.7": "consultancy", "3.10": "consultancy",
    "3.8": "sc", "2.18": "sc",
    # [PO Lifecycle #13]: prequalification applies per-item across every
    # real procurement pool -- long-lead, early activities, MEP, S/C.
    # Deliberately excludes consultancy (always exactly one known firm, no
    # real "which vendor" prequalification question there).
    "3.12": "long_lead,early_activity,mep,sc",
}


def _tag_line_item_categories(db):
    """Every DeliverableDefinition row for a LINE_ITEM_CATEGORY_BY_ITEM_NO
    item_no gets its category set -- filtered to L1 only, since several of
    these item_nos (e.g. "2.2", "3.1", "6.1") mean something completely
    different in the L0 catalog. Multiple department variants of the same
    item_no (the TBU/PBU/DBU or Supply Chain/Procurement(PBU) split) all get
    the same tag correctly -- _instantiate_deliverables' existing
    is_bu_applicable/is_scope_variant_applicable filtering already narrows
    which variant is actually active per project.
    """
    defs = (
        db.query(models.DeliverableDefinition)
        .filter(models.DeliverableDefinition.stage == models.Stage.L1,
                models.DeliverableDefinition.item_no.in_(LINE_ITEM_CATEGORY_BY_ITEM_NO))
        .all()
    )
    changed = 0
    for d in defs:
        cat = LINE_ITEM_CATEGORY_BY_ITEM_NO[d.item_no]
        if d.line_item_category != cat:
            d.line_item_category = cat
            changed += 1
    if changed:
        db.commit()
    return changed


def _backfill_po_line_items(db):
    """One-time (idempotent) migration for L1 projects that already had a
    submission for one of these item_nos before line-item tracking existed
    -- each gets a synthetic "Item 1 (migrated)" PoLineItem per category so
    existing in-flight progress is preserved (attached, not orphaned) rather
    than silently disappearing once the UI switches these items to
    line-item-driven rendering. Safe to re-run: only ever touches
    submissions whose po_line_item_id is still NULL.
    """
    projects = db.query(models.Project).filter(models.Project.stage == models.Stage.L1).all()
    created = 0
    for project in projects:
        subs = (
            db.query(models.DeliverableSubmission)
            .join(models.DeliverableDefinition)
            .filter(models.DeliverableSubmission.project_id == project.id,
                    models.DeliverableDefinition.item_no.in_(LINE_ITEM_CATEGORY_BY_ITEM_NO),
                    models.DeliverableSubmission.po_line_item_id.is_(None))
            .all()
        )
        if not subs:
            continue
        by_category: dict[str, list] = {}
        # A multi-category item_no (3.11 -> early_activity/mep; 3.12 ->
        # all four pools) can't be filed under its own raw comma-joined
        # string -- infer the real single category from whichever OTHER,
        # single-category item_no this project's own subs already fall
        # into (e.g. "2.6" present means "early_activity"). Falls back to
        # the first listed candidate on a project with no such sibling yet
        # (single-item-no-only edge case, rare in practice).
        single_cats_present = {
            LINE_ITEM_CATEGORY_BY_ITEM_NO[s.definition.item_no] for s in subs
            if "," not in LINE_ITEM_CATEGORY_BY_ITEM_NO[s.definition.item_no]
        }
        for s in subs:
            cat = LINE_ITEM_CATEGORY_BY_ITEM_NO[s.definition.item_no]
            if "," in cat:
                candidates = [c.strip() for c in cat.split(",")]
                matched = [c for c in candidates if c in single_cats_present]
                cat = matched[0] if matched else candidates[0]
            by_category.setdefault(cat, []).append(s)
        for cat, cat_subs in by_category.items():
            item = models.PoLineItem(project_id=project.id, category=cat, name="Item 1 (migrated)",
                                      source="manual", status="active")
            db.add(item)
            db.flush()
            for s in cat_subs:
                s.po_line_item_id = item.id
            created += 1
    if created:
        db.commit()
    return created


# [Request 5]: L0's own per-item review pattern -- 1.17 (Circulate
# technical offers, Engineering) and 1.18 (Circulate commercial offers,
# Supply Chain -- moved here from 1.21 by item [request 4]) each declare a
# manually-typed list of item names via po_selection.items, the exact same
# "sc" (2.11/2.17) manual-list shape L1 already uses -- no Excel, no MEP
# categories, see po_line_items.py's "l0_tech_offer"/"l0_comm_offer"
# branches. Only 4.6 (Engineering / Engineering (PBU)) and 3.5/3.6/3.7
# (Supply Chain / Procurement (PBU)) fan out this way.
L0_LINE_ITEM_CATEGORY_BY_ITEM_NO = {"4.6": "l0_tech_offer", "3.5": "l0_comm_offer", "3.6": "l0_comm_offer", "3.7": "l0_comm_offer"}
_L0_FAN_OUT_DEPT_NAMES = {"Engineering Department", "Engineering (PBU)", "Supply Chain", "Procurement (PBU)"}


def _tag_l0_line_item_categories(db):
    """Sibling of _tag_line_item_categories above, for L0. Scoped to stage
    L0 AND these exact department names -- the same item_nos also exist
    under L1 (different content entirely, e.g. 3.5-3.7 there are the PO
    Approval/Signature steps) and under the International departments
    (different department names), neither of which this should ever touch.
    """
    defs = (
        db.query(models.DeliverableDefinition)
        .join(models.Department)
        .filter(models.DeliverableDefinition.stage == models.Stage.L0,
                models.DeliverableDefinition.item_no.in_(L0_LINE_ITEM_CATEGORY_BY_ITEM_NO),
                models.Department.name.in_(_L0_FAN_OUT_DEPT_NAMES))
        .all()
    )
    changed = 0
    for d in defs:
        cat = L0_LINE_ITEM_CATEGORY_BY_ITEM_NO[d.item_no]
        if d.line_item_category != cat:
            d.line_item_category = cat
            changed += 1
    if changed:
        db.commit()
    return changed


def _backfill_l0_po_line_items(db):
    """Mirrors _backfill_po_line_items above, for L0 projects that already
    had real (plain, one-row-per-project) progress on 4.6/3.5/3.6/3.7
    before item [request 5] switched them to per-item tracking -- each
    gets a synthetic "Item 1 (migrated)" PoLineItem per category so
    existing in-flight progress stays attached instead of orphaning
    alongside whatever real items get added to 1.17/1.18 going forward.
    Unlike L1's version, no cross-category ambiguity to resolve here (3.5/
    3.6/3.7 always share the one "l0_comm_offer" pool together, never
    split across two candidate categories the way L1's 3.11 is), so no
    "single_cats_present" inference step is needed.
    """
    projects = db.query(models.Project).filter(models.Project.stage == models.Stage.L0).all()
    created = 0
    for project in projects:
        subs = (
            db.query(models.DeliverableSubmission)
            .join(models.DeliverableDefinition)
            .join(models.Department)
            .filter(models.DeliverableSubmission.project_id == project.id,
                    models.DeliverableDefinition.item_no.in_(L0_LINE_ITEM_CATEGORY_BY_ITEM_NO),
                    models.Department.name.in_(_L0_FAN_OUT_DEPT_NAMES),
                    models.DeliverableSubmission.po_line_item_id.is_(None))
            .all()
        )
        if not subs:
            continue
        by_category: dict[str, list] = {}
        for s in subs:
            by_category.setdefault(L0_LINE_ITEM_CATEGORY_BY_ITEM_NO[s.definition.item_no], []).append(s)
        for cat, cat_subs in by_category.items():
            item = models.PoLineItem(project_id=project.id, category=cat, name="Item 1 (migrated)",
                                      source="manual", status="active")
            db.add(item)
            db.flush()
            for s in cat_subs:
                s.po_line_item_id = item.id
            created += 1
    if created:
        db.commit()
    return created


def _has_line_item_gap(db, project) -> bool:
    """Cheap pre-check so _fill_po_line_item_gaps only calls the real
    (notification-firing) _instantiate_deliverables for a project that
    actually needs it -- without this, every seed run (i.e. every deploy)
    would re-notify every owner on every L1 project forever, not just once
    during this migration.
    """
    line_items = db.query(models.PoLineItem).filter(
        models.PoLineItem.project_id == project.id, models.PoLineItem.status == "active").all()
    if not line_items:
        return False
    cats_present = {li.category for li in line_items}
    defs = db.query(models.DeliverableDefinition).filter(
        models.DeliverableDefinition.stage == models.Stage.L1,
        models.DeliverableDefinition.line_item_category.isnot(None)).all()
    # Same applicability filter _instantiate_deliverables itself applies --
    # without it, a BU/scope variant that will never actually be created for
    # this project (e.g. the "(PBU)" copy on a non-PBU project) reads as a
    # permanent false-positive gap on every future deploy.
    defs = [d for d in defs if rules.is_bu_applicable(d, project) and rules.is_scope_variant_applicable(d, project)]
    existing_pairs = {
        (s.deliverable_definition_id, s.po_line_item_id) for s in
        db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.project_id == project.id).all()
    }
    for d in defs:
        cats = [c.strip() for c in d.line_item_category.split(",")]
        if not (set(cats) & cats_present):
            continue
        for li in line_items:
            if li.category in cats and (d.id, li.id) not in existing_pairs:
                return True
    return False


def _fill_po_line_item_gaps(db):
    """"3.11" is shared by early_activity and mep, but a project's one
    pre-existing (pre-migration) row can only attach to whichever of the two
    synthetic items the backfill assigned it to -- the other one is left
    missing its own 3.11 submission. Also the general catch-all for any
    other line-item fan-out gap. _instantiate_deliverables is already the
    idempotent, safe-to-re-run tool for exactly this (skip-set keyed by
    (definition_id, line_item_id), only creates what's missing) -- same
    function every project creation and scope resync already uses. Gated by
    _has_line_item_gap so this is a true no-op (no owner-notification
    side-effect) on every deploy after the gap's actually closed once.
    """
    from .routers.projects import _instantiate_deliverables
    filled = 0
    for project in db.query(models.Project).filter(models.Project.stage == models.Stage.L1).all():
        if _has_line_item_gap(db, project):
            _instantiate_deliverables(db, project)  # recomputes due dates + commits internally
            filled += 1
    return filled


def _ensure_consultancy_line_items(db):
    """Backfill for pre-existing L1 projects -- see
    routers.projects._ensure_consultancy_line_item's docstring for why this
    has to exist at all. New projects get it at creation from that same
    function; this is the one-time catch-up for every project created
    before it existed, since "2.7"/"3.10" (consultancy) had no PoLineItem
    to fan out against on any of them until now.
    """
    from .routers.projects import _instantiate_deliverables, _ensure_consultancy_line_item
    created = 0
    for project in db.query(models.Project).filter(models.Project.stage == models.Stage.L1).all():
        had = db.query(models.PoLineItem).filter(
            models.PoLineItem.project_id == project.id, models.PoLineItem.category == "consultancy",
            models.PoLineItem.status == "active",
        ).first()
        if not had:
            _ensure_consultancy_line_item(db, project)
            _instantiate_deliverables(db, project)  # recomputes due dates + commits internally
            created += 1
    return created


def _seed_branches_for(definition: "models.DeliverableDefinition") -> list[dict]:
    """The initial DeliverableFormulaBranch set for one DeliverableDefinition,
    reproducing today's hardcoded compute_due_date special cases exactly --
    used both for the one-time backfill (every pre-existing row, in run()
    below) and for a future "Restore to Default" admin action. See
    rules.py's PBU_CONDITIONAL_ITEMS/L0_SITE_VISIT_FALLBACK_ITEMS/
    L0_INTL_OR_ITEMS docstrings for why each of these ~14 items is special;
    this is the one place that turns that reference data into real seeded
    branches. Every other date-driven item gets a single "always" branch
    mirroring its own current anchor_type/predecessor_item_no/offset_days/
    offset_direction verbatim; client_dependent/library/on_request items
    get none (no computable due date, matching compute_due_date's own
    "empty branches -> None" rule).
    """
    if definition.deliverable_type in ("library", "on_request") or not definition.anchor_type:
        return []

    item_no = definition.item_no
    is_intl = bool(definition.department.is_international)
    is_l0_std = definition.stage == models.Stage.L0 and not is_intl
    own = {
        "anchor_type": definition.anchor_type, "predecessor_item_no": definition.predecessor_item_no,
        "offset_days": definition.offset_days or 0, "offset_direction": definition.offset_direction or "after",
    }

    if is_l0_std and item_no in rules.PBU_CONDITIONAL_ITEMS:
        return [
            {"branch_order": 0, "condition_type": "scope_contains_pbu",
             "anchor_type": "predecessor", "predecessor_item_no": "4.4", "offset_days": 1, "offset_direction": "after"},
            {"branch_order": 1, "condition_type": "tender_window_lt_days", "condition_value": 30,
             "anchor_type": "predecessor", "predecessor_item_no": "1.1", "offset_days": 3, "offset_direction": "after"},
            {"branch_order": 2, "condition_type": "always",
             "anchor_type": "predecessor", "predecessor_item_no": "1.1", "offset_days": 7, "offset_direction": "after"},
        ]
    if is_l0_std and item_no in rules.L0_SITE_VISIT_FALLBACK_ITEMS:
        return [
            {"branch_order": 0, "condition_type": "site_visit_unset",
             "anchor_type": "announcement", "offset_days": 3, "offset_direction": "after",
             "workday_duration": True},  # "the 3rd working day after announcement", not +3 calendar days
            {"branch_order": 1, "condition_type": "always", **own},
        ]
    if is_l0_std and item_no == "4.4":
        return [
            {"branch_order": 0, "condition_type": "tender_window_lt_days", "condition_value": 15,
             "anchor_type": "predecessor", "predecessor_item_no": "1.1", "offset_days": 5, "offset_direction": "after"},
            {"branch_order": 1, "condition_type": "tender_window_lt_days", "condition_value": 30,
             "anchor_type": "predecessor", "predecessor_item_no": "1.1", "offset_days": 7, "offset_direction": "after"},
            {"branch_order": 2, "condition_type": "tender_window_lt_days", "condition_value": 45,
             "anchor_type": "predecessor", "predecessor_item_no": "1.1", "offset_days": 10, "offset_direction": "after"},
            {"branch_order": 3, "condition_type": "always",
             "anchor_type": "predecessor", "predecessor_item_no": "1.1", "offset_days": 14, "offset_direction": "after"},
        ]
    if is_l0_std and item_no == "5.3":
        return [
            {"branch_order": 0, "condition_type": "tender_window_lt_days", "condition_value": 14,
             "anchor_type": "predecessor", "predecessor_item_no": "1.1", "offset_days": 12, "offset_direction": "after"},
            {"branch_order": 1, "condition_type": "always",
             "anchor_type": "predecessor", "predecessor_item_no": "1.1", "offset_days": 15, "offset_direction": "after"},
        ]
    if is_intl and item_no in rules.L0_INTL_OR_ITEMS:
        alt_pred, alt_offset, alt_direction = rules.L0_INTL_OR_ITEMS[item_no]
        tie = "earliest_of_siblings" if item_no in rules.L0_INTL_OR_ITEMS_EARLIEST_WINS else "latest_of_siblings"
        return [
            {"branch_order": 0, "condition_type": "always", "tie_break": tie, **own},
            {"branch_order": 1, "condition_type": "always", "tie_break": tie,
             "anchor_type": "predecessor", "predecessor_item_no": alt_pred,
             "offset_days": alt_offset, "offset_direction": alt_direction},
        ]
    return [{"branch_order": 0, "condition_type": "always", **own}]


def _backfill_formula_branches(db) -> None:
    """One-time (self-limiting) migration: every DeliverableDefinition
    without a seed_key gets one captured from its own current identity
    (must run before upsert()'s seed_key-keyed lookup below, so a
    pre-existing row is found rather than duplicated), and every definition
    with zero branches gets its initial set from _seed_branches_for --
    covers both this one-time backfill and any brand-new row upsert() adds
    later in the same run.
    """
    needing_key = db.query(models.DeliverableDefinition).filter(
        models.DeliverableDefinition.seed_key.is_(None)
    ).all()
    for d in needing_key:
        d.seed_key = f"{d.stage.value}:{d.item_no}:{d.department_id}"
    if needing_key:
        db.commit()


def _seed_missing_branches(db) -> None:
    needing_branches = (
        db.query(models.DeliverableDefinition)
        .outerjoin(models.DeliverableFormulaBranch)
        .filter(models.DeliverableFormulaBranch.id.is_(None))
        .all()
    )
    for d in needing_branches:
        for b in _seed_branches_for(d):
            db.add(models.DeliverableFormulaBranch(deliverable_definition_id=d.id, **b))
        rules.sync_definition_mirror_columns(d)
    if needing_branches:
        db.commit()


def run():
    db = SessionLocal()
    try:
        for old_name, new_name in DEPARTMENT_RENAMES.items():
            old = db.query(models.Department).filter_by(name=old_name).first()
            if old and not db.query(models.Department).filter_by(name=new_name).first():
                old.name = new_name
        db.commit()

        # L0's "06. Contract" and L1's "L1 Contract" become one shared
        # "Contract" department (matching Tendering/Supply Chain/Engineering/
        # HR, which already work this way) — a plain rename would collide
        # since one of the two target names may already exist, so re-point
        # every deliverable_definition from the L0-only row onto the shared
        # one instead, then drop the now-empty duplicate.
        l0_contract = db.query(models.Department).filter_by(name="06. Contract").first()
        shared_contract = db.query(models.Department).filter_by(name="Contract").first()
        if l0_contract and shared_contract and l0_contract.id != shared_contract.id:
            db.query(models.DeliverableDefinition).filter_by(department_id=l0_contract.id).update(
                {"department_id": shared_contract.id}
            )
            db.delete(l0_contract)
        elif l0_contract and not shared_contract:
            l0_contract.name = "Contract"
        db.commit()

        # Item 126: fold L1's "Insurance" department into "Finance" -- its
        # one deliverable (8.5) moves department, same item_no, same row
        # (so every project's existing 8.5 submission just quietly points
        # at a different department now, no data loss). Then the now-empty
        # Insurance department is retired.
        insurance_dept = db.query(models.Department).filter_by(name="Insurance").first()
        finance_dept = db.query(models.Department).filter_by(name="Finance").first()
        if insurance_dept and finance_dept:
            db.query(models.DeliverableDefinition).filter_by(department_id=insurance_dept.id).update(
                {"department_id": finance_dept.id}
            )
            db.delete(insurance_dept)
            db.commit()

        # Items 123/124: split L1's "HSSE and Quality Staffing plans" (9.3,
        # under a third "HSSE / Quality" department) into one item per
        # department -- the existing 9.3 row is repointed onto HSSE
        # in place (keeps its id, its history, every project's existing
        # submission), and a fresh Quality-side 9.3 gets created alongside
        # it, including a retroactive submission for every project that
        # already has one on the HSSE side -- copying the full completed
        # state across if that one's already approved (the underlying
        # work was genuinely done together), otherwise just matching its
        # applicability (not_required/pending/applicable) and leaving the
        # rest to the normal due-date computation.
        hsse_quality_dept = db.query(models.Department).filter_by(name="HSSE / Quality").first()
        hsse_dept = db.query(models.Department).filter_by(name="HSSE").first()
        quality_dept = db.query(models.Department).filter_by(name="Quality").first()
        if hsse_quality_dept and hsse_dept and quality_dept:
            old_def = db.query(models.DeliverableDefinition).filter_by(
                stage=models.Stage.L1, item_no="9.3", department_id=hsse_quality_dept.id
            ).first()
            if old_def:
                old_def.name = "Provide HSSE Staffing plan"
                old_def.short_name = "Staffing Plan"
                old_def.department_id = hsse_dept.id
                db.commit()

                new_def = models.DeliverableDefinition(
                    stage=models.Stage.L1, item_no="9.3", name="Provide Quality Staffing plan",
                    short_name="Staffing Plan", department_id=quality_dept.id,
                    anchor_type="predecessor", predecessor_item_no="1.2", offset_days=12, offset_direction="after",
                    deliverable_type="date_driven", default_owner_email=TEST_EMAIL, default_sme_email=TEST_EMAIL,
                )
                db.add(new_def)
                db.commit()
                db.refresh(new_def)

                for sub in db.query(models.DeliverableSubmission).filter_by(deliverable_definition_id=old_def.id).all():
                    dup = models.DeliverableSubmission(
                        project_id=sub.project_id, deliverable_definition_id=new_def.id,
                        owner_email=sub.owner_email, sme_email=sub.sme_email, applicability=sub.applicability,
                    )
                    if sub.status == models.SubmissionStatus.APPROVED:
                        dup.status = models.SubmissionStatus.APPROVED
                        dup.due_date = sub.due_date
                        dup.submitted_at = sub.submitted_at
                        dup.reviewed_at = sub.reviewed_at
                        dup.review_comment = sub.review_comment
                        dup.file_name = sub.file_name
                        dup.file_ref = sub.file_ref
                    db.add(dup)
                db.commit()

            # The department is only actually empty once its one item has
            # been moved off it above -- re-check rather than assuming.
            if not db.query(models.DeliverableDefinition).filter_by(department_id=hsse_quality_dept.id).first():
                db.delete(hsse_quality_dept)
                db.commit()

        # Item 127/129: L0's separate "Risk Department" folds into the
        # shared "Risk" department L1 already uses -- both are the same
        # real department, previously just split across two rows (and two
        # inconsistent numbers, 11 on L0 vs 10 on L1) by accident.
        old_risk = db.query(models.Department).filter_by(name="Risk Department").first()
        risk_dept = db.query(models.Department).filter_by(name="Risk").first()
        if old_risk and risk_dept and old_risk.id != risk_dept.id:
            db.query(models.DeliverableDefinition).filter_by(department_id=old_risk.id).update(
                {"department_id": risk_dept.id}
            )
            db.delete(old_risk)
            db.commit()
        elif old_risk and not risk_dept:
            old_risk.name = "Risk"
            db.commit()

        # Item 129: L0's "Control Department" (5.1-5.6) merges into the
        # shared "Planning" department (same department L1 already uses) --
        # then item 5.4 moves on to "Cost Control" (a clean single-item
        # move, its content is Cost-Control-specific), and 5.1/5.2 (Risk
        # Register, Pre-bid clarifications) get a real Cost Control-side
        # duplicate too since both departments need their own copy,
        # mirroring item 124's 9.3 split -- including copying
        # already-approved state across for existing projects.
        control_dept = db.query(models.Department).filter_by(name="Control Department").first()
        planning_dept = db.query(models.Department).filter_by(name="Planning").first()
        if control_dept and planning_dept and control_dept.id != planning_dept.id:
            db.query(models.DeliverableDefinition).filter_by(department_id=control_dept.id).update(
                {"department_id": planning_dept.id}
            )
            db.delete(control_dept)
            db.commit()
        elif control_dept and not planning_dept:
            control_dept.name = "Planning"
            planning_dept = control_dept
            db.commit()

        # The rest of item 129 (moving Fleet Productivities off Planning
        # onto Cost Control, and duplicating Risk Register/Pre-bid
        # clarifications for Cost Control) already fully completed in an
        # earlier deploy -- Cost Control has permanently had its own
        # 6.1/6.2/6.3 since then. That code is retired rather than left in
        # place: its guards matched on Planning/Cost Control's OLD 5.x
        # item_no values, which the item 127 follow-up renumbering (Cost
        # Control -> 6.x) made stale -- left running, it would misfire on
        # every future seed (mistaking Planning's now-permanent "5.4" for
        # the long-gone Fleet Productivities item, and endlessly
        # recreating "already exists" duplicates for Cost Control's Risk
        # Register/Pre-bid since the guard's "already" check still looked
        # for them at the old 5.1/5.2, not their real home at 6.1/6.2).

        # Item 128: L0's old combined "Fleet and Facility Management
        # Department" splits across the shared "Fleet" (equipment,
        # 12.1/12.2) and "FM" (camp, 12.3) departments L1 already uses -- a
        # clean single-item-each move, no duplication needed.
        old_fleet_fm = db.query(models.Department).filter_by(name="Fleet and Facility Management Department").first()
        fleet_dept = db.query(models.Department).filter_by(name="Fleet").first()
        fm_dept = db.query(models.Department).filter_by(name="FM").first()
        if old_fleet_fm and fleet_dept and fm_dept:
            db.query(models.DeliverableDefinition).filter_by(
                department_id=old_fleet_fm.id, stage=models.Stage.L0, item_no="12.3"
            ).update({"department_id": fm_dept.id})
            db.query(models.DeliverableDefinition).filter_by(department_id=old_fleet_fm.id).update(
                {"department_id": fleet_dept.id}
            )
            db.commit()
            if not db.query(models.DeliverableDefinition).filter_by(department_id=old_fleet_fm.id).first():
                db.delete(old_fleet_fm)
                db.commit()

        # Item 122 rework: L1's own plain-named "TBU"/"PBU"/"DBU"/"BBU"
        # departments (created earlier this session) merge into the same
        # "Operation Units (TBU)" etc. rows L0's item 69 split already
        # uses -- so the folder list nests them under a shared "2.
        # Operation Units" group header instead of showing as separate
        # ungrouped rows, matching L0's presentation exactly.
        for plain_name, shared_name in (
            ("TBU", "Operation Units (TBU)"), ("PBU", "Operation Units (PBU)"),
            ("DBU", "Operation Units (DBU)"), ("BBU", "Operation Units (BBU)"),
        ):
            plain_dept = db.query(models.Department).filter_by(name=plain_name).first()
            shared_dept = db.query(models.Department).filter_by(name=shared_name).first()
            if plain_dept and shared_dept and plain_dept.id != shared_dept.id:
                db.query(models.DeliverableDefinition).filter_by(department_id=plain_dept.id).update(
                    {"department_id": shared_dept.id}
                )
                db.delete(plain_dept)
                db.commit()

        # Item 141: L0's combined "Financial Department" splits across
        # Treasury (Risk Register duplicated + Issue Bid Bonds) and Finance
        # (Risk Register original + Insurance Cost + Overheads + Cash
        # Flow), mirroring L1's existing Treasury/Finance split -- same
        # duplicate-shared-item pattern as item 129's Planning/Cost Control
        # Risk Register duplication. Runs on the OLD (pre-renumber) item_no
        # values -- the renumber pass right after this fixes item_no itself.
        old_financial_dept = db.query(models.Department).filter_by(name="Financial Department").first()
        treasury_dept = db.query(models.Department).filter_by(name="Treasury").first()
        finance_dept = db.query(models.Department).filter_by(name="Finance").first()
        if old_financial_dept and treasury_dept and finance_dept:
            db.query(models.DeliverableDefinition).filter_by(
                department_id=old_financial_dept.id, stage=models.Stage.L0, item_no="8.2"
            ).update({"department_id": treasury_dept.id})
            db.query(models.DeliverableDefinition).filter(
                models.DeliverableDefinition.department_id == old_financial_dept.id,
                models.DeliverableDefinition.stage == models.Stage.L0,
                models.DeliverableDefinition.item_no.in_(["8.3", "8.4", "8.5"]),
            ).update({"department_id": finance_dept.id}, synchronize_session=False)
            db.commit()

            old_def = db.query(models.DeliverableDefinition).filter_by(
                stage=models.Stage.L0, item_no="8.1", department_id=old_financial_dept.id
            ).first()
            if old_def:
                old_def.department_id = finance_dept.id
                db.commit()

                already = db.query(models.DeliverableDefinition).filter_by(
                    stage=models.Stage.L0, item_no="8.1", department_id=treasury_dept.id
                ).first()
                if not already:
                    new_def = models.DeliverableDefinition(
                        stage=models.Stage.L0, item_no="8.1", name=old_def.name, short_name=old_def.short_name,
                        department_id=treasury_dept.id,
                        anchor_type=old_def.anchor_type, predecessor_item_no=old_def.predecessor_item_no,
                        offset_days=old_def.offset_days, offset_direction=old_def.offset_direction,
                        deliverable_type=old_def.deliverable_type,
                        default_owner_email=TEST_EMAIL, default_sme_email=TEST_EMAIL,
                    )
                    db.add(new_def)
                    db.commit()
                    db.refresh(new_def)

                    affected_projects = []
                    for sub in db.query(models.DeliverableSubmission).filter_by(deliverable_definition_id=old_def.id).all():
                        dup = models.DeliverableSubmission(
                            project_id=sub.project_id, deliverable_definition_id=new_def.id,
                            owner_email=sub.owner_email, sme_email=sub.sme_email, applicability=sub.applicability,
                        )
                        if sub.status == models.SubmissionStatus.APPROVED:
                            dup.status = models.SubmissionStatus.APPROVED
                            dup.due_date = sub.due_date
                            dup.submitted_at = sub.submitted_at
                            dup.reviewed_at = sub.reviewed_at
                            dup.review_comment = sub.review_comment
                            dup.file_name = sub.file_name
                            dup.file_ref = sub.file_ref
                        else:
                            affected_projects.append(sub.project)
                        db.add(dup)
                    db.commit()
                    for proj in affected_projects:
                        rules.recompute_project_due_dates(db, proj, force=True)
                    db.commit()

            if not db.query(models.DeliverableDefinition).filter_by(department_id=old_financial_dept.id).first():
                db.delete(old_financial_dept)
                db.commit()

        # Item 141: L0's combined "SHEQ Department" splits across Quality
        # (QA/QC Plan + Evaluate Subcontractors) and HSSE (Risk Register +
        # Pre-bid clarifications + Safety/PPE + HSE Plan + Personnel
        # Requirements), mirroring L1's existing Quality/HSSE split --
        # clean single-item moves, no duplication needed since every item
        # lands on exactly one side.
        old_sheq_dept = db.query(models.Department).filter_by(name="SHEQ Department").first()
        quality_dept = db.query(models.Department).filter_by(name="Quality").first()
        hsse_dept = db.query(models.Department).filter_by(name="HSSE").first()
        if old_sheq_dept and quality_dept and hsse_dept:
            db.query(models.DeliverableDefinition).filter(
                models.DeliverableDefinition.department_id == old_sheq_dept.id,
                models.DeliverableDefinition.stage == models.Stage.L0,
                models.DeliverableDefinition.item_no.in_(["9.4", "9.6"]),
            ).update({"department_id": quality_dept.id}, synchronize_session=False)
            db.query(models.DeliverableDefinition).filter(
                models.DeliverableDefinition.department_id == old_sheq_dept.id,
                models.DeliverableDefinition.stage == models.Stage.L0,
                models.DeliverableDefinition.item_no.in_(["9.1", "9.2", "9.3", "9.5", "9.7"]),
            ).update({"department_id": hsse_dept.id}, synchronize_session=False)
            db.commit()

            if not db.query(models.DeliverableDefinition).filter_by(department_id=old_sheq_dept.id).first():
                db.delete(old_sheq_dept)
                db.commit()

        # Item 141 rework: corrected the Quality/HSSE split -- Quality now
        # gets Risk Register, Pre-bid clarifications, and Personnel
        # Requirements too (moved off HSSE), keeping QA/QC Plan and
        # Evaluate Subcontractors it already had; HSSE keeps only
        # Safety/PPE and the HSE Plan. Guarded by NAME, not item_no --
        # after this runs once, HSSE's own remaining items get renumbered
        # down to 12.1/12.2, which would coincidentally match the OLD
        # item_no this block searches for and misfire on the next deploy
        # if the guard weren't renumber-proof (item_no values get reused
        # across unrelated migrations; a real deliverable's name doesn't).
        quality_dept3 = db.query(models.Department).filter_by(name="Quality").first()
        hsse_dept3 = db.query(models.Department).filter_by(name="HSSE").first()
        already_reworked = quality_dept3 and db.query(models.DeliverableDefinition).filter_by(
            stage=models.Stage.L0, department_id=quality_dept3.id, name="Prepare Risk Register"
        ).first()
        if quality_dept3 and hsse_dept3 and not already_reworked:
            db.query(models.DeliverableDefinition).filter(
                models.DeliverableDefinition.department_id == hsse_dept3.id,
                models.DeliverableDefinition.stage == models.Stage.L0,
                models.DeliverableDefinition.item_no.in_(["12.1", "12.2", "12.5"]),
            ).update({"department_id": quality_dept3.id}, synchronize_session=False)
            db.commit()

            personnel_def = db.query(models.DeliverableDefinition).filter_by(
                stage=models.Stage.L0, item_no="12.5", department_id=quality_dept3.id
            ).first()
            if personnel_def and "HSSE" in (personnel_def.name or ""):
                personnel_def.name = "Standard Personnel Requirements (Client's Standards)"
                db.commit()

            # Renumber Quality's now-5 items to 11.1-11.5 -- existing
            # 11.1/11.2 (QA/QC Plan, Evaluate Subcontractors) must move out
            # of the way (to 11.3/11.4) BEFORE the moved-in items (12.1,
            # 12.2) claim 11.1/11.2, or the lookup below would collide.
            for old_no, new_no in [("11.2", "11.4"), ("11.1", "11.3"), ("12.1", "11.1"), ("12.2", "11.2"), ("12.5", "11.5")]:
                d = db.query(models.DeliverableDefinition).filter_by(
                    stage=models.Stage.L0, item_no=old_no, department_id=quality_dept3.id
                ).first()
                if d:
                    d.item_no = new_no
                    db.flush()  # keep each rename visible to the next iteration's lookup -- session is autoflush=False
            db.commit()

            # HSSE's two remaining items (Safety/PPE, HSE Plan) renumber
            # down to 12.1/12.2.
            for old_no, new_no in [("12.3", "12.1"), ("12.4", "12.2")]:
                d = db.query(models.DeliverableDefinition).filter_by(
                    stage=models.Stage.L0, item_no=old_no, department_id=hsse_dept3.id
                ).first()
                if d:
                    d.item_no = new_no
                    db.flush()
            db.commit()

        # Item 141 third rework: reverted -- HSSE keeps its own full
        # original 5 items instead of losing Risk Register/Pre-bid
        # clarifications/Personnel Requirements to Quality. Since the
        # prior rework already moved those off HSSE, this duplicates them
        # back from Quality's now-permanent copies (mirroring Treasury/
        # Finance's own Risk Register duplication) rather than trying to
        # "undo" a move -- copying already-approved state across for
        # existing projects. Guarded by name, not item_no, same reasoning
        # as the rework above.
        quality_dept4 = db.query(models.Department).filter_by(name="Quality").first()
        hsse_dept4 = db.query(models.Department).filter_by(name="HSSE").first()
        already_restored = hsse_dept4 and db.query(models.DeliverableDefinition).filter_by(
            stage=models.Stage.L0, department_id=hsse_dept4.id, name="Prepare Risk Register"
        ).first()
        if quality_dept4 and hsse_dept4 and not already_restored:
            # HSSE's two remaining items (Safety/PPE, HSE Plan) make room
            # by moving from 12.1/12.2 to their final 12.3/12.4 first.
            for old_no, new_no in [("12.2", "12.4"), ("12.1", "12.3")]:
                d = db.query(models.DeliverableDefinition).filter_by(
                    stage=models.Stage.L0, item_no=old_no, department_id=hsse_dept4.id
                ).first()
                if d:
                    d.item_no = new_no
                    db.flush()
            db.commit()

            for src_item_no, new_item_no in [("11.1", "12.1"), ("11.2", "12.2"), ("11.5", "12.5")]:
                src_def = db.query(models.DeliverableDefinition).filter_by(
                    stage=models.Stage.L0, item_no=src_item_no, department_id=quality_dept4.id
                ).first()
                if not src_def:
                    continue
                new_def = models.DeliverableDefinition(
                    stage=models.Stage.L0, item_no=new_item_no, name=src_def.name, short_name=src_def.short_name,
                    department_id=hsse_dept4.id,
                    anchor_type=src_def.anchor_type, predecessor_item_no=src_def.predecessor_item_no,
                    offset_days=src_def.offset_days, offset_direction=src_def.offset_direction,
                    deliverable_type=src_def.deliverable_type,
                    default_owner_email=TEST_EMAIL, default_sme_email=TEST_EMAIL,
                )
                db.add(new_def)
                db.commit()
                db.refresh(new_def)

                affected_projects = []
                for sub in db.query(models.DeliverableSubmission).filter_by(deliverable_definition_id=src_def.id).all():
                    dup = models.DeliverableSubmission(
                        project_id=sub.project_id, deliverable_definition_id=new_def.id,
                        owner_email=sub.owner_email, sme_email=sub.sme_email, applicability=sub.applicability,
                    )
                    if sub.status == models.SubmissionStatus.APPROVED:
                        dup.status = models.SubmissionStatus.APPROVED
                        dup.due_date = sub.due_date
                        dup.submitted_at = sub.submitted_at
                        dup.reviewed_at = sub.reviewed_at
                        dup.review_comment = sub.review_comment
                        dup.file_name = sub.file_name
                        dup.file_ref = sub.file_ref
                    else:
                        affected_projects.append(sub.project)
                    db.add(dup)
                db.commit()
                for proj in affected_projects:
                    rules.recompute_project_due_dates(db, proj, force=True)
                db.commit()

        # Item 127 rework: full sequential renumbering -- Treasury/Finance
        # and Quality/HSSE no longer share one department number each, so
        # every item_no under a renumbered department gets rewritten to
        # match (e.g. L1 Finance's items become 10.1/10.2 instead of
        # 8.4/8.5). Plain old_item_no -> new_item_no swaps on whichever row
        # the department move above already relocated -- department itself
        # is untouched here. Runs before the upsert loop below so its
        # (stage, item_no, department_id) lookup finds the existing row
        # instead of creating a stray duplicate.
        _ITEM_NO_RENUMBER = [
            # Item 127 follow-up: the first renumbering pass only touched
            # departments actually moved by the Financial/SHEQ split
            # (Treasury onward) -- Cost Control/Contract/HR kept their
            # original template item_no prefixes (5.x/6.x/7.x) even though
            # their folder numbers had already moved to 6/7/8, so the
            # deliverable numbers shown never matched the folder header.
            # Same plain rename pattern, just extended to these three.
            (models.Stage.L0, "Cost Control", "5.1", "6.1"), (models.Stage.L0, "Cost Control", "5.2", "6.2"),
            (models.Stage.L0, "Cost Control", "5.4", "6.3"),
            # Item 127 follow-up: closed Planning's own numbering gap (was
            # 5.1,5.2,5.3,5.5,5.6, skipping 5.4 since that slot always
            # belonged to Cost Control's own item) to a gapless 5.1-5.5.
            # Order matters: 5.5 must vacate to 5.4 before 5.6 claims 5.5.
            (models.Stage.L0, "Planning", "5.5", "5.4"), (models.Stage.L0, "Planning", "5.6", "5.5"),
            # Same for L1 Planning: was 5.1,5.2,[Cost Control's 5.3-5.5],
            # 5.6,5.7 -- closed to a gapless 5.1-5.4. Cross-references to
            # the old 5.6/5.7 (Operation Units' 2.12 in every BU variant,
            # and Risk's own item) already point at the new 5.3/5.4 in the
            # L1_ITEMS tuples above, so no further updates needed here.
            (models.Stage.L1, "Planning", "5.6", "5.3"), (models.Stage.L1, "Planning", "5.7", "5.4"),
            (models.Stage.L0, "Contract", "6.1", "7.1"), (models.Stage.L0, "Contract", "6.2", "7.2"),
            (models.Stage.L0, "Contract", "6.3", "7.3"), (models.Stage.L0, "Contract", "6.4", "7.4"),
            (models.Stage.L0, "Human Resources", "7.1", "8.1"), (models.Stage.L0, "Human Resources", "7.2", "8.2"),
            (models.Stage.L0, "Human Resources", "7.3", "8.3"), (models.Stage.L0, "Human Resources", "7.4", "8.4"),
            (models.Stage.L1, "Cost Control", "5.3", "6.1"), (models.Stage.L1, "Cost Control", "5.4", "6.2"),
            (models.Stage.L1, "Cost Control", "5.5", "6.3"),
            (models.Stage.L1, "Contract", "6.1", "7.1"),
            (models.Stage.L1, "Human Resources", "7.1", "8.1"),
            (models.Stage.L0, "Treasury", "8.1", "9.1"), (models.Stage.L0, "Treasury", "8.2", "9.2"),
            (models.Stage.L0, "Finance", "8.1", "10.1"), (models.Stage.L0, "Finance", "8.3", "10.2"),
            (models.Stage.L0, "Finance", "8.4", "10.3"), (models.Stage.L0, "Finance", "8.5", "10.4"),
            (models.Stage.L0, "Quality", "9.4", "11.1"), (models.Stage.L0, "Quality", "9.6", "11.2"),
            (models.Stage.L0, "HSSE", "9.1", "12.1"), (models.Stage.L0, "HSSE", "9.2", "12.2"),
            (models.Stage.L0, "HSSE", "9.3", "12.3"), (models.Stage.L0, "HSSE", "9.5", "12.4"),
            (models.Stage.L0, "HSSE", "9.7", "12.5"),
            (models.Stage.L0, "IT Department", "10.1", "13.1"),
            (models.Stage.L0, "Risk", "11.1", "14.1"),
            (models.Stage.L0, "Fleet", "12.1", "15.1"), (models.Stage.L0, "Fleet", "12.2", "15.2"),
            (models.Stage.L0, "FM", "12.3", "16.1"),
            (models.Stage.L1, "Treasury", "8.1", "9.1"), (models.Stage.L1, "Treasury", "8.2", "9.2"),
            (models.Stage.L1, "Treasury", "8.3", "9.3"),
            (models.Stage.L1, "Finance", "8.4", "10.1"), (models.Stage.L1, "Finance", "8.5", "10.2"),
            (models.Stage.L1, "Quality", "9.1", "11.1"), (models.Stage.L1, "Quality", "9.3", "11.2"),
            (models.Stage.L1, "HSSE", "9.2", "12.1"), (models.Stage.L1, "HSSE", "9.3", "12.2"),
            (models.Stage.L1, "HSSE", "9.4", "12.3"), (models.Stage.L1, "HSSE", "9.5", "12.4"),
            (models.Stage.L1, "HSSE", "9.6", "12.5"),
            (models.Stage.L1, "Risk", "10.1", "14.1"),
            (models.Stage.L1, "Fleet", "11.1", "15.1"),
            (models.Stage.L1, "FM", "12.1", "16.1"),
        ]
        renumbered = 0
        for stage_val, dept_name, old_no, new_no in _ITEM_NO_RENUMBER:
            dept = db.query(models.Department).filter_by(name=dept_name).first()
            if not dept:
                continue
            # Skip if the target value is already occupied -- on a repeat
            # seed run, an earlier rename may have already landed a row on
            # new_no, and old_no can by then coincidentally belong to an
            # unrelated, already-correct row (bit us once already: on a
            # second run, Planning's real "5.5" Productivity Norms item
            # got wrongly renamed to "5.4" because "5.4"->"5.5" from a
            # DIFFERENT department's now-completed rename left "5.5" as a
            # stale old_no this entry still matched on). This makes every
            # entry safely re-appliable regardless of run count.
            already_at_target = db.query(models.DeliverableDefinition).filter_by(
                stage=stage_val, item_no=new_no, department_id=dept.id
            ).first()
            if already_at_target:
                continue
            d = db.query(models.DeliverableDefinition).filter_by(
                stage=stage_val, item_no=old_no, department_id=dept.id
            ).first()
            if d:
                d.item_no = new_no
                # Session is autoflush=False, so without this the "already
                # occupied" check above stays blind to renames earlier in
                # THIS SAME loop -- chained entries (Planning: 5.5->5.4
                # then 5.6->5.5) need the first rename actually visible in
                # the DB before the second one's guard query runs, or the
                # guard sees the row still sitting at its pre-rename value
                # and wrongly thinks the target is taken, skipping a
                # rename that should have gone through (this is exactly
                # how Planning ended up with a genuine duplicate on
                # production: id=54 stuck at "5.6" while upsert() quietly
                # created a fresh id=213 at "5.5" right next to it).
                db.flush()
                renumbered += 1
        if renumbered:
            db.commit()
            print(f"Renumbered {renumbered} deliverable definition(s) — Treasury/Finance/Quality/HSSE/IT/Risk/Fleet/FM sequential renumber.")

        # One-time cleanup: the missing-flush bug above (now fixed) let a
        # prior deploy's Planning "5.6"->"5.5" rename get silently skipped
        # while upsert() went ahead and created a brand-new "5.5" row for
        # the same content anyway -- leaving a genuine duplicate ("Provide
        # Updated Productivity Norms...", one row correctly targeted for
        # rename and stuck at the old "5.6", one freshly created at
        # "5.5"). Detected by content (same name, same department) rather
        # than by id, so this also cleans up if the same failure mode
        # ever recurs elsewhere -- keeps the older (lower id) row, which
        # is the one real projects' submissions point at, moves over any
        # submissions the newer duplicate already picked up (only for
        # projects the surviving row doesn't already have one for), then
        # retires the duplicate.
        dup_groups: dict[tuple, list] = {}
        for d in db.query(models.DeliverableDefinition).filter_by(active=True).all():
            key = (d.stage, d.department_id, d.name)
            dup_groups.setdefault(key, []).append(d)
        cleaned = 0
        for (stage_key, dept_id, name_key), rows in dup_groups.items():
            if len(rows) < 2:
                continue
            rows.sort(key=lambda r: r.id)
            keeper, extras = rows[0], rows[1:]
            for extra in extras:
                keeper_project_ids = {
                    s.project_id for s in db.query(models.DeliverableSubmission)
                    .filter_by(deliverable_definition_id=keeper.id).all()
                }
                for sub in db.query(models.DeliverableSubmission).filter_by(deliverable_definition_id=extra.id).all():
                    if sub.project_id in keeper_project_ids:
                        db.delete(sub)
                    else:
                        sub.deliverable_definition_id = keeper.id
                # The extra (spurious) row was created by upsert() reading
                # the CURRENT catalog tuple, so its item_no is the correct
                # final value -- the keeper is the one still stuck at the
                # stale pre-rename number.
                keeper.item_no = extra.item_no
                db.flush()
                db.delete(extra)
                cleaned += 1
        if cleaned:
            db.commit()
            print(f"Cleaned up {cleaned} duplicate deliverable definition(s) from the missing-flush bug.")

        dept_map = {}
        for name in DEPARTMENTS:
            dept = db.query(models.Department).filter_by(name=name).first()
            if not dept:
                dept = models.Department(name=name)
                db.add(dept)
                db.flush()
            dept.focal_point_email = dept.focal_point_email or TEST_EMAIL
            dept.focal_point_name = dept.focal_point_name or f"TEST focal ({name})"
            dept.number = DEPARTMENT_NUMBERS.get(name)
            # [L0 International]: flags these department rows so Performance/
            # Focal Points can show them only in their own International
            # subtab, hidden from the standard L0 view.
            dept.is_international = name in INTERNATIONAL_DEPARTMENTS
            dept_map[name] = dept
        db.commit()

        # [Deliverables Configuration]: must run before upsert() below --
        # backfills seed_key from each row's own current identity so
        # upsert()'s new seed_key-keyed lookup finds pre-existing rows
        # instead of duplicating them. No-op (fast query, zero updates) on
        # every run after the first.
        _backfill_formula_branches(db)

        def upsert(stage, item_no, name, short_name, dept_id, anchor_type, pred, offset, direction, dtype, is_ms, ms_code):
            seed_key = f"{stage}:{item_no}:{dept_id}"
            existing = db.query(models.DeliverableDefinition).filter_by(seed_key=seed_key).first()
            if existing:
                # [Deliverables Configuration]: an admin edit or an approved
                # formula-change suggestion sets is_customized=True -- once
                # set, this catalog's own hardcoded values never overwrite
                # the customization again. "Restore to Default" is the only
                # way back; it clears the flag and re-applies these exact
                # values directly (not through upsert()).
                if existing.is_customized:
                    return
                existing.name = name
                existing.short_name = short_name
                existing.anchor_type = anchor_type
                existing.predecessor_item_no = pred
                existing.offset_days = offset
                existing.offset_direction = direction
                existing.deliverable_type = dtype
                existing.is_milestone = is_ms
                existing.milestone_code = ms_code
                existing.milestone_name = ms_code
                return
            db.add(models.DeliverableDefinition(
                stage=stage, item_no=item_no, name=name, short_name=short_name, department_id=dept_id,
                anchor_type=anchor_type, predecessor_item_no=pred, offset_days=offset,
                offset_direction=direction, deliverable_type=dtype,
                is_milestone=is_ms, milestone_code=ms_code, milestone_name=ms_code,
                default_owner_email=TEST_EMAIL, default_sme_email=TEST_EMAIL,
                seed_key=seed_key,
            ))

        # Excel-formula replication (8 hardcoded L1 Start/Finish formulas):
        # snapshot these definitions' anchor fields before upsert() overwrites
        # them in place, so we can tell afterward whether this run actually
        # changed anything and needs to force a same-day recompute on
        # existing projects (recompute_project_due_dates otherwise skips a
        # project already computed today, per its own once-a-day gate).
        # Naturally idempotent: a no-op on every run after the first, once
        # the DB already matches L1_ITEMS. 3.4-3.7 added for the PO
        # Lifecycle duration correction (3.3 unchanged, listed anyway).
        _due_fix_items = ["2.2", "2.8", "3.2", "4.4", "7.1", "14.1", "3.3", "3.4", "3.5", "3.6", "3.7"]
        _due_fix_before = {
            (d.item_no, d.department_id): (d.anchor_type, d.predecessor_item_no, d.offset_days)
            for d in db.query(models.DeliverableDefinition)
            .filter(models.DeliverableDefinition.stage == models.Stage.L1,
                    models.DeliverableDefinition.item_no.in_(_due_fix_items))
            .all()
        }
        # Item [request 4]: L0 domestic Tendering's 1.18/1.19/1.20/1.21
        # renumber -- "Circulate commercial offers" (was 1.21) moves to
        # 1.18 to sit next to its technical-offer sibling 1.17 (item
        # [request 5] then makes both per-item declaring items), and
        # 1.18/1.19/1.20 (Develop Tech-Comm Proposal / Adjust Proposals /
        # Submit Proposal, M5) shift up one slot each. A straight 4-cycle
        # (18->19->20->21->18) has no slot that's free to move into first,
        # so the row that would collide detours through a temporary
        # item_no. seed_key is deliberately updated alongside item_no
        # (unlike a plain admin rename via the UI, which leaves seed_key
        # frozen on purpose -- see its own docstring in models.py) because
        # this is the catalog's own source-of-truth renumbering: L0_ITEMS
        # below now supplies these item_nos permanently, so upsert()'s
        # seed_key-keyed lookup must move with them or every future deploy
        # would stop finding these rows and insert duplicates instead.
        # Guarded by NAME, not seed_key -- the rename below deliberately
        # rewrites seed_key to track each row's new item_no (see the big
        # comment above), which means seed_key can never be used as the
        # "already done" marker: it stops matching its own guard the
        # moment the very first run succeeds, so a seed_key-keyed guard
        # would silently re-fire the whole rename dance on every later
        # deploy, rotating which physical row holds which item_no forever
        # (upsert() below self-heals the *displayed* name/predecessor each
        # time via its own seed_key lookup, masking the bug completely --
        # but every existing DeliverableSubmission still points at a fixed
        # deliverable_definition_id, so the row a real submission is
        # attached to would silently drift to a different item_no on every
        # future deploy). Same reasoning, and the same fix, as the
        # Quality/HSSE rework migration above. Also a safe no-op on a
        # brand-new DB (nothing to rename yet -- L0_ITEMS below seeds the
        # correct numbering directly).
        tendering_dept5 = db.query(models.Department).filter_by(name="Tendering Department").first()
        already_renumbered5 = tendering_dept5 and db.query(models.DeliverableDefinition).filter_by(
            stage=models.Stage.L0, department_id=tendering_dept5.id, item_no="1.18",
        ).filter(models.DeliverableDefinition.name.like("Circulate commercial offers%")).first()
        if tendering_dept5 and not already_renumbered5:
            def _rename_l0_tendering_item(old_no, new_no):
                d = db.query(models.DeliverableDefinition).filter_by(
                    stage=models.Stage.L0, item_no=old_no, department_id=tendering_dept5.id,
                ).first()
                if d:
                    d.item_no = new_no
                    d.seed_key = f"L0:{new_no}:{tendering_dept5.id}"
                    db.flush()
            _rename_l0_tendering_item("1.21", "1.18-tmp")
            _rename_l0_tendering_item("1.20", "1.21")
            _rename_l0_tendering_item("1.19", "1.20")
            _rename_l0_tendering_item("1.18", "1.19")
            _rename_l0_tendering_item("1.18-tmp", "1.18")
            db.commit()

        # Same snapshot-before-upsert trick as the L1 block above, for L0's
        # 5.4/8.4 offset change (3 -> 10 and 3 -> 5 workdays after 1.1),
        # and now also the item [request 4] renumber's predecessor
        # rewiring (1.6/7.1/9.2/10.2 now point at 1.21 instead of 1.20;
        # 3.5/3.6/3.7/11.4 now point at 1.18 instead of 1.21; 1.19/1.20 now
        # chain 1.19->1.21, 1.20->1.19) -- forces a same-day recompute on
        # existing projects instead of waiting for tomorrow's first read.
        _l0_due_fix_items = ["5.4", "8.4", "1.6", "1.18", "1.19", "1.20", "1.21", "3.5", "3.6", "3.7", "7.1", "9.2", "10.2", "11.4"]
        _l0_due_fix_before = {
            (d.item_no, d.department_id): (d.anchor_type, d.predecessor_item_no, d.offset_days)
            for d in db.query(models.DeliverableDefinition)
            .filter(models.DeliverableDefinition.stage == models.Stage.L0,
                    models.DeliverableDefinition.item_no.in_(_l0_due_fix_items))
            .all()
        }

        for item_no, name, dkey, anchor, pred, offset, direction, dtype, ms in L0_ITEMS:
            dept = dept_map[L0_DEPT[dkey]]
            upsert("L0", item_no, name, L0_SHORT_NAMES.get(item_no, name), dept.id, anchor, pred, offset, direction, dtype, bool(ms), ms)

        for item_no, name, dkey, anchor, pred, offset, direction, ms in L1_ITEMS:
            dept = dept_map[L1_DEPT[dkey]]
            upsert("L1", item_no, name, L1_SHORT_NAMES.get(item_no, name), dept.id, anchor, pred, offset, direction, "date_driven", bool(ms), ms)

        # Same snapshot-before-upsert trick as the two blocks above, for
        # International's 2.5 formula correction (was Site Visit +3 days,
        # now matches 5.3's own formula: predecessor 1.1, +15 workdays).
        _intl_due_fix_items = ["2.5"]
        _intl_due_fix_before = {
            (d.item_no, d.department_id): (d.anchor_type, d.predecessor_item_no, d.offset_days)
            for d in db.query(models.DeliverableDefinition)
            .filter(models.DeliverableDefinition.stage == models.Stage.L0,
                    models.DeliverableDefinition.item_no.in_(_intl_due_fix_items))
            .all()
        }

        # [L0 International]: still Stage.L0 (no separate Stage value), on its
        # own departments. Curated short names now live in
        # L0_INTERNATIONAL_SHORT_NAMES (queued item: matrix/timeline/assigned
        # deliverables were falling back to the full long name for every
        # international item, unlike the standard catalog).
        for item_no, name, dkey, anchor, pred, offset, direction, dtype, ms in L0_INTERNATIONAL_ITEMS:
            dept = dept_map[L0_INTERNATIONAL_DEPT[dkey]]
            upsert("L0", item_no, name, L0_INTERNATIONAL_SHORT_NAMES.get(item_no, name), dept.id, anchor, pred, offset, direction, dtype, bool(ms), ms)

        db.commit()

        # Item [request 4] customization fix: upsert() silently skips every
        # field (including predecessor_item_no) on a row with
        # is_customized=True -- correct for an ordinary formula tweak, but
        # wrong here: this is a structural identity renumber, and a
        # customized row (found live on production: 3.5/Supply Chain, its
        # is_customized almost certainly set by a short_name edit alone,
        # not a deliberate predecessor choice -- its offset/direction still
        # matched the plain catalog default exactly) would otherwise keep
        # pointing at whatever the OLD item_no now means post-renumber --
        # e.g. still "predecessor 1.21" after 1.21 became "Submit Proposal
        # to client" instead of the "Circulate commercial offers" it used
        # to be. Force the corrected predecessor through regardless of
        # is_customized for exactly the renumber-affected item_nos, same
        # domestic-only department scoping as everywhere else in this
        # migration.
        _l0_renumber_predecessor_fix = {"1.6": "1.21", "1.19": "1.21", "1.20": "1.19",
                                         "3.5": "1.18", "3.6": "1.18", "3.7": "1.18",
                                         "7.1": "1.21", "9.2": "1.21", "10.2": "1.21", "11.4": "1.18"}
        predecessor_forced = 0
        for d in (db.query(models.DeliverableDefinition).join(models.Department)
                  .filter(models.DeliverableDefinition.stage == models.Stage.L0,
                          models.DeliverableDefinition.item_no.in_(_l0_renumber_predecessor_fix),
                          models.Department.name.notlike("%International%")).all()):
            correct_pred = _l0_renumber_predecessor_fix[d.item_no]
            if d.predecessor_item_no != correct_pred:
                d.predecessor_item_no = correct_pred
                predecessor_forced += 1
        if predecessor_forced:
            db.commit()
            print(f"[Request 4]: force-corrected {predecessor_forced} customized/stale predecessor reference(s) past the renumber.")

        # Item [request 4] branch fix: upsert() above only updates a
        # DeliverableDefinition's own denormalized mirror columns (anchor_
        # type/predecessor_item_no/offset_days/offset_direction) -- actual
        # due-date computation reads DeliverableFormulaBranch rows instead
        # (rules.compute_due_date), which upsert() never touches for a
        # pre-existing row (only _seed_missing_branches below creates
        # branches, and only for a definition with zero of them). Every
        # item the [request 4] renumber's predecessor rewiring touches
        # already has a real branch from a prior deploy, so without this
        # the formula text/UI would say the predecessor moved while the
        # real due date silently never does. Scoped to plain, single
        # "always" branch items -- true for every one of these; skips
        # anything with real conditional branches (none of these are).
        _l0_renumber_branch_sync_items = ["1.6", "1.19", "1.20", "3.5", "3.6", "3.7", "7.1", "9.2", "10.2", "11.4"]
        branch_sync_defs = (
            db.query(models.DeliverableDefinition)
            .join(models.Department)
            .filter(models.DeliverableDefinition.stage == models.Stage.L0,
                    models.DeliverableDefinition.item_no.in_(_l0_renumber_branch_sync_items),
                    models.Department.name.notlike("%International%"))
            .all()
        )
        branch_synced = 0
        for d in branch_sync_defs:
            only_branch = d.branches[0] if len(d.branches) == 1 else None
            if only_branch and only_branch.condition_type == "always" and (
                only_branch.predecessor_item_no != d.predecessor_item_no or only_branch.offset_days != d.offset_days
            ):
                only_branch.anchor_type = d.anchor_type
                only_branch.predecessor_item_no = d.predecessor_item_no
                only_branch.offset_days = d.offset_days
                only_branch.offset_direction = d.offset_direction
                branch_synced += 1
        if branch_synced:
            db.commit()
            print(f"[Request 4]: synced {branch_synced} formula branch(es) to their renumbered predecessor.")

        # [Deliverables Configuration]: must run after upsert() above (needs
        # every definition's id, including brand-new ones just inserted)
        # and after that commit (needs department.is_international, already
        # committed with dept_map). Self-limiting -- only definitions with
        # zero branches yet get seeded.
        _seed_missing_branches(db)

        _due_fix_changed_def_ids = [
            d.id for d in db.query(models.DeliverableDefinition)
            .filter(models.DeliverableDefinition.stage == models.Stage.L1,
                    models.DeliverableDefinition.item_no.in_(_due_fix_items))
            .all()
            if _due_fix_before.get((d.item_no, d.department_id)) != (d.anchor_type, d.predecessor_item_no, d.offset_days)
        ]
        if _due_fix_changed_def_ids:
            affected_projects = {
                s.project for s in db.query(models.DeliverableSubmission)
                .filter(models.DeliverableSubmission.deliverable_definition_id.in_(_due_fix_changed_def_ids))
                .all()
            }
            for proj in affected_projects:
                rules.recompute_project_due_dates(db, proj, force=True)
            db.commit()

        _l0_due_fix_changed_def_ids = [
            d.id for d in db.query(models.DeliverableDefinition)
            .filter(models.DeliverableDefinition.stage == models.Stage.L0,
                    models.DeliverableDefinition.item_no.in_(_l0_due_fix_items))
            .all()
            if _l0_due_fix_before.get((d.item_no, d.department_id)) != (d.anchor_type, d.predecessor_item_no, d.offset_days)
        ]
        if _l0_due_fix_changed_def_ids:
            l0_affected_projects = {
                s.project for s in db.query(models.DeliverableSubmission)
                .filter(models.DeliverableSubmission.deliverable_definition_id.in_(_l0_due_fix_changed_def_ids))
                .all()
            }
            for proj in l0_affected_projects:
                rules.recompute_project_due_dates(db, proj, force=True)
            db.commit()

        _intl_due_fix_changed_def_ids = [
            d.id for d in db.query(models.DeliverableDefinition)
            .filter(models.DeliverableDefinition.stage == models.Stage.L0,
                    models.DeliverableDefinition.item_no.in_(_intl_due_fix_items))
            .all()
            if _intl_due_fix_before.get((d.item_no, d.department_id)) != (d.anchor_type, d.predecessor_item_no, d.offset_days)
        ]
        # This same pass also carries the 4.4/4.5/4.7/4.9 OR-formula
        # winner-logic fix (later-wins -> earliest-wins, see
        # L0_INTL_OR_ITEMS_EARLIEST_WINS in rules.py) through to every
        # existing international project -- that fix isn't a
        # DeliverableDefinition field so it has no snapshot-diff of its own,
        # but recompute_project_due_dates(force=True) below recomputes a
        # project's every item, not just 2.5, so it rides along for free on
        # 2.5's own trigger below (2.5 is real on every international
        # project, so this reaches all of them in one shot).
        if _intl_due_fix_changed_def_ids:
            intl_affected_projects = {
                s.project for s in db.query(models.DeliverableSubmission)
                .filter(models.DeliverableSubmission.deliverable_definition_id.in_(_intl_due_fix_changed_def_ids))
                .all()
            }
            for proj in intl_affected_projects:
                rules.recompute_project_due_dates(db, proj, force=True)
            db.commit()

        # Backfill (item 69): the old flat "Operation Units" department's
        # items 2.1-2.12 are superseded by the new TBU/PBU/DBU/BBU
        # sub-folders above — deactivate them so _provision_and_instantiate's
        # active==True filter stops handing them to new projects. Existing
        # projects keep their already-created submissions untouched (this
        # only flips `active` on the definitions, never touches submissions).
        old_operation_dept = dept_map.get("Operation Units")
        if old_operation_dept:
            deactivated = (
                db.query(models.DeliverableDefinition)
                .filter(
                    models.DeliverableDefinition.department_id == old_operation_dept.id,
                    models.DeliverableDefinition.stage == models.Stage.L0,
                    models.DeliverableDefinition.active == True,  # noqa: E712
                )
                .update({"active": False})
            )
            if deactivated:
                db.commit()
                print(f"Deactivated {deactivated} old flat Operation Units item(s) — superseded by TBU/PBU/DBU/BBU split.")

        # One-time full removal (Yasser's request): the old flat "Operation
        # Units" L0 department deactivated just above is permanently dead --
        # fully superseded by the TBU/PBU/DBU/BBU split, so nothing will
        # ever reactivate or reference it again -- and it was only ever
        # cluttering the Deliverables Configuration admin views (its 6 items
        # showed up as a grayed-out "(inactive)" group in the L0 Formulas
        # tab, and the empty department itself still listed in the
        # Departments tab). Same zero-progress safety check as the L1
        # TBU/PBU removal right below: only deletes if genuinely unused.
        old_operation_dept = db.query(models.Department).filter_by(name="Operation Units").first()
        if old_operation_dept:
            # Production's own safety check (below) correctly caught one
            # known blocker on its first run: Est-1711 ("test 10-8-9:37am",
            # obviously a test project by name) has a test PDF uploaded on
            # 2.2, plus 2.1/2.3 marked not_required. Confirmed with Yasser
            # this is throwaway test data, not real work -- explicit
            # authorization to clear it so the removal below can proceed.
            # Scoped tightly to this one known est_no so the safety check
            # keeps protecting anything else it might find, anywhere else.
            _op_test_proj = db.query(models.Project).filter_by(est_no="Est-1711").first()
            if _op_test_proj:
                _op_test_subs = (
                    db.query(models.DeliverableSubmission)
                    .join(models.DeliverableDefinition)
                    .filter(models.DeliverableSubmission.project_id == _op_test_proj.id,
                            models.DeliverableDefinition.department_id == old_operation_dept.id)
                    .all()
                )
                for s in _op_test_subs:
                    if s.status != models.SubmissionStatus.NO_PROGRESS or s.file_name:
                        s.status = models.SubmissionStatus.NO_PROGRESS
                        s.file_name = None
                        s.file_ref = None
                        print(f"Cleared known test blocker on Est-1711 item {s.definition.item_no} so the Operation Units removal below can proceed.")
                db.commit()
            # Est-1711 kept re-blocking this on every deploy even after being
            # cleared once before -- it's a general-purpose test project
            # people keep poking at, so the clearing above alone can't stay
            # ahead of it. Confirmed with Yasser and archived (2026-08-25),
            # which is what actually breaks the cycle: an archived project's
            # leftover submission data no longer counts as "real progress"
            # for this safety check, matching how archived projects are
            # already invisible everywhere else in the app (Project.archived).
            op_subs = (
                db.query(models.DeliverableSubmission)
                .join(models.DeliverableDefinition)
                .join(models.Project)
                .filter(models.DeliverableDefinition.department_id == old_operation_dept.id,
                        models.Project.archived.is_not(True))
                .all()
            )
            if any(s.status != models.SubmissionStatus.NO_PROGRESS or s.file_name for s in op_subs):
                print("WARNING: old flat 'Operation Units' has a submission with real progress -- skipped removal, left in place.")
            else:
                # Deletion itself must cover EVERY submission under this
                # department, archived project or not -- op_subs above is
                # deliberately narrowed to only what the safety check should
                # see, but an archived project's own (harmless) submissions
                # still FK-reference the definitions getting deleted below
                # and would 500 on Postgres if left behind.
                all_op_subs = (
                    db.query(models.DeliverableSubmission)
                    .join(models.DeliverableDefinition)
                    .filter(models.DeliverableDefinition.department_id == old_operation_dept.id)
                    .all()
                )
                op_sub_ids = [s.id for s in all_op_subs]
                if op_sub_ids:
                    db.query(models.WorkflowHistory).filter(models.WorkflowHistory.submission_id.in_(op_sub_ids)).delete(synchronize_session=False)
                    db.query(models.Document).filter(models.Document.submission_id.in_(op_sub_ids)).delete(synchronize_session=False)
                    db.query(models.Follower).filter(models.Follower.submission_id.in_(op_sub_ids)).delete(synchronize_session=False)
                    db.query(models.ReassignmentRequest).filter(models.ReassignmentRequest.submission_id.in_(op_sub_ids)).delete(synchronize_session=False)
                    db.query(models.DueDateRequest).filter(models.DueDateRequest.submission_id.in_(op_sub_ids)).delete(synchronize_session=False)
                    db.query(models.Announcement).filter(models.Announcement.submission_id.in_(op_sub_ids)).update(
                        {"submission_id": None}, synchronize_session=False)
                    db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.id.in_(op_sub_ids)).delete(synchronize_session=False)
                op_def_ids = [d[0] for d in db.query(models.DeliverableDefinition.id).filter_by(department_id=old_operation_dept.id).all()]
                if op_def_ids:
                    # [Deliverables Configuration]: three tables added after
                    # the L1 TBU/PBU removal above was written also FK-
                    # reference deliverable_definitions.id -- none has
                    # ondelete=CASCADE, so leaving these out would 500 on
                    # Postgres (FK violation) even though SQLite would
                    # silently let it through.
                    db.query(models.DeliverableFormulaBranch).filter(models.DeliverableFormulaBranch.deliverable_definition_id.in_(op_def_ids)).delete(synchronize_session=False)
                    # formula_change_requests <-> deliverable_definition_change_log
                    # cross-reference each other (applied_change_log_id /
                    # origin_request_id) -- null both links first so neither
                    # delete below trips the other table's FK.
                    db.query(models.FormulaChangeRequest).filter(models.FormulaChangeRequest.deliverable_definition_id.in_(op_def_ids)).update(
                        {"applied_change_log_id": None}, synchronize_session=False)
                    db.query(models.DeliverableDefinitionChangeLog).filter(models.DeliverableDefinitionChangeLog.deliverable_definition_id.in_(op_def_ids)).update(
                        {"origin_request_id": None}, synchronize_session=False)
                    db.query(models.FormulaChangeRequest).filter(models.FormulaChangeRequest.deliverable_definition_id.in_(op_def_ids)).delete(synchronize_session=False)
                    db.query(models.DeliverableDefinitionChangeLog).filter(models.DeliverableDefinitionChangeLog.deliverable_definition_id.in_(op_def_ids)).delete(synchronize_session=False)
                op_removed_defs = db.query(models.DeliverableDefinition).filter_by(department_id=old_operation_dept.id).delete(synchronize_session=False)
                db.query(models.PerformanceSnapshot).filter_by(department_id=old_operation_dept.id).delete(synchronize_session=False)
                db.query(models.User).filter_by(department_id=old_operation_dept.id).update({"department_id": None}, synchronize_session=False)
                db.delete(old_operation_dept)
                db.commit()
                print(f"Removed old flat L0 'Operation Units' department entirely — {op_removed_defs} definition(s), {len(op_sub_ids)} empty submission(s).")

        # One-time full removal (item 122 follow-up): L1's old combined
        # "TBU / PBU" / "BBU / PBU" buckets were carried for a while so
        # existing projects kept whatever they'd already created there
        # (just deactivated for new projects), but confirmed on production
        # that every submission ever created under them was still at
        # zero progress (no_progress, no file) -- genuinely never used,
        # not abandoned work -- so this deletes them outright instead of
        # leaving the confusing duplicate "TBU / PBU"/"BBU / PBU" folders
        # and gantt-legend entries sitting alongside the real TBU/PBU/DBU/
        # BBU split forever. Safety net: if a submission under either
        # somehow does carry progress (a state this repo's own production
        # data never had), that department is left alone and a warning
        # printed instead of silently discarding it.
        for old_name in ("TBU / PBU", "BBU / PBU"):
            old_dept = db.query(models.Department).filter_by(name=old_name).first()
            if not old_dept:
                continue
            subs = (
                db.query(models.DeliverableSubmission)
                .join(models.DeliverableDefinition)
                .filter(models.DeliverableDefinition.department_id == old_dept.id)
                .all()
            )
            has_progress = any(s.status != models.SubmissionStatus.NO_PROGRESS or s.file_name for s in subs)
            if has_progress:
                print(f"WARNING: '{old_name}' has a submission with real progress -- skipped removal, left in place.")
                continue
            sub_ids = [s.id for s in subs]
            if sub_ids:
                db.query(models.WorkflowHistory).filter(models.WorkflowHistory.submission_id.in_(sub_ids)).delete(synchronize_session=False)
                db.query(models.Document).filter(models.Document.submission_id.in_(sub_ids)).delete(synchronize_session=False)
                db.query(models.Follower).filter(models.Follower.submission_id.in_(sub_ids)).delete(synchronize_session=False)
                db.query(models.ReassignmentRequest).filter(models.ReassignmentRequest.submission_id.in_(sub_ids)).delete(synchronize_session=False)
                db.query(models.DueDateRequest).filter(models.DueDateRequest.submission_id.in_(sub_ids)).delete(synchronize_session=False)
                db.query(models.Announcement).filter(models.Announcement.submission_id.in_(sub_ids)).update(
                    {"submission_id": None}, synchronize_session=False)
                db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.id.in_(sub_ids)).delete(synchronize_session=False)
            removed_defs = db.query(models.DeliverableDefinition).filter_by(department_id=old_dept.id).delete(synchronize_session=False)
            db.query(models.PerformanceSnapshot).filter_by(department_id=old_dept.id).delete(synchronize_session=False)
            db.query(models.User).filter_by(department_id=old_dept.id).update({"department_id": None}, synchronize_session=False)
            db.delete(old_dept)
            db.commit()
            print(f"Removed old L1 '{old_name}' department entirely -- {removed_defs} definition(s), {len(sub_ids)} empty submission(s).")

        # One-time cleanup (item 168 follow-up): before that fix,
        # is_bu_applicable's lookup dict had the wrong keys (bare "TBU"
        # instead of "Operation Units (TBU)") and silently matched nothing,
        # so every L1 project got ALL FOUR Operation Units BU folders
        # instantiated regardless of its own business_units -- e.g. a
        # BBU/TBU-only project also got DBU and PBU items it was never
        # supposed to have. The code path itself is already fixed (new
        # projects only get their own BUs); this retroactively removes the
        # leftover wrong-BU submissions from projects created before that
        # fix, with the same zero-progress safety check as the TBU/PBU
        # cleanup above.
        _l1_op_bu_depts = {
            "Operation Units (TBU)": "TBU", "Operation Units (PBU)": "PBU",
            "Operation Units (DBU)": "DBU", "Operation Units (BBU)": "BBU",
        }
        bu_cleanup_total = 0
        for proj in db.query(models.Project).filter_by(stage=models.Stage.L1).all():
            bus = proj.business_units or []
            if not bus or "TBA" in bus:
                continue
            wrong_subs = [
                s for s in (
                    db.query(models.DeliverableSubmission)
                    .join(models.DeliverableDefinition)
                    .join(models.Department)
                    .filter(models.DeliverableSubmission.project_id == proj.id)
                    .filter(models.Department.name.in_(_l1_op_bu_depts.keys()))
                    .all()
                )
                if _l1_op_bu_depts[s.definition.department.name] not in bus
            ]
            if not wrong_subs:
                continue
            if any(s.status != models.SubmissionStatus.NO_PROGRESS or s.file_name for s in wrong_subs):
                print(f"WARNING: {proj.est_no} has a wrong-BU submission with real progress -- skipped, left in place.")
                continue
            sub_ids = [s.id for s in wrong_subs]
            db.query(models.WorkflowHistory).filter(models.WorkflowHistory.submission_id.in_(sub_ids)).delete(synchronize_session=False)
            db.query(models.Document).filter(models.Document.submission_id.in_(sub_ids)).delete(synchronize_session=False)
            db.query(models.Follower).filter(models.Follower.submission_id.in_(sub_ids)).delete(synchronize_session=False)
            db.query(models.ReassignmentRequest).filter(models.ReassignmentRequest.submission_id.in_(sub_ids)).delete(synchronize_session=False)
            db.query(models.DueDateRequest).filter(models.DueDateRequest.submission_id.in_(sub_ids)).delete(synchronize_session=False)
            db.query(models.Announcement).filter(models.Announcement.submission_id.in_(sub_ids)).update(
                {"submission_id": None}, synchronize_session=False)
            db.query(models.DeliverableSubmission).filter(models.DeliverableSubmission.id.in_(sub_ids)).delete(synchronize_session=False)
            db.commit()
            bu_cleanup_total += len(sub_ids)
            print(f"Removed {len(sub_ids)} wrong-BU submission(s) from {proj.est_no} (business_units={bus}).")
        if bu_cleanup_total:
            print(f"Total wrong-BU submissions removed across all L1 projects: {bu_cleanup_total}.")

        # Backfill: M6 (Contract Signing) already approved on some L1 project
        # before the auto-sign-on-approval logic existed, so contract_status
        # never got updated for it. Idempotent — a no-op once caught up.
        m6_approved_projects = (
            db.query(models.Project)
            .join(models.DeliverableSubmission, models.DeliverableSubmission.project_id == models.Project.id)
            .join(models.DeliverableDefinition)
            .filter(
                models.Project.stage == models.Stage.L1,
                models.DeliverableDefinition.milestone_code == "M6",
                models.DeliverableSubmission.status == models.SubmissionStatus.APPROVED,
                models.Project.contract_status != models.ContractStatus.SIGNED,
            )
            .all()
        )
        for p in m6_approved_projects:
            p.contract_status = models.ContractStatus.SIGNED
        if m6_approved_projects:
            db.commit()
            print(f"Backfilled contract_status=Signed for {len(m6_approved_projects)} project(s).")

        # Backfill: M5 (Submit Proposal, item 1.20) already approved on some L0
        # project before the auto-Submitted logic existed. Idempotent.
        m5_approved_projects = (
            db.query(models.Project)
            .join(models.DeliverableSubmission, models.DeliverableSubmission.project_id == models.Project.id)
            .join(models.DeliverableDefinition)
            .filter(
                models.Project.stage == models.Stage.L0,
                models.DeliverableDefinition.milestone_code == "M5",
                models.DeliverableSubmission.status == models.SubmissionStatus.APPROVED,
                models.Project.status == models.ProjectStatus.IN_PROGRESS,
            )
            .all()
        )
        for p in m5_approved_projects:
            p.status = models.ProjectStatus.SUBMITTED
        if m5_approved_projects:
            db.commit()
            print(f"Backfilled status=Submitted for {len(m5_approved_projects)} project(s).")

        # Backfill: business_units didn't exist for projects created before this
        # field shipped. Display/reporting only — deliverables already
        # instantiated for these projects are left exactly as they are, never
        # retroactively gated or removed.
        unset_bu_projects = db.query(models.Project).filter(models.Project.business_units.is_(None)).all()
        for p in unset_bu_projects:
            bus, needs_manual = rules.compute_business_units(p.scope)
            p.business_units = [] if needs_manual else bus
        if unset_bu_projects:
            db.commit()
            print(f"Backfilled business_units for {len(unset_bu_projects)} project(s).")

        # Backfill: applicability didn't exist before BM triage shipped — every
        # submission created before this defaults to "applicable" (business as
        # usual). Only NEW L0 projects go through the triage screen from here on.
        unset_applicability = db.query(models.DeliverableSubmission).filter(
            models.DeliverableSubmission.applicability.is_(None)
        ).all()
        for s in unset_applicability:
            s.applicability = "applicable"
        if unset_applicability:
            db.commit()
            print(f"Backfilled applicability=applicable for {len(unset_applicability)} submission(s).")

        # Seed the Bid Manager roster (item 75) from the old hardcoded list —
        # one-time: from here on BidManager rows in the DB are the source of
        # truth, admin-editable from the Focal Points tab. Only inserts
        # emails not already present, so an admin's own additions/removals
        # made since the last deploy are never overwritten.
        existing_bm_emails = {e.lower() for (e,) in db.query(models.BidManager.email).all()}
        new_bms = 0
        for email in models.BID_MANAGERS:
            if email.lower() not in existing_bm_emails:
                db.add(models.BidManager(email=email))
                new_bms += 1
        if new_bms:
            db.commit()
            print(f"Seeded {new_bms} Bid Manager(s) into the roster.")

        # One-time: item 143 (2nd revision) replaces the whole approval
        # mechanism, splitting what used to be one combined status into two
        # independent axes — Progress (this column) and Deadline (now
        # computed live, never stored, see rules.deadline_status()).
        # Remaps every existing submission off the old model:
        #   NOT_DUE/DUE/OVERDUE  -> NO_PROGRESS    (deadline info now lives elsewhere; refresh_status
        #                                            self-heals these on the next read too, this just
        #                                            doesn't make everyone wait for that read)
        #   PENDING_COMPLETION   -> PENDING_REVIEW  (repurposed: awaiting SME's confirm/reject, unambiguous
        #                                            since nothing sets PENDING_COMPLETION anymore)
        #   stale (old) PENDING_REVIEW -> IN_PROGRESS (had docs, never got as far as Mark Completed)
        #
        # That last step can't just sweep every row currently in
        # PENDING_REVIEW — after the first deploy, genuinely NEW
        # PENDING_REVIEW rows exist too (Owner's Mark Completed, the new
        # meaning), and re-running this on every seed would wrongly demote
        # them back to In Progress. The two meanings are told apart by
        # content instead: only the Owner's mark_complete endpoint ever logs
        # a "mark_complete_requested" WorkflowHistory row (true under both
        # the old PENDING_COMPLETION flow and the new one) — a PENDING_REVIEW
        # row missing that marker can only be a stale leftover from the old
        # per-document-upload flow, safe to re-run indefinitely.
        remapped = (
            db.query(models.DeliverableSubmission)
            .filter(models.DeliverableSubmission.status.in_([
                models.SubmissionStatus.NOT_DUE, models.SubmissionStatus.DUE, models.SubmissionStatus.OVERDUE,
            ]))
            .update({"status": models.SubmissionStatus.NO_PROGRESS}, synchronize_session=False)
        )
        remapped += (
            db.query(models.DeliverableSubmission)
            .filter(models.DeliverableSubmission.status == models.SubmissionStatus.PENDING_COMPLETION)
            .update({"status": models.SubmissionStatus.PENDING_REVIEW}, synchronize_session=False)
        )
        confirmed_ids = {
            sid for (sid,) in db.query(models.WorkflowHistory.submission_id)
            .filter(models.WorkflowHistory.action == "mark_complete_requested")
            .distinct()
        }
        pending_review_subs = (
            db.query(models.DeliverableSubmission)
            .filter(models.DeliverableSubmission.status == models.SubmissionStatus.PENDING_REVIEW)
            .all()
        )
        stale_pending_review = [s for s in pending_review_subs if s.id not in confirmed_ids]
        for sub in stale_pending_review:
            sub.status = models.SubmissionStatus.IN_PROGRESS
        remapped += len(stale_pending_review)
        if remapped:
            db.commit()
            print(f"Item 143 (2nd revision): remapped {remapped} submission(s) onto the new Progress-only status model.")

        # Item [multi-SME]: one-time backfill from the legacy singular
        # focal_point_email/default_sme_email/sme_email columns into their
        # new list-valued counterparts, for any row that predates this
        # feature. Only fires when the new column is still empty, so it
        # never overwrites something an admin has already set through the
        # new multi-picker UI, and is safe to re-run every deploy.
        backfilled = 0
        for d in db.query(models.DeliverableDefinition).all():
            if not d.focal_point_emails and d.focal_point_email:
                d.focal_point_emails = [d.focal_point_email]
                backfilled += 1
            if not d.default_sme_emails and d.default_sme_email:
                d.default_sme_emails = [d.default_sme_email]
                backfilled += 1
            if not d.default_owner_emails and d.default_owner_email:
                d.default_owner_emails = [d.default_owner_email]
                backfilled += 1
        for s in db.query(models.DeliverableSubmission).all():
            if not s.sme_emails and s.sme_email:
                s.sme_emails = [s.sme_email]
                backfilled += 1
            if not s.owner_emails and s.owner_email:
                s.owner_emails = [s.owner_email]
                backfilled += 1
        if backfilled:
            db.commit()
            print(f"Item [multi-SME]: backfilled {backfilled} legacy single-value focal/SME field(s) into their list form.")

        # Item [old projects 500]: auto_completed was added to an
        # already-live deliverable_submissions table via ensure_column, which
        # leaves every pre-existing row NULL (Postgres ADD COLUMN has no
        # backfill without an explicit DEFAULT) -- SubmissionOut requires a
        # real bool, so any project with a submission that predates this
        # column 500'd on every /deliverables read. NULL only ever means
        # "not auto-completed" here, so backfilling to False is safe.
        auto_completed_fixed = (
            db.query(models.DeliverableSubmission)
            .filter(models.DeliverableSubmission.auto_completed.is_(None))
            .update({models.DeliverableSubmission.auto_completed: False}, synchronize_session=False)
        )
        if auto_completed_fixed:
            db.commit()
            print(f"Item [old projects 500]: backfilled {auto_completed_fixed} submission(s) with a NULL auto_completed to False.")

        # [L0 International]: same NULL-boolean-on-existing-rows issue as
        # auto_completed above -- ProjectOut/is_international requires a
        # real bool, so every project created before this column existed
        # 500'd on any endpoint returning it (GET /api/projects, etc.).
        intl_fixed = (
            db.query(models.Project).filter(models.Project.is_international.is_(None))
            .update({models.Project.is_international: False}, synchronize_session=False)
        )
        dept_intl_fixed = (
            db.query(models.Department).filter(models.Department.is_international.is_(None))
            .update({models.Department.is_international: False}, synchronize_session=False)
        )
        if intl_fixed or dept_intl_fixed:
            db.commit()
            print(f"[L0 International]: backfilled {intl_fixed} project(s) and {dept_intl_fixed} department(s) with a NULL is_international to False.")

        # Item [points backfill]: mark_complete's SME-immediate-finalize
        # branch used to skip setting submitted_at (fixed separately), so
        # every submission approved before that fix has submitted_at stuck
        # at NULL forever -- kpi_points can never score them, so a genuinely
        # Completed item silently shows no points earned. reviewed_at is
        # always set by _finalize_approval regardless of which branch ran,
        # so it's the best available stand-in for when approval happened.
        submitted_at_fixed = (
            db.query(models.DeliverableSubmission)
            .filter(
                models.DeliverableSubmission.status == models.SubmissionStatus.APPROVED,
                models.DeliverableSubmission.submitted_at.is_(None),
                models.DeliverableSubmission.reviewed_at.isnot(None),
            )
            .update({models.DeliverableSubmission.submitted_at: models.DeliverableSubmission.reviewed_at}, synchronize_session=False)
        )
        if submitted_at_fixed:
            db.commit()
            print(f"Item [points backfill]: backfilled {submitted_at_fixed} approved submission(s) with a NULL submitted_at from reviewed_at.")

        # Item [performance history]: one-time seed of real pre-pilot monthly
        # performance, transcribed from Yasser's own Feb-Jul 2026 tracking
        # spreadsheet, into PerformanceSnapshot -- so the Yearly Trend chart
        # and YTD-vs-Feb figures have real history instead of starting blank
        # the day this feature shipped. August onward is deliberately NOT
        # seeded here; it's computed live by get_performance() every time,
        # same as before. A department/stage with no row below has no real
        # history and stays correctly blank rather than getting a fabricated
        # number. Idempotent: only inserts a given dept/stage/month once.
        import datetime as _dt
        _HIST_MONTHS = [2, 3, 4, 5, 6, 7]  # Feb..Jul 2026
        _HIST_L1 = {
            "Tendering Department": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
            "Operation Units (TBU)": [66.3, 67.0, 69.9, 69.5, 70.7, 62.4],
            "Operation Units (PBU)": [73.6, 73.1, 73.5, 72.2, 66.4, 64.9],
            "Operation Units (BBU)": [23.8, 20.8, 35.6, 35.6, 37.9, 24.7],
            "Engineering Department": [87.8, 84.6, 95.9, 96.0, 94.1, 89.7],
            "Planning": [67.0, 87.3, 94.5, 94.2, 86.9, 90.0],
            "Cost Control": [95.0, 88.5, 93.9, 97.6, 97.9, 96.0],
            "Contract": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
            "Human Resources": [50.0, 50.0, 46.2, 44.3, 39.8, 36.5],
            "HSSE": [100.0, 100.0, 100.0, 100.0, 100.0, 98.6],
            "Quality": [83.3, 91.4, 97.3, 97.6, 97.8, 97.7],
            "Fleet": [100.0, 100.0, 100.0, 100.0, 94.4, 90.5],
            # Supply Chain's L1 tracking (split SS/PBU Procurement in the
            # original sheet) only starts in Aug -- no Feb-Jul figure exists.
        }
        _HIST_L0 = {
            "Tendering Department": [73.1, 98.9, 99.7, 96.8, 96.2, 95.1],
            "Operation Units (TBU)": [41.5, 35.4, 34.9, 40.0, 40.8, 40.8],
            "Operation Units (PBU)": [51.2, 62.5, 50.5, 55.1, 53.9, 49.4],
            "Operation Units (BBU)": [21.4, 21.8, 21.6, 28.6, 30.8, 40.6],
            "Supply Chain": [31.0, 29.0, 27.7, 27.0, 27.3, 27.3],
            "Engineering Department": [78.2, 69.1, 87.2, 88.8, 82.8, 78.9],
            "Planning": [96.7, 96.9, 100.0, 100.0, 100.0, 90.3],
            "Contract": [90.0, 98.0, 98.8, 98.4, 98.6, 99.4],
            "Human Resources": [100.0, 15.4, 9.1, 6.9, 9.5, 8.3],
            "HSSE": [96.4, 86.1, 89.5, 99.8, 93.0, 100.0],
            "Quality": [97.0, 85.5, 89.4, 99.7, 91.9, 100.0],
            # Every other department genuinely has no L0 historical tracking.
        }
        hist_added = 0
        for stage, table in ((models.Stage.L1, _HIST_L1), (models.Stage.L0, _HIST_L0)):
            for dept_name, values in table.items():
                dept = dept_map.get(dept_name)
                if not dept:
                    continue
                for month_num, pct in zip(_HIST_MONTHS, values):
                    month = _dt.date(2026, month_num, 1)
                    existing = (
                        db.query(models.PerformanceSnapshot)
                        .filter(models.PerformanceSnapshot.department_id == dept.id,
                                models.PerformanceSnapshot.stage == stage,
                                models.PerformanceSnapshot.month == month)
                        .first()
                    )
                    if existing:
                        continue
                    db.add(models.PerformanceSnapshot(
                        department_id=dept.id, stage=stage, month=month,
                        pct=pct, approved=round(pct), total=100,
                    ))
                    hist_added += 1
        if hist_added:
            db.commit()
            print(f"Item [performance history]: seeded {hist_added} historical monthly performance snapshot(s).")

        tagged = _tag_line_item_categories(db)
        if tagged:
            print(f"[PO Lifecycle]: tagged {tagged} deliverable definition(s) with a line_item_category.")
        migrated = _backfill_po_line_items(db)
        if migrated:
            print(f"[PO Lifecycle]: backfilled {migrated} synthetic PoLineItem(s) for pre-existing L1 progress.")
        l0_tagged = _tag_l0_line_item_categories(db)
        if l0_tagged:
            print(f"[Request 5]: tagged {l0_tagged} L0 deliverable definition(s) with a line_item_category.")
        l0_migrated = _backfill_l0_po_line_items(db)
        if l0_migrated:
            print(f"[Request 5]: backfilled {l0_migrated} synthetic PoLineItem(s) for pre-existing L0 progress.")
        gap_filled = _fill_po_line_item_gaps(db)
        if gap_filled:
            print(f"[PO Lifecycle]: filled line-item fan-out gaps on {gap_filled} project(s).")
        consultancy_created = _ensure_consultancy_line_items(db)
        if consultancy_created:
            print(f"[PO Lifecycle]: created the missing Consultancy PO line item on {consultancy_created} project(s) -- 2.7/3.10 now instantiate.")

        print(f"Seed complete: {len(dept_map)} departments, {len(L0_ITEMS)} L0 items, {len(L1_ITEMS)} L1 items.")
    finally:
        db.close()


if __name__ == "__main__":
    run()

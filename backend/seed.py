"""Seeds departments and the FULL real deliverable catalogs, transcribed
directly from L0 Template (Final).xlsx (column O formulas) and New L1
Template (Final).xlsx / L1 Template (Tracking Sheet) (columns B/C/F/I, with
due dates from K/L). Every item, not a sample.

Focal point / owner / SME emails below are PLACEHOLDERS — swap for the real
per-department contacts and the real per-deliverable owner/SME mapping when
provided, then re-run: `python -m backend.seed` (safe to re-run, upserts).
"""
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

models.Base.metadata.create_all(bind=engine)

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
    "Tendering Department", "Operation Units", "Supply Chain", "Engineering Department",
    "Contract", "Human Resources", "IT Department",
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
    # Operation Units BU sub-folders (item 69) — "Operation Units" above stays
    # in place (existing projects still point at its old flat 2.1-2.12 items,
    # deactivated below so it's never handed to new ones); new L0 projects
    # instead get one of these four, matching whichever business unit(s) the
    # project's scope actually selected.
    "Operation Units (TBU)", "Operation Units (PBU)", "Operation Units (DBU)", "Operation Units (BBU)",
    # L1-only (additional real breakdown, no "L1 " prefix)
    # Items 123/124/126: Insurance and HSSE / Quality no longer get created
    # here -- their one deliverable each has been re-pointed onto Finance
    # and HSSE/Quality respectively by the migration in run() below, so
    # they'd otherwise just come back empty on every seed run.
    # Items 128/129: Planning, Cost Control, Risk, Fleet, FM are no longer
    # L1-only -- L0 now shares these same rows (see L0_DEPT below), same
    # pattern as Tendering/Supply Chain/Engineering/HR/Contract already use.
    "TBU / PBU", "BBU / PBU", "Planning", "Cost Control",
    "Treasury", "Finance", "Quality", "HSSE",
    "Risk", "Fleet", "FM",
    # Item 122 rework: L1's own TBU/PBU/DBU/BBU split now reuses the exact
    # same "Operation Units (TBU)" etc. rows L0's item 69 split already
    # created (see L0_DEPT/L1_DEPT below) -- so it nests under the same
    # "2. Operation Units" group header in the folder list, instead of
    # showing as its own separate ungrouped set of rows. "TBU / PBU" and
    # "BBU / PBU" above are the old combined buckets -- existing projects
    # keep whatever submissions they already created there (deactivated for
    # new projects below).
]

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
    "Operation Units": 2, "TBU / PBU": 2, "BBU": 2, "BBU / PBU": 2,
    "Operation Units (TBU)": 2, "Operation Units (PBU)": 2, "Operation Units (DBU)": 2, "Operation Units (BBU)": 2,
    "TBU": 2, "PBU": 2, "DBU": 2,
    "Supply Chain": 3,
    "Engineering Department": 4,
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
    ("1.6", "Request Bid Bond (if applicable)", "tendering", "predecessor", "1.20", 10, "before", "date_driven", None),
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
    ("1.17", "Circulate technical offers & Terms received from Vendors & SC & Consultant to Supply chain & Engineering", "tendering", "predecessor", "1.9", 10, "after", "date_driven", "M4"),
    ("1.18", "Develop a comprehensive Technical-commercial proposal", "tendering", "predecessor", "1.20", 5, "before", "date_driven", None),
    ("1.19", "Adjust Proposals based on Tender Committee and/or VC Comments", "tendering", "predecessor", "1.18", 1, "after", "date_driven", None),
    ("1.20", "Submit Proposal to client", "tendering", "bsd", None, 0, "before", "date_driven", "M5"),

    # NOTE: the flat "operation" rows below are the OLD, pre-split Operation
    # Units structure — kept (and kept in sync by upsert) only because
    # existing in-progress projects already have submissions pointing at
    # them. They're deactivated for new projects in the backfill near the
    # bottom of this file; every new L0 project instead gets one or more of
    # the per-BU blocks that follow (item 69).
    ("2.1", "Attend Site Visit (in coordination with BBU)", "operation", "site_visit", None, 0, "after", "date_driven", None),
    ("2.2", "Prepare and circulate Site Visit Report (in coordination with BBU)", "operation", "predecessor", "2.1", 1, "after", "date_driven", "M2"),
    ("2.3", "Highlight points require Pre-bid clarifications", "operation", "pre_bid", None, 3, "before", "date_driven", None),
    ("2.4", "Prepare Risk Register", "operation", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("2.5", "Prepare Project Execution Plan (Methodology) - (in coordination with BBU)", "operation", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("2.6", "Review and comments on Project schedule (Execution and Productivities)", "operation", "predecessor", "5.3", 2, "after", "date_driven", None),

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
    ("3.5", "Review and Evaluate of Main Materials (Long lead items) and Subcontracting Strategy", "supply", "predecessor", "1.17", 2, "after", "date_driven", None),
    ("3.6", "Prepare List of long lead items, key materials and items fall on critical path", "supply", "predecessor", "1.17", 2, "after", "date_driven", None),
    ("3.7", "Support tendering with required logistics pricing and provide backup data", "supply", "predecessor", "1.17", 2, "after", "date_driven", None),
    ("3.8", "Complete Internal Prequalification of Potential Vendors (where applicable)", "supply", None, None, 0, "after", "on_request", None),
    ("3.9", "Participate in negotiation rounds at bidding stage lead by tender team", "supply", None, None, 0, "after", "on_request", None),

    ("4.1", "Prepare Risk Register", "eng", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("4.2", "Highlight points require Pre-bid clarifications", "eng", "pre_bid", None, 3, "before", "date_driven", None),
    ("4.3", "Provide List of required Site Investigations, Studies or any Special Technical requirements", "eng", "predecessor", "1.1", 3, "after", "date_driven", None),
    ("4.4", "Generate Design & BOQ's for the relevant scope (detailed for OHTL)", "eng", "predecessor", "1.1", 10, "after", "date_driven", None),
    ("4.5", "Provide Studies of Value Engineering and Optimized design (wherever needed)", "eng", None, None, 0, "after", "on_request", None),
    ("4.6", "Review and evaluate technical offers received from Vendors", "eng", "predecessor", "1.17", 2, "after", "date_driven", None),
    ("4.7", "Support Technical Proposals with required design deliverables (if needed)", "eng", None, None, 0, "after", "on_request", None),

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
    ("5.4", "Verify Quantities for remeasured Contracts (if applicable)", "planning", "predecessor", "1.1", 3, "after", "date_driven", None),
    ("5.5", "Provide Updated Productivity Norms and Calculations (PCO-01-SPR-001)", "planning", None, None, 0, "after", "library", None),

    ("6.1", "Prepare Risk Register", "costctrl", "predecessor", "2.2", 1, "after", "date_driven", None),
    # Item 172: unlike every other department's identically-worded "Highlight
    # points require Pre-bid clarifications" item (e.g. Planning's 5.2 above,
    # which stays at 3 days), Cost Control's own 6.2 is 1 day before the
    # clarification deadline -- a deliberate, unique exception per Yasser.
    ("6.2", "Highlight points require Pre-bid clarifications", "costctrl", "pre_bid", None, 1, "before", "date_driven", None),
    ("6.3", "Fleet Productivities (equipment productivity rates)", "costctrl", None, None, 0, "after", "library", None),

    ("7.1", "Prepare Risk Register", "contract", "predecessor", "1.20", 5, "before", "date_driven", None),
    ("7.2", "Highlight points require Pre-bid clarifications (Review Contracts and Terms)", "contract", "pre_bid", None, 3, "before", "date_driven", None),
    ("7.3", "Prepare Non Disclosure Agreements (NDA's) (if applicable)", "contract", None, None, 0, "after", "on_request", None),
    ("7.4", "Review Pre-bid agreements and provide Contractual comments as needed", "contract", None, None, 0, "after", "on_request", None),

    ("8.1", "Verify local content requirements in coordination with the Manning Schedule", "hr", "predecessor", "5.3", 5, "after", "date_driven", None),
    ("8.2", "Updated HR Cost Estimates (Salaries / Wages / Benefits)", "hr", None, None, 0, "after", "library", None),
    ("8.3", "Provide updated information on Workforce availability, nationality, release dates", "hr", None, None, 0, "after", "library", None),
    ("8.4", "Provide Supporting documents, such as team CV's, certificates and Qualifications", "hr", "predecessor", "1.1", 3, "after", "date_driven", None),

    # Item 141: L0's old combined "Financial Department" splits into
    # Treasury (Risk Register duplicated + Issue Bid Bonds) and Finance
    # (Risk Register original + Insurance Cost + Overheads + Cash Flow),
    # mirroring L1's existing Treasury/Finance split -- same
    # shared-item_no-across-departments pattern as item 129's 5.1/5.2 split.
    ("9.1", "Prepare Risk Register", "treasury", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("9.2", "Issue Bid Bonds", "treasury", "predecessor", "1.20", 3, "before", "date_driven", None),

    ("10.1", "Prepare Risk Register", "finance", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("10.2", "Provide Insurance Cost, and additional client requirements", "finance", "predecessor", "1.20", 6, "before", "date_driven", None),
    ("10.3", "Provide Proposed Business Units, Corporate, Finance and Insurance Overheads", "finance", None, None, 0, "after", "library", None),
    ("10.4", "Provide Proposed Cash Flow & Finance Cost and Parameters", "finance", None, None, 0, "after", "library", None),

    # Item 141 rework: Quality gets Risk Register, Pre-bid clarifications,
    # QA/QC Plan, Evaluate Subcontractors, and Personnel Requirements.
    # Personnel Requirements drops the "HSSE / Quality" suffix from its
    # name now that it's landed cleanly on Quality alone.
    ("11.1", "Prepare Risk Register", "quality", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("11.2", "Highlight points require Pre-bid clarifications", "quality", "pre_bid", None, 3, "before", "date_driven", None),
    ("11.3", "Prepare QA/QC Plan - Tender Level", "quality", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("11.4", "Evaluate Selected subcontractors (for not Qualified / Approved Subcontractors)", "quality", "predecessor", "1.17", 2, "after", "date_driven", None),
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
# L1 catalog — from New L1 Template (Final).xlsx, "L1 Template (Tracking
# Sheet)", columns B/C/F (item/name/department), I (predecessor), J
# (duration). Items 1.1-1.6 ARE the milestones M1-M6 (column D).
# ---------------------------------------------------------------------------
L1_DEPT = {
    "tendering": "Tendering Department", "tbupbu": "TBU / PBU", "bbupbu": "BBU / PBU",
    "supply": "Supply Chain", "eng": "Engineering Department", "planning": "Planning",
    "costctrl": "Cost Control", "contract": "Contract", "hr": "Human Resources",
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

    ("2.1", "Submission of Cost Center request to Cost Control Department", "tbupbu", "predecessor", "1.2", 1, "after", None),
    ("2.2", "Creating PRs for long-lead items through the system", "tbupbu", "predecessor", "5.3", 2, "after", None),
    ("2.3", "Assignment of Temporary Project Manager & Project Engineer", "tbupbu", "predecessor", "1.1", 5, "after", None),
    ("2.4", "Internal Kick off Meeting (to be called by Project Manager)", "tbupbu", "predecessor", "2.3", 5, "after", None),
    ("2.5", "Draft Master Project Execution Plan ready to be submitted", "tbupbu", "predecessor", "1.2", 25, "after", None),
    ("2.6", "Create PRs for Early Activities (Soil Investigation, Topography)", "tbupbu", "predecessor", "5.3", 2, "after", None),
    ("2.7", "Create PR for Design Firm/Consultant", "tbupbu", "predecessor", "4.4", 2, "after", None),
    ("2.8", "Start Activities for Geotechnical Investigation (in house or vendor)", "tbupbu", "predecessor", "3.11", 7, "after", None),
    ("2.9", "Start Activities for Topography and Site Investigation", "tbupbu", "predecessor", "1.2", 25, "after", None),
    ("2.10", "Provide list of project permits (Governmental, Local Authority)", "tbupbu", "predecessor", "1.2", 15, "after", None),
    ("2.11", "Preparation of Subcontracting Strategy for (OHTL/UGC) projects", "tbupbu", "predecessor", "1.2", 5, "after", None),
    ("2.12", "Provide Confirmation on the Proposal recommendation for working schedule", "tbupbu", "predecessor", "5.3", 3, "after", None),

    ("2.13", "Submission of Cost Center request to Cost Control Department", "bbu", "predecessor", "1.2", 1, "after", None),
    ("2.14", "Creating PRs for MEP consultancy items through system", "bbu", "predecessor", "5.3", 2, "after", None),
    ("2.15", "BBU input for Draft Project Execution Plan", "bbu", "predecessor", "1.2", 20, "after", None),
    ("2.16", "Provide general layout of Temporary facilities, laydown and storage", "bbupbu", "predecessor", "1.2", 7, "after", None),
    ("2.17", "Prepare/Update Subcontracting Strategy / Model", "bbu", "predecessor", "1.2", 5, "after", None),
    ("2.18", "Finalize Subcontract Agreement for SS projects", "bbu", "predecessor", "1.6", 10, "after", None),

    # Item 122: full TBU/PBU/DBU/BBU split (mirrors item 69's L0 pattern) --
    # own copy of 2.1-2.12 per business unit instead of one combined
    # "TBU / PBU" folder applying to every project regardless of BU.
    ("2.1", "Submission of Cost Center request to Cost Control Department", "tbu", "predecessor", "1.2", 1, "after", None),
    ("2.2", "Creating PRs for long-lead items through the system", "tbu", "predecessor", "5.3", 2, "after", None),
    ("2.3", "Assignment of Temporary Project Manager & Project Engineer", "tbu", "predecessor", "1.1", 5, "after", None),
    ("2.4", "Internal Kick off Meeting (to be called by Project Manager)", "tbu", "predecessor", "2.3", 5, "after", None),
    ("2.5", "Draft Master Project Execution Plan ready to be submitted", "tbu", "predecessor", "1.2", 25, "after", None),
    ("2.6", "Create PRs for Early Activities (Soil Investigation, Topography)", "tbu", "predecessor", "5.3", 2, "after", None),
    ("2.7", "Create PR for Design Firm/Consultant", "tbu", "predecessor", "4.4", 2, "after", None),
    ("2.8", "Start Activities for Geotechnical Investigation (in house or vendor)", "tbu", "predecessor", "3.11", 7, "after", None),
    ("2.9", "Start Activities for Topography and Site Investigation", "tbu", "predecessor", "1.2", 25, "after", None),
    ("2.10", "Provide list of project permits (Governmental, Local Authority)", "tbu", "predecessor", "1.2", 15, "after", None),
    ("2.11", "Preparation of Subcontracting Strategy for (OHTL/UGC) projects", "tbu", "predecessor", "1.2", 5, "after", None),
    ("2.12", "Provide Confirmation on the Proposal recommendation for working schedule", "tbu", "predecessor", "5.3", 3, "after", None),

    ("2.1", "Submission of Cost Center request to Cost Control Department", "pbu", "predecessor", "1.2", 1, "after", None),
    ("2.2", "Creating PRs for long-lead items through the system", "pbu", "predecessor", "5.3", 2, "after", None),
    ("2.3", "Assignment of Temporary Project Manager & Project Engineer", "pbu", "predecessor", "1.1", 5, "after", None),
    ("2.4", "Internal Kick off Meeting (to be called by Project Manager)", "pbu", "predecessor", "2.3", 5, "after", None),
    ("2.5", "Draft Master Project Execution Plan ready to be submitted", "pbu", "predecessor", "1.2", 25, "after", None),
    ("2.6", "Create PRs for Early Activities (Soil Investigation, Topography)", "pbu", "predecessor", "5.3", 2, "after", None),
    ("2.7", "Create PR for Design Firm/Consultant", "pbu", "predecessor", "4.4", 2, "after", None),
    ("2.8", "Start Activities for Geotechnical Investigation (in house or vendor)", "pbu", "predecessor", "3.11", 7, "after", None),
    ("2.9", "Start Activities for Topography and Site Investigation", "pbu", "predecessor", "1.2", 25, "after", None),
    ("2.10", "Provide list of project permits (Governmental, Local Authority)", "pbu", "predecessor", "1.2", 15, "after", None),
    ("2.11", "Preparation of Subcontracting Strategy for (OHTL/UGC) projects", "pbu", "predecessor", "1.2", 5, "after", None),
    ("2.12", "Provide Confirmation on the Proposal recommendation for working schedule", "pbu", "predecessor", "5.3", 3, "after", None),
    ("2.16", "Provide general layout of Temporary facilities, laydown and storage", "pbu", "predecessor", "1.2", 7, "after", None),

    ("2.1", "Submission of Cost Center request to Cost Control Department", "dbu", "predecessor", "1.2", 1, "after", None),
    ("2.2", "Creating PRs for long-lead items through the system", "dbu", "predecessor", "5.3", 2, "after", None),
    ("2.3", "Assignment of Temporary Project Manager & Project Engineer", "dbu", "predecessor", "1.1", 5, "after", None),
    ("2.4", "Internal Kick off Meeting (to be called by Project Manager)", "dbu", "predecessor", "2.3", 5, "after", None),
    ("2.5", "Draft Master Project Execution Plan ready to be submitted", "dbu", "predecessor", "1.2", 25, "after", None),
    ("2.6", "Create PRs for Early Activities (Soil Investigation, Topography)", "dbu", "predecessor", "5.3", 2, "after", None),
    ("2.7", "Create PR for Design Firm/Consultant", "dbu", "predecessor", "4.4", 2, "after", None),
    ("2.8", "Start Activities for Geotechnical Investigation (in house or vendor)", "dbu", "predecessor", "3.11", 7, "after", None),
    ("2.9", "Start Activities for Topography and Site Investigation", "dbu", "predecessor", "1.2", 25, "after", None),
    ("2.10", "Provide list of project permits (Governmental, Local Authority)", "dbu", "predecessor", "1.2", 15, "after", None),
    ("2.11", "Preparation of Subcontracting Strategy for (OHTL/UGC) projects", "dbu", "predecessor", "1.2", 5, "after", None),
    ("2.12", "Provide Confirmation on the Proposal recommendation for working schedule", "dbu", "predecessor", "5.3", 3, "after", None),

    ("2.16", "Provide general layout of Temporary facilities, laydown and storage", "bbu", "predecessor", "1.2", 7, "after", None),

    ("3.1", "Issue RFQ to vendors including technical SOW, contractual and commercial baselines", "supply", "predecessor", "4.5", 7, "after", None),
    ("3.2", "Allowable time for negotiating commercial and technical terms", "supply", "predecessor", "2.2", 10, "after", None),
    ("3.3", "Award Approval on System (Buyer -> SCM -> Cost Control -> Operation)", "supply", "predecessor", "1.6", 5, "after", None),
    ("3.4", "Top Management approval of awarding, if required as per Authority Matrix", "supply", "predecessor", "3.3", 5, "after", None),
    ("3.5", "PO Approval on Oracle following Award Approval", "supply", "predecessor", "3.4", 3, "after", None),
    ("3.6", "Electronic Internal PO Signature (SCM Director and VP Technical)", "supply", "predecessor", "3.5", 2, "after", None),
    ("3.7", "Electronic PO Signature by Vendor", "supply", "predecessor", "3.6", 2, "after", None),
    ("3.8", "Finalize Subcontract Agreement for OHTL/UGC Projects", "supply", "predecessor", "1.6", 10, "after", None),
    ("3.9", "Share Design Firm Technical Offers received from vendors with Engineering", "supply", "predecessor", "4.3", 5, "after", None),
    ("3.10", "Prepare and Issue Engineering/Design Agreement/PO", "supply", "predecessor", "2.7", 8, "after", None),
    ("3.11", "Issue POs for Early Activities (Site Survey, Geotechnical Investigation)", "supply", "predecessor", "2.6", 8, "after", None),
    ("3.12", "Finalize prequalification of new vendors (if any)", "supply", "predecessor", "1.2", 21, "after", None),

    ("4.1", "Provide SC scope for Early Activities", "eng", "predecessor", "1.1", 9, "after", None),
    ("4.2", "Update the initial Design and Quantities including site layout", "eng", "predecessor", "2.9", 10, "after", None),
    ("4.3", "Provide brief SOW for Design Firm as per PTS for core project", "eng", "predecessor", "1.1", 2, "after", None),
    ("4.4", "Review and evaluate Design Firm Technical Offers and Finalize selection", "eng", "predecessor", "3.9", 4, "after", None),
    ("4.5", "Review Vendors technical offers received from Tendering & Procurement", "eng", "predecessor", "1.2", 10, "after", None),
    ("4.6", "Review Vendors technical offers received from Supply Chain", "eng", "predecessor", "3.2", 5, "after", None),
    ("4.7", "Verify site layout after approach Site for Preliminary investigation", "eng", "predecessor", "2.9", 5, "after", None),
    ("4.8", "Update Engineering Risk Register including lesson learned", "eng", "predecessor", "4.2", 10, "after", None),

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

    ("7.1", "Update Contracts Risk Register and Contract Liabilities", "contract", "client_dependent", None, 1, "after", None),

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

    ("14.1", "Verify and update Project Risk register", "risk", "predecessor", "5.4", 15, "after", None),

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
    "1.17": "Circulate Technical Offers", "1.18": "Develop Tech-Comm Proposal",
    "1.19": "Adjust Proposal (Comments)", "1.20": "Submit Proposal",

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
        for i, name in enumerate(DEPARTMENTS):
            dept = db.query(models.Department).filter_by(name=name).first()
            if not dept:
                dept = models.Department(name=name, order=i)
                db.add(dept)
                db.flush()
            dept.focal_point_email = dept.focal_point_email or TEST_EMAIL
            dept.focal_point_name = dept.focal_point_name or f"TEST focal ({name})"
            dept.number = DEPARTMENT_NUMBERS.get(name)
            dept_map[name] = dept
        db.commit()

        def upsert(stage, item_no, name, short_name, dept_id, anchor_type, pred, offset, direction, dtype, is_ms, ms_code):
            existing = db.query(models.DeliverableDefinition).filter_by(
                stage=stage, item_no=item_no, department_id=dept_id
            ).first()
            if existing:
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
            ))

        for item_no, name, dkey, anchor, pred, offset, direction, dtype, ms in L0_ITEMS:
            dept = dept_map[L0_DEPT[dkey]]
            upsert("L0", item_no, name, L0_SHORT_NAMES.get(item_no, name), dept.id, anchor, pred, offset, direction, dtype, bool(ms), ms)

        for item_no, name, dkey, anchor, pred, offset, direction, ms in L1_ITEMS:
            dept = dept_map[L1_DEPT[dkey]]
            upsert("L1", item_no, name, L1_SHORT_NAMES.get(item_no, name), dept.id, anchor, pred, offset, direction, "date_driven", bool(ms), ms)

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

        # Backfill (item 122): same as above but for L1's old combined
        # "TBU / PBU" / "BBU / PBU" buckets, now superseded by real
        # TBU/PBU/DBU/BBU folders. Existing projects keep their
        # already-created submissions on the old departments untouched.
        for old_name in ("TBU / PBU", "BBU / PBU"):
            old_dept = dept_map.get(old_name)
            if not old_dept:
                continue
            deactivated = (
                db.query(models.DeliverableDefinition)
                .filter(
                    models.DeliverableDefinition.department_id == old_dept.id,
                    models.DeliverableDefinition.stage == models.Stage.L1,
                    models.DeliverableDefinition.active == True,  # noqa: E712
                )
                .update({"active": False})
            )
            if deactivated:
                db.commit()
                print(f"Deactivated {deactivated} old L1 '{old_name}' item(s) — superseded by TBU/PBU/DBU/BBU split.")

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

        print(f"Seed complete: {len(dept_map)} departments, {len(L0_ITEMS)} L0 items, {len(L1_ITEMS)} L1 items.")
    finally:
        db.close()


if __name__ == "__main__":
    run()

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
ensure_column("deliverable_submissions", "auto_completed", "BOOLEAN")
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
    "Contract", "Human Resources", "Financial Department", "SHEQ Department", "IT Department",
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
# one department -- see the merge in run() below). "Financial Department"
# and "SHEQ Department" are untouched by 128/129 -- L0 still has ONE
# combined department for each, so those keep sharing a number with their
# L1 Treasury/Finance and Quality/HSSE counterparts, same pattern as before.
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
    "Financial Department": 9, "Treasury": 9, "Finance": 9,
    "SHEQ Department": 10, "Quality": 10, "HSSE": 10,
    "IT Department": 11,
    "Risk": 12, "Risk Department": 12,
    "Fleet": 13, "Fleet and Facility Management Department": 13,
    "FM": 14,
}

# ---------------------------------------------------------------------------
# L0 catalog — from L0 Template (Final).xlsx, sheet "Deliverables", column O.
# Fields: item_no, name, department, anchor_type, predecessor_item_no,
#         offset_days, offset_direction, deliverable_type, is_milestone, milestone_code
# ---------------------------------------------------------------------------
L0_DEPT = {
    "tendering": "Tendering Department", "operation": "Operation Units", "supply": "Supply Chain",
    "eng": "Engineering Department", "contract": "Contract",
    "hr": "Human Resources", "finance": "Financial Department", "sheq": "SHEQ Department",
    "it": "IT Department", "risk": "Risk",
    # Items 128/129: L0 now shares the same Planning/Cost Control and
    # Fleet/FM departments L1 already uses, instead of its own combined
    # "Control Department" / "Fleet and Facility Management Department".
    "planning": "Planning", "costctrl": "Cost Control", "fleet": "Fleet", "fm": "FM",
    "op_tbu": "Operation Units (TBU)", "op_pbu": "Operation Units (PBU)",
    "op_dbu": "Operation Units (DBU)", "op_bbu": "Operation Units (BBU)",
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
    # (5.1, 5.2, 5.3, 5.5, 5.6) and Cost Control (5.4, plus its own copy of
    # 5.1/5.2 since both departments need those two) -- same
    # shared-item_no-across-departments pattern as item 124's 9.3 split.
    ("5.1", "Prepare Risk Register", "planning", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("5.2", "Highlight points require Pre-bid clarifications", "planning", "pre_bid", None, 3, "before", "date_driven", None),
    ("5.3", "Prepare Project schedule (level according to client requirement, up to Level 3)", "planning", "predecessor", "1.1", 15, "after", "date_driven", "M3"),
    ("5.5", "Verify Quantities for remeasured Contracts (if applicable)", "planning", "predecessor", "1.1", 3, "after", "date_driven", None),
    ("5.6", "Provide Updated Productivity Norms and Calculations (PCO-01-SPR-001)", "planning", None, None, 0, "after", "library", None),

    ("5.1", "Prepare Risk Register", "costctrl", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("5.2", "Highlight points require Pre-bid clarifications", "costctrl", "pre_bid", None, 3, "before", "date_driven", None),
    ("5.4", "Fleet Productivities (equipment productivity rates)", "costctrl", None, None, 0, "after", "library", None),

    ("6.1", "Prepare Risk Register", "contract", "predecessor", "1.20", 5, "before", "date_driven", None),
    ("6.2", "Highlight points require Pre-bid clarifications (Review Contracts and Terms)", "contract", "pre_bid", None, 3, "before", "date_driven", None),
    ("6.3", "Prepare Non Disclosure Agreements (NDA's) (if applicable)", "contract", None, None, 0, "after", "on_request", None),
    ("6.4", "Review Pre-bid agreements and provide Contractual comments as needed", "contract", None, None, 0, "after", "on_request", None),

    ("7.1", "Verify local content requirements in coordination with the Manning Schedule", "hr", "predecessor", "5.3", 5, "after", "date_driven", None),
    ("7.2", "Updated HR Cost Estimates (Salaries / Wages / Benefits)", "hr", None, None, 0, "after", "library", None),
    ("7.3", "Provide updated information on Workforce availability, nationality, release dates", "hr", None, None, 0, "after", "library", None),
    ("7.4", "Provide Supporting documents, such as team CV's, certificates and Qualifications", "hr", "predecessor", "1.1", 3, "after", "date_driven", None),

    ("8.1", "Prepare Risk Register", "finance", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("8.2", "Issue Bid Bonds", "finance", "predecessor", "1.20", 3, "before", "date_driven", None),
    ("8.3", "Provide Insurance Cost, and additional client requirements", "finance", "predecessor", "1.20", 6, "before", "date_driven", None),
    ("8.4", "Provide Proposed Business Units, Corporate, Finance and Insurance Overheads", "finance", None, None, 0, "after", "library", None),
    ("8.5", "Provide Proposed Cash Flow & Finance Cost and Parameters", "finance", None, None, 0, "after", "library", None),

    ("9.1", "Prepare Risk Register", "sheq", "predecessor", "2.2", 1, "after", "date_driven", None),
    ("9.2", "Highlight points require Pre-bid clarifications", "sheq", "pre_bid", None, 3, "before", "date_driven", None),
    ("9.3", "List of Safety Requirements & PPE", "sheq", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("9.4", "Prepare QA/QC Plan - Tender Level", "sheq", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("9.5", "Prepare HSE Plan - Tender Level", "sheq", "predecessor", "1.1", 7, "after", "date_driven", None),
    ("9.6", "Evaluate Selected subcontractors (for not Qualified / Approved Subcontractors)", "sheq", "predecessor", "1.17", 2, "after", "date_driven", None),
    ("9.7", "Standard Personnel Requirements (Client's Standards) HSSE / Quality", "sheq", "predecessor", "1.1", 7, "after", "date_driven", None),

    ("10.1", "Cost for Staff and Office Requirements (Hardware, Software, Infrastructure)", "it", "predecessor", "5.3", 3, "after", "date_driven", None),

    ("11.1", "Compile risk registers received from all departments, Evaluate and present", "risk", None, None, 0, "after", "on_request", None),

    # Item 128: L0's old combined "Fleet and Facility Management Department"
    # splits into Fleet (equipment, 12.1/12.2) and FM (camp, 12.3), matching
    # how L1 already separates them.
    ("12.1", "Recent Equipment Cost Estimates, Consumptions and Maintenance", "fleet", None, None, 0, "after", "library", None),
    ("12.2", "Provide recent information on Equipment availability, location and release dates", "fleet", None, None, 0, "after", "library", None),
    ("12.3", "Provide Camp Cost Estimates, Consumptions and Maintenance based on manning", "fm", "predecessor", "5.3", 5, "after", "date_driven", None),
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
    ("2.12", "Provide Confirmation on the Proposal recommendation for working schedule", "tbupbu", "predecessor", "5.6", 3, "after", None),

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
    ("2.12", "Provide Confirmation on the Proposal recommendation for working schedule", "tbu", "predecessor", "5.6", 3, "after", None),

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
    ("2.12", "Provide Confirmation on the Proposal recommendation for working schedule", "pbu", "predecessor", "5.6", 3, "after", None),
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
    ("2.12", "Provide Confirmation on the Proposal recommendation for working schedule", "dbu", "predecessor", "5.6", 3, "after", None),

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
    ("5.3", "Prepare Temporary Project Budget on Oracle", "costctrl", "predecessor", "2.1", 3, "after", None),
    ("5.4", "Prepare Project Baseline Budget on Oracle", "costctrl", "predecessor", "1.3", 14, "after", None),
    ("5.5", "Prepare Project Locked Budget on Oracle (As per signed Contract)", "costctrl", "predecessor", "1.6", 14, "after", None),
    ("5.6", "Provide Proposal recommendation for working schedule for time schedule driven items", "planning", "predecessor", "5.1", 3, "after", None),
    ("5.7", "Update Planning Risk Register including lesson learned", "planning", "predecessor", "5.2", 3, "after", None),

    ("6.1", "Update Contracts Risk Register and Contract Liabilities", "contract", "client_dependent", None, 1, "after", None),

    ("7.1", "Provide Workforce Availability Plan with Hiring dates", "hr", "predecessor", "1.2", 15, "after", None),

    ("8.1", "Secure Bank Facilities for the project / Project Finance Model", "treasury", "predecessor", "8.4", 10, "after", None),
    ("8.2", "Issuance of Performance Bond", "treasury", "predecessor", "1.5", 6, "after", None),
    ("8.3", "Issuance of Advance Payment Guarantee", "treasury", "predecessor", "1.6", 14, "after", None),
    ("8.4", "Provide Updated Cashflow and Finance Cost", "finance", "predecessor", "1.2", 5, "after", None),
    # Item 126: Insurance folded into Finance -- was its own "Insurance" department.
    ("8.5", "Provide Insurance Requirements (Cost & Provider selection)", "finance", "predecessor", "1.6", 10, "after", None),

    ("9.1", "Provide QA/QC Detailed Plan including ITPs for major activities", "quality", "predecessor", "1.2", 17, "after", None),
    ("9.2", "Provide HSE Detailed Plan (Site Safety, HSE, Safety training)", "hsse", "predecessor", "1.2", 17, "after", None),
    # Item 123/124: "HSSE and Quality Staffing plans" split into one item
    # per department instead of one combined item under a third "HSSE /
    # Quality" department -- both keep item_no 9.3, same as how Operation
    # Units' BU split shares one item_no across several departments.
    ("9.3", "Provide HSSE Staffing plan", "hsse", "predecessor", "1.2", 12, "after", None),
    ("9.3", "Provide Quality Staffing plan", "quality", "predecessor", "1.2", 12, "after", None),
    ("9.4", "Provide Risk Assessment (including identification of main hazards)", "hsse", "predecessor", "1.2", 10, "after", None),
    ("9.5", "Provide Environmental management plan", "hsse", "predecessor", "1.2", 20, "after", None),
    ("9.6", "Provide Waste management plan", "hsse", "predecessor", "1.2", 20, "after", None),

    ("10.1", "Verify and update Project Risk register", "risk", "predecessor", "5.7", 15, "after", None),

    ("11.1", "Provide Updated information on Equipment availability, location", "fleet", "predecessor", "1.6", 7, "after", None),

    ("12.1", "Verify Updated Camp Cost Estimates, Consumptions and Maintenance", "fm", "predecessor", "1.2", 7, "after", None),
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
    "5.4": "Fleet Productivities", "5.5": "Verify Quantities", "5.6": "Productivity Norms",

    "6.1": "Prepare Risk Register", "6.2": "Review Contract Terms", "6.3": "Prepare NDA",
    "6.4": "Review Pre-bid Agreements",

    "7.1": "Verify Local Content", "7.2": "HR Cost Estimates", "7.3": "Workforce Availability",
    "7.4": "Team CVs & Certificates",

    "8.1": "Prepare Risk Register", "8.2": "Issue Bid Bonds", "8.3": "Insurance Cost",
    "8.4": "Proposed Overheads", "8.5": "Cash Flow & Finance Cost",

    "9.1": "Prepare Risk Register", "9.2": "Highlight Pre-bid Points", "9.3": "Safety Requirements & PPE",
    "9.4": "QA/QC Plan", "9.5": "HSE Plan", "9.6": "Evaluate Subcontractors", "9.7": "Personnel Requirements",

    "10.1": "Staff & Office Cost",
    "11.1": "Compile Risk Registers",
    "12.1": "Equipment Cost Estimates", "12.2": "Equipment Availability", "12.3": "Camp Cost Estimates",
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

    "5.1": "Baseline Schedule", "5.2": "Working Schedule", "5.3": "Temp Project Budget",
    "5.4": "Baseline Budget", "5.5": "Locked Budget", "5.6": "Schedule Recommendation",
    "5.7": "Update Risk Register",

    "6.1": "Update Risk Register",
    "7.1": "Workforce Availability Plan",

    "8.1": "Secure Bank Facilities", "8.2": "Performance Bond", "8.3": "Advance Payment Guarantee",
    "8.4": "Updated Cashflow", "8.5": "Insurance Requirements",

    "9.1": "QA/QC Detailed Plan", "9.2": "HSE Detailed Plan", "9.3": "Staffing Plan",
    "9.4": "Risk Assessment", "9.5": "Environmental Plan", "9.6": "Waste Management Plan",

    "10.1": "Update Risk Register",
    "11.1": "Equipment Availability",
    "12.1": "Camp Cost Estimates",
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

        cost_control_dept = db.query(models.Department).filter_by(name="Cost Control").first()
        if planning_dept and cost_control_dept:
            fleet_prod_def = db.query(models.DeliverableDefinition).filter_by(
                stage=models.Stage.L0, item_no="5.4", department_id=planning_dept.id
            ).first()
            if fleet_prod_def:
                fleet_prod_def.department_id = cost_control_dept.id
                db.commit()

            for item_no, name, short in (
                ("5.1", "Prepare Risk Register", "Prepare Risk Register"),
                ("5.2", "Highlight points require Pre-bid clarifications", "Highlight Pre-bid Points"),
            ):
                old_def = db.query(models.DeliverableDefinition).filter_by(
                    stage=models.Stage.L0, item_no=item_no, department_id=planning_dept.id
                ).first()
                already = db.query(models.DeliverableDefinition).filter_by(
                    stage=models.Stage.L0, item_no=item_no, department_id=cost_control_dept.id
                ).first()
                if old_def and not already:
                    new_def = models.DeliverableDefinition(
                        stage=models.Stage.L0, item_no=item_no, name=name, short_name=short,
                        department_id=cost_control_dept.id,
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
                    # A duplicate created here bypasses _provision_and_instantiate,
                    # so unless it was approved above, it starts out with the
                    # model's bare default (status=NOT_DUE, due_date=None) --
                    # force a recompute so pending items correctly land on
                    # PENDING_TRIAGE (item 129's Cost Control copies are L0,
                    # where that status is real) and everything else gets a
                    # real due date instead of sitting stuck at None.
                    for proj in affected_projects:
                        rules.recompute_project_due_dates(db, proj, force=True)
                    db.commit()

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

        print(f"Seed complete: {len(dept_map)} departments, {len(L0_ITEMS)} L0 items, {len(L1_ITEMS)} L1 items.")
    finally:
        db.close()


if __name__ == "__main__":
    run()

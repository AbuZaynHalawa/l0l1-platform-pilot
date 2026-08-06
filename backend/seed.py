"""Seeds departments, milestone definitions, and a starter deliverable catalog.

Real department names and item numbers/descriptions are from the actual L0
template (see architecture_map.md section 3.2). Focal point emails below are
PLACEHOLDERS — swap TEST_EMAILS for your team's real addresses when ready,
then re-run: `python -m app.backend.seed` (safe to re-run, it upserts).
"""
from .database import SessionLocal, engine
from . import models

models.Base.metadata.create_all(bind=engine)

# --- Swap these for real team emails when you have them ---
TEST_EMAILS = {
    "Tendering": "test-owner-1@example.com",
    "Operation": "test-owner-2@example.com",
    "Supply Chain": "test-owner-3@example.com",
    "Engineering": "test-owner-4@example.com",
    "Control Department": "test-owner-5@example.com",
    "Contract and QS": "test-owner-6@example.com",
    "HR": "test-owner-7@example.com",
    "Finance": "test-owner-8@example.com",
    "Quality & HSSE": "test-owner-9@example.com",
    "IT": "test-owner-10@example.com",
}

DEPARTMENTS = [
    ("01. Tendering", "Tendering"),
    ("02. Operation", "Operation"),
    ("03. Supply Chain", "Supply Chain"),
    ("04. Engineering", "Engineering"),
    ("05. Control Department", "Control Department"),
    ("06. Contract and QS", "Contract and QS"),
    ("07. HR", "HR"),
    ("08. Finance", "Finance"),
    ("09. Quality & HSSE", "Quality & HSSE"),
    ("10. IT", "IT"),
]

MILESTONES_L0 = [("M1", "GO", 1), ("M2", "Site Visit", 2), ("M3", "Schedule", 3), ("M4", "Technical Offers", 4), ("M5", "Proposal / BSD", 5)]
MILESTONES_L1 = [("M1", "L1 Announcement", 1), ("M2", "Early Plan", 2), ("M3", "Docs Handover", 3),
                  ("M4", "Post-Bid Starts", 4), ("M5", "LOA Received", 5), ("M6", "Contract Signed", 6)]

# (stage, item_no, name, department_short_name, anchor_type, anchor(milestone code or predecessor item_no), offset_days, direction)
DELIVERABLES = [
    ("L0", "1.1", "Receive Approval for GO Approach & Circulate Tender Documents", "Tendering", "milestone", "M1", 0, "after"),
    ("L0", "1.8", "Float SC RFQ's - Local", "Tendering", "milestone", "M1", 14, "after"),
    ("L0", "2.2", "Prepare & Circulate Site Visit Report", "Operation", "milestone", "M2", 3, "after"),
    ("L0", "3.1", "Prepare Risk Register", "Supply Chain", "milestone", "M1", 10, "after"),
    ("L0", "4.4", "Generate Design & BOQ's for SS and UGC", "Engineering", "milestone", "M1", 21, "after"),
    ("L0", "4.6", "Review & Evaluate Technical Offers from Vendors", "Engineering", "predecessor", "4.4", 5, "after"),
    ("L0", "5.3", "Prepare Project Schedule Loaded with Resources", "Control Department", "milestone", "M1", 21, "after"),
    ("L0", "6.1", "Prepare Risk Register", "Contract and QS", "milestone", "M1", 10, "after"),
    ("L0", "7.1", "Verify Local Content Requirements with Management", "HR", "milestone", "M1", 14, "after"),
    ("L0", "8.1", "Prepare Risk Register", "Finance", "milestone", "M1", 10, "after"),
    ("L0", "9.4", "Prepare QA/QC Plan - Tender Level", "Quality & HSSE", "milestone", "M1", 10, "after"),
    ("L0", "10.1", "Cost for Staff & Office Requirements", "IT", "milestone", "M1", 14, "after"),
    ("L1", "1.1", "L1 Announcement Email", "Tendering", "milestone", "M1", 0, "after"),
    ("L1", "2.3", "Assignment of PM + PE", "Operation", "milestone", "M1", 7, "after"),
    ("L1", "3.1", "Issue RFQ to Vendors", "Supply Chain", "milestone", "M1", 10, "after"),
    ("L1", "4.4", "Generate Design & BOQ's for SS and UGC", "Engineering", "milestone", "M1", 21, "after"),
    ("L1", "4.6", "Review & Evaluate Technical Offers from Vendors", "Engineering", "predecessor", "4.4", 5, "after"),
    ("L1", "5.3", "Prepare Baseline Project Schedule", "Control Department", "milestone", "M1", 21, "after"),
    ("L1", "6.1", "Prepare Risk Register", "Contract and QS", "milestone", "M2", 15, "after"),
    ("L1", "7.2", "HR Cost Estimate", "HR", "milestone", "M2", 10, "after"),
    ("L1", "8.1", "Provide Cashflow Input", "Finance", "milestone", "M2", 12, "after"),
    ("L1", "9.5", "Prepare HSE Plan", "Quality & HSSE", "milestone", "M2", 15, "after"),
    ("L1", "6.4", "Prebid Agreement Review", "Contract and QS", "milestone", "M4", 10, "after"),
    ("L1", "8.4", "Insurance Requirements (Cost & Provider)", "Finance", "milestone", "M5", 10, "after"),
]


def run():
    db = SessionLocal()
    try:
        dept_map = {}
        for full_name, short_name in DEPARTMENTS:
            dept = db.query(models.Department).filter_by(name=full_name).first()
            if not dept:
                dept = models.Department(name=full_name, order=len(dept_map))
                db.add(dept)
                db.flush()
            dept.focal_point_email = TEST_EMAILS.get(short_name)
            dept.focal_point_name = f"TEST focal ({short_name})"
            dept_map[short_name] = dept
        db.commit()

        for stage, ms_list in (("L0", MILESTONES_L0), ("L1", MILESTONES_L1)):
            for code, name, seq in ms_list:
                exists = db.query(models.MilestoneDefinition).filter_by(stage=stage, code=code).first()
                if not exists:
                    db.add(models.MilestoneDefinition(stage=stage, code=code, name=name, sequence=seq))
        db.commit()

        for stage, item_no, name, dept_short, anchor_type, anchor, offset, direction in DELIVERABLES:
            dept = dept_map[dept_short]
            exists = db.query(models.DeliverableDefinition).filter_by(stage=stage, item_no=item_no, department_id=dept.id).first()
            if exists:
                continue
            kwargs = dict(stage=stage, item_no=item_no, name=name, department_id=dept.id,
                          anchor_type=anchor_type, offset_days=offset, offset_direction=direction)
            if anchor_type == "milestone":
                kwargs["anchor_milestone_code"] = anchor
            else:
                kwargs["predecessor_item_no"] = anchor
            db.add(models.DeliverableDefinition(**kwargs))
        db.commit()
        print("Seed complete:", len(dept_map), "departments,", len(DELIVERABLES), "deliverable definitions.")
    finally:
        db.close()


if __name__ == "__main__":
    run()

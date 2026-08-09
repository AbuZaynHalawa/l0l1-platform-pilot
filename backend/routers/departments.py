from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, rules
from ..database import get_db

router = APIRouter(prefix="/api/departments", tags=["departments"])


class FocalPointUpdate(BaseModel):
    focal_point_name: str | None = None
    focal_point_email: str | None = None


@router.get("")
def list_departments(db: Session = Depends(get_db)):
    depts = db.query(models.Department).order_by(models.Department.number).all()
    return [
        {"id": d.id, "name": d.name, "number": d.number, "focal_point_name": d.focal_point_name, "focal_point_email": d.focal_point_email}
        for d in depts
    ]


@router.patch("/{department_id}/focal-point")
def update_focal_point(department_id: int, payload: FocalPointUpdate, db: Session = Depends(get_db)):
    dept = db.get(models.Department, department_id)
    if not dept:
        raise HTTPException(404, "Department not found")
    dept.focal_point_name = (payload.focal_point_name or "").strip() or None
    dept.focal_point_email = (payload.focal_point_email or "").strip() or None
    db.commit()
    return {"id": dept.id, "name": dept.name, "number": dept.number,
            "focal_point_name": dept.focal_point_name, "focal_point_email": dept.focal_point_email}


@router.get("/options")
def get_create_options():
    """Reference lists for the Create L0/L1 form dropdowns."""
    return {
        "bid_managers": models.BID_MANAGERS,
        "regions": models.REGION_OPTIONS,
        "scopes": models.SCOPE_OPTIONS,
        "bu_uncovered_scopes": rules.BU_UNCOVERED_SCOPES,
        "business_units": ["TBU", "PBU", "DBU", "BBU", "TBA"],
    }

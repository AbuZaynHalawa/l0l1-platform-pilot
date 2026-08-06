from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db

router = APIRouter(prefix="/api/departments", tags=["departments"])


@router.get("")
def list_departments(db: Session = Depends(get_db)):
    depts = db.query(models.Department).order_by(models.Department.order).all()
    return [
        {"id": d.id, "name": d.name, "focal_point_name": d.focal_point_name, "focal_point_email": d.focal_point_email}
        for d in depts
    ]


@router.get("/options")
def get_create_options():
    """Reference lists for the Create L0/L1 form dropdowns."""
    return {
        "bid_managers": models.BID_MANAGERS,
        "regions": models.REGION_OPTIONS,
        "scopes": models.SCOPE_OPTIONS,
    }

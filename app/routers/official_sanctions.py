from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.auth import get_current_platform_staff
from app.database import get_db
from app.models import PlatformStaff
from app.schemas import ModerationSanctionPage, ModerationSanctionResponse, ModerationSanctionReview
from app.services.moderation_sanction_service import (
    list_platform_sanctions,
    review_platform_sanction,
    serialize_platform_sanction,
)


router = APIRouter(prefix="/official/sanctions", tags=["Sanções da plataforma"])


@router.get("", response_model=ModerationSanctionPage)
def list_sanctions_route(
    staff: Annotated[PlatformStaff, Depends(get_current_platform_staff)],
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    target_user_id: int | None = Query(default=None, gt=0),
    report_id: int | None = Query(default=None, gt=0),
) -> dict:
    _ = staff
    return list_platform_sanctions(
        db,
        page=page,
        page_size=page_size,
        target_user_id=target_user_id,
        report_id=report_id,
    )


@router.post("/{sanction_id}/review", response_model=ModerationSanctionResponse)
def review_sanction_route(
    sanction_id: Annotated[int, Path(gt=0)],
    body: ModerationSanctionReview,
    staff: Annotated[PlatformStaff, Depends(get_current_platform_staff)],
    db: Annotated[Session, Depends(get_db)],
) -> ModerationSanctionResponse:
    sanction = review_platform_sanction(
        db,
        sanction_id=sanction_id,
        staff=staff,
        decision=body.decision,
        reason=body.reason,
    )
    return serialize_platform_sanction(db, sanction)

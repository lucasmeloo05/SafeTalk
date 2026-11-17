from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import ModerationReportCreate, ModerationReportResponse
from app.services.moderation_report_service import create_message_report


router = APIRouter(prefix="/reports", tags=["Denúncias"])


@router.post(
    "",
    response_model=ModerationReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_report_route(
    report_data: ModerationReportCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ModerationReportResponse:
    report = create_message_report(
        db=db,
        current_user=current_user,
        message_id=report_data.message_id,
        reason=report_data.reason,
    )
    return ModerationReportResponse.model_validate(report)

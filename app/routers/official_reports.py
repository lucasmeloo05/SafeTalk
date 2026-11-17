from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_platform_staff
from app.database import get_db
from app.models import ModerationAnalysisJob, ModerationAction, PlatformStaff
from app.schemas import (
    ModerationAnalysisSummary,
    ModerationHumanDecision,
    ModerationReportDetailResponse,
    ModerationReportPage,
    ModerationReportTriage,
)
from app.services.moderation_review_service import (
    get_official_analysis,
    get_official_report_detail,
    list_official_reports,
    record_human_decision,
    triage_report_for_external_analysis,
)


router = APIRouter(prefix="/official/reports", tags=["Moderação oficial"])


@router.get("", response_model=ModerationReportPage)
def list_reports_route(
    staff: Annotated[PlatformStaff, Depends(get_current_platform_staff)],
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    # Both approved official roles can review reports; the current product rules
    # do not define different capabilities for ADMIN versus MODERATOR.
    _ = staff
    return list_official_reports(db, page=page, page_size=page_size)


@router.get("/{report_id}", response_model=ModerationReportDetailResponse)
def get_report_route(
    report_id: int,
    staff: Annotated[PlatformStaff, Depends(get_current_platform_staff)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    _ = staff
    return get_official_report_detail(db, report_id)


@router.get(
    "/{report_id}/analysis",
    response_model=ModerationAnalysisSummary,
)
def get_analysis_route(
    report_id: int,
    staff: Annotated[PlatformStaff, Depends(get_current_platform_staff)],
    db: Annotated[Session, Depends(get_db)],
) -> ModerationAnalysisJob:
    _ = staff
    return get_official_analysis(db, report_id)


@router.post(
    "/{report_id}/triage",
    response_model=ModerationAnalysisSummary,
    status_code=202,
)
def triage_report_route(
    report_id: int,
    body: ModerationReportTriage,
    staff: Annotated[PlatformStaff, Depends(get_current_platform_staff)],
    db: Annotated[Session, Depends(get_db)],
) -> ModerationAnalysisJob:
    return triage_report_for_external_analysis(
        db,
        report_id=report_id,
        staff=staff,
        external_analysis_eligible=body.external_analysis_eligible,
        sensitive_content_suspected=body.sensitive_content_suspected,
        reason=body.reason,
    )


@router.post("/{report_id}/decision", status_code=201)
def record_decision_route(
    report_id: int,
    body: ModerationHumanDecision,
    staff: Annotated[PlatformStaff, Depends(get_current_platform_staff)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    action: ModerationAction = record_human_decision(
        db,
        report_id=report_id,
        staff=staff,
        decision=body.decision,
        reason=body.reason,
    )
    return {
        "id": action.id,
        "report_id": action.report_id,
        "actor_user_id": action.actor_user_id,
        "decision": action.action_type,
        "reason": action.reason,
        "created_at": action.created_at,
    }

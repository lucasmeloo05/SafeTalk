"""Official-staff-only report queue, triage, and human decision operations."""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    ModerationAction,
    ModerationAnalysisJob,
    ModerationReport,
    ModerationReportEvidence,
    PlatformStaff,
    Server,
)
from app.services.moderation_sanction_service import (
    HUMAN_DECISIONS,
    issue_sanctions_for_decision,
    lock_report_target_user,
)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Denúncia não encontrada.",
    )


def list_official_reports(
    db: Session,
    *,
    page: int,
    page_size: int,
    viewer_user_id: int | None = None,
) -> dict:
    from app.age_policy import report_age_filter
    age_scope = report_age_filter(db, viewer_user_id)
    total = db.scalar(select(func.count(ModerationReport.id)).where(age_scope)) or 0
    rows = db.execute(
        select(ModerationReport, ModerationAnalysisJob)
        .join(
            ModerationAnalysisJob,
            ModerationAnalysisJob.report_id == ModerationReport.id,
        )
        .where(age_scope)
        .order_by(ModerationReport.created_at.desc(), ModerationReport.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [
            {
                "id": report.id,
                "message_id": report.message_id,
                "reason": report.reason,
                "status": report.status,
                "triage_status": report.triage_status,
                "analysis": job,
                "created_at": report.created_at,
            }
            for report, job in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


def get_official_report_detail(db: Session, report_id: int) -> dict:
    row = db.execute(
        select(ModerationReport, ModerationReportEvidence, ModerationAnalysisJob)
        .join(
            ModerationReportEvidence,
            ModerationReportEvidence.report_id == ModerationReport.id,
        )
        .join(
            ModerationAnalysisJob,
            ModerationAnalysisJob.report_id == ModerationReport.id,
        )
        .where(ModerationReport.id == report_id)
    ).first()
    if row is None:
        raise _not_found()
    report, evidence, job = row
    actions = db.scalars(
        select(ModerationAction)
        .where(ModerationAction.report_id == report.id)
        .order_by(ModerationAction.created_at.asc(), ModerationAction.id.asc())
    ).all()
    return {
        "id": report.id,
        "message_id": report.message_id,
        "reporter_id": report.reporter_id,
        "reason": report.reason,
        "status": report.status,
        "triage_status": report.triage_status,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
        "evidence": evidence,
        "analysis": job,
        "actions": actions,
    }


def get_official_analysis(db: Session, report_id: int) -> ModerationAnalysisJob:
    job = db.scalar(
        select(ModerationAnalysisJob)
        .join(
            ModerationReport,
            ModerationReport.id == ModerationAnalysisJob.report_id,
        )
        .where(ModerationReport.id == report_id)
    )
    if job is None:
        raise _not_found()
    return job


def triage_report_for_external_analysis(
    db: Session,
    *,
    report_id: int,
    staff: PlatformStaff,
    external_analysis_eligible: bool,
    sensitive_content_suspected: bool = False,
    reason: str,
) -> ModerationAnalysisJob:
    now = datetime.now(timezone.utc)
    try:
        report = db.scalar(
            select(ModerationReport)
            .where(ModerationReport.id == report_id)
            .with_for_update()
        )
        if report is None:
            raise _not_found()
        job = db.scalar(
            select(ModerationAnalysisJob)
            .where(ModerationAnalysisJob.report_id == report_id)
            .with_for_update()
        )
        if job is None:
            raise _not_found()
        if report.status != "PENDING" or job.status != "PENDING_TRIAGE":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A denúncia já passou pela triagem inicial.",
            )

        if external_analysis_eligible and not sensitive_content_suspected:
            origin = db.scalar(select(ModerationReportEvidence.server_id).where(ModerationReportEvidence.report_id == report_id))
            if origin is not None and not db.scalar(select(Server.ai_moderation_enabled).where(Server.id == origin)):
                raise HTTPException(409, "A análise externa está desativada neste servidor.")
            job.status = "PENDING"
            job.available_at = now
            report.triage_status = "APPROVED"
            action_type = "EXTERNAL_ANALYSIS_APPROVED"
        else:
            job.status = "MANUAL_REVIEW"
            report.triage_status = "MANUAL_REVIEW"
            action_type = (
                "SENSITIVE_CONTENT_MANUAL_REVIEW"
                if sensitive_content_suspected
                else "MANUAL_REVIEW_REQUIRED"
            )

        job.updated_at = now
        report.updated_at = now
        db.add(
            ModerationAction(
                report_id=report.id,
                actor_user_id=staff.user_id,
                action_type=action_type,
                reason=reason,
            )
        )
        db.commit()
        db.refresh(job)
        return job
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível registrar a triagem.",
        ) from exc
    except Exception:
        db.rollback()
        raise


def record_human_decision(
    db: Session,
    *,
    report_id: int,
    staff: PlatformStaff,
    decision: str,
    reason: str,
) -> ModerationAction:
    if decision not in HUMAN_DECISIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Decisão de moderação inválida.",
        )
    now = datetime.now(timezone.utc)
    try:
        # All account-affecting moderation decisions lock the target user first.
        # This serializes lifetime warning counts across different reports.
        target_user_id = lock_report_target_user(db, report_id)
        report = db.scalar(
            select(ModerationReport)
            .where(ModerationReport.id == report_id)
            .with_for_update()
        )
        if report is None:
            raise _not_found()
        if report.status != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A denúncia já possui uma decisão humana registrada.",
            )

        evidence_target_id = db.scalar(
            select(ModerationReportEvidence.message_author_id).where(
                ModerationReportEvidence.report_id == report.id
            )
        )
        if evidence_target_id != target_user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A evidência da denúncia foi alterada durante a decisão.",
            )

        # After user -> report, preserve the worker's report -> job ordering.
        # This invalidates an in-flight claim token so its result cannot replace
        # the final human decision.
        job = db.scalar(
            select(ModerationAnalysisJob)
            .where(ModerationAnalysisJob.report_id == report_id)
            .with_for_update()
        )

        action = ModerationAction(
            report_id=report.id,
            actor_user_id=staff.user_id,
            action_type=decision,
            decision_code=decision,
            reason=reason,
        )
        db.add(action)
        db.flush()
        issue_sanctions_for_decision(
            db,
            report_id=report.id,
            target_user_id=target_user_id,
            staff=staff,
            source_action_id=action.id,
            decision=decision,
            reason=reason,
        )
        report.status = "REVIEWED"
        report.updated_at = now
        if job is not None and job.status in {
            "PENDING_TRIAGE",
            "PENDING",
            "PROCESSING",
        }:
            job.status = "MANUAL_REVIEW"
            job.claimed_at = None
            job.claim_token = None
            job.updated_at = now
            report.triage_status = "MANUAL_REVIEW"
        db.commit()
        db.refresh(action)
        return action
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível registrar a decisão.",
        ) from exc
    except Exception:
        db.rollback()
        raise

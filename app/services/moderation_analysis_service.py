"""Persistent, manually gated OpenAI Moderation API processing.

Message text is selected only from the stored evidence of an official-staff
approved job. The provider call is made after the claim transaction commits.
No message text or provider exception details are written to application logs.
The moderation result is a signal for human review and never applies a penalty.
"""

import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.models import ModerationAnalysisJob, ModerationReport, ModerationReportEvidence


MODEL_NAME = "omni-moderation-latest"
MAX_ATTEMPTS = 3
LEASE_DURATION = timedelta(minutes=2)
BASE_RETRY_DELAY = timedelta(seconds=30)


@dataclass(frozen=True)
class _ClaimedJob:
    job_id: int
    claim_token: UUID
    content: str


def create_openai_client():
    """Create the official SDK client from OPENAI_API_KEY only."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    from openai import OpenAI
    from app.settings import settings

    return OpenAI(
        api_key=api_key,
        timeout=settings.moderation_openai_timeout_seconds,
        max_retries=0,
    )


def _claim_next_job(session_factory: sessionmaker[Session]) -> _ClaimedJob | None:
    now = datetime.now(timezone.utc)
    stale_before = now - LEASE_DURATION
    with session_factory() as db:
        try:
            # Lock the report first, then its job. Review operations use the
            # same order, and SKIP LOCKED lets other workers claim other reports.
            candidate_row = db.execute(
                select(ModerationReport, ModerationAnalysisJob)
                .join(
                    ModerationAnalysisJob,
                    ModerationAnalysisJob.report_id == ModerationReport.id,
                )
                .where(
                    ModerationReport.status == "PENDING",
                    ModerationReport.triage_status == "APPROVED",
                    or_(
                        and_(
                            ModerationAnalysisJob.status == "PENDING",
                            ModerationAnalysisJob.available_at <= now,
                        ),
                        and_(
                            ModerationAnalysisJob.status == "PROCESSING",
                            ModerationAnalysisJob.claimed_at < stale_before,
                        ),
                    )
                )
                .order_by(
                    ModerationAnalysisJob.available_at,
                    ModerationAnalysisJob.created_at,
                    ModerationAnalysisJob.id,
                )
                .with_for_update(of=ModerationReport, skip_locked=True)
                .limit(1)
            ).first()
            if candidate_row is None:
                db.commit()
                return None

            report, candidate_snapshot = candidate_row
            candidate = db.scalar(
                select(ModerationAnalysisJob)
                .where(ModerationAnalysisJob.id == candidate_snapshot.id)
                .with_for_update()
            )
            if candidate is None:
                db.commit()
                return None

            # Recheck after acquiring both locks, before any content is read.
            if (
                report.status != "PENDING"
                or report.triage_status != "APPROVED"
                or not (
                    (
                        candidate.status == "PENDING"
                        and candidate.available_at <= now
                    )
                    or (
                        candidate.status == "PROCESSING"
                        and candidate.claimed_at is not None
                        and candidate.claimed_at < stale_before
                    )
                )
            ):
                db.commit()
                return None

            # A crashed worker may have exhausted its final attempt while in
            # PROCESSING. Close that lease without another provider call.
            if candidate.attempt_count >= MAX_ATTEMPTS:
                candidate.status = "FAILED"
                candidate.claimed_at = None
                candidate.claim_token = None
                candidate.last_error_code = "WORKER_INTERRUPTED"
                candidate.updated_at = now
                report.triage_status = "FAILED"
                report.updated_at = now
                db.commit()
                return None

            evidence = db.scalar(
                select(ModerationReportEvidence).where(
                    ModerationReportEvidence.report_id == candidate.report_id
                )
            )
            if evidence is None:
                candidate.status = "FAILED"
                candidate.claimed_at = None
                candidate.claim_token = None
                candidate.last_error_code = "EVIDENCE_MISSING"
                candidate.updated_at = now
                report.triage_status = "FAILED"
                report.updated_at = now
                db.commit()
                return None

            token = uuid4()
            candidate.status = "PROCESSING"
            candidate.attempt_count += 1
            candidate.claimed_at = now
            candidate.claim_token = token
            candidate.last_error_code = None
            candidate.updated_at = now
            claimed = _ClaimedJob(
                job_id=candidate.id,
                claim_token=token,
                content=evidence.content_snapshot,
            )
            db.commit()
            return claimed
        except SQLAlchemyError:
            db.rollback()
            raise


def _object_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, dict):
        return None
    return value


def _parse_response(response: Any) -> dict[str, Any] | None:
    payload = _object_mapping(response)
    if payload is None:
        return None
    model = payload.get("model")
    results = payload.get("results")
    if not isinstance(model, str) or not model.strip():
        return None
    if not isinstance(results, list) or len(results) != 1:
        return None

    result = _object_mapping(results[0])
    if result is None or not isinstance(result.get("flagged"), bool):
        return None
    categories = _object_mapping(result.get("categories"))
    scores = _object_mapping(result.get("category_scores"))
    if categories is None or scores is None:
        return None
    if any(not isinstance(value, bool) for value in categories.values()):
        return None
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for value in scores.values()
    ):
        return None

    applied_types = _object_mapping(result.get("category_applied_input_types"))
    if applied_types is not None and any(
        not isinstance(value, list)
        or any(not isinstance(item, str) for item in value)
        for value in applied_types.values()
    ):
        applied_types = None

    response_id = payload.get("id")
    return {
        "model": model,
        "flagged": result["flagged"],
        "categories": categories,
        "category_scores": scores,
        "category_applied_input_types": applied_types,
        "provider_response_id": response_id if isinstance(response_id, str) else None,
    }


def _error_code(error: Exception) -> str:
    # Avoid serializing/logging SDK exceptions because they can contain request
    # metadata. Only stable, non-content-bearing codes are persisted.
    if isinstance(error, (TimeoutError,)) or error.__class__.__name__ in {
        "APITimeoutError",
        "APIConnectionError",
    }:
        return "PROVIDER_TIMEOUT_OR_UNAVAILABLE"
    return "PROVIDER_ERROR"


def _record_failure(
    session_factory: sessionmaker[Session],
    claimed: _ClaimedJob,
    code: str,
) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as db:
        try:
            report = db.scalar(
                select(ModerationReport)
                .join(
                    ModerationAnalysisJob,
                    ModerationAnalysisJob.report_id == ModerationReport.id,
                )
                .where(ModerationAnalysisJob.id == claimed.job_id)
                .with_for_update(of=ModerationReport)
            )
            if report is None:
                db.rollback()
                return
            job = db.scalar(
                select(ModerationAnalysisJob)
                .where(
                    ModerationAnalysisJob.id == claimed.job_id,
                    ModerationAnalysisJob.status == "PROCESSING",
                    ModerationAnalysisJob.claim_token == claimed.claim_token,
                )
                .with_for_update()
            )
            if job is None:
                db.rollback()
                return
            if report.status != "PENDING" or report.triage_status != "APPROVED":
                job.status = "MANUAL_REVIEW"
                job.claimed_at = None
                job.claim_token = None
                job.updated_at = now
                db.commit()
                return
            exhausted = job.attempt_count >= MAX_ATTEMPTS
            job.status = "FAILED" if exhausted else "PENDING"
            job.claimed_at = None
            job.claim_token = None
            job.last_error_code = code
            if not exhausted:
                delay = BASE_RETRY_DELAY * (2 ** (job.attempt_count - 1))
                job.available_at = now + delay
            job.updated_at = now
            if exhausted:
                report.triage_status = "FAILED"
                report.updated_at = now
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            # The processing lease will expire and be recovered by the worker.


def _record_success(
    session_factory: sessionmaker[Session],
    claimed: _ClaimedJob,
    result: dict[str, Any],
) -> bool:
    now = datetime.now(timezone.utc)
    with session_factory() as db:
        try:
            report = db.scalar(
                select(ModerationReport)
                .join(
                    ModerationAnalysisJob,
                    ModerationAnalysisJob.report_id == ModerationReport.id,
                )
                .where(ModerationAnalysisJob.id == claimed.job_id)
                .with_for_update(of=ModerationReport)
            )
            if report is None:
                db.rollback()
                return False
            job = db.scalar(
                select(ModerationAnalysisJob)
                .where(
                    ModerationAnalysisJob.id == claimed.job_id,
                    ModerationAnalysisJob.status == "PROCESSING",
                    ModerationAnalysisJob.claim_token == claimed.claim_token,
                )
                .with_for_update()
            )
            if job is None:
                db.rollback()
                return False
            if report.status != "PENDING" or report.triage_status != "APPROVED":
                job.status = "MANUAL_REVIEW"
                job.claimed_at = None
                job.claim_token = None
                job.updated_at = now
                db.commit()
                return False
            job.status = "COMPLETED"
            job.claimed_at = None
            job.claim_token = None
            job.model = result["model"]
            job.flagged = result["flagged"]
            job.categories = result["categories"]
            job.category_scores = result["category_scores"]
            job.category_applied_input_types = result[
                "category_applied_input_types"
            ]
            job.provider_response_id = result["provider_response_id"]
            job.analyzed_at = now
            job.last_error_code = None
            job.updated_at = now
            report.triage_status = "COMPLETED"
            report.updated_at = now
            db.commit()
            return True
        except SQLAlchemyError:
            db.rollback()
            # A retry can repeat the provider request after the processing lease
            # expires, but the unique outbox row prevents duplicate results.
            return False


def process_next_analysis_job(
    session_factory: sessionmaker[Session],
    client: Any,
) -> bool:
    """Process at most one eligible job; return False when the queue is empty."""
    claimed = _claim_next_job(session_factory)
    if claimed is None:
        return False

    try:
        # This network call is deliberately outside any database transaction.
        response = client.moderations.create(
            model=MODEL_NAME,
            input=claimed.content,
        )
        result = _parse_response(response)
        if result is None:
            _record_failure(session_factory, claimed, "INVALID_PROVIDER_RESPONSE")
            return True
        _record_success(session_factory, claimed, result)
    except Exception as exc:
        _record_failure(session_factory, claimed, _error_code(exc))
    return True

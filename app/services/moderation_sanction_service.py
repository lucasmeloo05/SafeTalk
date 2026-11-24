"""Platform account sanctions, recurrence and human review operations."""

from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    ModerationAction,
    ModerationReportEvidence,
    ModerationSanction,
    ModerationSanctionBasis,
    ModerationSanctionReview,
    PlatformStaff,
    User,
)

TEMPORARY_SUSPENSION_DAYS = 7
HUMAN_DECISIONS = frozenset(
    {
        "NO_VIOLATION",
        "REVIEWED_MANUALLY",
        "WARNING",
        "TEMPORARY_SUSPENSION",
        "PERMANENT_BAN",
    }
)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Sanção não encontrada.")


def lock_report_target_user(db: Session, report_id: int) -> int:
    """Read the immutable evidence target, then lock its user before report locks."""
    target_id = db.scalar(
        select(ModerationReportEvidence.message_author_id).where(
            ModerationReportEvidence.report_id == report_id
        )
    )
    if target_id is None:
        raise HTTPException(status_code=404, detail="Denúncia não encontrada.")
    locked_id = db.scalar(
        select(User.id).where(User.id == target_id).with_for_update()
    )
    if locked_id is None:
        raise HTTPException(status_code=404, detail="Denúncia não encontrada.")
    return locked_id


def issue_sanctions_for_decision(
    db: Session,
    *,
    report_id: int,
    target_user_id: int,
    staff: PlatformStaff,
    source_action_id: int,
    decision: str,
    reason: str,
) -> list[ModerationSanction]:
    """Create direct or recurrence-derived sanctions in caller's transaction.

    Caller must hold the target user's row lock and the report/job locks.
    """
    now = db.scalar(select(func.now()))
    created: list[ModerationSanction] = []

    if decision == "WARNING":
        warning = ModerationSanction(
            report_id=report_id,
            target_user_id=target_user_id,
            actor_user_id=staff.user_id,
            source_action_id=source_action_id,
            sanction_type="WARNING",
            reason=reason,
        )
        db.add(warning)
        db.flush()
        created.append(warning)

        warnings = list(
            db.scalars(
                select(ModerationSanction)
                .where(
                    ModerationSanction.target_user_id == target_user_id,
                    ModerationSanction.sanction_type == "WARNING",
                    ModerationSanction.reversed_at.is_(None),
                )
                .order_by(ModerationSanction.issued_at, ModerationSanction.id)
                .with_for_update()
            ).all()
        )
        threshold_type = {2: "TEMPORARY_SUSPENSION", 3: "PERMANENT_BAN"}.get(
            len(warnings)
        )
        if threshold_type is not None:
            derived = ModerationSanction(
                report_id=report_id,
                target_user_id=target_user_id,
                actor_user_id=staff.user_id,
                source_action_id=source_action_id,
                sanction_type=threshold_type,
                reason=(
                    f"Escalada automática por {len(warnings)} advertências válidas. "
                    f"Decisão humana: {reason}"
                ),
                expires_at=(
                    now + timedelta(days=TEMPORARY_SUSPENSION_DAYS)
                    if threshold_type == "TEMPORARY_SUSPENSION"
                    else None
                ),
            )
            db.add(derived)
            db.flush()
            db.add_all(
                [
                    ModerationSanctionBasis(
                        derived_sanction_id=derived.id,
                        warning_sanction_id=warning_item.id,
                        derived_report_id=derived.report_id,
                        warning_report_id=warning_item.report_id,
                    )
                    for warning_item in warnings
                ]
            )
            created.append(derived)
    elif decision in {"TEMPORARY_SUSPENSION", "PERMANENT_BAN"}:
        created.append(
            ModerationSanction(
                report_id=report_id,
                target_user_id=target_user_id,
                actor_user_id=staff.user_id,
                source_action_id=source_action_id,
                sanction_type=decision,
                reason=reason,
                expires_at=(
                    now + timedelta(days=TEMPORARY_SUSPENSION_DAYS)
                    if decision == "TEMPORARY_SUSPENSION"
                    else None
                ),
            )
        )
        db.add(created[-1])

    return created


def get_active_account_restriction(
    db: Session, user_id: int
) -> ModerationSanction | None:
    now = db.scalar(select(func.now()))
    return db.scalar(
        select(ModerationSanction)
        .where(
            ModerationSanction.target_user_id == user_id,
            ModerationSanction.reversed_at.is_(None),
            (
                ModerationSanction.sanction_type == "PERMANENT_BAN"
            )
            | (
                (ModerationSanction.sanction_type == "TEMPORARY_SUSPENSION")
                & (ModerationSanction.expires_at > now)
            ),
        )
        .order_by(
            (ModerationSanction.sanction_type == "PERMANENT_BAN").desc(),
            ModerationSanction.issued_at.desc(),
            ModerationSanction.id.desc(),
        )
        .limit(1)
    )


def account_restriction_exception(sanction: ModerationSanction) -> HTTPException:
    kind = sanction.sanction_type
    detail = {
        "code": "ACCOUNT_SUSPENDED" if kind == "TEMPORARY_SUSPENSION" else "ACCOUNT_BANNED",
        "sanction_type": kind,
        "expires_at": sanction.expires_at.isoformat() if sanction.expires_at else None,
    }
    return HTTPException(status_code=403, detail=detail)


def list_platform_sanctions(
    db: Session,
    *,
    page: int,
    page_size: int,
    target_user_id: int | None = None,
    report_id: int | None = None,
) -> dict:
    query = select(ModerationSanction)
    count_query = select(func.count(ModerationSanction.id))
    if target_user_id is not None:
        query = query.where(ModerationSanction.target_user_id == target_user_id)
        count_query = count_query.where(
            ModerationSanction.target_user_id == target_user_id
        )
    if report_id is not None:
        query = query.where(ModerationSanction.report_id == report_id)
        count_query = count_query.where(ModerationSanction.report_id == report_id)
    total = db.scalar(count_query) or 0
    items = db.scalars(
        query.order_by(
            ModerationSanction.issued_at.desc(), ModerationSanction.id.desc()
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [serialize_platform_sanction(db, item) for item in items],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


def serialize_platform_sanction(
    db: Session, sanction: ModerationSanction
) -> dict:
    basis_warning_ids = db.scalars(
        select(ModerationSanctionBasis.warning_sanction_id)
        .where(ModerationSanctionBasis.derived_sanction_id == sanction.id)
        .order_by(ModerationSanctionBasis.warning_sanction_id)
    ).all()
    review_history = db.scalars(
        select(ModerationSanctionReview)
        .where(ModerationSanctionReview.sanction_id == sanction.id)
        .order_by(ModerationSanctionReview.created_at, ModerationSanctionReview.id)
    ).all()
    return {
        "id": sanction.id,
        "report_id": sanction.report_id,
        "target_user_id": sanction.target_user_id,
        "actor_user_id": sanction.actor_user_id,
        "sanction_type": sanction.sanction_type,
        "reason": sanction.reason,
        "issued_at": sanction.issued_at,
        "expires_at": sanction.expires_at,
        "reversed_at": sanction.reversed_at,
        "reversed_by": sanction.reversed_by,
        "reversal_reason": sanction.reversal_reason,
        "requires_review": sanction.requires_review,
        "basis_warning_ids": list(basis_warning_ids),
        "review_history": review_history,
    }


def review_platform_sanction(
    db: Session,
    *,
    sanction_id: int,
    staff: PlatformStaff,
    decision: str,
    reason: str,
) -> ModerationSanction:
    """Uphold or reverse a sanction; reversing a warning queues review of dependents."""
    try:
        target_id = db.scalar(
            select(ModerationSanction.target_user_id).where(
                ModerationSanction.id == sanction_id
            )
        )
        if target_id is None:
            raise _not_found()
        locked_user_id = db.scalar(
            select(User.id).where(User.id == target_id).with_for_update()
        )
        if locked_user_id is None:
            raise _not_found()
        sanction = db.scalar(
            select(ModerationSanction)
            .where(ModerationSanction.id == sanction_id)
            .with_for_update()
        )
        if sanction is None:
            raise _not_found()
        if sanction.reversed_at is not None:
            raise HTTPException(
                status_code=409, detail="A sanção já foi revertida."
            )
        if decision == "UPHOLD" and not sanction.requires_review:
            raise HTTPException(
                status_code=409,
                detail="A sanção não possui revisão derivada pendente.",
            )

        now = db.scalar(select(func.now()))
        event_type = "UPHELD" if decision == "UPHOLD" else "REVERSED"
        if decision == "REVERSE":
            sanction.reversed_at = now
            sanction.reversed_by = staff.user_id
            sanction.reversal_reason = reason
        sanction.requires_review = False
        db.add(
            ModerationSanctionReview(
                sanction_id=sanction.id,
                actor_user_id=staff.user_id,
                review_type=event_type,
                reason=reason,
            )
        )
        db.add(
            ModerationAction(
                report_id=sanction.report_id,
                actor_user_id=staff.user_id,
                action_type=f"SANCTION_{event_type}",
                reason=reason,
            )
        )

        if decision == "REVERSE" and sanction.sanction_type == "WARNING":
            dependents = db.scalars(
                select(ModerationSanction)
                .join(
                    ModerationSanctionBasis,
                    ModerationSanctionBasis.derived_sanction_id
                    == ModerationSanction.id,
                )
                .where(
                    ModerationSanctionBasis.warning_sanction_id == sanction.id,
                    ModerationSanction.reversed_at.is_(None),
                )
                .order_by(ModerationSanction.id)
                .with_for_update()
            ).all()
            for dependent in dependents:
                dependent.requires_review = True
                review_reason = (
                    "Uma advertência que fundamentou esta sanção foi revertida; "
                    "revisão humana explícita necessária."
                )
                db.add(
                    ModerationSanctionReview(
                        sanction_id=dependent.id,
                        actor_user_id=staff.user_id,
                        review_type="REVIEW_REQUIRED",
                        reason=review_reason,
                    )
                )
                db.add(
                    ModerationAction(
                        report_id=dependent.report_id,
                        actor_user_id=staff.user_id,
                        action_type="DERIVED_SANCTION_REVIEW_REQUIRED",
                        reason=review_reason,
                    )
                )

        db.commit()
        db.refresh(sanction)
        return sanction
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível revisar a sanção.",
        ) from exc
    except Exception:
        db.rollback()
        raise

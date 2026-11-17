"""Report creation and evidence capture.

This service never sends message content to an external provider. Before any
future external submission, a human/manual triage step must route known or
suspected child sexual exploitation content without sending it to the API.
Do not assume an AI model can safely identify such content before submission.
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    ConversationParticipant,
    Message,
    ModerationAnalysisJob,
    ModerationReport,
    ModerationReportEvidence,
    User,
)


_DUPLICATE_REPORT_CONSTRAINT = "uq_moderation_reports_reporter_message"


def _is_duplicate_report(error: IntegrityError) -> bool:
    original = getattr(error, "orig", None)
    diagnostic = getattr(original, "diag", None)
    return (
        getattr(diagnostic, "constraint_name", None)
        == _DUPLICATE_REPORT_CONSTRAINT
    )


def create_message_report(
    db: Session,
    current_user: User,
    message_id: int,
    reason: str,
) -> ModerationReport:
    """Create one report per reporter/message and preserve the message snapshot.

    The unique database constraint is the final concurrency guard. Report and
    evidence are committed together; this function never calls an AI provider.
    """
    try:
        message = db.scalar(
            select(Message)
            .join(
                ConversationParticipant,
                ConversationParticipant.conversation_id
                == Message.conversation_id,
            )
            .where(
                Message.id == message_id,
                ConversationParticipant.user_id == current_user.id,
                ConversationParticipant.status == "ACTIVE",
            )
        )
        if message is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mensagem não encontrada.",
            )

        if message.sender_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não pode denunciar a própria mensagem.",
            )

        report = ModerationReport(
            reporter_id=current_user.id,
            message_id=message.id,
            reason=reason,
        )
        db.add(report)
        db.flush()
        db.refresh(report)

        evidence = ModerationReportEvidence(
            report_id=report.id,
            message_id=message.id,
            message_author_id=message.sender_id,
            content_snapshot=message.content,
            message_created_at=message.created_at,
            message_updated_at=message.updated_at,
            message_edited_at=message.edited_at,
        )
        db.add(evidence)
        db.flush()

        # Durable outbox row is committed atomically with the report/evidence.
        # It remains in PENDING_TRIAGE until an official moderator explicitly
        # approves sending this single snapshot to the external provider.
        db.add(ModerationAnalysisJob(report_id=report.id))

        db.commit()
        return report

    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        if _is_duplicate_report(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Você já denunciou esta mensagem.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível registrar a denúncia.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível registrar a denúncia.",
        ) from exc
    except Exception:
        db.rollback()
        raise

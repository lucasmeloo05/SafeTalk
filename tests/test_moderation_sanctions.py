from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    Conversation,
    ConversationParticipant,
    Message,
    ModerationAction,
    ModerationAnalysisJob,
    ModerationReport,
    ModerationReportEvidence,
    ModerationSanction,
    ModerationSanctionBasis,
    ModerationSanctionReview,
    PlatformStaff,
    User,
)
from app.services.moderation_review_service import record_human_decision
from conftest import test_engine


def _persistent_two_report_context():
    suffix = uuid4().hex[:8]
    with Session(test_engine) as db:
        target = User(
            username=f"sanct{suffix}",
            email=f"sanct{suffix}@example.test",
            password_hash="test-only-hash",
            is_active=True,
        )
        reporters = [
            User(
                username=f"sr{index}{suffix}",
                email=f"sr{index}{suffix}@example.test",
                password_hash="test-only-hash",
                is_active=True,
            )
            for index in (1, 2)
        ]
        moderators = [
            User(
                username=f"sm{index}{suffix}",
                email=f"sm{index}{suffix}@example.test",
                password_hash="test-only-hash",
                is_active=True,
            )
            for index in (1, 2)
        ]
        db.add_all([target, *reporters, *moderators])
        db.flush()
        db.add_all(
            [
                PlatformStaff(user_id=user.id, role="MODERATOR", status="ACTIVE")
                for user in moderators
            ]
        )
        db.flush()
        report_ids = []
        conversation_ids = []
        message_ids = []
        for reporter in reporters:
            user_a_id, user_b_id = sorted((reporter.id, target.id))
            conversation = Conversation(
                type="DIRECT",
                user_a_id=user_a_id,
                user_b_id=user_b_id,
                created_by=reporter.id,
            )
            db.add(conversation)
            db.flush()
            conversation_ids.append(conversation.id)
            db.add_all(
                [
                    ConversationParticipant(
                        conversation_id=conversation.id,
                        user_id=member_id,
                        role="MEMBER",
                        status="ACTIVE",
                    )
                    for member_id in (reporter.id, target.id)
                ]
            )
            message = Message(
                conversation_id=conversation.id,
                sender_id=target.id,
                content="Inofensiva mensagem usada no teste de concorrência.",
            )
            db.add(message)
            db.flush()
            message_ids.append(message.id)
            report = ModerationReport(
                reporter_id=reporter.id,
                message_id=message.id,
                reason="Motivo de teste concorrente.",
            )
            db.add(report)
            db.flush()
            report_ids.append(report.id)
            db.add_all(
                [
                    ModerationReportEvidence(
                        report_id=report.id,
                        message_id=message.id,
                        message_author_id=target.id,
                        content_snapshot=message.content,
                        message_created_at=message.created_at,
                        message_updated_at=message.updated_at,
                    ),
                    ModerationAnalysisJob(report_id=report.id),
                ]
            )
        db.commit()
        return {
            "target_id": target.id,
            "reporter_ids": [user.id for user in reporters],
            "moderator_ids": [user.id for user in moderators],
            "report_ids": report_ids,
            "conversation_ids": conversation_ids,
            "message_ids": message_ids,
        }


def _cleanup_persistent_two_report_context(context):
    with Session(test_engine) as db:
        report_ids = context["report_ids"]
        sanction_ids = select(ModerationSanction.id).where(
            ModerationSanction.target_user_id == context["target_id"]
        )
        db.execute(
            delete(ModerationSanctionReview).where(
                ModerationSanctionReview.sanction_id.in_(sanction_ids)
            )
        )
        db.execute(
            delete(ModerationSanctionBasis).where(
                (ModerationSanctionBasis.derived_sanction_id.in_(sanction_ids))
                | (ModerationSanctionBasis.warning_sanction_id.in_(sanction_ids))
            )
        )
        db.execute(
            delete(ModerationSanction).where(
                ModerationSanction.id.in_(sanction_ids)
            )
        )
        db.execute(delete(ModerationAction).where(ModerationAction.report_id.in_(report_ids)))
        db.execute(delete(ModerationAnalysisJob).where(ModerationAnalysisJob.report_id.in_(report_ids)))
        db.execute(delete(ModerationReportEvidence).where(ModerationReportEvidence.report_id.in_(report_ids)))
        db.execute(delete(ModerationReport).where(ModerationReport.id.in_(report_ids)))
        db.execute(delete(Message).where(Message.id.in_(context["message_ids"])))
        db.execute(
            delete(ConversationParticipant).where(
                ConversationParticipant.conversation_id.in_(context["conversation_ids"])
            )
        )
        db.execute(
            delete(Conversation).where(
                Conversation.id.in_(context["conversation_ids"])
            )
        )
        all_user_ids = [
            context["target_id"],
            *context["reporter_ids"],
            *context["moderator_ids"],
        ]
        db.execute(delete(PlatformStaff).where(PlatformStaff.user_id.in_(context["moderator_ids"])))
        db.execute(delete(User).where(User.id.in_(all_user_ids)))
        db.commit()


def test_concurrent_warning_decisions_on_different_reports_serialize_count():
    context = _persistent_two_report_context()
    barrier = Barrier(2)

    def decide(report_id: int, moderator_id: int):
        with Session(test_engine) as db:
            moderator = db.get(PlatformStaff, moderator_id)
            barrier.wait(timeout=10)
            try:
                record_human_decision(
                    db,
                    report_id=report_id,
                    staff=moderator,
                    decision="WARNING",
                    reason="Advertência emitida após revisão humana.",
                )
                return "created"
            except HTTPException as exc:
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(decide, report_id, moderator_id)
                for report_id, moderator_id in zip(
                    context["report_ids"], context["moderator_ids"]
                )
            ]
            outcomes = [future.result(timeout=30) for future in futures]
        assert outcomes == ["created", "created"]
        with Session(test_engine) as db:
            sanctions = db.scalars(
                select(ModerationSanction).where(
                    ModerationSanction.target_user_id == context["target_id"]
                )
            ).all()
            warning_count = db.scalar(
                select(func.count(ModerationSanction.id)).where(
                    ModerationSanction.target_user_id == context["target_id"],
                    ModerationSanction.sanction_type == "WARNING",
                    ModerationSanction.reversed_at.is_(None),
                )
            )
        assert warning_count == 2
        assert [row.sanction_type for row in sanctions].count("TEMPORARY_SUSPENSION") == 1
        assert [row.sanction_type for row in sanctions].count("WARNING") == 2
    finally:
        _cleanup_persistent_two_report_context(context)

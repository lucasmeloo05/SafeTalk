from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import require_platform_staff_roles, resolve_current_platform_staff
from app.models import (
    Conversation,
    ConversationParticipant,
    Message,
    ModerationAction,
    ModerationAnalysisJob,
    ModerationReport,
    ModerationReportEvidence,
    PlatformStaff,
    User,
)
from app.services.moderation_report_service import create_message_report
from conftest import test_engine


def _conversation_with_message(
    db_session,
    first_id: int,
    second_id: int,
    *,
    sender_id: int | None = None,
):
    user_a_id, user_b_id = sorted((first_id, second_id))
    conversation = Conversation(
        type="DIRECT",
        user_a_id=user_a_id,
        user_b_id=user_b_id,
        created_by=user_a_id,
    )
    db_session.add(conversation)
    db_session.flush()
    db_session.add_all(
        [
            ConversationParticipant(
                conversation_id=conversation.id,
                user_id=user_a_id,
                role="MEMBER",
                status="ACTIVE",
            ),
            ConversationParticipant(
                conversation_id=conversation.id,
                user_id=user_b_id,
                role="MEMBER",
                status="ACTIVE",
            ),
        ]
    )
    message = Message(
        conversation_id=conversation.id,
        sender_id=sender_id or user_a_id,
        content="Conteúdo denunciado para teste.",
    )
    db_session.add(message)
    db_session.flush()
    return conversation, message


def test_authenticated_participant_can_report_message_without_exposing_evidence(
    client,
    db_session,
    create_user,
    auth_headers,
):
    reporter = create_user()
    other = create_user()
    _, message = _conversation_with_message(
        db_session,
        reporter["id"],
        other["id"],
        sender_id=other["id"],
    )

    response = client.post(
        "/reports",
        json={"message_id": message.id, "reason": "Conteúdo abusivo"},
        headers=auth_headers(reporter),
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["message_id"] == message.id
    assert payload["status"] == "PENDING"
    assert payload["triage_status"] == "PENDING"
    assert payload["analysis_status"] == "PENDING_TRIAGE"
    assert "content_snapshot" not in payload
    assert "reporter_id" not in payload

    report = db_session.get(ModerationReport, payload["id"])
    evidence = db_session.scalar(
        select(ModerationReportEvidence).where(
            ModerationReportEvidence.report_id == report.id
        )
    )
    assert report.reporter_id == reporter["id"]
    assert evidence.message_id == message.id
    assert evidence.content_snapshot == message.content
    assert evidence.message_created_at == message.created_at
    assert db_session.scalar(select(func.count(ModerationAction.id))) == 0


def test_report_requires_authentication(client):
    response = client.post(
        "/reports",
        json={"message_id": 1, "reason": "Motivo"},
    )

    assert response.status_code == 401


def test_report_rejects_missing_message(client, create_user, auth_headers):
    reporter = create_user()
    response = client.post(
        "/reports",
        json={"message_id": 999999, "reason": "Motivo"},
        headers=auth_headers(reporter),
    )
    assert response.status_code == 404


def test_report_rejects_user_without_active_conversation_participation(
    client,
    db_session,
    create_user,
    auth_headers,
):
    first = create_user()
    second = create_user()
    outsider = create_user()
    _, message = _conversation_with_message(
        db_session, first["id"], second["id"]
    )

    response = client.post(
        "/reports",
        json={"message_id": message.id, "reason": "Motivo"},
        headers=auth_headers(outsider),
    )
    assert response.status_code == 404


def test_report_message_from_another_conversation_is_rejected(
    client,
    db_session,
    create_user,
    auth_headers,
):
    reporter = create_user()
    own_peer = create_user()
    other_a = create_user()
    other_b = create_user()
    _conversation_with_message(db_session, reporter["id"], own_peer["id"])
    _, foreign_message = _conversation_with_message(
        db_session, other_a["id"], other_b["id"]
    )

    response = client.post(
        "/reports",
        json={"message_id": foreign_message.id, "reason": "Motivo"},
        headers=auth_headers(reporter),
    )
    assert response.status_code == 404
    missing = client.post(
        "/reports",
        json={"message_id": 999999, "reason": "Motivo"},
        headers=auth_headers(reporter),
    )
    assert missing.status_code == response.status_code
    assert missing.json() == response.json()


def test_report_is_unique_per_reporter_and_message(
    client,
    db_session,
    create_user,
    auth_headers,
):
    reporter = create_user()
    other = create_user()
    _, message = _conversation_with_message(
        db_session,
        reporter["id"],
        other["id"],
        sender_id=other["id"],
    )
    headers = auth_headers(reporter)
    payload = {"message_id": message.id, "reason": "Motivo"}

    first = client.post("/reports", json=payload, headers=headers)
    duplicate = client.post("/reports", json=payload, headers=headers)

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert db_session.scalar(select(func.count(ModerationReport.id))) == 1
    assert db_session.scalar(
        select(func.count(ModerationReportEvidence.id))
    ) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"message_id": True, "reason": "Motivo"},
        {"message_id": 1, "reason": "   "},
        {"message_id": 1, "reason": "x" * 501},
        {"message_id": 1, "reason": "Motivo", "content": "não confiável"},
        {"message_id": 1, "reason": "Motivo", "reporter_id": 123},
        {"message_id": 1, "reason": "Motivo", "message_author_id": 123},
        {
            "message_id": 1,
            "reason": "Motivo",
            "message_updated_at": "2026-01-01T00:00:00Z",
        },
    ],
)
def test_report_rejects_invalid_or_internal_fields(
    client,
    create_user,
    auth_headers,
    body,
):
    response = client.post(
        "/reports",
        json=body,
        headers=auth_headers(create_user()),
    )
    assert response.status_code == 422


def test_report_evidence_is_a_snapshot_of_the_message(
    client,
    db_session,
    create_user,
    auth_headers,
):
    reporter = create_user()
    other = create_user()
    _, message = _conversation_with_message(
        db_session,
        reporter["id"],
        other["id"],
        sender_id=other["id"],
    )
    original_content = message.content
    original_created_at = message.created_at
    original_author_id = message.sender_id
    original_updated_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    original_edited_at = datetime(2026, 1, 2, 0, 30, tzinfo=timezone.utc)
    message.updated_at = original_updated_at
    message.edited_at = original_edited_at
    db_session.flush()

    response = client.post(
        "/reports",
        json={"message_id": message.id, "reason": "Motivo"},
        headers=auth_headers(reporter),
    )
    assert response.status_code == 201

    message.content = "Alteração posterior do conteúdo original."
    message.sender_id = reporter["id"]
    message.updated_at = datetime(2026, 2, 3, tzinfo=timezone.utc)
    message.edited_at = datetime(2026, 2, 3, 0, 30, tzinfo=timezone.utc)
    db_session.flush()
    evidence = db_session.scalar(
        select(ModerationReportEvidence).where(
            ModerationReportEvidence.message_id == message.id
        )
    )
    assert evidence.content_snapshot == original_content
    assert evidence.message_created_at == original_created_at
    assert evidence.message_author_id == original_author_id
    assert evidence.message_updated_at == original_updated_at
    assert evidence.message_edited_at == original_edited_at


def test_deleted_for_everyone_message_remains_reportable_with_original_official_evidence(
    client,
    db_session,
    create_user,
    auth_headers,
):
    reporter = create_user()
    author = create_user()
    staff_user = create_user()
    _conversation, message = _conversation_with_message(
        db_session,
        reporter["id"],
        author["id"],
        sender_id=author["id"],
    )
    original_content = message.content
    message.deleted_for_everyone_at = datetime.now(timezone.utc)
    message.deleted_for_everyone_by_id = author["id"]
    db_session.flush()

    deleted_message = client.get(
        f"/conversations/{message.conversation_id}/messages",
        headers=auth_headers(reporter),
    )
    assert deleted_message.status_code == 200, deleted_message.text
    assert deleted_message.json()[0]["content"] == "Esta mensagem foi excluída"
    assert deleted_message.json()[0]["is_deleted_for_everyone"] is True

    report_response = client.post(
        "/reports",
        json={"message_id": message.id, "reason": "Revisar mensagem apagada"},
        headers=auth_headers(reporter),
    )
    assert report_response.status_code == 201, report_response.text
    report_id = report_response.json()["id"]
    evidence = db_session.scalar(
        select(ModerationReportEvidence).where(
            ModerationReportEvidence.report_id == report_id
        )
    )
    assert evidence.content_snapshot == original_content
    assert evidence.message_author_id == author["id"]

    db_session.add(
        PlatformStaff(
            user_id=staff_user["id"],
            role="MODERATOR",
            status="ACTIVE",
        )
    )
    db_session.flush()
    official_detail = client.get(
        f"/official/reports/{report_id}",
        headers=auth_headers(staff_user),
    )
    assert official_detail.status_code == 200, official_detail.text
    assert official_detail.json()["evidence"]["content_snapshot"] == original_content
    assert official_detail.json()["evidence"]["message_author_id"] == author["id"]


def test_deleting_message_after_report_preserves_original_official_evidence(
    client,
    db_session,
    create_user,
    auth_headers,
):
    reporter = create_user()
    author = create_user()
    staff_user = create_user()
    _conversation, message = _conversation_with_message(
        db_session,
        reporter["id"],
        author["id"],
        sender_id=author["id"],
    )
    original_content = message.content
    response = client.post(
        "/reports",
        json={"message_id": message.id, "reason": "Preservar evidência"},
        headers=auth_headers(reporter),
    )
    assert response.status_code == 201, response.text
    report_id = response.json()["id"]

    message.deleted_for_everyone_at = datetime.now(timezone.utc)
    message.deleted_for_everyone_by_id = author["id"]
    db_session.flush()
    deleted_message = client.get(
        f"/conversations/{message.conversation_id}/messages",
        headers=auth_headers(reporter),
    )
    assert deleted_message.status_code == 200, deleted_message.text
    assert deleted_message.json()[0]["is_deleted_for_everyone"] is True
    assert deleted_message.json()[0]["content"] == "Esta mensagem foi excluída"

    evidence = db_session.scalar(
        select(ModerationReportEvidence).where(
            ModerationReportEvidence.report_id == report_id
        )
    )
    assert evidence.content_snapshot == original_content
    db_session.add(
        PlatformStaff(
            user_id=staff_user["id"],
            role="MODERATOR",
            status="ACTIVE",
        )
    )
    db_session.flush()
    official_detail = client.get(
        f"/official/reports/{report_id}",
        headers=auth_headers(staff_user),
    )
    assert official_detail.status_code == 200, official_detail.text
    assert official_detail.json()["evidence"]["content_snapshot"] == original_content


def test_report_and_evidence_roll_back_together_on_commit_failure(
    db_session,
    create_user,
    monkeypatch,
):
    reporter = create_user()
    other = create_user()
    _, message = _conversation_with_message(
        db_session,
        reporter["id"],
        other["id"],
        sender_id=other["id"],
    )

    def fail_commit():
        raise SQLAlchemyError("simulated commit failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(HTTPException) as exc_info:
        create_message_report(
            db_session,
            db_session.get(User, reporter["id"]),
            message.id,
            "Motivo",
        )

    assert exc_info.value.status_code == 500
    assert db_session.scalar(select(func.count(ModerationReport.id))) == 0
    assert db_session.scalar(
        select(func.count(ModerationReportEvidence.id))
    ) == 0


def test_only_active_official_staff_can_access_staff_dependencies(
    db_session,
    create_user,
):
    ordinary_user = create_user()
    active_user = create_user()
    inactive_user = create_user()
    revoked_user = create_user()

    active_staff = PlatformStaff(
        user_id=active_user["id"], role="MODERATOR", status="ACTIVE"
    )
    inactive_staff = PlatformStaff(
        user_id=inactive_user["id"], role="ADMIN", status="INACTIVE"
    )
    active_but_revoked_staff = PlatformStaff(
        user_id=revoked_user["id"],
        role="ADMIN",
        status="ACTIVE",
        revoked_at=datetime.now(timezone.utc),
    )
    db_session.add_all(
        [active_staff, inactive_staff, active_but_revoked_staff]
    )
    db_session.flush()

    resolved = resolve_current_platform_staff(
        db_session, db_session.get(User, active_user["id"])
    )
    assert resolved.role == "MODERATOR"
    assert require_platform_staff_roles("MODERATOR")(staff=resolved) is resolved
    with pytest.raises(HTTPException) as role_error:
        require_platform_staff_roles("ADMIN")(staff=resolved)
    assert role_error.value.status_code == 403

    with pytest.raises(HTTPException) as revoked_error:
        resolve_current_platform_staff(
            db_session, db_session.get(User, revoked_user["id"])
        )
    assert revoked_error.value.status_code == 403

    with pytest.raises(HTTPException) as inactive_error:
        resolve_current_platform_staff(
            db_session, db_session.get(User, inactive_user["id"])
        )
    assert inactive_error.value.status_code == 403

    with pytest.raises(HTTPException) as ordinary_error:
        resolve_current_platform_staff(
            db_session, db_session.get(User, ordinary_user["id"])
        )
    assert ordinary_error.value.status_code == 403


def test_report_rejects_own_message(
    db_session,
    create_user,
):
    """A participant cannot submit a report against their own message."""
    reporter = create_user()
    peer = create_user()
    _, message = _conversation_with_message(
        db_session,
        reporter["id"],
        peer["id"],
        sender_id=reporter["id"],
    )
    with pytest.raises(HTTPException) as exc_info:
        create_message_report(
            db_session,
            db_session.get(User, reporter["id"]),
            message.id,
            "Motivo",
        )
    assert exc_info.value.status_code == 403


def test_left_participant_cannot_report_message(db_session, create_user):
    reporter = create_user()
    peer = create_user()
    _, message = _conversation_with_message(
        db_session,
        reporter["id"],
        peer["id"],
        sender_id=peer["id"],
    )
    participant = db_session.scalar(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == message.conversation_id,
            ConversationParticipant.user_id == reporter["id"],
        )
    )
    participant.status = "LEFT"
    participant.left_at = datetime.now(timezone.utc)
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        create_message_report(
            db_session,
            db_session.get(User, reporter["id"]),
            message.id,
            "Motivo",
        )
    assert exc_info.value.status_code == 404


def _persistent_report_context():
    suffix = uuid4().hex[:10]
    with Session(test_engine) as db:
        reporter = User(
            username=f"reporter_{suffix}",
            email=f"reporter_{suffix}@example.com",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        peer = User(
            username=f"report_peer_{suffix}",
            email=f"report_peer_{suffix}@example.com",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        db.add_all([reporter, peer])
        db.flush()
        user_a_id, user_b_id = sorted((reporter.id, peer.id))
        conversation = Conversation(
            type="DIRECT",
            user_a_id=user_a_id,
            user_b_id=user_b_id,
            created_by=reporter.id,
        )
        db.add(conversation)
        db.flush()
        db.add_all(
            [
                ConversationParticipant(
                    conversation_id=conversation.id,
                    user_id=reporter.id,
                    role="MEMBER",
                    status="ACTIVE",
                ),
                ConversationParticipant(
                    conversation_id=conversation.id,
                    user_id=peer.id,
                    role="MEMBER",
                    status="ACTIVE",
                ),
            ]
        )
        message = Message(
            conversation_id=conversation.id,
            sender_id=peer.id,
            content="Mensagem para teste concorrente.",
        )
        db.add(message)
        db.commit()
        return reporter.id, peer.id, conversation.id, message.id


def _cleanup_persistent_report_context(context):
    reporter_id, peer_id, conversation_id, message_id = context
    with Session(test_engine) as db:
        db.execute(
            delete(ModerationAction).where(
                ModerationAction.report_id.in_(
                    select(ModerationReport.id).where(
                        ModerationReport.message_id == message_id
                    )
                )
            )
        )
        db.execute(
            delete(ModerationAnalysisJob).where(
                ModerationAnalysisJob.report_id.in_(
                    select(ModerationReport.id).where(
                        ModerationReport.message_id == message_id
                    )
                )
            )
        )
        db.execute(
            delete(ModerationReportEvidence).where(
                ModerationReportEvidence.message_id == message_id
            )
        )
        db.execute(
            delete(ModerationReport).where(
                ModerationReport.message_id == message_id
            )
        )
        db.execute(delete(Message).where(Message.id == message_id))
        db.execute(
            delete(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id
            )
        )
        db.execute(
            delete(Conversation).where(Conversation.id == conversation_id)
        )
        db.execute(delete(User).where(User.id.in_([reporter_id, peer_id])))
        db.commit()


def test_concurrent_duplicate_reports_create_once_and_conflict_once():
    context = _persistent_report_context()
    reporter_id, _peer_id, _conversation_id, message_id = context
    barrier = Barrier(2)

    def submit_report():
        with Session(test_engine) as db:
            reporter = db.get(User, reporter_id)
            barrier.wait(timeout=10)
            try:
                create_message_report(
                    db,
                    reporter,
                    message_id,
                    "Motivo concorrente",
                )
                return "created"
            except HTTPException as exc:
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(submit_report) for _ in range(2)]
            outcomes = [future.result(timeout=30) for future in futures]

        assert outcomes.count("created") == 1
        assert outcomes.count(409) == 1
        with Session(test_engine) as db:
            report_count = db.scalar(
                select(func.count(ModerationReport.id)).where(
                    ModerationReport.reporter_id == reporter_id,
                    ModerationReport.message_id == message_id,
                )
            )
            evidence_count = db.scalar(
                select(func.count(ModerationReportEvidence.id)).where(
                    ModerationReportEvidence.message_id == message_id
                )
            )
        assert report_count == 1
        assert evidence_count == 1
    finally:
        _cleanup_persistent_report_context(context)

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

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


def _create_report(db, create_user, client, auth_headers):
    reporter = create_user()
    author = create_user()
    staff_user = create_user()
    user_a, user_b = sorted((reporter["id"], author["id"]))
    conversation = Conversation(
        type="DIRECT",
        user_a_id=user_a,
        user_b_id=user_b,
        created_by=user_a,
    )
    db.add(conversation)
    db.flush()
    db.add_all(
        [
            ConversationParticipant(
                conversation_id=conversation.id,
                user_id=user_a,
                role="MEMBER",
                status="ACTIVE",
            ),
            ConversationParticipant(
                conversation_id=conversation.id,
                user_id=user_b,
                role="MEMBER",
                status="ACTIVE",
            ),
        ]
    )
    message = Message(
        conversation_id=conversation.id,
        sender_id=author["id"],
        content="Conteúdo privado somente para equipe oficial.",
    )
    db.add(message)
    db.flush()
    report_response = client.post(
        "/reports",
        json={"message_id": message.id, "reason": "Motivo reportado"},
        headers=auth_headers(reporter),
    )
    assert report_response.status_code == 201, report_response.text
    db.add(
        PlatformStaff(
            user_id=staff_user["id"],
            role="MODERATOR",
            status="ACTIVE",
        )
    )
    db.flush()
    return (
        report_response.json()["id"],
        staff_user,
        reporter,
        report_response.json(),
    )


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/official/reports", None),
        ("get", "/official/reports/1", None),
        ("get", "/official/reports/1/analysis", None),
        (
            "post",
            "/official/reports/1/triage",
            {
                "external_analysis_eligible": True,
                "reason": "Triagem autenticada.",
            },
        ),
        (
            "post",
            "/official/reports/1/decision",
            {"decision": "REVIEWED", "reason": "Justificativa"},
        ),
    ],
)
def test_official_report_routes_require_authentication(client, method, path, body):
    response = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
    assert response.status_code == 401


@pytest.mark.parametrize(
    "staff_status,revoked_at,expected",
    [
        ("ACTIVE", None, 200),
        ("ACTIVE", datetime.now(timezone.utc), 403),
        ("INACTIVE", None, 403),
    ],
)
def test_official_queue_requires_active_unrevoked_platform_staff(
    client,
    db_session,
    create_user,
    auth_headers,
    staff_status,
    revoked_at,
    expected,
):
    user = create_user()
    db_session.add(
        PlatformStaff(
            user_id=user["id"],
            role="MODERATOR",
            status=staff_status,
            revoked_at=revoked_at,
        )
    )
    db_session.flush()

    response = client.get(
        "/official/reports", headers=auth_headers(user)
    )
    assert response.status_code == expected, response.text


def test_common_user_cannot_read_evidence_or_results(
    client, db_session, create_user, auth_headers
):
    report_id, _staff, reporter, _payload = _create_report(
        db_session, create_user, client, auth_headers
    )
    headers = auth_headers(reporter)
    detail = client.get(f"/official/reports/{report_id}", headers=headers)
    analysis = client.get(
        f"/official/reports/{report_id}/analysis", headers=headers
    )
    assert detail.status_code == 403
    assert analysis.status_code == 403


def test_active_official_staff_can_list_and_view_evidence(
    client, db_session, create_user, auth_headers
):
    report_id, staff_user, _reporter, _payload = _create_report(
        db_session, create_user, client, auth_headers
    )
    headers = auth_headers(staff_user)

    queue = client.get("/official/reports?page=1&page_size=10", headers=headers)
    detail = client.get(f"/official/reports/{report_id}", headers=headers)
    analysis = client.get(
        f"/official/reports/{report_id}/analysis", headers=headers
    )
    assert queue.status_code == 200, queue.text
    assert queue.json()["total"] == 1
    assert queue.json()["items"][0]["analysis"]["status"] == "PENDING_TRIAGE"
    assert detail.status_code == 200, detail.text
    assert detail.json()["evidence"]["content_snapshot"] == (
        "Conteúdo privado somente para equipe oficial."
    )
    assert analysis.status_code == 200, analysis.text
    assert analysis.json()["flagged"] is None
    assert "content_snapshot" not in analysis.json()


def test_queue_pagination_and_missing_report_are_scoped(
    client, db_session, create_user, auth_headers
):
    first_id, staff_user, _reporter1, _payload1 = _create_report(
        db_session, create_user, client, auth_headers
    )
    _second_id, _staff2, _reporter2, _payload2 = _create_report(
        db_session, create_user, client, auth_headers
    )
    headers = auth_headers(staff_user)

    page = client.get("/official/reports?page=1&page_size=1", headers=headers)
    missing = client.get("/official/reports/999999", headers=headers)
    assert page.status_code == 200
    assert len(page.json()["items"]) == 1
    assert page.json()["total"] == 2
    assert missing.status_code == 404
    assert first_id > 0


def test_manual_triage_gates_external_analysis_and_is_audited(
    client, db_session, create_user, auth_headers
):
    report_id, staff_user, _reporter, _payload = _create_report(
        db_session, create_user, client, auth_headers
    )
    response = client.post(
        f"/official/reports/{report_id}/triage",
        json={
            "external_analysis_eligible": False,
            "reason": "Manter sob análise humana.",
        },
        headers=auth_headers(staff_user),
    )
    job = db_session.scalar(
        select(ModerationAnalysisJob).where(
            ModerationAnalysisJob.report_id == report_id
        )
    )
    action = db_session.scalar(
        select(ModerationAction).where(ModerationAction.report_id == report_id)
    )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "MANUAL_REVIEW"
    assert job.status == "MANUAL_REVIEW"
    assert action.actor_user_id == staff_user["id"]
    assert action.action_type == "MANUAL_REVIEW_REQUIRED"
    assert action.reason == "Manter sob análise humana."


def test_triage_approval_is_required_before_queueing_provider_work(
    client, db_session, create_user, auth_headers
):
    report_id, staff_user, _reporter, _payload = _create_report(
        db_session, create_user, client, auth_headers
    )
    response = client.post(
        f"/official/reports/{report_id}/triage",
        json={
            "external_analysis_eligible": True,
            "reason": "Aprovar análise externa após revisão.",
        },
        headers=auth_headers(staff_user),
    )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "PENDING"
    assert response.json()["attempt_count"] == 0

    duplicate = client.post(
        f"/official/reports/{report_id}/triage",
        json={
            "external_analysis_eligible": True,
            "reason": "Repetir triagem para validar conflito.",
        },
        headers=auth_headers(staff_user),
    )
    assert duplicate.status_code == 409


def test_sensitive_content_triage_stays_available_for_human_decision(
    client, db_session, create_user, auth_headers
):
    report_id, staff_user, _reporter, _payload = _create_report(
        db_session, create_user, client, auth_headers
    )
    headers = auth_headers(staff_user)
    triage = client.post(
        f"/official/reports/{report_id}/triage",
        json={
            "external_analysis_eligible": True,
            "sensitive_content_suspected": True,
            "reason": "Suspeita direcionada à análise humana.",
        },
        headers=headers,
    )
    assert triage.status_code == 202, triage.text
    assert triage.json()["status"] == "MANUAL_REVIEW"

    detail = client.get(f"/official/reports/{report_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "PENDING"
    assert detail.json()["triage_status"] == "MANUAL_REVIEW"
    assert detail.json()["actions"][-1]["action_type"] == "SENSITIVE_CONTENT_MANUAL_REVIEW"
    assert detail.json()["actions"][-1]["reason"] == "Suspeita direcionada à análise humana."

    decision = client.post(
        f"/official/reports/{report_id}/decision",
        json={"decision": "REVIEWED_MANUALLY", "reason": "Análise humana concluída."},
        headers=headers,
    )
    assert decision.status_code == 201, decision.text
    assert db_session.get(ModerationReport, report_id).status == "REVIEWED"


def test_human_decision_is_audited_without_automatic_sanction(
    client, db_session, create_user, auth_headers
):
    report_id, staff_user, _reporter, _payload = _create_report(
        db_session, create_user, client, auth_headers
    )
    response = client.post(
        f"/official/reports/{report_id}/decision",
        json={"decision": "NO_VIOLATION", "reason": "Revisão humana concluída."},
        headers=auth_headers(staff_user),
    )
    report = db_session.get(ModerationReport, report_id)
    action = db_session.scalar(
        select(ModerationAction).where(ModerationAction.report_id == report_id)
    )
    assert response.status_code == 201, response.text
    assert action.actor_user_id == staff_user["id"]
    assert action.action_type == "NO_VIOLATION"
    assert action.reason == "Revisão humana concluída."
    assert report.status == "REVIEWED"
    assert db_session.scalar(
        select(ModerationAnalysisJob.flagged).where(
            ModerationAnalysisJob.report_id == report_id
        )
    ) is None
    repeated = client.post(
        f"/official/reports/{report_id}/decision",
        json={"decision": "ANOTHER", "reason": "Outra revisão."},
        headers=auth_headers(staff_user),
    )
    assert repeated.status_code == 409


def test_decision_validation_rejects_empty_or_extra_fields(
    client, db_session, create_user, auth_headers
):
    staff_user = create_user()
    db_session.add(
        PlatformStaff(
            user_id=staff_user["id"], role="MODERATOR", status="ACTIVE"
        )
    )
    db_session.flush()
    response = client.post(
        "/official/reports/1/decision",
        json={"decision": " ", "reason": "justificativa", "actor_user_id": 1},
        headers=auth_headers(staff_user),
    )
    assert response.status_code == 422

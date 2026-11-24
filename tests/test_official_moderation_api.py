from datetime import datetime, timezone
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

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


def _create_report(db, create_user, client, auth_headers, *, author=None):
    reporter = create_user()
    author = author or create_user()
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
    assert db_session.scalar(
        select(func.count(ModerationSanction.id)).where(
            ModerationSanction.report_id == report_id
        )
    ) == 0
    repeated = client.post(
        f"/official/reports/{report_id}/decision",
        json={"decision": "NO_VIOLATION", "reason": "Outra revisão."},
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


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/official/sanctions", None),
        (
            "post",
            "/official/sanctions/1/review",
            {"decision": "REVERSE", "reason": "Revisão autorizada."},
        ),
    ],
)
def test_sanction_routes_require_active_official_staff(
    client, create_user, auth_headers, method, path, body
):
    common_user = create_user()
    request = getattr(client, method)
    response = request(path, json=body, headers=auth_headers(common_user)) if body else request(
        path, headers=auth_headers(common_user)
    )
    assert response.status_code == 403
    unauthenticated = request(path, json=body) if body else request(path)
    assert unauthenticated.status_code == 401


def _decide(client, report_id, staff, headers, decision, reason="Decisão humana"):
    return client.post(
        f"/official/reports/{report_id}/decision",
        json={"decision": decision, "reason": reason},
        headers=headers(staff),
    )


def test_warning_escalation_is_atomic_and_uses_lifetime_valid_warnings(
    client, db_session, create_user, auth_headers
):
    target = create_user()
    report_ids = []
    for expected_count, expected_types in [
        (1, ["WARNING"]),
        (2, ["WARNING", "WARNING", "TEMPORARY_SUSPENSION"]),
        (3, ["WARNING", "WARNING", "TEMPORARY_SUSPENSION", "WARNING", "PERMANENT_BAN"]),
    ]:
        report_id, staff, _reporter, _ = _create_report(
            db_session, create_user, client, auth_headers, author=target
        )
        report_ids.append(report_id)
        response = _decide(client, report_id, staff, auth_headers, "WARNING")
        assert response.status_code == 201, response.text
        sanctions = db_session.scalars(
            select(ModerationSanction)
            .where(ModerationSanction.target_user_id == target["id"])
            .order_by(ModerationSanction.issued_at, ModerationSanction.id)
        ).all()
        assert [row.sanction_type for row in sanctions] == expected_types
        assert all(row.report_id in report_ids for row in sanctions)
        assert len(response.json()["sanctions"]) == (2 if expected_count in {2, 3} else 1)
        if expected_count == 2:
            derived_payload = next(
                item for item in response.json()["sanctions"]
                if item["sanction_type"] == "TEMPORARY_SUSPENSION"
            )
            assert len(derived_payload["basis_warning_ids"]) == 2

    suspension = next(
        row for row in sanctions if row.sanction_type == "TEMPORARY_SUSPENSION"
    )
    permanent = next(row for row in sanctions if row.sanction_type == "PERMANENT_BAN")
    assert suspension.expires_at - suspension.issued_at == timedelta(days=7)
    assert permanent.expires_at is None
    assert db_session.scalar(
        select(func.count(ModerationSanctionBasis.warning_sanction_id)).where(
            ModerationSanctionBasis.derived_sanction_id == suspension.id
        )
    ) == 2
    assert db_session.scalar(
        select(func.count(ModerationSanctionBasis.warning_sanction_id)).where(
            ModerationSanctionBasis.derived_sanction_id == permanent.id
        )
    ) == 3


def test_direct_suspension_is_seven_days_and_blocks_login_and_existing_jwt(
    client, db_session, create_user, auth_headers
):
    target = create_user()
    token_headers = auth_headers(target)
    report_id, staff, _reporter, _ = _create_report(
        db_session, create_user, client, auth_headers, author=target
    )
    response = _decide(client, report_id, staff, auth_headers, "TEMPORARY_SUSPENSION")
    assert response.status_code == 201, response.text
    sanction = db_session.scalar(
        select(ModerationSanction).where(
            ModerationSanction.report_id == report_id
        )
    )
    assert sanction.sanction_type == "TEMPORARY_SUSPENSION"
    assert sanction.expires_at - sanction.issued_at == timedelta(days=7)
    denied_api = client.get("/users/me", headers=token_headers)
    denied_login = client.post(
        "/users/login",
        json={"login": target["username"], "password": target["password"]},
    )
    assert denied_api.status_code == 403
    assert denied_api.json()["detail"] == {
        "code": "ACCOUNT_SUSPENDED",
        "sanction_type": "TEMPORARY_SUSPENSION",
        "expires_at": sanction.expires_at.isoformat(),
    }
    assert denied_login.status_code == 403
    assert "report" not in denied_login.text.lower()

    sanction.issued_at = datetime.now(timezone.utc) - timedelta(days=8)
    sanction.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert client.get("/users/me", headers=token_headers).status_code == 200


def test_direct_permanent_ban_blocks_login_without_disabling_user(
    client, db_session, create_user, auth_headers
):
    target = create_user()
    token_headers = auth_headers(target)
    report_id, staff, _reporter, _ = _create_report(
        db_session, create_user, client, auth_headers, author=target
    )
    response = _decide(client, report_id, staff, auth_headers, "PERMANENT_BAN")
    assert response.status_code == 201, response.text
    assert response.json()["sanctions"][0]["expires_at"] is None
    assert client.get("/users/me", headers=token_headers).status_code == 403
    assert db_session.get(User, target["id"]).is_active is True


def test_reversing_warning_requires_explicit_review_of_derived_sanction(
    client, db_session, create_user, auth_headers
):
    target = create_user()
    reports = []
    for _ in range(2):
        report_id, staff, _reporter, _ = _create_report(
            db_session, create_user, client, auth_headers, author=target
        )
        reports.append((report_id, staff))
        response = _decide(client, report_id, staff, auth_headers, "WARNING")
        assert response.status_code == 201, response.text
    warnings = db_session.scalars(
        select(ModerationSanction).where(
            ModerationSanction.target_user_id == target["id"],
            ModerationSanction.sanction_type == "WARNING",
        )
    ).all()
    suspension = db_session.scalar(
        select(ModerationSanction).where(
            ModerationSanction.target_user_id == target["id"],
            ModerationSanction.sanction_type == "TEMPORARY_SUSPENSION",
        )
    )

    reverse_warning = client.post(
        f"/official/sanctions/{warnings[0].id}/review",
        json={"decision": "REVERSE", "reason": "Advertência anulada."},
        headers=auth_headers(reports[0][1]),
    )
    assert reverse_warning.status_code == 200, reverse_warning.text
    assert reverse_warning.json()["review_history"][-1]["review_type"] == "REVERSED"
    db_session.refresh(suspension)
    assert suspension.requires_review is True
    assert client.post(
        "/users/login",
        json={"login": target["username"], "password": target["password"]},
    ).status_code == 403
    assert db_session.scalar(
        select(ModerationSanctionReview.id).where(
            ModerationSanctionReview.sanction_id == suspension.id,
            ModerationSanctionReview.review_type == "REVIEW_REQUIRED",
        )
    ) is not None

    reviewed = client.post(
        f"/official/sanctions/{suspension.id}/review",
        json={"decision": "REVERSE", "reason": "Revisão da escalada concluída."},
        headers=auth_headers(reports[1][1]),
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review_history"][-1]["review_type"] == "REVERSED"
    assert client.post(
        "/users/login",
        json={"login": target["username"], "password": target["password"]},
    ).status_code == 200
    db_session.refresh(warnings[0])
    db_session.refresh(suspension)
    assert warnings[0].reversed_by == reports[0][1]["id"]
    assert suspension.reversed_by == reports[1][1]["id"]


def test_failure_after_sanction_flush_rolls_back_decision_and_report(
    db_session, create_user, client, auth_headers, monkeypatch
):
    import app.services.moderation_review_service as review_service

    report_id, staff, _reporter, _ = _create_report(
        db_session, create_user, client, auth_headers
    )

    def fail_after_insert(db, **values):
        db.add(
            ModerationSanction(
                report_id=values["report_id"],
                target_user_id=values["target_user_id"],
                actor_user_id=values["staff"].user_id,
                source_action_id=values["source_action_id"],
                sanction_type="WARNING",
                reason=values["reason"],
            )
        )
        db.flush()
        raise RuntimeError("simulated failure after sanction insert")

    monkeypatch.setattr(review_service, "issue_sanctions_for_decision", fail_after_insert)
    platform_staff = db_session.get(PlatformStaff, staff["id"])
    with pytest.raises(RuntimeError, match="simulated failure"):
        review_service.record_human_decision(
            db_session,
            report_id=report_id,
            staff=platform_staff,
            decision="WARNING",
            reason="Advertência de teste.",
        )
    db_session.expire_all()
    assert db_session.get(ModerationReport, report_id).status == "PENDING"
    assert db_session.scalar(
        select(func.count(ModerationAction.id)).where(
            ModerationAction.report_id == report_id
        )
    ) == 0


def test_sanction_target_must_match_immutable_report_evidence(
    db_session, create_user, client, auth_headers
):
    report_id, staff, _reporter, _ = _create_report(
        db_session, create_user, client, auth_headers
    )
    wrong_target = create_user()
    action = ModerationAction(
        report_id=report_id,
        actor_user_id=staff["id"],
        action_type="WARNING",
        decision_code="WARNING",
        reason="Advertência de teste.",
    )
    db_session.add(action)
    db_session.flush()
    with pytest.raises(IntegrityError):
        db_session.add(
            ModerationSanction(
                report_id=report_id,
                target_user_id=wrong_target["id"],
                actor_user_id=staff["id"],
                source_action_id=action.id,
                sanction_type="WARNING",
                reason="Alvo inconsistente.",
            )
        )
        db_session.flush()
    db_session.rollback()
    assert db_session.scalar(
        select(func.count(ModerationSanction.id)).where(
            ModerationSanction.report_id == report_id
        )
    ) == 0

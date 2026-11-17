from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

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
from app.services.moderation_analysis_service import (
    MODEL_NAME,
    process_next_analysis_job,
)
from app.services.moderation_report_service import create_message_report
from app.services.moderation_review_service import (
    record_human_decision,
    triage_report_for_external_analysis,
)


def _direct_message(db, first_id, second_id, content="denunciada snapshot"):
    user_a, user_b = sorted((first_id, second_id))
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
        sender_id=second_id,
        content=content,
    )
    db.add(message)
    db.flush()
    return conversation, message


def _report_with_staff(db, create_user, *, content="denunciada snapshot"):
    reporter = create_user()
    author = create_user()
    moderator = create_user()
    _, message = _direct_message(
        db, reporter["id"], author["id"], content=content
    )
    report = create_message_report(
        db,
        db.get(User, reporter["id"]),
        message.id,
        "Denúncia para teste",
    )
    staff = PlatformStaff(
        user_id=moderator["id"], role="MODERATOR", status="ACTIVE"
    )
    db.add(staff)
    db.flush()
    job = db.scalar(
        select(ModerationAnalysisJob).where(
            ModerationAnalysisJob.report_id == report.id
        )
    )
    return report, job, staff, message


def _same_session_factory(session):
    @contextmanager
    def make_session():
        yield session

    return make_session


class FakeModerations:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response=None, error=None):
        self.moderations = FakeModerations(response=response, error=error)


def _provider_response(*, flagged: bool):
    return {
        "id": "modr-test-response",
        "model": "omni-moderation-2024-09-26",
        "results": [
            {
                "flagged": flagged,
                "categories": {"harassment": flagged, "sexual": False},
                "category_scores": {"harassment": 0.91, "sexual": 0.01},
                "category_applied_input_types": {
                    "harassment": ["text"],
                    "sexual": ["text"],
                },
            }
        ],
    }


def test_report_creation_persists_a_durable_job_waiting_for_manual_triage(
    db_session, create_user
):
    report, job, _staff, _message = _report_with_staff(db_session, create_user)

    assert job.report_id == report.id
    assert job.status == "PENDING_TRIAGE"
    assert job.attempt_count == 0
    assert db_session.scalar(
        select(func.count(ModerationReportEvidence.id)).where(
            ModerationReportEvidence.report_id == report.id
        )
    ) == 1


def test_untriaged_report_never_calls_openai(db_session, create_user):
    _report, _job, _staff, _message = _report_with_staff(db_session, create_user)
    client = FakeClient(response=_provider_response(flagged=False))

    processed = process_next_analysis_job(
        _same_session_factory(db_session), client
    )

    assert processed is False
    assert client.moderations.calls == []


@pytest.mark.parametrize("flagged", [False, True])
def test_approved_job_sends_only_reported_snapshot_and_persists_result(
    db_session, create_user, flagged
):
    report, job, staff, message = _report_with_staff(
        db_session, create_user, content="only this private message"
    )
    triage_report_for_external_analysis(
        db_session,
        report_id=report.id,
        staff=staff,
        external_analysis_eligible=True,
        reason="Triagem manual autorizou análise externa.",
    )
    client = FakeClient(response=_provider_response(flagged=flagged))

    assert process_next_analysis_job(
        _same_session_factory(db_session), client
    ) is True
    assert client.moderations.calls == [
        {"model": MODEL_NAME, "input": "only this private message"}
    ]

    db_session.refresh(job)
    db_session.refresh(report)
    assert job.status == "COMPLETED"
    assert job.attempt_count == 1
    assert job.model == "omni-moderation-2024-09-26"
    assert job.flagged is flagged
    assert job.categories == {"harassment": flagged, "sexual": False}
    assert job.category_scores == {"harassment": 0.91, "sexual": 0.01}
    assert job.category_applied_input_types["harassment"] == ["text"]
    assert job.provider_response_id == "modr-test-response"
    assert job.analyzed_at is not None
    assert report.status == "PENDING"  # AI signals never decide the case.
    assert report.triage_status == "COMPLETED"
    assert db_session.scalar(
        select(func.count(ModerationAnalysisJob.id)).where(
            ModerationAnalysisJob.report_id == report.id
        )
    ) == 1

    # A completed outbox item is idempotent and cannot create another result.
    assert process_next_analysis_job(
        _same_session_factory(db_session), client
    ) is False
    assert len(client.moderations.calls) == 1


def test_manual_review_gate_never_submits_content(db_session, create_user):
    report, job, staff, _message = _report_with_staff(db_session, create_user)
    triage_report_for_external_analysis(
        db_session,
        report_id=report.id,
        staff=staff,
        external_analysis_eligible=False,
        reason="Conteúdo encaminhado para análise humana apropriada.",
    )
    client = FakeClient(response=_provider_response(flagged=True))

    assert process_next_analysis_job(
        _same_session_factory(db_session), client
    ) is False
    db_session.refresh(job)
    assert job.status == "MANUAL_REVIEW"
    assert client.moderations.calls == []


def test_sensitive_content_suspicion_forces_manual_review_and_never_calls_openai(
    db_session, create_user
):
    report, job, staff, _message = _report_with_staff(
        db_session, create_user, content="texto fictício inofensivo de teste"
    )
    triage_report_for_external_analysis(
        db_session,
        report_id=report.id,
        staff=staff,
        external_analysis_eligible=True,
        sensitive_content_suspected=True,
        reason="Suspeita encaminhada para revisão humana especializada.",
    )
    client = FakeClient(response=_provider_response(flagged=True))

    assert process_next_analysis_job(
        _same_session_factory(db_session), client
    ) is False
    db_session.refresh(report)
    db_session.refresh(job)
    action = db_session.scalar(
        select(ModerationAction).where(ModerationAction.report_id == report.id)
    )
    assert report.status == "PENDING"
    assert report.triage_status == "MANUAL_REVIEW"
    assert job.status == "MANUAL_REVIEW"
    assert action.action_type == "SENSITIVE_CONTENT_MANUAL_REVIEW"
    assert action.reason == "Suspeita encaminhada para revisão humana especializada."
    assert client.moderations.calls == []


def test_pending_job_cannot_bypass_sensitive_content_triage_gate(
    db_session, create_user
):
    report, job, staff, _message = _report_with_staff(
        db_session, create_user, content="texto fictício inofensivo de teste"
    )
    triage_report_for_external_analysis(
        db_session,
        report_id=report.id,
        staff=staff,
        external_analysis_eligible=True,
        sensitive_content_suspected=True,
        reason="Revisão humana obrigatória.",
    )
    # Simulate a stale queue state. Eligibility must be independently enforced
    # by the worker from the report's persisted triage state.
    job.status = "PENDING"
    db_session.flush()
    client = FakeClient(response=_provider_response(flagged=True))

    assert process_next_analysis_job(
        _same_session_factory(db_session), client
    ) is False
    assert client.moderations.calls == []
    assert job.status == "PENDING"
    assert report.triage_status == "MANUAL_REVIEW"


def test_human_decision_before_claim_cancels_approved_job(db_session, create_user):
    report, job, staff, _message = _report_with_staff(db_session, create_user)
    triage_report_for_external_analysis(
        db_session,
        report_id=report.id,
        staff=staff,
        external_analysis_eligible=True,
        reason="Triagem aprovou a análise externa.",
    )
    record_human_decision(
        db_session,
        report_id=report.id,
        staff=staff,
        decision="CLOSED",
        reason="Decisão humana final antes do processamento.",
    )
    client = FakeClient(response=_provider_response(flagged=True))

    assert process_next_analysis_job(
        _same_session_factory(db_session), client
    ) is False
    db_session.refresh(report)
    db_session.refresh(job)
    assert report.status == "REVIEWED"
    assert job.status == "MANUAL_REVIEW"
    assert job.claim_token is None
    assert client.moderations.calls == []


def test_human_decision_during_analysis_is_not_overwritten(db_session, create_user):
    report, job, staff, _message = _report_with_staff(db_session, create_user)
    triage_report_for_external_analysis(
        db_session,
        report_id=report.id,
        staff=staff,
        external_analysis_eligible=True,
        reason="Triagem aprovou a análise externa.",
    )

    client = FakeClient(response=_provider_response(flagged=True))

    def decide_then_respond(**kwargs):
        client.moderations.calls.append(kwargs)
        record_human_decision(
            db_session,
            report_id=report.id,
            staff=staff,
            decision="CLOSED",
            reason="Decisão humana durante a análise.",
        )
        return _provider_response(flagged=True)

    client.moderations.create = decide_then_respond
    assert process_next_analysis_job(
        _same_session_factory(db_session), client
    ) is True

    db_session.refresh(report)
    db_session.refresh(job)
    assert report.status == "REVIEWED"
    assert report.triage_status == "MANUAL_REVIEW"
    assert job.status == "MANUAL_REVIEW"
    assert job.claim_token is None
    assert job.flagged is None
    assert len(client.moderations.calls) == 1


def test_worker_does_not_claim_job_when_report_is_no_longer_open(
    db_session, create_user
):
    report, job, staff, _message = _report_with_staff(db_session, create_user)
    triage_report_for_external_analysis(
        db_session,
        report_id=report.id,
        staff=staff,
        external_analysis_eligible=True,
        reason="A triagem autorizou, mas a denúncia foi encerrada antes do envio.",
    )
    # Simulate a stale/inconsistent queue row to ensure the worker independently
    # enforces the report eligibility predicate.
    report.status = "REVIEWED"
    db_session.flush()
    client = FakeClient(response=_provider_response(flagged=True))

    assert process_next_analysis_job(
        _same_session_factory(db_session), client
    ) is False
    db_session.refresh(job)
    assert job.status == "PENDING"
    assert client.moderations.calls == []


def test_provider_timeout_retries_are_bounded_and_content_is_not_stored_as_error(
    db_session, create_user, monkeypatch
):
    from app.services import moderation_analysis_service as analysis

    monkeypatch.setattr(analysis, "BASE_RETRY_DELAY", timedelta(0))
    report, job, staff, _message = _report_with_staff(db_session, create_user)
    triage_report_for_external_analysis(
        db_session,
        report_id=report.id,
        staff=staff,
        external_analysis_eligible=True,
        reason="Triagem autorizada para validar retentativas.",
    )
    client = FakeClient(error=TimeoutError("private content must not be logged"))

    for _ in range(analysis.MAX_ATTEMPTS):
        assert analysis.process_next_analysis_job(
            _same_session_factory(db_session), client
        ) is True

    db_session.refresh(job)
    db_session.refresh(report)
    assert len(client.moderations.calls) == analysis.MAX_ATTEMPTS
    assert job.status == "FAILED"
    assert job.attempt_count == analysis.MAX_ATTEMPTS
    assert job.last_error_code == "PROVIDER_TIMEOUT_OR_UNAVAILABLE"
    assert "private content" not in job.last_error_code
    assert report.triage_status == "FAILED"


def test_invalid_provider_response_is_not_treated_as_a_classification(
    db_session, create_user
):
    report, job, staff, _message = _report_with_staff(db_session, create_user)
    triage_report_for_external_analysis(
        db_session,
        report_id=report.id,
        staff=staff,
        external_analysis_eligible=True,
        reason="Triagem autorizada para validar resposta inválida.",
    )
    client = FakeClient(response={"model": MODEL_NAME, "results": []})

    assert process_next_analysis_job(
        _same_session_factory(db_session), client
    ) is True
    db_session.refresh(job)
    assert job.status == "PENDING"
    assert job.last_error_code == "INVALID_PROVIDER_RESPONSE"
    assert job.flagged is None


def test_result_persistence_failure_keeps_job_recoverable_without_partial_result(
    db_session, create_user, monkeypatch
):
    from app.services import moderation_analysis_service as analysis

    report, job, staff, _message = _report_with_staff(db_session, create_user)
    triage_report_for_external_analysis(
        db_session,
        report_id=report.id,
        staff=staff,
        external_analysis_eligible=True,
        reason="Triagem autorizada para validar recuperação.",
    )
    client = FakeClient(response=_provider_response(flagged=True))
    original_commit = db_session.commit
    commit_count = 0

    def fail_result_commit():
        nonlocal commit_count
        commit_count += 1
        if commit_count == 2:
            raise SQLAlchemyError("simulated result persistence failure")
        original_commit()

    monkeypatch.setattr(db_session, "commit", fail_result_commit)
    assert analysis.process_next_analysis_job(
        _same_session_factory(db_session), client
    ) is True
    monkeypatch.setattr(db_session, "commit", original_commit)
    db_session.refresh(job)
    assert job.status == "PROCESSING"
    assert job.flagged is None
    assert job.categories is None

    # Expire the abandoned lease: retry uses the same unique outbox row.
    job.claimed_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    db_session.flush()
    monkeypatch.setattr(analysis, "LEASE_DURATION", timedelta(0))
    assert analysis.process_next_analysis_job(
        _same_session_factory(db_session), client
    ) is True
    db_session.refresh(job)
    assert job.status == "COMPLETED"
    assert job.attempt_count == 2
    assert len(client.moderations.calls) == 2
    assert db_session.scalar(
        select(func.count(ModerationAnalysisJob.id)).where(
            ModerationAnalysisJob.report_id == report.id
        )
    ) == 1


def test_triage_is_audited_with_authenticated_official_staff(
    db_session, create_user
):
    report, _job, staff, _message = _report_with_staff(db_session, create_user)
    triage_report_for_external_analysis(
        db_session,
        report_id=report.id,
        staff=staff,
        external_analysis_eligible=True,
        reason="Aprovado na triagem manual.",
    )
    action = db_session.scalar(
        select(ModerationAction).where(
            ModerationAction.report_id == report.id
        )
    )
    assert action.actor_user_id == staff.user_id
    assert action.action_type == "EXTERNAL_ANALYSIS_APPROVED"
    assert action.reason == "Aprovado na triagem manual."


def test_message_send_does_not_create_analysis_job(
    client, db_session, create_user, auth_headers
):
    sender = create_user()
    recipient = create_user()
    _conversation, _seed_message = _direct_message(
        db_session, sender["id"], recipient["id"]
    )
    headers = auth_headers(sender)
    sent = client.post(
        f"/conversations/{_conversation.id}/messages",
        json={"content": "Mensagem privada sem denúncia."},
        headers=headers,
    )
    assert sent.status_code == 201, sent.text
    assert db_session.scalar(
        select(func.count(ModerationAnalysisJob.id))
    ) == 0


def test_duplicate_triage_is_conflict(db_session, create_user):
    report, _job, staff, _message = _report_with_staff(db_session, create_user)
    triage_report_for_external_analysis(
        db_session,
        report_id=report.id,
        staff=staff,
        external_analysis_eligible=True,
        reason="Primeira triagem registrada.",
    )
    with pytest.raises(HTTPException) as exc_info:
        triage_report_for_external_analysis(
            db_session,
            report_id=report.id,
            staff=staff,
            external_analysis_eligible=True,
            reason="Tentativa de triagem repetida.",
        )
    assert exc_info.value.status_code == 409

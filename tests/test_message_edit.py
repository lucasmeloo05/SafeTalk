from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Block,
    Conversation,
    ConversationParticipant,
    Friendship,
    Message,
    MessageEditHistory,
    MessageUpdateEvent,
    ModerationReportEvidence,
    User,
)
from app.services.message_service import edit_message
from conftest import test_engine


def _conversation(db_session, first_id: int, second_id: int) -> Conversation:
    low, high = sorted((first_id, second_id))
    db_session.add(
        Friendship(
            user_a_id=low,
            user_b_id=high,
            requested_by_id=low,
            status="ACCEPTED",
        )
    )
    db_session.flush()
    conversation = Conversation(
        type="DIRECT", user_a_id=low, user_b_id=high, created_by=low
    )
    db_session.add(conversation)
    db_session.flush()
    db_session.add_all(
        [
            ConversationParticipant(
                conversation_id=conversation.id, user_id=low, status="ACTIVE"
            ),
            ConversationParticipant(
                conversation_id=conversation.id, user_id=high, status="ACTIVE"
            ),
        ]
    )
    db_session.flush()
    return conversation


def _create_message(client, db_session, create_user, auth_headers):
    author, recipient = create_user(), create_user()
    conversation = _conversation(db_session, author["id"], recipient["id"])
    headers = auth_headers(author)
    sent = client.post(
        f"/conversations/{conversation.id}/messages",
        json={"content": "Conteúdo original"},
        headers=headers,
    )
    assert sent.status_code == 201, sent.text
    return author, recipient, conversation.id, sent.json(), headers


def _persistent_edit_context() -> tuple[int, int, int, int]:
    suffix = uuid4().hex[:8]
    with Session(test_engine) as db:
        author = User(
            username=f"edita_{suffix}",
            email=f"edita_{suffix}@example.test",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        recipient = User(
            username=f"editb_{suffix}",
            email=f"editb_{suffix}@example.test",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        db.add_all([author, recipient])
        db.flush()
        low, high = sorted((author.id, recipient.id))
        conversation = Conversation(
            type="DIRECT", user_a_id=low, user_b_id=high, created_by=low
        )
        db.add(conversation)
        db.flush()
        db.add_all(
            [
                ConversationParticipant(
                    conversation_id=conversation.id,
                    user_id=author.id,
                    status="ACTIVE",
                ),
                ConversationParticipant(
                    conversation_id=conversation.id,
                    user_id=recipient.id,
                    status="ACTIVE",
                ),
            ]
        )
        message = Message(
            conversation_id=conversation.id,
            sender_id=author.id,
            content="Versão original",
        )
        db.add(message)
        db.commit()
        return author.id, recipient.id, conversation.id, message.id


def _cleanup_persistent_edit_context(context: tuple[int, int, int, int]) -> None:
    author_id, recipient_id, conversation_id, message_id = context
    with Session(test_engine) as db:
        db.execute(
            delete(MessageEditHistory).where(
                MessageEditHistory.conversation_id == conversation_id
            )
        )
        db.execute(
            delete(MessageUpdateEvent).where(
                MessageUpdateEvent.conversation_id == conversation_id
            )
        )
        db.execute(delete(Message).where(Message.id == message_id))
        db.execute(
            delete(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id
            )
        )
        db.execute(delete(Conversation).where(Conversation.id == conversation_id))
        db.execute(delete(User).where(User.id.in_([author_id, recipient_id])))
        db.commit()


class _CommitGateSession(Session):
    def commit(self) -> None:
        gate = self.info.pop("commit_gate", None)
        if gate is not None:
            reached, allow = gate
            reached.set()
            if not allow.wait(timeout=20):
                raise TimeoutError("A transação A não foi liberada pelo teste.")
        super().commit()


def _wait_for_lock_wait(backend_pid: int, finished: Event) -> bool:
    deadline = monotonic() + 10
    while monotonic() < deadline and not finished.is_set():
        with Session(test_engine) as observer:
            activity = observer.execute(
                text(
                    "SELECT wait_event_type, query FROM pg_stat_activity "
                    "WHERE pid = :pid"
                ),
                {"pid": backend_pid},
            ).one_or_none()
        if (
            activity is not None
            and activity.wait_event_type == "Lock"
            and "FOR UPDATE" in activity.query.upper()
        ):
            return True
        finished.wait(0.01)
    return False


def test_author_can_edit_and_persists_one_history_row_and_one_update_event(
    client, db_session, create_user, auth_headers
):
    author, recipient, conversation_id, original, headers = _create_message(
        client, db_session, create_user, auth_headers
    )

    response = client.patch(
        f"/conversations/{conversation_id}/messages/{original['id']}",
        json={"content": "  Conteúdo revisado  "},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["message"]["content"] == "Conteúdo revisado"
    assert payload["message"]["sender_id"] == author["id"]
    assert payload["message_state_revision"] == 1
    assert payload["message"]["edited_at"] is not None
    assert payload["message"]["updated_at"] == payload["message"]["edited_at"]
    assert payload["message"]["updated_at"] > original["updated_at"]

    history = db_session.scalars(
        select(MessageEditHistory).where(MessageEditHistory.message_id == original["id"])
    ).all()
    events = db_session.scalars(
        select(MessageUpdateEvent).where(
            MessageUpdateEvent.conversation_id == conversation_id
        )
    ).all()
    assert len(history) == 1
    assert (history[0].previous_content, history[0].new_content) == (
        "Conteúdo original",
        "Conteúdo revisado",
    )
    assert history[0].edited_by_id == author["id"]
    assert history[0].message_state_revision == 1
    assert len(events) == 1
    assert (events[0].revision, events[0].event_type, events[0].message_id) == (
        1,
        "UPDATED",
        original["id"],
    )

    sync = client.get(
        f"/conversations/{conversation_id}/message-updates",
        params={"after_revision": 0},
        headers=auth_headers(recipient),
    )
    assert sync.status_code == 200, sync.text
    assert sync.json()["items"][0]["message"]["content"] == "Conteúdo revisado"


def test_non_author_cannot_edit_message(client, db_session, create_user, auth_headers):
    _, recipient, conversation_id, message, _ = _create_message(
        client, db_session, create_user, auth_headers
    )
    response = client.patch(
        f"/conversations/{conversation_id}/messages/{message['id']}",
        json={"content": "Alteração indevida"},
        headers=auth_headers(recipient),
    )
    assert response.status_code == 403


def test_edit_requires_authentication(client, db_session, create_user, auth_headers):
    _, _, conversation_id, message, _ = _create_message(
        client, db_session, create_user, auth_headers
    )
    response = client.patch(
        f"/conversations/{conversation_id}/messages/{message['id']}",
        json={"content": "Sem sessão"},
    )
    assert response.status_code == 401


@pytest.mark.parametrize("content", ["", "   ", "x" * 5001])
def test_edit_rejects_empty_or_overlong_content(
    client, db_session, create_user, auth_headers, content
):
    _, _, conversation_id, message, headers = _create_message(
        client, db_session, create_user, auth_headers
    )
    response = client.patch(
        f"/conversations/{conversation_id}/messages/{message['id']}",
        json={"content": content},
        headers=headers,
    )
    assert response.status_code == 422


def test_edit_rejects_fields_owned_by_server(
    client, db_session, create_user, auth_headers
):
    _, _, conversation_id, message, headers = _create_message(
        client, db_session, create_user, auth_headers
    )
    response = client.patch(
        f"/conversations/{conversation_id}/messages/{message['id']}",
        json={"content": "Nova", "sender_id": 999, "edited_at": None},
        headers=headers,
    )
    assert response.status_code == 422


def test_edit_after_fifteen_minutes_is_rejected(
    client, db_session, create_user, auth_headers
):
    _, _, conversation_id, message, headers = _create_message(
        client, db_session, create_user, auth_headers
    )
    db_message = db_session.get(Message, message["id"])
    db_message.created_at = datetime.now(timezone.utc) - timedelta(minutes=16)
    db_session.commit()

    response = client.patch(
        f"/conversations/{conversation_id}/messages/{message['id']}",
        json={"content": "Tarde demais"},
        headers=headers,
    )
    assert response.status_code == 409
    assert "15 minutos" in response.json()["detail"]


def test_edit_within_fifteen_minutes_is_allowed(
    client, db_session, create_user, auth_headers
):
    _, _, conversation_id, message, headers = _create_message(
        client, db_session, create_user, auth_headers
    )
    db_message = db_session.get(Message, message["id"])
    db_message.created_at = datetime.now(timezone.utc) - timedelta(minutes=14)
    db_session.commit()

    response = client.patch(
        f"/conversations/{conversation_id}/messages/{message['id']}",
        json={"content": "Ainda no prazo"},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def test_deleted_message_cannot_be_edited(
    client, db_session, create_user, auth_headers
):
    author, _, conversation_id, message, headers = _create_message(
        client, db_session, create_user, auth_headers
    )
    db_message = db_session.get(Message, message["id"])
    db_message.deleted_for_everyone_at = datetime.now(timezone.utc)
    db_message.deleted_for_everyone_by_id = author["id"]
    db_session.commit()

    response = client.patch(
        f"/conversations/{conversation_id}/messages/{message['id']}",
        json={"content": "Não deve alterar"},
        headers=headers,
    )
    assert response.status_code == 409


def test_inactive_participant_cannot_edit(
    client, db_session, create_user, auth_headers
):
    author, _, conversation_id, message, headers = _create_message(
        client, db_session, create_user, auth_headers
    )
    participant = db_session.scalar(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == author["id"],
        )
    )
    participant.status = "LEFT"
    participant.left_at = datetime.now(timezone.utc)
    db_session.commit()

    response = client.patch(
        f"/conversations/{conversation_id}/messages/{message['id']}",
        json={"content": "Sem participação"},
        headers=headers,
    )
    assert response.status_code == 403


def test_blocked_participants_cannot_edit(
    client, db_session, create_user, auth_headers
):
    author, recipient, conversation_id, message, headers = _create_message(
        client, db_session, create_user, auth_headers
    )
    db_session.add(Block(blocker_id=recipient["id"], blocked_id=author["id"]))
    db_session.commit()

    response = client.patch(
        f"/conversations/{conversation_id}/messages/{message['id']}",
        json={"content": "Bloqueada"},
        headers=headers,
    )
    assert response.status_code == 403


def test_message_from_another_conversation_is_not_editable(
    client, db_session, create_user, auth_headers
):
    author, _, _, message, headers = _create_message(
        client, db_session, create_user, auth_headers
    )
    other_user = create_user()
    other_conversation = _conversation(db_session, author["id"], other_user["id"])
    db_session.commit()

    response = client.patch(
        f"/conversations/{other_conversation.id}/messages/{message['id']}",
        json={"content": "ID cruzado"},
        headers=headers,
    )
    assert response.status_code == 404


def test_identical_normalized_content_is_a_noop(
    client, db_session, create_user, auth_headers
):
    _, _, conversation_id, message, headers = _create_message(
        client, db_session, create_user, auth_headers
    )
    before_updated_at = message["updated_at"]

    response = client.patch(
        f"/conversations/{conversation_id}/messages/{message['id']}",
        json={"content": "  Conteúdo original  "},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["message"]["content"] == "Conteúdo original"
    assert response.json()["message_state_revision"] == 0
    assert response.json()["message"]["updated_at"] == before_updated_at
    assert response.json()["message"]["edited_at"] is None
    assert db_session.scalar(select(func.count()).select_from(MessageEditHistory)) == 0
    assert db_session.scalar(select(func.count()).select_from(MessageUpdateEvent)) == 0


def test_edit_preserves_existing_report_evidence(
    client, db_session, create_user, auth_headers
):
    author, reporter, conversation_id, message, author_headers = _create_message(
        client, db_session, create_user, auth_headers
    )
    original = db_session.get(Message, message["id"])
    original_snapshot = (original.content, original.sender_id, original.created_at, original.updated_at)
    report_response = client.post(
        "/reports",
        json={"message_id": message["id"], "reason": "Evidência de teste"},
        headers=auth_headers(reporter),
    )
    assert report_response.status_code == 201, report_response.text
    evidence = db_session.scalar(
        select(ModerationReportEvidence).where(
            ModerationReportEvidence.message_id == message["id"]
        )
    )
    evidence_snapshot = (
        evidence.content_snapshot,
        evidence.message_author_id,
        evidence.message_created_at,
        evidence.message_updated_at,
        evidence.message_edited_at,
    )

    edited = client.patch(
        f"/conversations/{conversation_id}/messages/{message['id']}",
        json={"content": "Texto alterado depois da denúncia"},
        headers=author_headers,
    )

    assert edited.status_code == 200, edited.text
    db_session.refresh(evidence)
    current = db_session.get(Message, message["id"])
    assert current.content == "Texto alterado depois da denúncia"
    assert current.sender_id == original_snapshot[1]
    assert current.created_at == original_snapshot[2]
    assert current.updated_at > original_snapshot[3]
    assert (
        evidence.content_snapshot,
        evidence.message_author_id,
        evidence.message_created_at,
        evidence.message_updated_at,
        evidence.message_edited_at,
    ) == evidence_snapshot


def test_edit_history_event_foreign_key_requires_matching_message(
    client, db_session, create_user, auth_headers
):
    _, _, conversation_id, first_message, _ = _create_message(
        client, db_session, create_user, auth_headers
    )
    second_message = Message(
        conversation_id=conversation_id,
        sender_id=first_message["sender_id"],
        content="Outra mensagem da mesma conversa",
    )
    db_session.add(second_message)
    db_session.flush()
    db_session.add(
        MessageUpdateEvent(
            conversation_id=conversation_id,
            revision=1,
            message_id=first_message["id"],
            event_type="UPDATED",
        )
    )
    db_session.flush()
    db_session.add(
        MessageEditHistory(
            message_id=second_message.id,
            conversation_id=conversation_id,
            previous_content="Antes",
            new_content="Depois",
            edited_by_id=first_message["sender_id"],
            message_state_revision=1,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "SET CONSTRAINTS "
                "fk_message_edit_history_update_event_message IMMEDIATE"
            )
        )
    db_session.rollback()


def test_edit_response_does_not_refresh_after_successful_commit(
    client, db_session, create_user, auth_headers, monkeypatch
):
    _, _, conversation_id, message, headers = _create_message(
        client, db_session, create_user, auth_headers
    )

    def fail_if_refreshed(*args, **kwargs):
        raise RuntimeError("refresh não deve ocorrer depois do commit")

    monkeypatch.setattr(db_session, "refresh", fail_if_refreshed)
    response = client.patch(
        f"/conversations/{conversation_id}/messages/{message['id']}",
        json={"content": "Edição persistida com resposta segura"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["message"]["content"] == "Edição persistida com resposta segura"
    assert response.json()["message_state_revision"] == 1
    db_session.expire_all()
    assert db_session.get(Message, message["id"]).content == "Edição persistida com resposta segura"


def test_event_failure_rolls_back_message_history_and_revision(
    client, db_session, create_user, auth_headers, monkeypatch
):
    from app.services import message_service

    _, _, conversation_id, message, headers = _create_message(
        client, db_session, create_user, auth_headers
    )
    original_recorder = message_service.record_message_update_event

    def fail_after_event_flush(db, conversation, edited_message, event_type):
        original_recorder(db, conversation, edited_message, event_type)
        raise RuntimeError("Falha simulada após inserir evento")

    monkeypatch.setattr(message_service, "record_message_update_event", fail_after_event_flush)
    with pytest.raises(RuntimeError, match="Falha simulada"):
        client.patch(
            f"/conversations/{conversation_id}/messages/{message['id']}",
            json={"content": "Não persistir"},
            headers=headers,
        )

    db_session.expire_all()
    assert db_session.get(Message, message["id"]).content == "Conteúdo original"
    assert db_session.get(Conversation, conversation_id).messages_revision == 0
    assert db_session.scalar(select(func.count()).select_from(MessageEditHistory)) == 0
    assert db_session.scalar(select(func.count()).select_from(MessageUpdateEvent)) == 0


def test_history_insert_failure_rolls_back_message_and_revision(
    client, db_session, create_user, auth_headers
):
    _, _, conversation_id, message, headers = _create_message(
        client, db_session, create_user, auth_headers
    )

    def fail_history_insert(mapper, connection, history):
        raise RuntimeError("Falha simulada ao persistir histórico")

    event.listen(MessageEditHistory, "before_insert", fail_history_insert)
    try:
        with pytest.raises(RuntimeError, match="Falha simulada ao persistir histórico"):
            client.patch(
                f"/conversations/{conversation_id}/messages/{message['id']}",
                json={"content": "Não persistir"},
                headers=headers,
            )
    finally:
        event.remove(MessageEditHistory, "before_insert", fail_history_insert)

    db_session.expire_all()
    assert db_session.get(Message, message["id"]).content == "Conteúdo original"
    assert db_session.get(Conversation, conversation_id).messages_revision == 0
    assert db_session.scalar(select(func.count()).select_from(MessageEditHistory)) == 0
    assert db_session.scalar(select(func.count()).select_from(MessageUpdateEvent)) == 0


def test_commit_failure_rolls_back_message_history_and_revision(
    client, db_session, create_user, auth_headers, monkeypatch
):
    _, _, conversation_id, message, headers = _create_message(
        client, db_session, create_user, auth_headers
    )

    def fail_commit():
        raise RuntimeError("Falha simulada no commit")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="Falha simulada no commit"):
        client.patch(
            f"/conversations/{conversation_id}/messages/{message['id']}",
            json={"content": "Não persistir"},
            headers=headers,
        )

    db_session.expire_all()
    assert db_session.get(Message, message["id"]).content == "Conteúdo original"
    assert db_session.get(Conversation, conversation_id).messages_revision == 0
    assert db_session.scalar(select(func.count()).select_from(MessageEditHistory)) == 0
    assert db_session.scalar(select(func.count()).select_from(MessageUpdateEvent)) == 0


def test_concurrent_edits_serialize_and_receive_distinct_revisions():
    context = _persistent_edit_context()
    author_id, recipient_id, conversation_id, message_id = context
    a_reached_commit, allow_a_commit = Event(), Event()
    b_backend_ready, b_finished = Event(), Event()
    b_backend_pid: list[int] = []
    results: dict[str, dict] = {}
    errors: dict[str, BaseException] = {}

    def edit_a() -> None:
        try:
            with _CommitGateSession(test_engine, expire_on_commit=False) as db:
                author = db.get(User, author_id)
                db.info["commit_gate"] = (a_reached_commit, allow_a_commit)
                results["a"] = edit_message(
                    db, author, conversation_id, message_id, "Edição A"
                )
        except BaseException as error:
            errors["a"] = error

    def edit_b() -> None:
        try:
            with Session(test_engine, expire_on_commit=False) as db:
                db.execute(
                    text("SELECT set_config('application_name', :name, false)"),
                    {"name": f"safetalk-edit-test-{uuid4().hex}"},
                )
                b_backend_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
                b_backend_ready.set()
                author = db.get(User, author_id)
                results["b"] = edit_message(
                    db, author, conversation_id, message_id, "Edição B"
                )
        except BaseException as error:
            errors["b"] = error
        finally:
            b_finished.set()

    thread_a = Thread(target=edit_a)
    thread_b = Thread(target=edit_b)
    try:
        thread_a.start()
        assert a_reached_commit.wait(timeout=10), "A não chegou ao commit mantendo o lock."
        thread_b.start()
        assert b_backend_ready.wait(timeout=10), "B não abriu sua sessão PostgreSQL."
        assert _wait_for_lock_wait(b_backend_pid[0], b_finished), (
            "PostgreSQL não reportou B aguardando o lock da conversa."
        )
        assert not b_finished.is_set()
        allow_a_commit.set()
        thread_a.join(timeout=15)
        thread_b.join(timeout=15)
        assert not thread_a.is_alive() and not thread_b.is_alive()
        assert errors == {}
        assert results["a"]["message_state_revision"] == 1
        assert results["b"]["message_state_revision"] == 2

        with Session(test_engine) as verify:
            current = verify.get(Message, message_id)
            history = verify.scalars(
                select(MessageEditHistory)
                .where(MessageEditHistory.message_id == message_id)
                .order_by(MessageEditHistory.message_state_revision)
            ).all()
            events = verify.scalars(
                select(MessageUpdateEvent)
                .where(MessageUpdateEvent.conversation_id == conversation_id)
                .order_by(MessageUpdateEvent.revision)
            ).all()
            assert current.content == "Edição B"
            assert [item.message_state_revision for item in history] == [1, 2]
            assert [item.previous_content for item in history] == [
                "Versão original",
                "Edição A",
            ]
            assert [item.revision for item in events] == [1, 2]
    finally:
        allow_a_commit.set()
        thread_a.join(timeout=20)
        thread_b.join(timeout=20)
        _cleanup_persistent_edit_context(context)

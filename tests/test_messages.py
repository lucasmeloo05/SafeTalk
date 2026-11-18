from datetime import datetime, timezone
from threading import Event, Thread
from time import monotonic, sleep
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.models import (
    Block,
    Conversation,
    ConversationParticipant,
    Friendship,
    Message,
    MessageUserDeletion,
    User,
)
from app.services.message_service import list_messages, send_message
from conftest import test_engine


class _CommitGateSession(Session):
    """Pause one commit after flush so another session can contend for a lock."""

    def commit(self) -> None:
        gate = self.info.pop("commit_gate", None)
        if gate is not None:
            commit_reached, allow_commit = gate
            commit_reached.set()
            if not allow_commit.wait(timeout=20):
                raise TimeoutError("O teste não liberou o commit da sessão A.")
        super().commit()


def _friendship(db_session, first_user_id: int, second_user_id: int) -> None:
    user_a_id, user_b_id = sorted((first_user_id, second_user_id))
    db_session.add(
        Friendship(
            user_a_id=user_a_id,
            user_b_id=user_b_id,
            requested_by_id=user_a_id,
            status="ACCEPTED",
        )
    )
    db_session.flush()


def _conversation(client: TestClient, headers: dict, recipient_id: int) -> int:
    response = client.post(
        "/conversations/direct",
        json={"recipient_id": recipient_id},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _persistent_message_conversation() -> tuple[int, int, int]:
    suffix = uuid4().hex[:12]
    with Session(test_engine) as db:
        first = User(
            username=f"message_first_{suffix}",
            email=f"message_first_{suffix}@example.test",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        second = User(
            username=f"message_second_{suffix}",
            email=f"message_second_{suffix}@example.test",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        db.add_all([first, second])
        db.flush()
        user_a_id, user_b_id = sorted((first.id, second.id))
        conversation = Conversation(
            type="DIRECT",
            user_a_id=user_a_id,
            user_b_id=user_b_id,
            created_by=user_a_id,
        )
        db.add(conversation)
        db.flush()
        db.add_all(
            [
                ConversationParticipant(
                    conversation_id=conversation.id,
                    user_id=first.id,
                    role="MEMBER",
                    status="ACTIVE",
                ),
                ConversationParticipant(
                    conversation_id=conversation.id,
                    user_id=second.id,
                    role="MEMBER",
                    status="ACTIVE",
                ),
            ]
        )
        db.commit()
        return first.id, second.id, conversation.id


def _cleanup_persistent_message_conversation(context: tuple[int, int, int]) -> None:
    first_id, second_id, conversation_id = context
    with Session(test_engine) as db:
        message_ids = select(Message.id).where(
            Message.conversation_id == conversation_id
        )
        db.execute(
            delete(MessageUserDeletion).where(
                MessageUserDeletion.message_id.in_(message_ids)
            )
        )
        db.execute(delete(Message).where(Message.conversation_id == conversation_id))
        db.execute(
            delete(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id
            )
        )
        db.execute(delete(Conversation).where(Conversation.id == conversation_id))
        db.execute(delete(User).where(User.id.in_([first_id, second_id])))
        db.commit()


def _wait_for_postgres_lock_wait(backend_pid: int, finished: Event) -> bool:
    """Observe B bloqueada na consulta FOR UPDATE, não apenas sem resposta."""
    deadline = monotonic() + 10
    while monotonic() < deadline and not finished.is_set():
        with Session(test_engine) as observer:
            activity = observer.execute(
                text(
                    """
                    SELECT wait_event_type, query
                    FROM pg_stat_activity
                    WHERE pid = :backend_pid
                    """
                ),
                {"backend_pid": backend_pid},
            ).one_or_none()
        if (
            activity is not None
            and activity.wait_event_type == "Lock"
            and "FOR UPDATE" in activity.query.upper()
        ):
            return True
        # Event.wait yields between observations; the assertion is based on
        # PostgreSQL's reported lock wait, not on elapsed time alone.
        finished.wait(timeout=0.01)
    return False


def test_send_message_trims_content_and_returns_created_message(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    _friendship(db_session, sender["id"], recipient["id"])
    headers = auth_headers(sender)
    conversation_id = _conversation(client, headers, recipient["id"])

    response = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "  Olá, mundo!  "},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["content"] == "Olá, mundo!"
    assert response.json()["sender_id"] == sender["id"]
    assert response.json()["conversation_id"] == conversation_id


def test_message_list_is_ordered_and_obeys_limit_and_offset(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    _friendship(db_session, sender["id"], recipient["id"])
    headers = auth_headers(sender)
    conversation_id = _conversation(client, headers, recipient["id"])
    for content in ("primeira", "segunda", "terceira"):
        sent = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": content},
            headers=headers,
        )
        assert sent.status_code == 201

    response = client.get(
        f"/conversations/{conversation_id}/messages?limit=2&offset=1",
        headers=headers,
    )

    assert response.status_code == 200
    assert [message["content"] for message in response.json()] == [
        "segunda",
        "terceira",
    ]


def test_initial_message_window_returns_latest_messages_in_chronological_order(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    _friendship(db_session, sender["id"], recipient["id"])
    headers = auth_headers(sender)
    conversation_id = _conversation(client, headers, recipient["id"])
    for content in ("primeira", "segunda", "terceira", "quarta"):
        sent = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": content},
            headers=headers,
        )
        assert sent.status_code == 201

    response = client.get(
        f"/conversations/{conversation_id}/messages?limit=2&latest=true",
        headers=headers,
    )

    assert response.status_code == 200
    assert [message["content"] for message in response.json()] == [
        "terceira",
        "quarta",
    ]


def test_explicit_offset_zero_preserves_legacy_first_page(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    _friendship(db_session, sender["id"], recipient["id"])
    headers = auth_headers(sender)
    conversation_id = _conversation(client, headers, recipient["id"])
    for content in ("primeira", "segunda", "terceira", "quarta"):
        sent = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": content},
            headers=headers,
        )
        assert sent.status_code == 201

    response = client.get(
        f"/conversations/{conversation_id}/messages?limit=2&offset=0",
        headers=headers,
    )

    assert response.status_code == 200
    assert [message["content"] for message in response.json()] == [
        "primeira",
        "segunda",
    ]


def test_omitted_offset_preserves_legacy_first_page(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    _friendship(db_session, sender["id"], recipient["id"])
    headers = auth_headers(sender)
    conversation_id = _conversation(client, headers, recipient["id"])
    for content in ("primeira", "segunda", "terceira", "quarta"):
        sent = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": content},
            headers=headers,
        )
        assert sent.status_code == 201

    response = client.get(
        f"/conversations/{conversation_id}/messages?limit=2",
        headers=headers,
    )

    assert response.status_code == 200
    assert [message["content"] for message in response.json()] == [
        "primeira",
        "segunda",
    ]


def test_incremental_messages_use_created_at_and_id_cursor_without_duplicates(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    _friendship(db_session, sender["id"], recipient["id"])
    headers = auth_headers(sender)
    conversation_id = _conversation(client, headers, recipient["id"])
    timestamp = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    first = Message(
        conversation_id=conversation_id,
        sender_id=sender["id"],
        content="primeira",
        created_at=timestamp,
        updated_at=timestamp,
    )
    second = Message(
        conversation_id=conversation_id,
        sender_id=recipient["id"],
        content="segunda",
        created_at=timestamp,
        updated_at=timestamp,
    )
    third = Message(
        conversation_id=conversation_id,
        sender_id=sender["id"],
        content="terceira",
        created_at=timestamp,
        updated_at=timestamp,
    )
    db_session.add_all([first, second, third])
    db_session.flush()

    response = client.get(
        f"/conversations/{conversation_id}/messages",
        params={"after_created_at": timestamp.isoformat(), "after_id": first.id},
        headers=headers,
    )
    repeated = client.get(
        f"/conversations/{conversation_id}/messages",
        params={"after_created_at": timestamp.isoformat(), "after_id": third.id},
        headers=headers,
    )

    assert response.status_code == 200
    assert [message["id"] for message in response.json()] == [second.id, third.id]
    assert repeated.status_code == 200
    assert repeated.json() == []


def test_late_commit_from_earlier_transaction_remains_after_cursor():
    """An earlier transaction timestamp must not sort after a later commit."""
    context = _persistent_message_conversation()
    first_id, second_id, conversation_id = context
    earlier_transaction = Session(test_engine, expire_on_commit=False)
    try:
        first_user = earlier_transaction.get(User, first_id)
        transaction_started_at = earlier_transaction.scalar(select(func.now()))
        sleep(0.02)

        with Session(test_engine) as later_transaction:
            second_user = later_transaction.get(User, second_id)
            committed_first = send_message(
                later_transaction,
                second_user,
                conversation_id,
                "Confirmação que chega primeiro.",
            )

        assert transaction_started_at < committed_first["created_at"]

        committed_late = send_message(
            earlier_transaction,
            first_user,
            conversation_id,
            "Confirmação de uma transação iniciada antes.",
        )
        assert committed_late["created_at"] > committed_first["created_at"]

        with Session(test_engine) as reader:
            reader_user = reader.get(User, first_id)
            messages_after_first_commit = list_messages(
                reader,
                reader_user,
                conversation_id,
                after_created_at=committed_first["created_at"],
                after_id=committed_first["id"],
            )
            messages_after_late_commit = list_messages(
                reader,
                reader_user,
                conversation_id,
                after_created_at=committed_late["created_at"],
                after_id=committed_late["id"],
            )

        assert [message["id"] for message in messages_after_first_commit] == [
            committed_late["id"]
        ]
        assert messages_after_late_commit == []
    finally:
        earlier_transaction.close()
        _cleanup_persistent_message_conversation(context)


def test_concurrent_send_waits_for_conversation_lock_and_is_retrieved_after_cursor():
    """B must wait on PostgreSQL's row lock until A commits its message."""
    context = _persistent_message_conversation()
    first_id, second_id, conversation_id = context
    a_at_commit = Event()
    allow_a_commit = Event()
    b_has_backend = Event()
    b_finished = Event()
    backend_pid: list[int] = []
    results: dict[str, dict] = {}
    errors: dict[str, BaseException] = {}

    def send_a() -> None:
        try:
            with _CommitGateSession(test_engine, expire_on_commit=False) as db:
                actor = db.get(User, first_id)
                db.info["commit_gate"] = (a_at_commit, allow_a_commit)
                results["a"] = send_message(
                    db, actor, conversation_id, "Mensagem A segura o lock."
                )
        except BaseException as error:
            errors["a"] = error

    def send_b() -> None:
        try:
            with Session(test_engine, expire_on_commit=False) as db:
                db.execute(
                    text("SELECT set_config('application_name', :name, false)"),
                    {"name": f"safetalk-lock-test-{uuid4().hex}"},
                )
                backend_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
                b_has_backend.set()
                actor = db.get(User, second_id)
                results["b"] = send_message(
                    db, actor, conversation_id, "Mensagem B aguarda o lock."
                )
        except BaseException as error:
            errors["b"] = error
        finally:
            b_finished.set()

    thread_a = Thread(target=send_a, name="message-send-a", daemon=True)
    thread_b = Thread(target=send_b, name="message-send-b", daemon=True)
    try:
        thread_a.start()
        assert a_at_commit.wait(timeout=10), "A não chegou ao commit mantendo o lock."

        thread_b.start()
        assert b_has_backend.wait(timeout=10), "B não abriu sua sessão PostgreSQL."
        assert _wait_for_postgres_lock_wait(backend_pid[0], b_finished), (
            "PostgreSQL não reportou B aguardando o SELECT FOR UPDATE da conversa."
        )
        assert not b_finished.is_set(), "B concluiu antes do commit de A."

        allow_a_commit.set()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)
        assert not thread_a.is_alive(), "A não concluiu após liberar o commit."
        assert not thread_b.is_alive(), "B não prosseguiu após A liberar o lock."
        assert errors == {}

        message_a = results["a"]
        message_b = results["b"]
        assert (message_a["created_at"], message_a["id"]) < (
            message_b["created_at"],
            message_b["id"],
        )

        with Session(test_engine) as reader:
            reader_user = reader.get(User, first_id)
            messages_after_a = list_messages(
                reader,
                reader_user,
                conversation_id,
                after_created_at=message_a["created_at"],
                after_id=message_a["id"],
            )
            messages_after_b = list_messages(
                reader,
                reader_user,
                conversation_id,
                after_created_at=message_b["created_at"],
                after_id=message_b["id"],
            )

        assert [item["id"] for item in messages_after_a] == [message_b["id"]]
        assert messages_after_b == []
    finally:
        allow_a_commit.set()
        thread_a.join(timeout=20)
        if thread_b.ident is not None:
            thread_b.join(timeout=20)
        if not thread_a.is_alive() and not thread_b.is_alive():
            _cleanup_persistent_message_conversation(context)


def test_send_in_another_conversation_does_not_wait_for_first_conversation_lock():
    first_context = _persistent_message_conversation()
    second_context = _persistent_message_conversation()
    first_user_id, _, first_conversation_id = first_context
    _, second_user_id, second_conversation_id = second_context
    a_at_commit = Event()
    allow_a_commit = Event()
    b_finished = Event()
    results: dict[str, dict] = {}
    errors: dict[str, BaseException] = {}

    def send_a() -> None:
        try:
            with _CommitGateSession(test_engine, expire_on_commit=False) as db:
                actor = db.get(User, first_user_id)
                db.info["commit_gate"] = (a_at_commit, allow_a_commit)
                results["a"] = send_message(
                    db, actor, first_conversation_id, "Conversa A permanece aberta."
                )
        except BaseException as error:
            errors["a"] = error

    def send_b() -> None:
        try:
            with Session(test_engine, expire_on_commit=False) as db:
                actor = db.get(User, second_user_id)
                results["b"] = send_message(
                    db, actor, second_conversation_id, "Conversa B segue independente."
                )
        except BaseException as error:
            errors["b"] = error
        finally:
            b_finished.set()

    thread_a = Thread(target=send_a, name="message-conversation-a", daemon=True)
    thread_b = Thread(target=send_b, name="message-conversation-b", daemon=True)
    try:
        thread_a.start()
        assert a_at_commit.wait(timeout=10), "A não chegou ao commit mantendo o lock."

        thread_b.start()
        assert b_finished.wait(timeout=10), (
            "O envio de outra conversa aguardou indevidamente o lock de A."
        )
        assert thread_a.is_alive(), "A não permaneceu pausada antes do commit."
        assert "a" not in results, "A deveria continuar pausada antes do commit."
        assert "b" in results
        assert errors == {}
    finally:
        allow_a_commit.set()
        thread_a.join(timeout=20)
        thread_b.join(timeout=20)
        if not thread_a.is_alive() and not thread_b.is_alive():
            _cleanup_persistent_message_conversation(first_context)
            _cleanup_persistent_message_conversation(second_context)


def test_incremental_cursor_cannot_read_another_conversations_messages(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    first_user = create_user()
    second_user = create_user()
    third_user = create_user()
    fourth_user = create_user()
    _friendship(db_session, first_user["id"], second_user["id"])
    _friendship(db_session, third_user["id"], fourth_user["id"])
    headers = auth_headers(first_user)
    first_conversation = _conversation(client, headers, second_user["id"])
    other_headers = auth_headers(third_user)
    other_conversation = _conversation(client, other_headers, fourth_user["id"])
    sent = client.post(
        f"/conversations/{other_conversation}/messages",
        json={"content": "mensagem de outra conversa"},
        headers=other_headers,
    )
    assert sent.status_code == 201
    cursor_message = sent.json()

    response = client.get(
        f"/conversations/{first_conversation}/messages",
        params={
            "after_created_at": cursor_message["created_at"],
            "after_id": cursor_message["id"],
        },
        headers=headers,
    )

    assert response.status_code == 404


def test_incremental_messages_require_active_participation(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    outsider = create_user()
    _friendship(db_session, sender["id"], recipient["id"])
    headers = auth_headers(sender)
    conversation_id = _conversation(client, headers, recipient["id"])
    timestamp = datetime.now(timezone.utc).isoformat()
    outsider_response = client.get(
        f"/conversations/{conversation_id}/messages",
        params={"after_created_at": timestamp, "after_id": 0},
        headers=auth_headers(outsider),
    )
    participant = db_session.query(ConversationParticipant).filter_by(
        conversation_id=conversation_id,
        user_id=recipient["id"],
    ).one()
    participant.status = "LEFT"
    participant.left_at = datetime.now(timezone.utc)
    db_session.flush()
    inactive_response = client.get(
        f"/conversations/{conversation_id}/messages",
        params={"after_created_at": timestamp, "after_id": 0},
        headers=auth_headers(recipient),
    )

    assert outsider_response.status_code == 403
    assert inactive_response.status_code == 403


def test_incremental_messages_preserve_block_checks_in_either_direction(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    _friendship(db_session, sender["id"], recipient["id"])
    headers = auth_headers(sender)
    conversation_id = _conversation(client, headers, recipient["id"])
    timestamp = datetime.now(timezone.utc).isoformat()
    for blocker, blocked in (
        (sender["id"], recipient["id"]),
        (recipient["id"], sender["id"]),
    ):
        db_session.add(Block(blocker_id=blocker, blocked_id=blocked))
        db_session.flush()
        response = client.get(
            f"/conversations/{conversation_id}/messages",
            params={"after_created_at": timestamp, "after_id": 0},
            headers=headers,
        )
        assert response.status_code == 403
        db_session.query(Block).filter_by(
            blocker_id=blocker,
            blocked_id=blocked,
        ).delete()
        db_session.flush()


def test_incremental_message_limit_remains_bounded(
    client: TestClient,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    headers = auth_headers(sender)
    response = client.get(
        "/conversations/1/messages?limit=101&after_id=0&after_created_at=2026-11-17T00:00:00Z",
        headers=headers,
    )

    assert response.status_code == 422


def test_send_message_rejects_blank_content(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    _friendship(db_session, sender["id"], recipient["id"])
    headers = auth_headers(sender)
    conversation_id = _conversation(client, headers, recipient["id"])

    response = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "   "},
        headers=headers,
    )

    assert response.status_code == 422

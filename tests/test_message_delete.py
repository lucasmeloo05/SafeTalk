from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, text
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
from app.services.message_service import (
    delete_message_for_everyone,
    edit_message,
    list_message_update_events,
    list_messages,
    send_message,
)
from app.services.social_service import block_user
from conftest import test_engine


PLACEHOLDER = "Esta mensagem foi excluída"


def _create_conversation(db_session, first_id: int, second_id: int) -> Conversation:
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


def _send_message(client, db_session, create_user, auth_headers, *, content="Segredo original"):
    author, recipient = create_user(), create_user()
    conversation = _create_conversation(db_session, author["id"], recipient["id"])
    response = client.post(
        f"/conversations/{conversation.id}/messages",
        json={"content": content},
        headers=auth_headers(author),
    )
    assert response.status_code == 201, response.text
    return author, recipient, conversation.id, response.json()


def test_author_can_delete_old_message_and_publishes_one_deleted_event(
    client, db_session, create_user, auth_headers
):
    author, _, conversation_id, sent = _send_message(
        client, db_session, create_user, auth_headers
    )
    message = db_session.get(Message, sent["id"])
    message.created_at = datetime.now(timezone.utc) - timedelta(days=30)
    db_session.commit()

    response = client.delete(
        f"/conversations/{conversation_id}/messages/{sent['id']}",
        headers=auth_headers(author),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["message"]["content"] == PLACEHOLDER
    assert payload["message"]["is_deleted_for_everyone"] is True
    assert payload["message"]["sender_id"] == author["id"]
    assert payload["message_state_revision"] == 1
    stored = db_session.get(Message, sent["id"])
    assert stored.content == "Segredo original"
    assert stored.deleted_for_everyone_by_id == author["id"]
    assert stored.deleted_for_everyone_at is not None
    assert db_session.get(Conversation, conversation_id).messages_revision == 1
    events = db_session.scalars(
        select(MessageUpdateEvent).where(
            MessageUpdateEvent.conversation_id == conversation_id
        )
    ).all()
    assert [(event.revision, event.message_id, event.event_type) for event in events] == [
        (1, sent["id"], "DELETED")
    ]


def test_only_active_author_can_delete_and_authentication_is_required(
    client, db_session, create_user, auth_headers
):
    author, recipient, conversation_id, sent = _send_message(
        client, db_session, create_user, auth_headers
    )
    path = f"/conversations/{conversation_id}/messages/{sent['id']}"

    assert client.delete(path).status_code == 401
    other_authority = client.delete(path, headers=auth_headers(recipient))
    assert other_authority.status_code == 403
    assert db_session.get(Message, sent["id"]).deleted_for_everyone_at is None

    outsider = create_user()
    outsider_response = client.delete(path, headers=auth_headers(outsider))
    assert outsider_response.status_code == 403
    db_session.add(Block(blocker_id=author["id"], blocked_id=recipient["id"]))
    db_session.commit()
    blocked_response = client.delete(path, headers=auth_headers(author))
    assert blocked_response.status_code == 403
    db_session.delete(
        db_session.scalar(
            select(Block).where(
                Block.blocker_id == author["id"], Block.blocked_id == recipient["id"]
            )
        )
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
    left_response = client.delete(path, headers=auth_headers(author))
    assert left_response.status_code == 403
    assert db_session.get(Message, sent["id"]).deleted_for_everyone_at is None
    assert db_session.get(Conversation, conversation_id).messages_revision == 0


def test_missing_conversation_or_message_returns_not_found(
    client, db_session, create_user, auth_headers
):
    user = create_user()
    headers = auth_headers(user)
    assert client.delete("/conversations/999999/messages/1", headers=headers).status_code == 404
    author, _, conversation_id, _ = _send_message(client, db_session, create_user, auth_headers)
    missing = client.delete(
        f"/conversations/{conversation_id}/messages/999999", headers=auth_headers(author)
    )
    assert missing.status_code == 404


def test_repeated_delete_returns_current_state_without_creating_another_event(
    client, db_session, create_user, auth_headers
):
    author, recipient, conversation_id, sent = _send_message(
        client, db_session, create_user, auth_headers
    )
    path = f"/conversations/{conversation_id}/messages/{sent['id']}"
    headers = auth_headers(author)

    first = client.delete(path, headers=headers)
    repeated = client.delete(path, headers=headers)
    unauthorized_repeat = client.delete(path, headers=auth_headers(recipient))

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json()["message"]["content"] == PLACEHOLDER
    assert repeated.json()["message_state_revision"] == first.json()["message_state_revision"]
    assert unauthorized_repeat.status_code == 403
    assert db_session.get(Conversation, conversation_id).messages_revision == 1
    assert db_session.scalar(
        select(func.count()).select_from(MessageUpdateEvent).where(
            MessageUpdateEvent.conversation_id == conversation_id
        )
    ) == 1


def test_deleted_message_is_masked_in_history_sync_and_event_responses(
    client, db_session, create_user, auth_headers
):
    author, recipient, conversation_id, sent = _send_message(
        client, db_session, create_user, auth_headers, content="PRIVATE_ORIGINAL_SENTINEL"
    )
    assert client.delete(
        f"/conversations/{conversation_id}/messages/{sent['id']}",
        headers=auth_headers(author),
    ).status_code == 200
    recipient_headers = auth_headers(recipient)

    responses = [
        client.get(
            f"/conversations/{conversation_id}/messages", headers=recipient_headers
        ),
        client.get(
            f"/conversations/{conversation_id}/messages/sync", headers=recipient_headers
        ),
        client.get(
            f"/conversations/{conversation_id}/message-updates",
            params={"after_revision": 0},
            headers=recipient_headers,
        ),
    ]
    for response in responses:
        assert response.status_code == 200, response.text
        assert "PRIVATE_ORIGINAL_SENTINEL" not in response.text
        payload = response.json()
        items = payload if isinstance(payload, list) else payload.get("items", [])
        if "message" in (items[0] if items else {}):
            assert items[0]["message"]["content"] == PLACEHOLDER
        else:
            assert items[0]["content"] == PLACEHOLDER
    event_payload = responses[2].json()["items"][0]
    assert event_payload["event_type"] == "DELETED"
    assert event_payload["message"]["is_deleted_for_everyone"] is True


def test_delete_preserves_report_evidence_and_does_not_make_message_editable(
    client, db_session, create_user, auth_headers
):
    author, reporter, conversation_id, sent = _send_message(
        client, db_session, create_user, auth_headers, content="Evidence snapshot original"
    )
    report = client.post(
        "/reports",
        json={"message_id": sent["id"], "reason": "Registro para teste"},
        headers=auth_headers(reporter),
    )
    assert report.status_code == 201, report.text
    evidence = db_session.scalar(
        select(ModerationReportEvidence).where(
            ModerationReportEvidence.message_id == sent["id"]
        )
    )
    snapshot_before = (
        evidence.content_snapshot,
        evidence.message_author_id,
        evidence.message_created_at,
        evidence.message_updated_at,
        evidence.message_edited_at,
    )

    deleted = client.delete(
        f"/conversations/{conversation_id}/messages/{sent['id']}",
        headers=auth_headers(author),
    )
    edit = client.patch(
        f"/conversations/{conversation_id}/messages/{sent['id']}",
        json={"content": "Editar depois de excluir"},
        headers=auth_headers(author),
    )

    assert deleted.status_code == 200
    assert edit.status_code == 409
    db_session.refresh(evidence)
    assert (
        evidence.content_snapshot,
        evidence.message_author_id,
        evidence.message_created_at,
        evidence.message_updated_at,
        evidence.message_edited_at,
    ) == snapshot_before
    assert snapshot_before[0] == "Evidence snapshot original"
    assert db_session.scalar(
        select(func.count()).select_from(MessageEditHistory).where(
            MessageEditHistory.message_id == sent["id"]
        )
    ) == 0
    assert db_session.get(Conversation, conversation_id).messages_revision == 1


class _CommitGateSession(Session):
    def commit(self) -> None:
        gate = self.info.pop("commit_gate", None)
        if gate is not None:
            reached, allow = gate
            reached.set()
            if not allow.wait(timeout=20):
                raise TimeoutError("O teste não liberou o commit da operação A.")
        super().commit()


class _RefreshGateSession(Session):
    def refresh(self, instance, attribute_names=None, with_for_update=None) -> None:
        if isinstance(instance, Message):
            published, allow = self.info.pop("refresh_gate")
            self.info["refreshed_message_id"] = instance.id
            published.set()
            if not allow.wait(timeout=20):
                raise TimeoutError("O teste não liberou a leitura pós-commit.")
        super().refresh(instance, attribute_names, with_for_update)


def _persistent_context() -> tuple[int, int, int, int]:
    suffix = uuid4().hex[:10]
    with Session(test_engine) as db:
        author = User(
            username=f"del_a_{suffix}",
            email=f"del_a_{suffix}@example.test",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        recipient = User(
            username=f"del_b_{suffix}",
            email=f"del_b_{suffix}@example.test",
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
            content="Concurrent original",
        )
        db.add(message)
        db.commit()
        return author.id, recipient.id, conversation.id, message.id


def _cleanup_persistent_context(context: tuple[int, int, int, int]) -> None:
    author_id, recipient_id, conversation_id, message_id = context
    with Session(test_engine) as db:
        db.execute(delete(Block).where(or_(
            Block.blocker_id.in_([author_id, recipient_id]),
            Block.blocked_id.in_([author_id, recipient_id]),
        )))
        db.execute(delete(MessageEditHistory).where(MessageEditHistory.conversation_id == conversation_id))
        db.execute(delete(MessageUpdateEvent).where(MessageUpdateEvent.conversation_id == conversation_id))
        db.execute(delete(Message).where(Message.conversation_id == conversation_id))
        db.execute(delete(ConversationParticipant).where(ConversationParticipant.conversation_id == conversation_id))
        db.execute(delete(Conversation).where(Conversation.id == conversation_id))
        db.execute(delete(User).where(User.id.in_([author_id, recipient_id])))
        db.commit()


def _wait_for_lock_wait(
    backend_pid: int,
    finished: Event,
    statement_fragment: str = "FOR UPDATE",
) -> bool:
    deadline = monotonic() + 10
    while monotonic() < deadline and not finished.is_set():
        with Session(test_engine) as observer:
            activity = observer.execute(
                text("SELECT wait_event_type, query FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": backend_pid},
            ).one_or_none()
        if (
            activity is not None
            and activity.wait_event_type == "Lock"
            and statement_fragment in activity.query.upper()
        ):
            return True
        finished.wait(0.01)
    return False


@pytest.mark.parametrize(
    ("first_operation", "second_operation", "second_succeeds"),
    [("delete", "delete", True), ("edit", "delete", True), ("delete", "edit", False)],
)
def test_delete_serializes_with_concurrent_delete_and_edit(
    first_operation, second_operation, second_succeeds
):
    context = _persistent_context()
    author_id, _, conversation_id, message_id = context
    first_reached, allow_first = Event(), Event()
    second_ready, second_finished = Event(), Event()
    second_pid: list[int] = []
    results: dict[str, dict] = {}
    errors: dict[str, BaseException] = {}

    def invoke(db: Session, operation: str):
        actor = db.get(User, author_id)
        if operation == "delete":
            return delete_message_for_everyone(db, actor, conversation_id, message_id)
        return edit_message(db, actor, conversation_id, message_id, "Concurrent edit")

    def run_first() -> None:
        try:
            with _CommitGateSession(test_engine, expire_on_commit=False) as db:
                db.info["commit_gate"] = (first_reached, allow_first)
                results["first"] = invoke(db, first_operation)
        except BaseException as error:
            errors["first"] = error

    def run_second() -> None:
        try:
            with Session(test_engine, expire_on_commit=False) as db:
                db.execute(
                    text("SELECT set_config('application_name', :name, false)"),
                    {"name": f"safetalk-delete-test-{uuid4().hex}"},
                )
                second_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
                second_ready.set()
                results["second"] = invoke(db, second_operation)
        except BaseException as error:
            errors["second"] = error
        finally:
            second_finished.set()

    thread_first, thread_second = Thread(target=run_first), Thread(target=run_second)
    try:
        thread_first.start()
        assert first_reached.wait(timeout=10), "A primeira operação não chegou ao commit."
        thread_second.start()
        assert second_ready.wait(timeout=10), "A segunda sessão PostgreSQL não iniciou."
        assert _wait_for_lock_wait(second_pid[0], second_finished), (
            "O PostgreSQL não reportou a segunda operação aguardando FOR UPDATE."
        )
        assert not second_finished.is_set()
        allow_first.set()
        thread_first.join(timeout=15)
        thread_second.join(timeout=15)
        assert not thread_first.is_alive() and not thread_second.is_alive()
        assert "first" not in errors
        if second_succeeds:
            assert "second" not in errors
        else:
            assert isinstance(errors.get("second"), HTTPException)
            assert errors["second"].status_code == 409

        with Session(test_engine) as verify:
            message = verify.get(Message, message_id)
            events = verify.scalars(
                select(MessageUpdateEvent)
                .where(MessageUpdateEvent.conversation_id == conversation_id)
                .order_by(MessageUpdateEvent.revision)
            ).all()
            if first_operation == "edit":
                assert message.deleted_for_everyone_at is not None
                assert message.content == "Concurrent edit"
                assert [event.event_type for event in events] == ["UPDATED", "DELETED"]
                assert [event.revision for event in events] == [1, 2]
                history = verify.scalars(
                    select(MessageEditHistory).where(MessageEditHistory.message_id == message_id)
                ).all()
                assert len(history) == 1
            else:
                assert message.deleted_for_everyone_at is not None
                assert [event.event_type for event in events] == ["DELETED"]
                assert [event.revision for event in events] == [1]
                assert verify.scalar(
                    select(func.count()).select_from(MessageEditHistory).where(
                        MessageEditHistory.message_id == message_id
                    )
                ) == 0
    finally:
        allow_first.set()
        thread_first.join(timeout=20)
        thread_second.join(timeout=20)
        _cleanup_persistent_context(context)


def test_post_response_refresh_reflects_concurrent_delete_after_send_commit():
    context = _persistent_context()
    author_id, _, conversation_id, _ = context
    refresh_reached, allow_refresh = Event(), Event()
    send_result: dict[str, dict] = {}
    send_error: dict[str, BaseException] = {}

    def send_in_independent_session() -> None:
        try:
            with _RefreshGateSession(test_engine, expire_on_commit=False) as db:
                db.info["refresh_gate"] = (refresh_reached, allow_refresh)
                actor = db.get(User, author_id)
                send_result["message"] = send_message(
                    db, actor, conversation_id, "Mensagem concorrente"
                )
        except BaseException as error:
            send_error["send"] = error

    thread = Thread(target=send_in_independent_session)
    try:
        thread.start()
        assert refresh_reached.wait(timeout=10), "O envio não chegou à leitura pós-commit."
        # The gate is reached only after send_message committed; the marker
        # therefore identifies a committed row without depending on a sequence.
        with Session(test_engine) as observer:
            sent_id = observer.scalar(
                select(Message.id).where(
                    Message.conversation_id == conversation_id,
                    Message.content == "Mensagem concorrente",
                )
            )
        assert sent_id is not None

        with Session(test_engine, expire_on_commit=False) as deleting:
            actor = deleting.get(User, author_id)
            delete_message_for_everyone(deleting, actor, conversation_id, sent_id)

        allow_refresh.set()
        thread.join(timeout=15)
        assert not thread.is_alive()
        assert "send" not in send_error
        response_message = send_result["message"]
        assert response_message["id"] == sent_id
        assert response_message["content"] == PLACEHOLDER
        assert response_message["is_deleted_for_everyone"] is True
    finally:
        allow_refresh.set()
        thread.join(timeout=20)
        _cleanup_persistent_context(context)


def test_block_waits_for_in_flight_message_mutation_using_user_lock_order():
    context = _persistent_context()
    author_id, recipient_id, conversation_id, message_id = context
    delete_reached, allow_delete_commit = Event(), Event()
    block_ready, block_finished = Event(), Event()
    block_pid: list[int] = []
    errors: dict[str, BaseException] = {}
    results: dict[str, object] = {}

    def run_delete() -> None:
        try:
            with _CommitGateSession(test_engine, expire_on_commit=False) as db:
                db.info["commit_gate"] = (delete_reached, allow_delete_commit)
                actor = db.get(User, author_id)
                results["delete"] = delete_message_for_everyone(
                    db, actor, conversation_id, message_id
                )
        except BaseException as error:
            errors["delete"] = error

    def run_block() -> None:
        try:
            with Session(test_engine) as db:
                db.execute(text("SELECT set_config('application_name', :name, false)"),
                           {"name": f"safetalk-block-test-{uuid4().hex}"})
                block_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
                block_ready.set()
                block_user(db, author_id, recipient_id)
        except BaseException as error:
            errors["block"] = error
        finally:
            block_finished.set()

    first, second = Thread(target=run_delete), Thread(target=run_block)
    try:
        first.start()
        assert delete_reached.wait(timeout=10), "A exclusão não chegou ao commit."
        second.start()
        assert block_ready.wait(timeout=10), "A sessão do bloqueio não iniciou."
        assert _wait_for_lock_wait(block_pid[0], block_finished, "FOR UPDATE")
        assert not block_finished.is_set()
        allow_delete_commit.set()
        first.join(timeout=15)
        second.join(timeout=15)
        assert not first.is_alive() and not second.is_alive()
        assert not errors
        assert results["delete"]["message_state_revision"] == 1
        with Session(test_engine) as verify:
            assert verify.get(Message, message_id).deleted_for_everyone_at is not None
            assert verify.scalar(select(Block.id).where(
                Block.blocker_id == author_id, Block.blocked_id == recipient_id
            )) is not None
    finally:
        allow_delete_commit.set()
        first.join(timeout=20)
        second.join(timeout=20)
        _cleanup_persistent_context(context)


def test_existing_block_serializes_before_message_operation_and_read():
    context = _persistent_context()
    author_id, recipient_id, conversation_id, message_id = context
    block_reached, allow_block_commit = Event(), Event()
    delete_ready, delete_finished = Event(), Event()
    delete_pid: list[int] = []
    errors: dict[str, BaseException] = {}

    def run_block() -> None:
        try:
            with _CommitGateSession(test_engine, expire_on_commit=False) as db:
                db.info["commit_gate"] = (block_reached, allow_block_commit)
                block_user(db, author_id, recipient_id)
        except BaseException as error:
            errors["block"] = error

    def run_delete() -> None:
        try:
            with Session(test_engine) as db:
                db.execute(text("SELECT set_config('application_name', :name, false)"),
                           {"name": f"safetalk-msg-block-wait-{uuid4().hex}"})
                delete_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
                delete_ready.set()
                actor = db.get(User, author_id)
                delete_message_for_everyone(db, actor, conversation_id, message_id)
        except BaseException as error:
            errors["delete"] = error
        finally:
            delete_finished.set()

    first, second = Thread(target=run_block), Thread(target=run_delete)
    try:
        first.start()
        assert block_reached.wait(timeout=10), "O bloqueio não chegou ao commit."
        second.start()
        assert delete_ready.wait(timeout=10), "A sessão de exclusão não iniciou."
        assert _wait_for_lock_wait(delete_pid[0], delete_finished, "FOR KEY SHARE")
        assert not delete_finished.is_set()
        allow_block_commit.set()
        first.join(timeout=15)
        second.join(timeout=15)
        assert not first.is_alive() and not second.is_alive()
        assert "block" not in errors
        assert isinstance(errors.get("delete"), HTTPException)
        assert errors["delete"].status_code == 403

        with Session(test_engine) as verify:
            assert verify.get(Message, message_id).deleted_for_everyone_at is None
            assert verify.get(Conversation, conversation_id).messages_revision == 0
            assert verify.scalar(select(func.count()).select_from(MessageUpdateEvent).where(
                MessageUpdateEvent.conversation_id == conversation_id
            )) == 0

        with Session(test_engine) as blocked_reader:
            actor = blocked_reader.get(User, author_id)
            with pytest.raises(HTTPException) as error:
                list_messages(blocked_reader, actor, conversation_id)
            assert error.value.status_code == 403
    finally:
        allow_block_commit.set()
        first.join(timeout=20)
        second.join(timeout=20)
        _cleanup_persistent_context(context)


def test_block_waits_until_an_in_flight_history_read_finishes():
    context = _persistent_context()
    author_id, recipient_id, conversation_id, _ = context
    read_complete, allow_read_session_close = Event(), Event()
    block_ready, block_finished = Event(), Event()
    block_pid: list[int] = []
    errors: dict[str, BaseException] = {}
    read_result: dict[str, list[dict]] = {}

    def run_read() -> None:
        try:
            with Session(test_engine) as db:
                actor = db.get(User, author_id)
                read_result["items"] = list_messages(db, actor, conversation_id)
                read_complete.set()
                if not allow_read_session_close.wait(timeout=20):
                    raise TimeoutError("O teste não liberou o encerramento da leitura.")
        except BaseException as error:
            errors["read"] = error

    def run_block() -> None:
        try:
            with Session(test_engine) as db:
                db.execute(text("SELECT set_config('application_name', :name, false)"),
                           {"name": f"safetalk-read-block-test-{uuid4().hex}"})
                block_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
                block_ready.set()
                block_user(db, author_id, recipient_id)
        except BaseException as error:
            errors["block"] = error
        finally:
            block_finished.set()

    reader, blocker = Thread(target=run_read), Thread(target=run_block)
    try:
        reader.start()
        assert read_complete.wait(timeout=10), "A consulta do histórico não terminou."
        blocker.start()
        assert block_ready.wait(timeout=10), "A sessão do bloqueio não iniciou."
        assert _wait_for_lock_wait(block_pid[0], block_finished, "FOR UPDATE")
        assert not block_finished.is_set()
        allow_read_session_close.set()
        reader.join(timeout=15)
        blocker.join(timeout=15)
        assert not reader.is_alive() and not blocker.is_alive()
        assert not errors
        assert len(read_result["items"]) == 1
        with Session(test_engine) as verify:
            assert verify.scalar(select(Block.id).where(
                Block.blocker_id == author_id, Block.blocked_id == recipient_id
            )) is not None
    finally:
        allow_read_session_close.set()
        reader.join(timeout=20)
        blocker.join(timeout=20)
        _cleanup_persistent_context(context)


def test_block_waits_for_in_flight_send_then_rejects_later_send():
    context = _persistent_context()
    author_id, recipient_id, conversation_id, _ = context
    send_reached, allow_send_commit = Event(), Event()
    block_ready, block_finished = Event(), Event()
    block_pid: list[int] = []
    errors: dict[str, BaseException] = {}
    send_result: dict[str, dict] = {}

    def run_send() -> None:
        try:
            with _CommitGateSession(test_engine, expire_on_commit=False) as db:
                db.info["commit_gate"] = (send_reached, allow_send_commit)
                actor = db.get(User, author_id)
                send_result["message"] = send_message(
                    db, actor, conversation_id, "Mensagem enviada antes do bloqueio"
                )
        except BaseException as error:
            errors["send"] = error

    def run_block() -> None:
        try:
            with Session(test_engine) as db:
                db.execute(
                    text("SELECT set_config('application_name', :name, false)"),
                    {"name": f"safetalk-send-block-test-{uuid4().hex}"},
                )
                block_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
                block_ready.set()
                block_user(db, author_id, recipient_id)
        except BaseException as error:
            errors["block"] = error
        finally:
            block_finished.set()

    sender, blocker = Thread(target=run_send), Thread(target=run_block)
    try:
        sender.start()
        assert send_reached.wait(timeout=10), "O envio não chegou ao commit com os locks mantidos."
        blocker.start()
        assert block_ready.wait(timeout=10), "A sessão de bloqueio não iniciou."
        assert _wait_for_lock_wait(block_pid[0], block_finished, "FOR UPDATE"), (
            "O bloqueio não aguardou os locks compartilhados dos usuários."
        )
        assert not block_finished.is_set(), "O bloqueio concluiu antes do commit do envio."

        allow_send_commit.set()
        sender.join(timeout=15)
        blocker.join(timeout=15)
        assert not sender.is_alive() and not blocker.is_alive(), "Operações concorrentes não terminaram."
        assert not errors, f"Falha nas operações concorrentes: {errors}"
        assert send_result["message"]["content"] == "Mensagem enviada antes do bloqueio"

        with Session(test_engine) as verify:
            assert verify.scalar(select(Block.id).where(
                Block.blocker_id == author_id, Block.blocked_id == recipient_id
            )) is not None
            assert verify.scalar(select(func.count()).select_from(Message).where(
                Message.conversation_id == conversation_id
            )) == 2

        with Session(test_engine) as retry:
            actor = retry.get(User, author_id)
            with pytest.raises(HTTPException) as error:
                send_message(retry, actor, conversation_id, "Envio após bloqueio")
            assert error.value.status_code == 403
        with Session(test_engine) as verify:
            assert verify.scalar(select(func.count()).select_from(Message).where(
                Message.conversation_id == conversation_id
            )) == 2
    finally:
        allow_send_commit.set()
        sender.join(timeout=20)
        blocker.join(timeout=20)
        _cleanup_persistent_context(context)


def test_block_waits_for_in_flight_poll_then_later_poll_is_rejected():
    context = _persistent_context()
    author_id, recipient_id, conversation_id, _ = context
    poll_complete, allow_poll_session_close = Event(), Event()
    block_ready, block_finished = Event(), Event()
    block_pid: list[int] = []
    errors: dict[str, BaseException] = {}
    poll_result: dict[str, dict] = {}

    def run_poll() -> None:
        try:
            with Session(test_engine) as db:
                actor = db.get(User, author_id)
                poll_result["page"] = list_message_update_events(
                    db, actor, conversation_id, after_revision=0
                )
                poll_complete.set()
                if not allow_poll_session_close.wait(timeout=20):
                    raise TimeoutError("O teste não liberou o encerramento da consulta de polling.")
        except BaseException as error:
            errors["poll"] = error

    def run_block() -> None:
        try:
            with Session(test_engine) as db:
                db.execute(
                    text("SELECT set_config('application_name', :name, false)"),
                    {"name": f"safetalk-poll-block-test-{uuid4().hex}"},
                )
                block_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
                block_ready.set()
                block_user(db, author_id, recipient_id)
        except BaseException as error:
            errors["block"] = error
        finally:
            block_finished.set()

    poller, blocker = Thread(target=run_poll), Thread(target=run_block)
    try:
        poller.start()
        assert poll_complete.wait(timeout=10), "A consulta de polling não terminou."
        assert poll_result["page"]["updates_revision"] == 0
        blocker.start()
        assert block_ready.wait(timeout=10), "A sessão de bloqueio não iniciou."
        assert _wait_for_lock_wait(block_pid[0], block_finished, "FOR UPDATE"), (
            "O bloqueio não aguardou os locks compartilhados da consulta de polling."
        )
        assert not block_finished.is_set(), "O bloqueio concluiu antes do encerramento do polling."

        allow_poll_session_close.set()
        poller.join(timeout=15)
        blocker.join(timeout=15)
        assert not poller.is_alive() and not blocker.is_alive(), "Operações concorrentes não terminaram."
        assert not errors, f"Falha nas operações concorrentes: {errors}"

        with Session(test_engine) as verify:
            assert verify.scalar(select(Block.id).where(
                Block.blocker_id == author_id, Block.blocked_id == recipient_id
            )) is not None
        with Session(test_engine) as later_poll:
            actor = later_poll.get(User, author_id)
            with pytest.raises(HTTPException) as error:
                list_message_update_events(later_poll, actor, conversation_id, after_revision=0)
            assert error.value.status_code == 403
    finally:
        allow_poll_session_close.set()
        poller.join(timeout=20)
        blocker.join(timeout=20)
        _cleanup_persistent_context(context)

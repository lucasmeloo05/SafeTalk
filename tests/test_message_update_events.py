from datetime import datetime, timezone

from sqlalchemy import func, select

from app.models import (
    Block,
    Conversation,
    ConversationParticipant,
    Friendship,
    Message,
    MessageUpdateEvent,
)
from app.services.message_service import lock_conversation_for_message_update, record_message_update_event


def _conversation(db, first_id, second_id):
    low, high = sorted((first_id, second_id))
    db.add(Friendship(user_a_id=low, user_b_id=high, requested_by_id=low, status="ACCEPTED"))
    db.flush()
    conversation = Conversation(type="DIRECT", user_a_id=low, user_b_id=high, created_by=low)
    db.add(conversation)
    db.flush()
    db.add_all([
        ConversationParticipant(conversation_id=conversation.id, user_id=low, status="ACTIVE"),
        ConversationParticipant(conversation_id=conversation.id, user_id=high, status="ACTIVE"),
    ])
    return conversation


def test_message_update_events_are_paged_and_return_current_message_state(client, db_session, create_user, auth_headers):
    author = create_user()
    reader = create_user()
    conversation = _conversation(db_session, author["id"], reader["id"])
    message = Message(conversation_id=conversation.id, sender_id=author["id"], content="old", created_at=datetime.now(timezone.utc))
    db_session.add(message)
    db_session.flush()
    locked = lock_conversation_for_message_update(db_session, conversation.id)
    first_revision = record_message_update_event(db_session, locked, message, "UPDATED")
    message.content = "new"
    db_session.commit()

    response = client.get(
        f"/conversations/{conversation.id}/message-updates",
        params={"after_revision": 0, "limit": 1},
        headers=auth_headers(reader),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["updates_revision"] == first_revision
    assert payload["next_cursor"] == first_revision
    assert payload["has_more"] is False
    assert payload["items"][0]["event_revision"] == first_revision
    assert payload["items"][0]["message_state_revision"] == first_revision
    assert payload["items"][0]["message"]["content"] == "new"


def test_event_pagination_uses_last_delivered_revision_until_page_is_complete(
    client, db_session, create_user, auth_headers
):
    author, reader = create_user(), create_user()
    conversation = _conversation(db_session, author["id"], reader["id"])
    message = Message(conversation_id=conversation.id, sender_id=author["id"], content="v0")
    db_session.add(message)
    db_session.flush()
    locked = lock_conversation_for_message_update(db_session, conversation.id)
    revisions = []
    for content in ("v1", "v2", "v3"):
        message.content = content
        revisions.append(record_message_update_event(db_session, locked, message, "UPDATED"))
    db_session.commit()

    first = client.get(
        f"/conversations/{conversation.id}/message-updates",
        params={"after_revision": 0, "limit": 1},
        headers=auth_headers(reader),
    )
    assert first.status_code == 200, first.text
    first_page = first.json()
    assert first_page["has_more"] is True
    assert first_page["updates_revision"] == revisions[-1]
    assert first_page["items"][0]["event_revision"] == revisions[0]
    assert first_page["items"][0]["message_state_revision"] == revisions[-1]
    assert first_page["items"][0]["message"]["content"] == "v3"
    assert first_page["next_cursor"] == revisions[0]

    second = client.get(
        f"/conversations/{conversation.id}/message-updates",
        params={"after_revision": first_page["next_cursor"], "limit": 1},
        headers=auth_headers(reader),
    )
    assert second.status_code == 200, second.text
    second_page = second.json()
    assert second_page["has_more"] is True
    assert second_page["items"][0]["event_revision"] == revisions[1]
    assert second_page["next_cursor"] == revisions[1]

    third = client.get(
        f"/conversations/{conversation.id}/message-updates",
        params={"after_revision": second_page["next_cursor"], "limit": 1},
        headers=auth_headers(reader),
    )
    assert third.status_code == 200, third.text
    third_page = third.json()
    assert third_page["has_more"] is False
    assert third_page["items"][0]["event_revision"] == revisions[2]
    assert third_page["next_cursor"] == third_page["updates_revision"] == revisions[-1]


def test_event_page_returns_only_events_for_requested_conversation(
    client, db_session, create_user, auth_headers
):
    author_a, reader_a = create_user(), create_user()
    author_b, reader_b = create_user(), create_user()
    conversation_a = _conversation(db_session, author_a["id"], reader_a["id"])
    conversation_b = _conversation(db_session, author_b["id"], reader_b["id"])
    message_a = Message(conversation_id=conversation_a.id, sender_id=author_a["id"], content="a")
    message_b = Message(conversation_id=conversation_b.id, sender_id=author_b["id"], content="b")
    db_session.add_all([message_a, message_b])
    db_session.flush()
    record_message_update_event(
        db_session,
        lock_conversation_for_message_update(db_session, conversation_a.id),
        message_a,
        "UPDATED",
    )
    record_message_update_event(
        db_session,
        lock_conversation_for_message_update(db_session, conversation_b.id),
        message_b,
        "UPDATED",
    )
    db_session.commit()

    response = client.get(
        f"/conversations/{conversation_a.id}/message-updates",
        headers=auth_headers(reader_a),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["message"]["conversation_id"] == conversation_a.id
    assert payload["items"][0]["message"]["content"] == "a"
    assert payload["updates_revision"] == payload["next_cursor"] == 1


def test_event_cursor_ahead_of_watermark_is_rejected(
    client, db_session, create_user, auth_headers
):
    first, second = create_user(), create_user()
    conversation = _conversation(db_session, first["id"], second["id"])
    db_session.commit()

    response = client.get(
        f"/conversations/{conversation.id}/message-updates",
        params={"after_revision": 1},
        headers=auth_headers(second),
    )
    assert response.status_code == 422


def test_event_endpoint_rejects_blocked_and_left_participants(
    client, db_session, create_user, auth_headers
):
    first, second = create_user(), create_user()
    conversation = _conversation(db_session, first["id"], second["id"])
    db_session.add(Block(blocker_id=first["id"], blocked_id=second["id"]))
    db_session.commit()

    blocked_response = client.get(
        f"/conversations/{conversation.id}/message-updates",
        headers=auth_headers(second),
    )
    assert blocked_response.status_code == 403

    block = db_session.scalar(
        select(Block).where(Block.blocker_id == first["id"], Block.blocked_id == second["id"])
    )
    db_session.delete(block)
    participant = db_session.scalar(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation.id,
            ConversationParticipant.user_id == second["id"],
        )
    )
    participant.status = "LEFT"
    participant.left_at = datetime.now(timezone.utc)
    db_session.commit()

    left_response = client.get(
        f"/conversations/{conversation.id}/message-updates",
        headers=auth_headers(second),
    )
    assert left_response.status_code == 403


def test_rollback_removes_event_and_restores_conversation_revision(
    db_session, create_user
):
    author, reader = create_user(), create_user()
    conversation = _conversation(db_session, author["id"], reader["id"])
    message = Message(conversation_id=conversation.id, sender_id=author["id"], content="original")
    db_session.add(message)
    db_session.commit()
    conversation_id, message_id = conversation.id, message.id

    nested = db_session.begin_nested()
    locked = lock_conversation_for_message_update(db_session, conversation_id)
    message = db_session.get(Message, message_id)
    message.content = "transitória"
    record_message_update_event(db_session, locked, message, "UPDATED")
    db_session.flush()
    nested.rollback()
    db_session.expire_all()

    assert db_session.get(Conversation, conversation_id).messages_revision == 0
    assert db_session.scalar(
        select(func.count()).select_from(MessageUpdateEvent).where(
            MessageUpdateEvent.conversation_id == conversation_id
        )
    ) == 0
    assert db_session.get(Message, message_id).content == "original"


def test_latest_history_returns_revision_in_same_response(client, db_session, create_user, auth_headers):
    author = create_user()
    reader = create_user()
    conversation = _conversation(db_session, author["id"], reader["id"])
    message = Message(conversation_id=conversation.id, sender_id=author["id"], content="history")
    db_session.add(message)
    db_session.flush()
    record_message_update_event(
        db_session,
        lock_conversation_for_message_update(db_session, conversation.id),
        message,
        "UPDATED",
    )
    db_session.commit()
    response = client.get(
        f"/conversations/{conversation.id}/messages/sync", headers=auth_headers(reader)
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["content"] == "history"
    assert response.json()["updates_revision"] == 1


def test_message_update_events_enforce_active_participation(client, db_session, create_user, auth_headers):
    first = create_user()
    second = create_user()
    conversation = _conversation(db_session, first["id"], second["id"])
    outsider = create_user()
    response = client.get(
        f"/conversations/{conversation.id}/message-updates", headers=auth_headers(outsider)
    )
    assert response.status_code == 403


def test_update_event_model_is_registered():
    assert MessageUpdateEvent.__tablename__ == "message_update_events"

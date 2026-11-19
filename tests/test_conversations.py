from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import (
    Block,
    Conversation,
    ConversationParticipant,
    Friendship,
    UserPrivacySettings,
)


def _direct_conversation(client: TestClient, headers: dict, recipient_id: int):
    return client.post(
        "/conversations/direct",
        json={"recipient_id": recipient_id},
        headers=headers,
    )


def _accept_friendship(db_session, first_user_id: int, second_user_id: int) -> None:
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


def test_creates_and_recovers_same_direct_conversation(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    _accept_friendship(db_session, sender["id"], recipient["id"])
    headers = auth_headers(sender)

    first = _direct_conversation(client, headers, recipient["id"])
    second = _direct_conversation(client, headers, recipient["id"])

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["type"] == "DIRECT"


def test_rejects_direct_conversation_with_self(
    client: TestClient,
    create_user,
    auth_headers,
):
    user = create_user()

    response = _direct_conversation(
        client,
        auth_headers(user),
        user["id"],
    )

    assert response.status_code == 400


def test_non_friend_needs_recipient_privacy_permission(
    client: TestClient,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()

    response = _direct_conversation(
        client,
        auth_headers(sender),
        recipient["id"],
    )

    assert response.status_code == 403


def test_non_friend_can_start_conversation_when_recipient_allows_strangers(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    settings = db_session.get(UserPrivacySettings, recipient["id"])
    settings.allow_messages_from_strangers = True
    db_session.flush()

    response = _direct_conversation(
        client,
        auth_headers(sender),
        recipient["id"],
    )

    assert response.status_code == 200
    assert response.json()["user_a_id"] == min(sender["id"], recipient["id"])
    assert response.json()["user_b_id"] == max(sender["id"], recipient["id"])


def test_accepted_friends_can_start_conversation_when_strangers_are_disabled(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    _accept_friendship(db_session, sender["id"], recipient["id"])

    response = _direct_conversation(
        client,
        auth_headers(sender),
        recipient["id"],
    )

    assert response.status_code == 200


@pytest.mark.parametrize("blocker_is_sender", [True, False])
def test_block_in_either_direction_prevents_starting_conversation(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
    blocker_is_sender: bool,
):
    sender = create_user()
    recipient = create_user()
    blocker_id, blocked_id = (
        (sender["id"], recipient["id"])
        if blocker_is_sender
        else (recipient["id"], sender["id"])
    )
    db_session.add(Block(blocker_id=blocker_id, blocked_id=blocked_id))
    db_session.flush()

    response = _direct_conversation(
        client,
        auth_headers(sender),
        recipient["id"],
    )

    assert response.status_code == 403


def test_block_prevents_new_message_in_existing_conversation(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    _accept_friendship(db_session, sender["id"], recipient["id"])
    sender_headers = auth_headers(sender)
    recipient_headers = auth_headers(recipient)
    conversation_id = _direct_conversation(
        client,
        sender_headers,
        recipient["id"],
    ).json()["id"]
    db_session.add(Block(blocker_id=sender["id"], blocked_id=recipient["id"]))
    # Commit the setup savepoint before the requests. Both requests share the
    # fixture Session, and a rejected message operation rolls that Session
    # back; keeping the Block uncommitted would let the first request erase it
    # before the second request runs. The outer fixture transaction still
    # rolls this data back when the test ends.
    db_session.commit()

    responses = [
        client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "Não deve ser enviada após o bloqueio."},
            headers=headers,
        )
        for headers in (sender_headers, recipient_headers)
    ]

    assert [response.status_code for response in responses] == [403, 403]


@pytest.mark.parametrize("blocker_is_sender", [True, False])
def test_block_prevents_reading_existing_direct_message_history(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
    blocker_is_sender: bool,
):
    sender = create_user()
    recipient = create_user()
    _accept_friendship(db_session, sender["id"], recipient["id"])
    sender_headers = auth_headers(sender)
    recipient_headers = auth_headers(recipient)
    conversation_id = _direct_conversation(
        client,
        sender_headers,
        recipient["id"],
    ).json()["id"]
    sent = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "Histórico que deve continuar acessível."},
        headers=sender_headers,
    )
    assert sent.status_code == 201

    blocker_id, blocked_id = (
        (sender["id"], recipient["id"])
        if blocker_is_sender
        else (recipient["id"], sender["id"])
    )
    db_session.add(Block(blocker_id=blocker_id, blocked_id=blocked_id))
    db_session.flush()

    for headers in (sender_headers, recipient_headers):
        read = client.get(
            f"/conversations/{conversation_id}/messages",
            headers=headers,
        )

        assert read.status_code == 403


def test_reusing_direct_conversation_reactivates_left_participant(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    _accept_friendship(db_session, sender["id"], recipient["id"])
    headers = auth_headers(sender)
    created = _direct_conversation(client, headers, recipient["id"])
    conversation_id = created.json()["id"]
    sent = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "Mensagem anterior à saída."},
        headers=headers,
    )
    assert sent.status_code == 201

    sender_participant = db_session.scalar(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == sender["id"],
        )
    )
    recipient_participant = db_session.scalar(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == recipient["id"],
        )
    )
    left_at = datetime.now(timezone.utc)
    sender_participant.status = "LEFT"
    sender_participant.left_at = left_at
    recipient_participant.status = "LEFT"
    recipient_participant.left_at = left_at
    db_session.flush()

    response = _direct_conversation(client, headers, recipient["id"])

    assert response.status_code == 200
    assert response.json()["id"] == conversation_id

    db_session.refresh(sender_participant)
    db_session.refresh(recipient_participant)
    assert sender_participant.status == "ACTIVE"
    assert sender_participant.left_at is None
    assert recipient_participant.status == "LEFT"
    assert recipient_participant.left_at is not None
    assert db_session.scalar(
        select(func.count()).select_from(Conversation).where(
            Conversation.type == "DIRECT",
            Conversation.user_a_id == min(sender["id"], recipient["id"]),
            Conversation.user_b_id == max(sender["id"], recipient["id"]),
        )
    ) == 1
    assert db_session.scalar(
        select(func.count()).select_from(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == sender["id"],
        )
    ) == 1
    assert db_session.scalar(
        select(func.count()).select_from(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == recipient["id"],
        )
    ) == 1

    history = client.get(
        f"/conversations/{conversation_id}/messages",
        headers=headers,
    )
    assert history.status_code == 200
    assert [message["content"] for message in history.json()] == [
        "Mensagem anterior à saída."
    ]


def test_reactivation_still_respects_block_and_privacy(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    settings = db_session.get(UserPrivacySettings, recipient["id"])
    settings.allow_messages_from_strangers = True
    db_session.flush()
    headers = auth_headers(sender)
    conversation_id = _direct_conversation(
        client,
        headers,
        recipient["id"],
    ).json()["id"]
    participant = db_session.scalar(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == sender["id"],
        )
    )
    participant.status = "LEFT"
    participant.left_at = datetime.now(timezone.utc)
    settings.allow_messages_from_strangers = False
    db_session.flush()

    response = _direct_conversation(client, headers, recipient["id"])

    assert response.status_code == 403
    db_session.refresh(participant)
    assert participant.status == "LEFT"


def test_blocked_user_cannot_reactivate_existing_direct_conversation(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    user_a_id, user_b_id = sorted((sender["id"], recipient["id"]))
    db_session.add(
        Friendship(
            user_a_id=user_a_id,
            user_b_id=user_b_id,
            requested_by_id=user_a_id,
            status="ACCEPTED",
        )
    )
    db_session.flush()
    headers = auth_headers(sender)
    conversation_id = _direct_conversation(
        client,
        headers,
        recipient["id"],
    ).json()["id"]
    participant = db_session.scalar(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == sender["id"],
        )
    )
    participant.status = "LEFT"
    participant.left_at = datetime.now(timezone.utc)
    db_session.add(Block(blocker_id=recipient["id"], blocked_id=sender["id"]))
    db_session.flush()

    response = _direct_conversation(client, headers, recipient["id"])

    assert response.status_code == 403
    db_session.refresh(participant)
    assert participant.status == "LEFT"

    history = client.get(
        f"/conversations/{conversation_id}/messages",
        headers=headers,
    )
    assert history.status_code == 403


def test_nonparticipant_cannot_read_or_send_messages(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    sender = create_user()
    recipient = create_user()
    outsider = create_user()
    _accept_friendship(db_session, sender["id"], recipient["id"])
    conversation_id = _direct_conversation(
        client,
        auth_headers(sender),
        recipient["id"],
    ).json()["id"]
    outsider_headers = auth_headers(outsider)

    read = client.get(
        f"/conversations/{conversation_id}/messages",
        headers=outsider_headers,
    )
    send = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "Não deve entrar."},
        headers=outsider_headers,
    )

    assert read.status_code == 403
    assert send.status_code == 403

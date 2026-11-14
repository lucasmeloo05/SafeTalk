from fastapi.testclient import TestClient

from app.models import Friendship


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

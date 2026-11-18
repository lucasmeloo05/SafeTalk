import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Block, Conversation, ConversationParticipant, Friendship, User, UserPrivacySettings
from app.services.conversation_service import create_or_get_direct_conversation
from app.services.social_service import (
    cancel_friend_request,
    create_friend_request,
    update_privacy_settings,
)
from conftest import test_engine


def _persist_concurrent_pair(*, friendship_status=None):
    # Keep User.username under its 30-character column limit while retaining
    # enough random data to avoid collisions between parallel test runs.
    suffix = uuid.uuid4().hex[:12]
    session = Session(test_engine, expire_on_commit=False)
    try:
        first = User(username=f"race_a_{suffix}", email=f"race_a_{suffix}@example.test", password_hash="x")
        second = User(username=f"race_b_{suffix}", email=f"race_b_{suffix}@example.test", password_hash="x")
        session.add_all([first, second])
        session.flush()
        session.add_all([
            UserPrivacySettings(user_id=first.id),
            UserPrivacySettings(user_id=second.id),
        ])
        friendship = None
        if friendship_status is not None:
            low, high = sorted((first.id, second.id))
            friendship = Friendship(
                user_a_id=low,
                user_b_id=high,
                requested_by_id=first.id,
                status=friendship_status,
            )
            session.add(friendship)
        session.commit()
        return first.id, second.id, friendship.id if friendship else None
    finally:
        session.close()


def _wait_for_postgres_lock_wait(application_name: str, timeout: float = 8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with test_engine.connect() as connection:
            state = connection.execute(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE application_name = :name"),
                {"name": application_name},
            ).scalar_one_or_none()
        if state == "Lock":
            return
        time.sleep(0.02)
    pytest.fail(f"A sessão {application_name} não aguardou um lock PostgreSQL.")


def test_privacy_update_serializes_with_concurrent_friend_request():
    actor_id, recipient_id, _ = _persist_concurrent_pair()
    update_entered_commit = threading.Event()
    allow_update_commit = threading.Event()
    request_started = threading.Event()
    request_app = f"social_privacy_race_{uuid.uuid4().hex}"
    outcome = {}

    class CommitGateSession(Session):
        def commit(self):
            update_entered_commit.set()
            if not allow_update_commit.wait(timeout=8):
                raise TimeoutError("A sincronização do teste não liberou o commit.")
            return super().commit()

    def update_privacy():
        session = CommitGateSession(test_engine, expire_on_commit=False)
        try:
            outcome["updated"] = update_privacy_settings(
                session, recipient_id, {"allow_friend_requests": False}
            )
        except Exception as exc:  # Captura falhas da thread para repassá-las ao teste.
            outcome["update_error"] = exc
            session.rollback()
        finally:
            session.close()

    def create_request():
        session = Session(test_engine, expire_on_commit=False)
        try:
            session.connection().exec_driver_sql(
                f"SET application_name = '{request_app}'"
            )
            request_started.set()
            try:
                create_friend_request(session, actor_id, recipient_id)
                outcome["request"] = "created"
            except HTTPException as exc:
                outcome["request"] = exc.status_code
            except Exception as exc:
                outcome["request_error"] = exc
                session.rollback()
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        update_future = pool.submit(update_privacy)
        assert update_entered_commit.wait(timeout=5)
        request_future = pool.submit(create_request)
        assert request_started.wait(timeout=5)
        try:
            _wait_for_postgres_lock_wait(request_app)
        finally:
            allow_update_commit.set()
        update_future.result(timeout=8)
        request_future.result(timeout=8)

    assert "update_error" not in outcome, outcome.get("update_error")
    assert outcome["updated"]["allow_friend_requests"] is False
    assert "request_error" not in outcome, outcome.get("request_error")
    assert outcome["request"] == 404


def test_relationship_mutations_lock_users_before_friendship_without_deadlock():
    actor_id, other_id, friendship_id = _persist_concurrent_pair(friendship_status="PENDING")
    app_name = f"social_relationship_race_{uuid.uuid4().hex}"
    a_waiting = threading.Event()
    outcome = {}

    def cancel_request():
        session = Session(test_engine, expire_on_commit=False)
        try:
            session.connection().exec_driver_sql(f"SET application_name = '{app_name}'")
            a_waiting.set()
            outcome["cancelled"] = cancel_friend_request(session, actor_id, friendship_id)
        except Exception as exc:
            outcome["cancel_error"] = exc
            session.rollback()
        finally:
            session.close()

    blocking_session = Session(test_engine, expire_on_commit=False)
    try:
        blocking_session.scalars(
            select(User)
            .where(User.id.in_(sorted((actor_id, other_id))))
            .order_by(User.id)
            .with_for_update()
        ).all()
        with ThreadPoolExecutor(max_workers=1) as pool:
            cancel_future = pool.submit(cancel_request)
            assert a_waiting.wait(timeout=5)
            _wait_for_postgres_lock_wait(app_name)
            try:
                with pytest.raises(HTTPException) as conflict:
                    create_friend_request(blocking_session, other_id, actor_id)
                assert conflict.value.status_code == 409
            finally:
                blocking_session.rollback()
            cancel_future.result(timeout=8)
    finally:
        blocking_session.close()

    assert "cancel_error" not in outcome, outcome.get("cancel_error")
    assert outcome["cancelled"]["status"] == "CANCELLED"


def test_user_search_ignores_terminal_friendship_states(client, db_session, create_user, auth_headers):
    actor = create_user(username="terminal_search_actor")
    states = [
        ("terminal_cancelled", "CANCELLED"),
        ("terminal_rejected", "REJECTED"),
        ("terminal_removed", "REMOVED"),
    ]
    for index, (username, relation_status) in enumerate(states):
        target = create_user(username=username)
        low, high = sorted((actor["id"], target["id"]))
        db_session.add(Friendship(
            user_a_id=low,
            user_b_id=high,
            requested_by_id=actor["id"],
            status=relation_status,
        ))
    db_session.commit()
    response = client.get("/users/search?query=terminal_", headers=auth_headers(actor))
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == len(states)
    for item in response.json()["items"]:
        assert item["relationship_status"] == "NONE"
        assert item["friendship_id"] is None


def test_search_requires_auth_and_returns_only_public_profile_fields(client, create_user, auth_headers):
    actor = create_user(username="social_actor")
    target = create_user(username="social_target")
    response = client.get("/users/search", params={"query": "social_"})
    assert response.status_code == 401

    response = client.get("/users/search", params={"query": "social_"}, headers=auth_headers(actor))
    assert response.status_code == 200, response.text
    results = response.json()["items"]
    assert {item["username"] for item in results} == {target["username"]}
    assert set(results[0]) == {"id", "username", "relationship_status", "friendship_id"}
    assert results[0]["relationship_status"] == "NONE"


@pytest.mark.parametrize("query", ["", "   ", "  \t  "])
def test_user_search_rejects_empty_or_whitespace_queries(client, create_user, auth_headers, query):
    actor = create_user(username="empty_search_actor")
    response = client.get("/users/search", params={"query": query}, headers=auth_headers(actor))
    assert response.status_code == 422
    assert "ao menos 2 caracteres" in response.json()["detail"]


def test_user_search_trims_before_minimum_length_validation(client, create_user, auth_headers):
    actor = create_user(username="trim_search_actor")
    target = create_user(username="valid_search_target")
    response = client.get(
        "/users/search",
        params={"query": "  valid_search  "},
        headers=auth_headers(actor),
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert [item["username"] for item in response.json()["items"]] == [target["username"]]


def test_user_search_supports_bounded_pagination(client, create_user, auth_headers):
    actor = create_user(username="paged_search_actor")
    names = ["paged_person_a", "paged_person_b", "paged_person_c"]
    for name in names:
        create_user(username=name)

    response = client.get(
        "/users/search",
        params={"query": "paged_person", "limit": 2, "offset": 1},
        headers=auth_headers(actor),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 3
    assert payload["limit"] == 2
    assert payload["offset"] == 1
    assert [item["username"] for item in payload["items"]] == names[1:]


def test_relationship_list_supports_bounded_pagination(client, db_session, create_user, auth_headers):
    actor = create_user(username="paged_relation_actor")
    targets = [create_user(username=f"paged_relation_{letter}") for letter in "abc"]
    for target in targets:
        low, high = sorted((actor["id"], target["id"]))
        db_session.add(Friendship(
            user_a_id=low,
            user_b_id=high,
            requested_by_id=actor["id"],
            status="ACCEPTED",
        ))
    db_session.commit()

    response = client.get(
        "/social/friends",
        params={"limit": 2, "offset": 1},
        headers=auth_headers(actor),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 3
    assert payload["limit"] == 2
    assert payload["offset"] == 1
    assert {item["username"] for item in payload["items"]} == {
        "paged_relation_a",
        "paged_relation_b",
    }


def test_search_excludes_users_blocked_in_either_direction(client, db_session, create_user, auth_headers):
    actor = create_user(username="search_actor")
    blocked_by_actor = create_user(username="blocked_by_actor")
    blocks_actor = create_user(username="blocks_actor")
    visible = create_user(username="visible_person")
    db_session.add_all([
        Block(blocker_id=actor["id"], blocked_id=blocked_by_actor["id"]),
        Block(blocker_id=blocks_actor["id"], blocked_id=actor["id"]),
    ])
    db_session.commit()
    response = client.get("/users/search?query=person", headers=auth_headers(actor))
    assert response.status_code == 200
    assert [item["username"] for item in response.json()["items"]] == [visible["username"]]


def test_friend_request_lifecycle_and_actor_scoping(client, create_user, auth_headers):
    sender = create_user(username="request_sender")
    recipient = create_user(username="request_recipient")
    sent = client.post("/social/requests", json={"recipient_id": recipient["id"]}, headers=auth_headers(sender))
    assert sent.status_code == 201, sent.text
    friendship_id = sent.json()["friendship_id"]
    assert sent.json()["status"] == "PENDING"

    duplicate = client.post("/social/requests", json={"recipient_id": recipient["id"]}, headers=auth_headers(sender))
    assert duplicate.status_code == 409
    self_request = client.post("/social/requests", json={"recipient_id": sender["id"]}, headers=auth_headers(sender))
    assert self_request.status_code == 400

    wrong_actor = create_user(username="third_party")
    assert client.post(f"/social/requests/{friendship_id}/accept", headers=auth_headers(wrong_actor)).status_code == 404
    received = client.get("/social/requests/received", headers=auth_headers(recipient))
    assert received.status_code == 200
    assert received.json()["items"][0]["username"] == sender["username"]
    accepted = client.post(f"/social/requests/{friendship_id}/accept", headers=auth_headers(recipient))
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "ACCEPTED"
    friends = client.get("/social/friends", headers=auth_headers(sender))
    assert friends.status_code == 200
    assert friends.json()["items"][0]["username"] == recipient["username"]
    removed = client.delete(f"/social/friends/{recipient['id']}", headers=auth_headers(sender))
    assert removed.status_code == 200
    assert removed.json()["status"] == "REMOVED"


def test_request_privacy_and_block_are_enforced(client, db_session, create_user, auth_headers):
    actor = create_user(username="privacy_requester")
    recipient = create_user(username="private_requests")
    settings = db_session.get(UserPrivacySettings, recipient["id"])
    settings.allow_friend_requests = False
    db_session.commit()
    response = client.post("/social/requests", json={"recipient_id": recipient["id"]}, headers=auth_headers(actor))
    assert response.status_code == 404

    settings.allow_friend_requests = True
    db_session.add(Block(blocker_id=recipient["id"], blocked_id=actor["id"]))
    db_session.commit()
    response = client.post("/social/requests", json={"recipient_id": recipient["id"]}, headers=auth_headers(actor))
    assert response.status_code == 404


def test_privacy_settings_are_private_and_control_direct_conversation(client, create_user, auth_headers):
    sender = create_user(username="dm_sender")
    recipient = create_user(username="dm_recipient")
    sender_headers = auth_headers(sender)
    recipient_headers = auth_headers(recipient)

    settings = client.get("/users/me/privacy", headers=recipient_headers)
    assert settings.status_code == 200
    assert settings.json() == {"allow_messages_from_strangers": False, "allow_friend_requests": True}
    rejected = client.post("/conversations/direct", json={"recipient_id": recipient["id"]}, headers=sender_headers)
    assert rejected.status_code == 403

    patched = client.patch(
        "/users/me/privacy",
        json={"allow_messages_from_strangers": True},
        headers=recipient_headers,
    )
    assert patched.status_code == 200
    created = client.post("/conversations/direct", json={"recipient_id": recipient["id"]}, headers=sender_headers)
    assert created.status_code == 200, created.text

    invalid = client.patch("/users/me/privacy", json={"allow_friend_requests": 1}, headers=recipient_headers)
    assert invalid.status_code == 422
    empty = client.patch("/users/me/privacy", json={}, headers=recipient_headers)
    assert empty.status_code == 422
    extra = client.patch("/users/me/privacy", json={"user_id": sender["id"]}, headers=recipient_headers)
    assert extra.status_code == 422


def test_accepted_friend_can_start_direct_conversation_when_strangers_disabled(client, create_user, auth_headers):
    first = create_user(username="friend_first")
    second = create_user(username="friend_second")
    request = client.post("/social/requests", json={"recipient_id": second["id"]}, headers=auth_headers(first))
    assert request.status_code == 201
    accepted = client.post(f"/social/requests/{request.json()['friendship_id']}/accept", headers=auth_headers(second))
    assert accepted.status_code == 200
    conversation = client.post("/conversations/direct", json={"recipient_id": second["id"]}, headers=auth_headers(first))
    assert conversation.status_code == 200, conversation.text


def test_request_can_be_cancelled_rejected_and_resent(client, create_user, auth_headers):
    sender = create_user(username="resend_sender")
    recipient = create_user(username="resend_recipient")
    first = client.post("/social/requests", json={"recipient_id": recipient["id"]}, headers=auth_headers(sender))
    assert first.status_code == 201
    rejected = client.post(f"/social/requests/{first.json()['friendship_id']}/reject", headers=auth_headers(recipient))
    assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"
    resent = client.post("/social/requests", json={"recipient_id": recipient["id"]}, headers=auth_headers(sender))
    assert resent.status_code == 201 and resent.json()["status"] == "PENDING"
    cancelled = client.delete(f"/social/requests/{resent.json()['friendship_id']}", headers=auth_headers(sender))
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"


def test_reciprocal_first_direct_conversation_serializes():
    a, b, _ = _persist_concurrent_pair(friendship_status="ACCEPTED")
    start = threading.Barrier(3)
    inserting = threading.Event()
    release = threading.Event()
    pids = {}
    winner = []

    def open_direct(actor, recipient):
        with Session(test_engine) as session:
            session.execute(text("SET LOCAL statement_timeout = '15s'"))
            pids[actor] = session.scalar(text("SELECT pg_backend_pid()"))
            user = session.get(User, actor)

            @event.listens_for(session, "before_flush", once=True)
            def hold_first_insert(*_):
                winner.append(actor)
                inserting.set()
                if not release.wait(10):
                    raise TimeoutError("Inserção não liberada")

            start.wait(10)
            return create_or_get_direct_conversation(session, user, recipient).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(open_direct, a, b), pool.submit(open_direct, b, a)]
        try:
            start.wait(10)
            assert inserting.wait(10)
            first = winner[0]
            second = b if first == a else a
            deadline = time.monotonic() + 8
            with test_engine.connect() as observer:
                while not observer.scalar(text("SELECT :first = ANY(pg_blocking_pids(:second))"),
                                          {"first": pids[first], "second": pids[second]}):
                    if time.monotonic() >= deadline:
                        pytest.fail("A segunda abertura não aguardou a primeira antes da inserção")
                    time.sleep(0.02)
        finally:
            release.set()
        ids = [future.result(timeout=15) for future in futures]
    with Session(test_engine) as session:
        conversations = session.scalars(select(Conversation.id).where(
            Conversation.type == "DIRECT", Conversation.user_a_id == min(a, b),
            Conversation.user_b_id == max(a, b),
        )).all()
        assert conversations == [ids[0]] == [ids[1]]
        assert sorted(session.scalars(select(ConversationParticipant.user_id).where(
            ConversationParticipant.conversation_id == ids[0], ConversationParticipant.status == "ACTIVE",
        ))) == sorted((a, b))

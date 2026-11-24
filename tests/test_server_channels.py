import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from queue import Queue
from threading import Barrier, Event
from time import monotonic

import pytest

from fastapi import HTTPException
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.channel_schemas import ChannelCreate, ChannelUpdate
from app.models import Server, ServerAuditLog, ServerChannel, ServerMember, ServerRole
from app.services.server_channel_service import change_role_access, create_channel, delete_channel, list_authorized_roles, update_channel
from conftest import test_engine
from test_server_member_roles_api import _manager_context, _create_server, _role
from test_server_ownership_transfer import _persistent_concurrent_context, _cleanup_persistent_context


def test_channel_lifecycle_and_access(client, db_session, create_user, auth_headers):
    owner, manager, server, other, _ = _manager_context(client, db_session, create_user, auth_headers)
    db_session.commit()  # Persist fixture memberships before independent HTTP requests.
    sid = server["id"]
    role = db_session.scalar(select(ServerRole.id).where(ServerRole.server_id == sid, ServerRole.position == 10))
    base = f"/servers/{sid}/channels"
    admin, member, outsider = map(auth_headers, (owner, manager, other))
    assert client.get(base).status_code == 401
    assert client.post(base, json={"name": "test"}, headers=member).status_code == 403
    created = client.post(base, json={"name": "Geral"}, headers=admin)
    assert created.status_code == 201
    cid = created.json()["id"]
    url = f"{base}/{cid}"
    assert client.get(url, headers=outsider).status_code == 200
    private = {"is_private": True, "authorized_role_ids": [role]}
    assert client.patch(url, json=private, headers=member).status_code == 403
    assert client.patch(url, json=private, headers={**admin, "X-Expected-Channel-Grants": "[]"}).json()["is_private"]
    assert client.get(url + "/authorized-roles", headers=admin).json() == [role]
    assert client.get(url, headers=member).status_code == 200
    grant_url = f"{url}/roles/{role}"
    assert client.delete(grant_url, headers=member).status_code == 403
    assert client.delete(grant_url, headers=admin).status_code == 204
    assert client.get(url, headers=member).status_code == 404
    assert client.put(grant_url, headers=admin).status_code == 204
    assert client.get(url, headers=member).status_code == 200
    assert client.get(url, headers=outsider).status_code == 404
    assert client.get(base, headers=outsider).json() == []
    assert client.delete(url, headers=member).status_code == 403
    assert client.delete(f"/servers/{sid}/members/{manager['id']}/roles/{role}", headers=admin).status_code == 204
    assert client.get(url, headers=member).status_code == 404
    assert client.delete(f"/servers/{sid}/roles/{role}", headers=admin).status_code == 409
    assert client.patch(url, json={"is_private": False}, headers={**admin, "X-Expected-Channel-Grants": json.dumps([role])}).status_code == 200
    assert client.get(url, headers=member).status_code == 200
    assert client.post(f"/servers/{sid}/leave", headers=member).is_success
    assert client.get(url, headers=member).status_code == 404
    assert client.get(base, headers=member).status_code == 404
    assert client.patch(url, json={"name": "Novo"}, headers=admin).json()["name"] == "Novo"
    assert client.delete(url, headers=admin).status_code == 204
    assert client.get(url, headers=admin).status_code == 404
    logs = client.get(f"/servers/{sid}/audit-logs", headers=admin).json()
    events = {log["event_type"]: log for log in logs if log["channel_id"] == cid}
    assert set(events) == {"CHANNEL_BECAME_PRIVATE", "CHANNEL_BECAME_PUBLIC",
                           "CHANNEL_ROLE_ACCESS_GRANTED", "CHANNEL_ROLE_ACCESS_REVOKED"}
    assert all(log["actor_user_id"] == owner["id"] for log in events.values())
    assert events["CHANNEL_ROLE_ACCESS_REVOKED"]["role_id"] == role


def test_private_channel_cross_server_and_rollback(client, db_session, create_user, auth_headers):
    owner, manager, server, _, _ = _manager_context(client, db_session, create_user, auth_headers)
    second = _create_server(client, manager, auth_headers)
    foreign = _role(db_session, second["id"], name="foreign", position=2)
    admin, member = auth_headers(owner), auth_headers(manager)
    base = f"/servers/{server['id']}/channels"
    channel = client.post(base, headers=admin, json={"name": "private", "is_private": True}).json()
    url = f"{base}/{channel['id']}"
    assert client.get(url, headers=admin).status_code == 200
    assert client.get(url, headers=member).status_code == 404
    assert client.get(f"/servers/{second['id']}/channels/{channel['id']}", headers=member).status_code == 404
    assert client.patch(url, headers={**admin, "X-Expected-Channel-Grants": "[]"}, json={"name": "rollback", "authorized_role_ids": [foreign.id]}).status_code == 404
    assert client.get(url, headers=admin).json()["name"] == "private"
    assert client.post(base, headers=admin, json={"name": "private"}).status_code == 409
    assert client.patch(url, headers=admin, json={"owner_id": manager["id"]}).status_code == 422


def test_independent_concurrent_grants_preserve_both_roles():
    context = _persistent_concurrent_context()
    sid, users = context
    barrier = Barrier(2)
    try:
        with Session(test_engine) as db:
            roles = [_role(db, sid, name=name, position=1).id for name in ("a", "b")]
            cid = create_channel(db, sid, users[0], ChannelCreate(name="private", is_private=True)).id

        def grant(role):
            with Session(test_engine) as db:
                barrier.wait(timeout=10)
                change_role_access(db, sid, cid, users[0], role, grant=True)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(grant, role) for role in roles]
            for future in futures:
                future.result(timeout=20)
        with Session(test_engine) as db:
            assert list_authorized_roles(db, sid, cid, users[0]) == sorted(roles)
    finally:
        with Session(test_engine) as db:
            for channel_id in db.scalars(select(ServerChannel.id).where(ServerChannel.server_id == sid)).all():
                delete_channel(db, sid, channel_id, users[0])
            db.execute(ServerRole.__table__.delete().where(ServerRole.server_id == sid))
            db.commit()
        _cleanup_persistent_context(context)


def test_concurrent_creation_of_same_channel():
    context = _persistent_concurrent_context()
    sid, users = context
    barrier = Barrier(2)

    def create():
        with Session(test_engine) as db:
            barrier.wait(timeout=10)
            try:
                return create_channel(db, sid, users[0], ChannelCreate(name="unique")).id
            except HTTPException as exc:
                assert exc.status_code == 409
                return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(create) for _ in range(2)]
            ids = [future.result(timeout=20) for future in results]
        assert ids.count(None) == 1
        with Session(test_engine) as db:
            assert db.scalars(select(ServerChannel.id).where(ServerChannel.server_id == sid)).all() == [
                next(value for value in ids if value is not None)
            ]
    finally:
        with Session(test_engine) as db:
            for cid in db.scalars(select(ServerChannel.id).where(ServerChannel.server_id == sid)).all():
                delete_channel(db, sid, cid, users[0])
        _cleanup_persistent_context(context)

HEADER = "X-Expected-Channel-Grants"


@pytest.fixture
def channel_context(client, db_session, create_user, auth_headers):
    owner, _, server, _, _ = _manager_context(client, db_session, create_user, auth_headers)
    sid = server["id"]
    a = _role(db_session, sid, name="A", position=1).id
    b = _role(db_session, sid, name="B", position=2, is_system_role=True).id
    headers = auth_headers(owner)
    base = f"/servers/{sid}/channels"
    created = client.post(base, headers=headers, json={"name": "Privado", "is_private": True,
                                                       "authorized_role_ids": [a]})
    assert created.status_code == 201
    return f"{base}/{created.json()['id']}", headers, a, b


@pytest.mark.parametrize("header,status", [
    (None, 428), ("[]", 409), ("null", 422), ("{}", 422), ("bad", 422),
    ("[true]", 422), ('["2"]', 422), ("[1.5]", 422), ("[0]", 422), ("[-1]", 422),
])
def test_grants_patch_rejects_bad_base_without_partial_changes(client, channel_context, header, status):
    url, headers, a, _ = channel_context
    request_headers = headers if header is None else {**headers, HEADER: header}
    response = client.patch(url, headers=request_headers, json={"name": "Outro", "authorized_role_ids": [a]})
    assert response.status_code == status
    if status == 409:
        assert response.json()["detail"] == {"code": "channel_grants_conflict"}
    assert client.get(url, headers=headers).json()["name"] == "Privado"
    assert client.get(url + "/authorized-roles", headers=headers).json() == [a]


def test_publish_requires_current_grants_and_metadata_does_not(client, channel_context):
    url, headers, a, _ = channel_context
    assert client.patch(url, headers=headers, json={"name": "Renomeado"}).status_code == 200
    for extra, status in [({}, 428), ({HEADER: "[]"}, 409)]:
        response = client.patch(url, headers={**headers, **extra}, json={"is_private": False})
        assert response.status_code == status
        assert client.get(url, headers=headers).json()["is_private"] is True
        assert client.get(url + "/authorized-roles", headers=headers).json() == [a]
    assert client.patch(url, headers={**headers, HEADER: json.dumps([a])},
                        json={"is_private": False}).status_code == 200
    assert client.get(url + "/authorized-roles", headers=headers).json() == []
    assert client.patch(url, headers=headers, json={"description": "Público"}).status_code == 200
    assert client.patch(url, headers=headers, json={"is_private": True}).status_code == 200
    assert client.patch(url, headers=headers, json={"authorized_role_ids": []}).status_code == 428
    assert client.patch(url, headers={**headers, HEADER: "[]"}, json={"authorized_role_ids": []}).status_code == 200


def test_grants_are_sets_and_can_include_existing_system_role(client, channel_context):
    url, headers, a, b = channel_context
    response = client.patch(url, headers={**headers, HEADER: json.dumps([a, a])},
                            json={"authorized_role_ids": [a, b, b]})
    assert response.status_code == 200
    base = {**headers, HEADER: json.dumps([b, a, b])}
    assert client.patch(url, headers=base, json={"authorized_role_ids": [a, b, 2147483647]}).status_code == 404
    assert client.get(url + "/authorized-roles", headers=headers).json() == sorted([a, b])
    assert client.patch(url, headers=base, json={"authorized_role_ids": []}).status_code == 200
    assert client.get(url + "/authorized-roles", headers=headers).json() == []


def test_inactive_owner_cannot_patch_grants(client, db_session, channel_context):
    url, headers, _, _ = channel_context
    sid = int(url.split("/")[2])
    membership = db_session.scalar(select(ServerMember).join(Server, Server.id == ServerMember.server_id)
                                   .where(Server.id == sid, ServerMember.user_id == Server.owner_id))
    membership.status = "LEFT"
    membership.left_at = datetime.now(timezone.utc)
    db_session.commit()
    assert client.patch(url, headers=headers, json={"authorized_role_ids": []}).status_code == 404


def test_grant_audit_failure_rolls_back_publish(db_session, channel_context):
    url, _, a, _ = channel_context
    sid, cid = map(int, url.split("/")[2::2])
    owner = db_session.get(Server, sid).owner_id

    def fail_audit(mapper, connection, target):
        raise RuntimeError("audit failure")

    event.listen(ServerAuditLog, "before_insert", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="audit failure"):
            update_channel(db_session, sid, cid, owner, ChannelUpdate(name="Outro", is_private=False), json.dumps([a]))
    finally:
        event.remove(ServerAuditLog, "before_insert", fail_audit)
    db_session.expire_all()
    channel = db_session.get(ServerChannel, cid)
    assert (channel.name, channel.is_private) == ("Privado", True)
    assert list_authorized_roles(db_session, sid, cid, owner) == [a]
    assert db_session.scalars(select(ServerAuditLog.event_type).where(ServerAuditLog.channel_id == cid)).all() == [
        "CHANNEL_ROLE_ACCESS_GRANTED"
    ]


def test_channel_grants_preflight(client):
    response = client.options("/servers/12/channels/3", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "authorization,content-type,x-expected-channel-grants",
    })
    assert response.status_code == 200
    assert HEADER.lower() in response.headers["access-control-allow-headers"].lower()


def test_concurrent_stale_channel_patch_cannot_restore_revoked_access():
    context = _persistent_concurrent_context()
    sid, users = context
    owner = users[0]
    ready = Queue()
    revoked = Event()
    try:
        with Session(test_engine) as db:
            a, b = [_role(db, sid, name=name, position=1).id for name in ("A", "B")]
            cid = create_channel(db, sid, owner, ChannelCreate(
                name="Privado", is_private=True, authorized_role_ids={a},
            )).id

        def stale_editor():
            with Session(test_engine) as db:
                base = list_authorized_roles(db, sid, cid, owner)
                assert base == [a]
                ready.put(db.scalar(text("select pg_backend_pid()")))
                assert revoked.wait(timeout=10)
                with pytest.raises(HTTPException) as failure:
                    update_channel(db, sid, cid, owner, ChannelUpdate(
                        name="Alterado", position=9, authorized_role_ids={a, b},
                    ), json.dumps(base))
                assert failure.value.status_code == 409
                assert failure.value.detail == {"code": "channel_grants_conflict"}

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(stale_editor)
            waiter = ready.get(timeout=10)
            with test_engine.begin() as conn, Session(bind=conn, join_transaction_mode="create_savepoint") as db:
                assert list_authorized_roles(db, sid, cid, owner) == [a]
                change_role_access(db, sid, cid, owner, a, grant=False)
                revoked.set()
                # The outer transaction still holds the server lock after the service releases its savepoint.
                deadline = monotonic() + 10
                while not conn.scalar(text("select pg_backend_pid() = any(pg_blocking_pids(:pid))"), {"pid": waiter}):
                    assert monotonic() < deadline, "O PATCH não aguardou a revogação"
            future.result(timeout=15)

        with Session(test_engine) as db:
            assert list_authorized_roles(db, sid, cid, owner) == []
            channel = db.get(ServerChannel, cid)
            assert (channel.name, channel.position, channel.is_private) == ("Privado", 0, True)
            assert db.execute(select(ServerAuditLog.event_type, ServerAuditLog.role_id)
                              .where(ServerAuditLog.channel_id == cid).order_by(ServerAuditLog.id)).all() == [
                ("CHANNEL_ROLE_ACCESS_GRANTED", a), ("CHANNEL_ROLE_ACCESS_REVOKED", a),
            ]
    finally:
        with Session(test_engine) as db:
            for channel_id in db.scalars(select(ServerChannel.id).where(ServerChannel.server_id == sid)).all():
                delete_channel(db, sid, channel_id, owner)
            db.execute(ServerRole.__table__.delete().where(ServerRole.server_id == sid))
            db.commit()
        _cleanup_persistent_context(context)

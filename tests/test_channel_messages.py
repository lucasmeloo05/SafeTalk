from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Message, ModerationAnalysisJob, ModerationReportEvidence, PlatformStaff, ServerRole
from test_server_member_roles_api import _manager_context


@pytest.fixture
def chat(client, db_session, create_user, auth_headers):
    owner, manager, server, member, _ = _manager_context(client, db_session, create_user, auth_headers)
    db_session.commit()
    headers = [auth_headers(user) for user in (owner, manager, member)]
    base = f"/servers/{server['id']}/channels"
    channel = client.post(base, headers=headers[0], json={"name": "geral"}).json()
    return base + "/" + str(channel["id"]), headers, server["id"]


def test_channel_publishing_policy_and_sync(client, chat, db_session):
    url, (owner, manager, member), sid = chat
    path = url + "/messages"
    assert client.get(path).status_code == 401
    first = client.post(path, headers=manager, json={"content": "primeira"}).json()
    second = client.post(path, headers=member, json={"content": "segunda"}).json()
    mid = first["message"]["id"]
    msg = path + "/" + str(mid)
    response = client.get(path, headers=owner, params={"limit": 1}).json()
    assert response["items"] == [second["message"]] and response["has_more"]
    assert client.get(path, headers=owner, params={"before_id": second["message"]["id"]}).json()["items"] == [first["message"]]
    assert client.get(path, headers=owner, params={"after_id": mid}).json()["items"] == [second["message"]]
    assert client.patch(msg, headers=owner, json={"content": "alheia"}).status_code == 403
    assert client.delete(msg, headers=owner).status_code == 403
    assert client.patch(msg, headers=manager, json={"content": "editada"}).status_code == 200
    assert client.patch(url, headers=manager, json={"is_read_only": True}).status_code == 403
    assert client.patch(url, headers=owner, json={"is_read_only": True}).json()["is_read_only"]
    for actor in (manager, member):
        assert not client.get(path, headers=actor).json()["can_publish"]
        assert client.post(path, headers=actor, json={"content": "bloqueada"}).status_code == 403
    assert client.patch(msg, headers=manager, json={"content": "bloqueada"}).status_code == 403
    assert client.post(path, headers=owner, json={"content": "aviso"}).status_code == 201
    deleted = client.delete(msg, headers=manager).json()
    assert deleted["message"]["is_deleted_for_everyone"]
    assert client.delete(msg, headers=manager).json() == deleted
    updates = url + "/message-updates"
    page = client.get(updates, headers=member, params={"after_revision": 2, "limit": 1}).json()
    assert page["has_more"] and page["next_cursor"] == 3
    event = page["items"][0]
    assert event["event_type"] == "UPDATED" and event["message_state_revision"] == 5
    assert event["message"]["content"] == "Esta mensagem foi excluída"
    assert [e["event_type"] for e in client.get(updates, headers=member,
            params={"after_revision": 3}).json()["items"]] == ["CREATED", "DELETED"]
    assert client.patch(url, headers=owner, json={"is_read_only": False}).is_success
    old = db_session.get(Message, second["message"]["id"])
    old.created_at -= timedelta(minutes=16)
    db_session.commit()
    assert client.patch(path + "/" + str(old.id), headers=member, json={"content": "tarde"}).status_code == 409


def test_channel_scope_and_membership(client, chat, db_session):
    url, (owner, manager, member), sid = chat
    role = db_session.scalar(select(ServerRole.id).where(ServerRole.server_id == sid, ServerRole.position == 10))
    assert client.patch(url, headers={**owner, "X-Expected-Channel-Grants": "[]"},
                        json={"is_private": True, "authorized_role_ids": [role]}).is_success
    sent = client.post(url + "/messages", headers=manager, json={"content": "reservada"}).json()["message"]
    path = url + "/messages/" + str(sent["id"])
    assert client.get(url + "/messages", headers=member).status_code == 404
    assert client.get(url + "/message-updates", headers=member).status_code == 404
    assert client.post(url + "/messages", headers=member, json={"content": "não"}).status_code == 404
    assert client.post(path + "/reports", headers=member, json={"reason": "motivo"}).status_code == 404
    other = client.post("/servers/", headers=member, json={"name": "outro"}).json()["id"]
    foreign = url.replace(f"/servers/{sid}/", f"/servers/{other}/")
    assert client.get(foreign + "/messages", headers=member).status_code == 404
    assert client.get(f"/conversations/{sent['conversation_id']}/messages", headers=owner).status_code == 404
    assert client.post("/reports", headers=owner, json={"message_id": sent["id"], "reason": "motivo"}).status_code == 404
    assert client.post(f"/servers/{sid}/leave", headers=manager).is_success
    assert client.get(url + "/messages", headers=manager).status_code == 404


def test_channel_evidence_survives_edits_deletion_and_archival(client, chat, db_session, create_user, auth_headers):
    url, (owner, manager, member), sid = chat
    staff = create_user()
    db_session.add(PlatformStaff(user_id=staff["id"], role="MODERATOR", status="ACTIVE"))
    db_session.commit()
    sent = client.post(url + "/messages", headers=manager, json={"content": "original"}).json()["message"]
    msg = url + "/messages/" + str(sent["id"])
    assert client.post(msg + "/reports", headers=manager, json={"reason": "própria"}).status_code == 403
    report = client.post(msg + "/reports", headers=member, json={"reason": "revisar"}).json()
    rid = report["id"]
    assert client.post(msg + "/reports", headers=member, json={"reason": "repetida"}).status_code == 409
    job = db_session.scalar(select(ModerationAnalysisJob).where(ModerationAnalysisJob.report_id == rid))
    assert job.status == "PENDING_TRIAGE" and job.attempt_count == 0
    assert client.patch(msg, headers=manager, json={"content": "nova"}).is_success
    assert client.delete(msg, headers=manager).is_success
    assert client.delete(url, headers=owner).is_success
    assert client.get(url + "/messages", headers=owner).status_code == 404
    evidence = db_session.scalar(select(ModerationReportEvidence).where(ModerationReportEvidence.report_id == rid))
    assert (evidence.content_snapshot, evidence.server_id, evidence.channel_id, evidence.message_author_id) == (
        "original", sid, int(url.split("/")[-1]), sent["sender_id"])
    triage = f"/official/reports/{rid}/triage"
    payload = {"reason": "revisão humana", "external_analysis_eligible": True}
    assert client.post(triage, headers=auth_headers(staff), json=payload).status_code == 409
    assert client.patch(f"/servers/{sid}", headers=manager, json={"ai_moderation_enabled": True}).status_code == 403
    assert client.patch(f"/servers/{sid}", headers=owner, json={"ai_moderation_enabled": True}).is_success
    result = client.post(triage, headers=auth_headers(staff), json=payload)
    assert result.status_code == 202 and result.json()["status"] == "PENDING"

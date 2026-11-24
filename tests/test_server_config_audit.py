import json

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from app.models import Server, ServerConfigHistory, ServerRole


@pytest.fixture
def owned(client, create_user, auth_headers):
    owner = create_user()
    headers = auth_headers(owner)
    response = client.post("/servers/", headers=headers, json={"name": "Original", "description": "Antes"})
    assert response.status_code == 201
    return response.json()["id"], owner["id"], headers


def history(db, sid):
    return db.scalars(select(ServerConfigHistory).where(ServerConfigHistory.server_id == sid)).all()


def test_server_patch_audits_only_effective_changes(client, db_session, owned):
    sid, actor, headers = owned
    url = f"/servers/{sid}"
    for payload in ({"name": "Novo", "description": None}, {"name": "Novo"}):
        assert client.patch(url, headers=headers, json=payload).status_code == 200
    rows = history(db_session, sid)
    assert len(rows) == 2
    assert {(r.setting_name, r.changed_by, json.loads(r.old_value), json.loads(r.new_value))
            for r in rows} == {("name", actor, "Original", "Novo"), ("description", actor, "Antes", None)}


def test_role_creation_records_snapshot(client, db_session, owned):
    sid, actor, headers = owned
    payload = {"name": "Equipe", "position": 3, "permissions": {"manage_roles": False}}
    response = client.post(f"/servers/{sid}/roles", headers=headers, json=payload)
    assert response.status_code == 201
    role = db_session.get(ServerRole, response.json()["id"])
    row, = history(db_session, sid)
    assert (row.setting_name, row.changed_by) == (f"server_role:{role.id}", actor)
    assert json.loads(row.old_value) is None
    assert json.loads(row.new_value) == {
        **payload, "id": role.id, "description": None, "is_default": False,
        "is_system_role": False, "created_at": role.created_at.isoformat(),
    }


@pytest.mark.parametrize("operation", ["patch", "create_role"])
def test_config_history_failure_rolls_back(client, db_session, owned, operation):
    sid, _, headers = owned

    def fail_insert(mapper, connection, target):
        raise SQLAlchemyError("audit insert failed")

    event.listen(ServerConfigHistory, "after_insert", fail_insert)
    try:
        if operation == "patch":
            response = client.patch(f"/servers/{sid}", headers=headers, json={"name": "Novo", "description": None})
        else:
            response = client.post(f"/servers/{sid}/roles", headers=headers, json={"name": "Equipe", "position": 1})
    finally:
        event.remove(ServerConfigHistory, "after_insert", fail_insert)
    assert response.status_code == 500
    db_session.expire_all()
    server = db_session.get(Server, sid)
    assert (server.name, server.description) == ("Original", "Antes")
    assert not db_session.scalar(select(ServerRole.id).where(ServerRole.server_id == sid, ServerRole.name == "Equipe"))
    assert history(db_session, sid) == []

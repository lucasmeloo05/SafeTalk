from datetime import date, timedelta
import pytest
from sqlalchemy import select
from app import age_policy
from app.models import User, Server, ServerInvite, ServerMember
from test_server_member_roles_api import _manager_context

@pytest.mark.parametrize("birthday,accepted", [
    ("2013-06-15",False), ("2012-06-15",True), ("1995-01-01",True),
    ("2012-06-16",False), ("2012-06-14",True), ("2027-01-01",False), ("invalid",False)])
def test_registration_age_boundaries(client, monkeypatch, birthday, accepted):
    monkeypatch.setattr(age_policy, "today", lambda: date(2026,6,15))
    response = client.post("/users/", json={"username":"age_test","email":"age@example.com",
                        "password":"Safe-Password-123!", "birth_date":birthday})
    assert response.status_code == (201 if accepted else 422), response.text

def test_age_calculation():
    assert age_policy.age_on(date(2008,6,15),date(2026,6,14)) == 17
    assert age_policy.age_on(date(2008,6,15),date(2026,6,15)) == 18
    assert age_policy.age_on(date(2008,2,29),date(2026,2,28)) == 17
    assert age_policy.age_on(date(2008,2,29),date(2026,3,1)) == 18
    assert not age_policy.is_adult(None)

@pytest.fixture
def community(client, db_session, create_user, auth_headers, monkeypatch):
    monkeypatch.setattr(age_policy,"today",lambda:date(2026,6,15))
    owner, manager, server, target, _ = _manager_context(client,db_session,create_user,auth_headers)
    headers=auth_headers(owner)
    base=f"/servers/{server['id']}"
    channel=client.post(base+"/channels",headers=headers,json={"name":"geral"}).json()
    message=client.post(base+f"/channels/{channel['id']}/messages",headers=headers,json={"content":"conteúdo"}).json()
    db_session.get(Server,server["id"]).is_adult=True
    db_session.commit()
    return owner,manager,server,target,channel,message

@pytest.mark.parametrize("suffix,method", [
    ("","get"),("/members","get"),("/authorization-context","get"),("/roles","get"),
    ("/invites","get"),("/audit-logs","get"),("/bans","get"),("/channels","get"),
    ("/channels/{cid}","get"),("/channels/{cid}/messages","get"),
    ("/channels/{cid}/message-updates","get"),("/channels/{cid}/messages","post"),
    ("/channels/{cid}/messages/{mid}","patch"),
    ("/channels/{cid}/messages/{mid}/reports","post")])
def test_minor_cannot_bypass_any_server_endpoint(client,db_session,community,auth_headers,suffix,method):
    owner,manager,server,target,channel,message=community
    db_session.get(User,owner["id"]).birth_date=date(2010,1,1)
    db_session.commit()
    url=f"/servers/{server['id']}"+suffix.format(cid=channel["id"],mid=message["message"]["id"])
    response=getattr(client,method)(url,headers=auth_headers(owner),
          **({"json":{"content":"tentativa","reason":"motivo"}} if method in {"post","patch"} else {}))
    assert response.status_code == 404
    assert "conteúdo" not in response.text
    assert client.get("/servers/",headers=auth_headers(owner)).json() == []

@pytest.mark.parametrize("birthday,allowed",[(None,False),(date(2027,1,1),False),(date(2008,6,16),False),(date(2008,6,15),True)])
def test_existing_members_age_gate(client,db_session,community,auth_headers,birthday,allowed):
    owner,manager,server,target,channel,message=community
    db_session.get(User,target["id"]).birth_date=birthday
    db_session.commit()
    response=client.get(f"/servers/{server['id']}",headers=auth_headers(target))
    assert response.status_code == (200 if allowed else 404)

def test_invite_restriction_does_not_consume_or_create_membership(client,db_session,community,create_user,auth_headers):
    owner,manager,server,target,channel,message=community
    url=f"/servers/{server['id']}"
    invite=client.post(url+"/invites",headers=auth_headers(owner),json={}).json()
    newcomer=create_user()
    db_session.get(User,newcomer["id"]).birth_date=date(2010,1,1)
    db_session.commit()
    assert client.post(url+"/invites/accept",headers=auth_headers(newcomer),json={"token":invite["token"]}).status_code == 404
    assert db_session.get(ServerInvite,invite["id"]).uses_count == 0
    assert db_session.scalar(select(ServerMember).where(ServerMember.server_id==server["id"],ServerMember.user_id==newcomer["id"])) is None

def test_adult_classification_is_creation_only(client,db_session,create_user,auth_headers):
    owner=create_user()
    headers=auth_headers(owner)
    response=client.post("/servers/",headers=headers,json={"name":"adultos","is_adult":True})
    assert response.status_code==201
    assert response.json()["is_adult"] is True
    sid=response.json()["id"]
    assert client.patch(f"/servers/{sid}",headers=headers,json={"is_adult":False}).status_code==422
    assert client.get(f"/servers/{sid}",headers=headers).json()["is_adult"] is True
    db_session.get(User,owner["id"]).birth_date=age_policy.today()-timedelta(days=15*365)
    db_session.commit()
    assert client.post("/servers/",headers=auth_headers(owner),json={"name":"proibido","is_adult":True}).status_code==403
    assert client.post("/servers/",headers=auth_headers(owner),json={"name":"comum"}).status_code==201

def test_legacy_declaration_is_private_once_and_password_protected(client,db_session,create_user,auth_headers):
    user=create_user()
    db_session.get(User,user["id"]).birth_date=None
    db_session.commit()
    headers=auth_headers(user)
    url="/users/me/birth-date"
    assert client.post(url,headers=headers,json={"birth_date":"1990-01-01","password":"wrong"}).status_code==403
    good=client.post(url,headers=headers,json={"birth_date":"1990-01-01","password":user["password"]})
    assert good.status_code==200
    assert client.post(url,headers=headers,json={"birth_date":"1980-01-01","password":user["password"]}).status_code==409
    assert client.get("/users/search",headers=headers,params={"query":user["username"]}).status_code==200


def test_minor_official_staff_cannot_read_adult_channel_evidence(client,db_session,community,create_user,auth_headers):
    from app.models import PlatformStaff
    owner,manager,server,target,channel,message=community
    url=f"/servers/{server['id']}/channels/{channel['id']}/messages/{message['message']['id']}/reports"
    report=client.post(url,headers=auth_headers(manager),json={"reason":"revisar"}).json()
    staff=create_user()
    db_session.get(User,staff["id"]).birth_date=date(2010,1,1)
    db_session.add(PlatformStaff(user_id=staff["id"],role="MODERATOR",status="ACTIVE"))
    db_session.commit()
    headers=auth_headers(staff)
    assert client.get(f"/official/reports/{report['id']}",headers=headers).status_code==404
    assert client.get("/official/reports",headers=headers).json()["total"]==0

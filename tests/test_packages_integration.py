"""Real loopback HTTP -> FastAPI -> isolated PostgreSQL; no provider network calls."""
import base64
import json
import socket
from datetime import date
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pyotp
import uvicorn
from sqlalchemy import select

from app.main import app
from app.models import User, PlatformStaff, ModerationReportEvidence, ModerationSanction
from app import age_policy
from app.settings import settings


def test_packages_over_real_http(client, db_session, monkeypatch):
    # Deliberately public deterministic test fixture, never an environment key.
    monkeypatch.setattr(settings, "two_factor_encryption_key", base64.urlsafe_b64encode(bytes(range(32))).decode())
    monkeypatch.setattr(settings, "moderation_worker_enabled", False)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, lifespan="off"))
    thread = Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    base = "http://127.0.0.1:" + str(sock.getsockname()[1])

    def request(method, path, body=None, token=None, expected=200, headers=None):
        data = None if body is None else json.dumps(body).encode()
        auth = {} if token is None else {"Authorization": "Bearer " + token}
        req = Request(base + path, data=data, method=method,
                      headers={"Content-Type":"application/json", **auth, **(headers or {})})
        try:
            response = urlopen(req, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            status = response.status
            raw = response.read()
        assert status == expected, f"{method} {path} returned {status}, expected {expected}"
        return json.loads(raw) if raw else None

    password = "Fixture-Password-123!"
    def register(name, born):
        return request("POST","/users/",{"username":name,"email":name+"@example.com",
                                        "password":password,"birth_date":born.isoformat()},expected=201)
    def login(name):
        return request("POST","/users/login",{"login":name,"password":password})

    try:
        on = age_policy.today()
        fourteen = date(on.year-14,on.month,on.day)
        thirteen = date(on.year-13,on.month,on.day)
        request("POST","/users/",{"username":"pkg13","email":"pkg13@example.com",
                                "password":password,"birth_date":thirteen.isoformat()},expected=422)
        teen = register("pkg14",fourteen)
        owner = register("pkgowner",date(1990,1,1))
        member = register("pkgmember",date(1991,1,1))
        staff = register("pkgstaff",date(1992,1,1))
        ot = login("pkgowner")["access_token"]
        mt = login("pkgmember")["access_token"]
        tt = login("pkg14")["access_token"]
        setup = request("POST","/users/me/2fa/setup",{"password":password},ot)
        enabled = request("POST","/users/me/2fa/confirm",
                          {"password":password,"code":pyotp.TOTP(setup["manual_key"]).now()},ot)
        pending = login("pkgowner")
        assert "access_token" not in pending
        request("GET","/users/me",token=pending["challenge"],expected=401)
        # A new step is accepted within the supported clock-drift window.
        step = pyotp.TOTP(setup["manual_key"])
        next_code = step.at((int(__import__("time").time())//30+1)*30)
        ot = request("POST","/users/login/2fa",{"challenge":pending["challenge"],"code":next_code})["access_token"]
        request("POST","/users/login/2fa",{"challenge":pending["challenge"],"code":next_code},expected=401)
        pending = login("pkgowner")
        recovery = {"challenge":pending["challenge"],"code":enabled["recovery_codes"][0],"recovery":True}
        ot = request("POST","/users/login/2fa",recovery)["access_token"]
        pending = login("pkgowner")
        recovery["challenge"] = pending["challenge"]
        request("POST","/users/login/2fa",recovery,expected=401)

        common = request("POST","/servers/",{"name":"Pacotes comum"},ot,201)["id"]
        adult = request("POST","/servers/",{"name":"Pacotes adulto","is_adult":True},ot,201)["id"]
        invite = request("POST",f"/servers/{adult}/invites",{},ot,201)
        request("POST",f"/servers/{adult}/invites/accept",{"token":invite["token"]},tt,404)
        request("GET",f"/servers/{adult}",token=tt,expected=404)
        db_session.get(User,teen["id"]).birth_date = None
        db_session.commit()
        request("GET",f"/servers/{adult}",token=tt,expected=404)
        request("POST",f"/servers/{adult}/invites/accept",{"token":invite["token"]},mt)
        request("GET",f"/servers/{adult}",token=mt)
        role = request("POST",f"/servers/{adult}/roles",
                       {"name":"Administrador","position":10,"permissions":{"manage_roles":True,"manage_invites":True}},ot,201)
        request("PUT",f"/servers/{adult}/members/{member["id"]}/roles/{role["id"]}",token=ot,expected=204)
        db_session.get(User,member["id"]).birth_date = fourteen
        db_session.commit()
        request("GET",f"/servers/{adult}",token=mt,expected=404)
        db_session.get(User,member["id"]).birth_date = date(1991,1,1)
        db_session.commit()
        public = request("POST",f"/servers/{adult}/channels",{"name":"geral"},ot,201)["id"]
        private = request("POST",f"/servers/{adult}/channels",{"name":"privado","is_private":True},ot,201)["id"]
        url = f"/servers/{adult}/channels/{public}"
        secret = f"/servers/{adult}/channels/{private}"
        request("GET",secret+"/messages",token=mt,expected=404)
        request("PUT",secret+f"/roles/{role["id"]}",token=ot,expected=204)
        request("GET",secret+"/messages",token=mt)
        first = request("POST",url+"/messages",{"content":"Evidência original fictícia"},mt,201)["message"]
        second = request("POST",url+"/messages",{"content":"Segunda fictícia"},ot,201)["message"]
        page = request("GET",url+"/messages?limit=1",token=mt)
        assert page["has_more"] and page["items"][0]["id"]==second["id"]
        older = request("GET",url+f"/messages?before_id={second["id"]}",token=mt)
        assert older["items"][0]["id"]==first["id"]
        report = request("POST",url+f"/messages/{first["id"]}/reports",{"reason":"Revisar exemplo"},ot,201)
        request("PATCH",url+f"/messages/{first["id"]}",{"content":"Edição fictícia"},mt)
        request("DELETE",url+f"/messages/{first["id"]}",token=ot,expected=403)
        request("DELETE",url+f"/messages/{first["id"]}",token=mt)
        events = request("GET",url+"/message-updates?after_revision=0&limit=1",token=ot)
        assert events["has_more"] and events["next_cursor"]==1
        assert events["items"][0]["message"]["is_deleted_for_everyone"]
        snapshot = db_session.scalar(select(ModerationReportEvidence).where(ModerationReportEvidence.report_id==report["id"]))
        assert snapshot.content_snapshot=="Evidência original fictícia"
        assert snapshot.server_id==adult and snapshot.channel_id==public
        assert db_session.scalars(select(ModerationSanction)).all()==[]
        db_session.add(PlatformStaff(user_id=staff["id"],role="MODERATOR",status="ACTIVE"))
        db_session.commit()
        st=login("pkgstaff")["access_token"]
        detail=request("GET",f"/official/reports/{report["id"]}",token=st)
        assert detail["analysis"]["status"]=="PENDING_TRIAGE"
        db_session.get(User,staff["id"]).birth_date=fourteen
        db_session.commit()
        request("GET",f"/official/reports/{report["id"]}",token=st,expected=404)
        request("PATCH",url,{"is_read_only":True},ot)
        request("POST",url+"/messages",{"content":"Tentativa"},mt,403)
        request("POST",url+"/messages",{"content":"Aviso do proprietário"},ot,201)
        # Only this channel's role grant changes; no request is retried.
        request("DELETE",secret+f"/roles/{role["id"]}",token=ot,expected=204)
        request("GET",secret+"/messages",token=mt,expected=404)
        request("POST",secret+f"/messages/{first["id"]}/reports",{"reason":"Tentativa"},mt,404)
        request("GET",f"/servers/{common}",token=ot)
    finally:
        server.should_exit=True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()

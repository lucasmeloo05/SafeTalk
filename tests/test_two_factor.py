from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pyotp
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.two_factor import TwoFactor, TwoFactorChallenge, TwoFactorAudit
from app.services import two_factor_service as service
from app.settings import settings
from conftest import test_engine

@pytest.fixture
def factor(client, db_session, create_user, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "two_factor_encryption_key", Fernet.generate_key().decode())
    user = create_user()
    # create_user fixture password is inspected by the test below.
    return user, auth_headers(user)

def enroll(client, factor):
    user, headers = factor
    setup = client.post("/users/me/2fa/setup", headers=headers, json={"password": user["password"]})
    assert setup.status_code == 200, setup.text
    code = pyotp.TOTP(setup.json()["manual_key"]).now()
    response = client.post("/users/me/2fa/confirm", headers=headers, json={"password": user["password"], "code": code})
    assert response.status_code == 200, response.text
    return setup.json(), response.json()

def test_enrollment_challenge_and_recovery(client, db_session, factor):
    user, old_headers = factor
    setup, active = enroll(client, factor)
    state = db_session.get(TwoFactor, user["id"])
    assert setup["manual_key"] not in state.secret
    assert all(value not in state.recovery_hashes for value in active["recovery_codes"])
    assert client.get("/users/me", headers=old_headers).status_code == 401
    headers = {"Authorization": "Bearer " + active["access_token"]}
    assert client.get("/users/me/2fa", headers=headers).json() == {"enabled": True}
    assert "secret" not in client.get("/users/me", headers=headers).json()
    pending = client.post("/users/login", json={"login": user["username"], "password": user["password"]}).json()
    assert "access_token" not in pending
    assert client.get("/users/me", headers={"Authorization": "Bearer " + pending["challenge"]}).status_code == 401
    payload = {"challenge": pending["challenge"], "code": active["recovery_codes"][0], "recovery": True}
    completed = client.post("/users/login/2fa", json=payload)
    assert completed.status_code == 200
    assert client.post("/users/login/2fa", json=payload).status_code == 401
    pending = client.post("/users/login", json={"login": user["username"], "password": user["password"]}).json()
    payload["challenge"] = pending["challenge"]
    assert client.post("/users/login/2fa", json=payload).status_code == 401
    proof = {"password": user["password"], "code": active["recovery_codes"][1], "recovery": True}
    regenerated = client.post("/users/me/2fa/regenerate", headers=headers, json=proof).json()
    assert "recovery_codes" in regenerated
    fresh = {"Authorization": "Bearer " + regenerated["access_token"]}
    proof["code"] = active["recovery_codes"][2]
    assert client.post("/users/me/2fa/disable", headers=fresh, json=proof).status_code == 401
    proof["code"] = regenerated["recovery_codes"][0]
    disabled = client.post("/users/me/2fa/disable", headers=fresh, json=proof).json()
    assert disabled["enabled"] is False
    assert client.get("/users/me", headers=old_headers).status_code == 401
    assert client.get("/users/me", headers={"Authorization": "Bearer " + disabled["access_token"]}).status_code == 200
    assert db_session.get(TwoFactor, user["id"]).secret is None
    assert len(db_session.scalars(select(TwoFactorAudit).where(TwoFactorAudit.user_id == user["id"])).all()) == 3

def test_totp_expiry_replay_and_rate_limit(client, db_session, factor):
    user, headers = factor
    setup, active = enroll(client, factor)
    state = db_session.get(TwoFactor, user["id"])
    state.last_step -= 1
    db_session.commit()
    pending = service.begin_challenge(db_session, user["id"])
    totp = pyotp.TOTP(setup["manual_key"]).now()
    assert client.post("/users/login/2fa", json={"challenge": pending["challenge"], "code": totp}).status_code == 200
    pending = service.begin_challenge(db_session, user["id"])
    assert client.post("/users/login/2fa", json={"challenge": pending["challenge"], "code": totp}).status_code == 401
    challenge = db_session.get(TwoFactorChallenge, service.digest(pending["challenge"]))
    challenge.expires_at -= timedelta(minutes=6)
    db_session.commit()
    assert client.post("/users/login/2fa", json={"challenge": pending["challenge"], "code": active["recovery_codes"][0], "recovery": True}).status_code == 401
    pending = service.begin_challenge(db_session, user["id"])
    for _ in range(4):
        assert client.post("/users/login/2fa", json={"challenge": pending["challenge"], "code": "bad"}).status_code == 401
    assert client.post("/users/login/2fa", json={"challenge": pending["challenge"], "code": "bad"}).status_code == 429

def test_concurrent_recovery_consumption():
    from uuid import uuid4
    from app.models import User
    from app.routers.users import password_hash
    suffix = uuid4().hex[:12]
    with Session(test_engine) as db:
        user = User(username="tf_" + suffix, email=suffix + "@example.test", password_hash=password_hash.hash("unused"))
        db.add(user)
        db.flush()
        uid = user.id
        state = TwoFactor(user_id=uid, enabled=True, secret="unused", session_version="version",
                          recovery_hashes=[service.digest("ONETIME")], failures=0, last_step=-1)
        db.add(state)
        db.commit()
    gate = Barrier(2)
    def consume():
        with Session(test_engine) as db:
            gate.wait(timeout=10)
            try:
                _, state, now = service.locked_state(db, uid)
                service.verify_factor(db, state, now, "ONETIME", True)
                db.commit()
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: consume(), range(2)))
        assert sorted(results) == [200, 401]
    finally:
        with Session(test_engine) as db:
            db.query(TwoFactor).filter_by(user_id=uid).delete()
            db.query(User).filter_by(id=uid).delete()
            db.commit()

def test_invalid_setup_never_enables_and_requires_encryption(client, db_session, factor, monkeypatch):
    user, headers = factor
    response = client.post("/users/me/2fa/setup", headers=headers, json={"password": user["password"]})
    assert response.status_code == 200
    wrong = client.post("/users/me/2fa/confirm", headers=headers,
                        json={"password": user["password"], "code": "invalid"})
    assert wrong.status_code == 401
    assert client.get("/users/me/2fa", headers=headers).json() == {"enabled": False}
    monkeypatch.setattr(settings, "two_factor_encryption_key", None)
    assert client.post("/users/me/2fa/setup", headers=headers,
                       json={"password": user["password"]}).status_code == 503

def test_two_factor_migration_cycle():
    from uuid import uuid4
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from sqlalchemy import text
    schema = "two_factor_" + uuid4().hex
    scripts = ScriptDirectory("migrations")
    revision = scripts.get_revision("e21b7c84a603")
    with test_engine.connect() as db:
        db.execute(text(f"CREATE SCHEMA {schema}"))
        db.execute(text(f"SET LOCAL search_path TO {schema}"))
        with Operations.context(MigrationContext.configure(db)):
            for step in reversed(list(scripts.iterate_revisions("e21b7c84a603", "base"))):
                step.module.upgrade()
            assert db.scalar(text("SELECT to_regclass('user_two_factor')")) is not None
            revision.module.downgrade()
            revision.module.upgrade()
            assert db.scalar(text("SELECT count(*) FROM two_factor_challenges")) == 0

def test_validation_does_not_echo_proof(client):
    response = client.post("/users/login/2fa", json={"challenge": "short", "code": "PRIVATE-PROOF", "recovery": False})
    assert response.status_code == 422
    assert "PRIVATE-PROOF" not in response.text and "short" not in response.text

"""Persistent TOTP enrollment, single-use challenges and recovery credentials."""
import hashlib
import hmac
import io
import secrets
from datetime import timedelta

import jwt
import pyotp
import qrcode
import qrcode.image.svg
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import User
from app.models.two_factor import TwoFactor, TwoFactorAudit, TwoFactorChallenge
from app.settings import settings
from app.services.moderation_sanction_service import account_restriction_exception, get_active_account_restriction


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def cipher() -> Fernet:
    try:
        key = settings.two_factor_encryption_key
        if not key or key == settings.jwt_secret_key:
            raise ValueError()
        return Fernet(key.encode())
    except (ValueError, TypeError):
        raise HTTPException(503, "A configuração segura de 2FA está indisponível.") from None


def clock(db):
    return db.scalar(select(func.clock_timestamp()))


def locked_state(db, uid):
    user = db.scalar(select(User).where(User.id == uid).with_for_update().execution_options(populate_existing=True))
    if user is None or not user.is_active:
        raise HTTPException(401, "Autenticação inválida.")
    restriction = get_active_account_restriction(db, uid)
    if restriction:
        raise account_restriction_exception(restriction)
    state = db.get(TwoFactor, uid, populate_existing=True)
    if state is None:
        state = TwoFactor(user_id=uid, enabled=False, last_step=-1, recovery_hashes=[], failures=0)
        db.add(state)
        db.flush()
    now = clock(db)
    if state.locked_until and state.locked_until > now:
        raise HTTPException(429, "Muitas tentativas. Aguarde 15 minutos.")
    return user, state, now


def fail(db, state, now):
    state.failures += 1
    if state.failures >= 5:
        state.locked_until = now + timedelta(minutes=15)
        state.failures = 0
    db.commit()  # Persist the attempt even though the request is rejected.
    raise HTTPException(401, "Autenticação ou código inválido.")


def verify_factor(db, state, now, code, recovery=False):
    if recovery:
        hashed = digest(code.strip().upper())
        hashes = state.recovery_hashes
        found = next((v for v in hashes if hmac.compare_digest(v, hashed)), None)
        if found is None:
            fail(db, state, now)
        state.recovery_hashes = [v for v in hashes if v != found]
    else:
        try:
            secret = cipher().decrypt(state.secret.encode()).decode()
        except (InvalidToken, AttributeError):
            raise HTTPException(503, "A configuração segura de 2FA está indisponível.") from None
        step = int(now.timestamp()) // 30
        match = next((v for v in (step - 1, step, step + 1)
                      if v > state.last_step and hmac.compare_digest(pyotp.TOTP(secret).at(v * 30), code)), None)
        if match is None:
            fail(db, state, now)
        state.last_step = match
    state.failures = 0
    state.locked_until = None


def recovery_codes(state):
    codes = [secrets.token_hex(10).upper() for _ in range(10)]
    state.recovery_hashes = [digest(code) for code in codes]
    return codes


def access_token(uid, state, now):
    claims = {"sub": str(uid), "iat": now, "exp": now + timedelta(minutes=30)}
    if state and state.session_version:
        claims["tfv"] = state.session_version
    return {"access_token": jwt.encode(claims, settings.jwt_secret_key, algorithm="HS256"), "token_type": "bearer"}


def begin_challenge(db, uid):
    user, state, now = locked_state(db, uid)
    if not state.enabled:
        result = access_token(uid, state, now)
    else:
        # One outstanding challenge per account; issue only after password validation.
        db.execute(delete(TwoFactorChallenge).where(TwoFactorChallenge.user_id == uid))
        raw = secrets.token_urlsafe(32)
        db.add(TwoFactorChallenge(token_hash=digest(raw), user_id=uid, expires_at=now + timedelta(minutes=5)))
        result = {"two_factor_required": True, "challenge": raw, "expires_in": 300}
    db.commit()
    return result


def complete_challenge(db, token, code, recovery):
    uid = db.scalar(select(TwoFactorChallenge.user_id).where(TwoFactorChallenge.token_hash == digest(token)))
    if uid is None:
        raise HTTPException(401, "Desafio inválido ou expirado.")
    user, state, now = locked_state(db, uid)
    challenge = db.get(TwoFactorChallenge, digest(token), populate_existing=True)
    if challenge is None or challenge.expires_at <= now or not state.enabled:
        raise HTTPException(401, "Desafio inválido ou expirado.")
    verify_factor(db, state, now, code, recovery)
    db.delete(challenge)
    result = access_token(uid, state, now)
    db.commit()
    return result


def configure(db, uid, operation, password, code="", recovery=False):
    from app.routers.users import password_hash
    user, state, now = locked_state(db, uid)
    if not password_hash.verify(password, user.password_hash):
        fail(db, state, now)
    if operation == "setup":
        if state.enabled:
            raise HTTPException(409, "O 2FA já está ativo.")
        secret = pyotp.random_base32()
        state.secret = cipher().encrypt(secret.encode()).decode()
        state.setup_expires_at = now + timedelta(minutes=10)
        state.last_step = -1
        uri = pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name="SafeTalk")
        output = io.BytesIO()
        qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathFillImage).save(output)
        result = {"manual_key": secret, "qr_svg": output.getvalue().decode(), "expires_in": 600}
    else:
        if operation == "confirm":
            if state.enabled or not state.setup_expires_at or state.setup_expires_at <= now or recovery:
                raise HTTPException(409, "Configuração expirada ou indisponível. Inicie novamente.")
        elif not state.enabled:
            raise HTTPException(409, "O 2FA não está ativo.")
        verify_factor(db, state, now, code, recovery)
        if operation in ("confirm", "regenerate"):
            state.enabled = True
            state.setup_expires_at = None
            state.session_version = secrets.token_hex(16)
            result = {"recovery_codes": recovery_codes(state), **access_token(uid, state, now)}
        else:
            state.enabled = False
            state.secret = None
            state.recovery_hashes = []
            state.session_version = secrets.token_hex(16)
            result = {"enabled": False, **access_token(uid, state, now)}
        db.execute(delete(TwoFactorChallenge).where(TwoFactorChallenge.user_id == uid))
        db.add(TwoFactorAudit(user_id=uid, event=operation.upper()))
    state.failures = 0
    db.commit()
    return result

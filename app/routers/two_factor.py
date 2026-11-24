from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.models.two_factor import TwoFactor
from app.two_factor_schemas import ChallengeProof, StrongProof, SetupProof
from app.services import two_factor_service as service

router = APIRouter(prefix="/users", tags=["Autenticação em dois fatores"])
DB = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(get_current_user)]

@router.post("/login/2fa")
def complete(data: ChallengeProof, db: DB, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return service.complete_challenge(db, data.challenge, data.code, data.recovery)

@router.get("/me/2fa")
def status(actor: Actor, db: DB, response: Response):
    response.headers["Cache-Control"] = "no-store"
    state = db.get(TwoFactor, actor.id)
    return {"enabled": bool(state and state.enabled)}

@router.post("/me/2fa/setup")
def setup(data: SetupProof, actor: Actor, db: DB, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return service.configure(db, actor.id, "setup", data.password.get_secret_value())

@router.post("/me/2fa/{operation}")
def manage(operation: Literal["confirm", "regenerate", "disable"], data: StrongProof,
           actor: Actor, db: DB, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return service.configure(db, actor.id, operation, data.password.get_secret_value(), data.code, data.recovery)

from typing import Annotated
from fastapi import Depends, Request
from sqlalchemy.orm import Session
from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.age_policy import require_age

def require_server_age(request: Request, db: Annotated[Session, Depends(get_db)],
                       actor: Annotated[User, Depends(get_current_user)]):
    sid = request.path_params.get("server_id")
    if sid is not None:
        try:
            sid = int(sid)
        except (ValueError, TypeError):
            return  # Path validation produces 422.
        require_age(db, sid, actor.id)


def require_report_age(request: Request, db: Annotated[Session, Depends(get_db)],
                       actor: Annotated[User, Depends(get_current_user)]):
    from sqlalchemy import select
    from app.models import ModerationReportEvidence
    rid = request.path_params.get("report_id")
    if rid is not None:
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            return
        sid = db.scalar(select(ModerationReportEvidence.server_id).where(ModerationReportEvidence.report_id == rid))
        if sid is not None:
            require_age(db, sid, actor.id)

"""Self-declared age policy. Dates are never proof of identity."""
from datetime import date, datetime, timezone
from fastapi import HTTPException
from sqlalchemy import or_, select
from app.models import Server, User

def today() -> date:
    return datetime.now(timezone.utc).date()

def age_on(born: date, on: date) -> int:
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))

def validate_birth_date(born: date) -> date:
    on = today()
    if born > on or born.year < 1900:
        raise ValueError("Informe uma data de nascimento válida e não futura.")
    if age_on(born, on) < 14:
        raise ValueError("É necessário ter pelo menos 14 anos para criar uma conta.")
    return born

def is_adult(born: date | None) -> bool:
    return born is not None and 1900 <= born.year and born <= today() and age_on(born, today()) >= 18

def require_age(db, server_id: int, user_id: int):
    row = db.execute(select(Server.is_adult, User.birth_date).select_from(Server).join(User, User.id == user_id)
                     .where(Server.id == server_id)).first()
    if row is not None and row.is_adult and not is_adult(row.birth_date):
        raise HTTPException(404, "Servidor não encontrado.")

def age_filter(user):
    return or_(Server.is_adult.is_(False), is_adult(user.birth_date))


def report_age_filter(db, user_id):
    from sqlalchemy import true
    from app.models import ModerationReport, ModerationReportEvidence
    if user_id is None or is_adult(db.get(User, user_id).birth_date):
        return true()
    adult_evidence = select(ModerationReportEvidence.report_id).join(
        Server, Server.id == ModerationReportEvidence.server_id
    ).where(ModerationReportEvidence.report_id == ModerationReport.id, Server.is_adult.is_(True)).exists()
    return ~adult_evidence

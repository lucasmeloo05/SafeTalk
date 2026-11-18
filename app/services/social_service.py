from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Block, Friendship, User, UserPrivacySettings


def _blocked_between(db: Session, first_id: int, second_id: int) -> bool:
    return db.scalar(
        select(Block.id).where(
            or_(
                and_(Block.blocker_id == first_id, Block.blocked_id == second_id),
                and_(Block.blocker_id == second_id, Block.blocked_id == first_id),
            )
        ).limit(1)
    ) is not None


def _lock_users(db: Session, first_id: int, second_id: int) -> None:
    ids = sorted({first_id, second_id})
    db.scalars(select(User).where(User.id.in_(ids)).order_by(User.id).with_for_update()).all()


def search_users(db: Session, actor_id: int, query: str, limit: int, offset: int):
    term = query.strip()
    if len(term) < 2:
        raise HTTPException(
            status_code=422,
            detail="A busca deve conter ao menos 2 caracteres após remover espaços.",
        )
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    blocked = select(Block.id).where(
        or_(
            and_(Block.blocker_id == actor_id, Block.blocked_id == User.id),
            and_(Block.blocker_id == User.id, Block.blocked_id == actor_id),
        )
    ).exists()
    base = select(User).where(
        User.is_active.is_(True),
        User.id != actor_id,
        User.username.ilike(f"%{escaped}%", escape="\\"),
        ~blocked,
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    users = db.scalars(base.order_by(User.username, User.id).limit(limit).offset(offset)).all()
    if not users:
        return {"items": [], "total": total, "limit": limit, "offset": offset}

    user_ids = [user.id for user in users]
    friendships = db.scalars(
        select(Friendship).where(
            or_(
                and_(Friendship.user_a_id == actor_id, Friendship.user_b_id.in_(user_ids)),
                and_(Friendship.user_b_id == actor_id, Friendship.user_a_id.in_(user_ids)),
            ),
            # Apenas relações ativas: terminadas (CANCELLED, REJECTED, REMOVED)
            # não devem expor friendship_id nem influenciar o relationship_status.
            Friendship.status.in_({"PENDING", "ACCEPTED"}),
        )
    ).all()
    by_other = {
        (row.user_b_id if row.user_a_id == actor_id else row.user_a_id): row
        for row in friendships
    }
    items = []
    for user in users:
        relation = by_other.get(user.id)
        relation_status = "NONE"
        friendship_id = None
        if relation is not None:
            friendship_id = relation.id
            if relation.status == "ACCEPTED":
                relation_status = "FRIENDS"
            elif relation.status == "PENDING":
                relation_status = "REQUEST_SENT" if relation.requested_by_id == actor_id else "REQUEST_RECEIVED"
        items.append({
            "id": user.id,
            "username": user.username,
            "relationship_status": relation_status,
            "friendship_id": friendship_id,
        })
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def _friendship_response(db: Session, row: Friendship, actor_id: int):
    other_id = row.user_b_id if row.user_a_id == actor_id else row.user_a_id
    other = db.get(User, other_id)
    if other is None:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")
    return {
        "friendship_id": row.id,
        "user_id": other.id,
        "username": other.username,
        "status": row.status,
        "created_at": row.created_at,
        "responded_at": row.responded_at,
    }


def list_relationships(db: Session, actor_id: int, kind: str, limit: int, offset: int):
    query = select(Friendship).where(
        Friendship.status == ("ACCEPTED" if kind == "friends" else "PENDING")
    )
    if kind == "friends":
        query = query.where(or_(Friendship.user_a_id == actor_id, Friendship.user_b_id == actor_id))
    elif kind == "received":
        query = query.where(
            or_(Friendship.user_a_id == actor_id, Friendship.user_b_id == actor_id),
            Friendship.requested_by_id != actor_id,
        )
    else:
        query = query.where(
            or_(Friendship.user_a_id == actor_id, Friendship.user_b_id == actor_id),
            Friendship.requested_by_id == actor_id,
        )
    rows_total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Friendship.created_at.desc(), Friendship.id.desc()).limit(limit).offset(offset)).all()
    items = [_friendship_response(db, row, actor_id) for row in rows]
    return {"items": items, "total": rows_total, "limit": limit, "offset": offset}


def create_friend_request(db: Session, actor_id: int, recipient_id: int):
    if actor_id == recipient_id:
        raise HTTPException(status_code=400, detail="Não é possível enviar solicitação para si mesmo.")
    _lock_users(db, actor_id, recipient_id)
    recipient = db.get(User, recipient_id)
    if recipient is None or not recipient.is_active or _blocked_between(db, actor_id, recipient_id):
        db.rollback()
        raise HTTPException(status_code=404, detail="Usuário não encontrado ou indisponível.")
    privacy = db.get(UserPrivacySettings, recipient_id)
    if privacy is not None and not privacy.allow_friend_requests:
        db.rollback()
        raise HTTPException(status_code=404, detail="Usuário não encontrado ou indisponível.")

    low, high = sorted((actor_id, recipient_id))
    row = db.scalar(
        select(Friendship).where(Friendship.user_a_id == low, Friendship.user_b_id == high).with_for_update()
    )
    if row is not None and row.status in {"PENDING", "ACCEPTED"}:
        db.rollback()
        raise HTTPException(status_code=409, detail="Já existe uma relação ou solicitação entre os usuários.")
    now = datetime.now(timezone.utc)
    try:
        if row is None:
            row = Friendship(user_a_id=low, user_b_id=high, requested_by_id=actor_id, status="PENDING")
            db.add(row)
        else:
            row.requested_by_id = actor_id
            row.status = "PENDING"
            row.created_at = now
            row.responded_at = None
        db.commit()
        db.refresh(row)
        return _friendship_response(db, row, actor_id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Já existe uma solicitação entre os usuários.")


def _load_actor_relationship(db: Session, actor_id: int, friendship_id: int):
    # Primeiro localiza os participantes apenas dentro do escopo do ator, sem
    # lock. Todas as mutações sociais bloqueiam os usuários em ordem crescente
    # antes de bloquear a amizade, evitando o ciclo amizade -> usuários contra
    # usuários -> amizade.
    pair = db.execute(
        select(Friendship.user_a_id, Friendship.user_b_id).where(
            Friendship.id == friendship_id,
            or_(Friendship.user_a_id == actor_id, Friendship.user_b_id == actor_id),
        )
    ).one_or_none()
    if pair is None:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")

    _lock_users(db, pair.user_a_id, pair.user_b_id)
    row = db.scalar(
        select(Friendship)
        .where(
            Friendship.id == friendship_id,
            or_(Friendship.user_a_id == actor_id, Friendship.user_b_id == actor_id),
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")
    return row


def respond_friend_request(db: Session, actor_id: int, friendship_id: int, action: str):
    row = _load_actor_relationship(db, actor_id, friendship_id)
    if row.status != "PENDING":
        db.rollback()
        raise HTTPException(status_code=409, detail="A solicitação não está pendente.")
    if row.requested_by_id == actor_id:
        db.rollback()
        raise HTTPException(status_code=403, detail="Somente o destinatário pode responder à solicitação.")
    row.status = "ACCEPTED" if action == "accept" else "REJECTED"
    row.responded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _friendship_response(db, row, actor_id)


def cancel_friend_request(db: Session, actor_id: int, friendship_id: int):
    row = _load_actor_relationship(db, actor_id, friendship_id)
    if row.status != "PENDING":
        db.rollback()
        raise HTTPException(status_code=409, detail="A solicitação não está pendente.")
    if row.requested_by_id != actor_id:
        db.rollback()
        raise HTTPException(status_code=403, detail="Somente o remetente pode cancelar a solicitação.")
    row.status = "CANCELLED"
    row.responded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _friendship_response(db, row, actor_id)


def remove_friend(db: Session, actor_id: int, other_id: int):
    if actor_id == other_id:
        raise HTTPException(status_code=404, detail="Amizade não encontrada.")
    _lock_users(db, actor_id, other_id)
    low, high = sorted((actor_id, other_id))
    row = db.scalar(
        select(Friendship).where(
            Friendship.user_a_id == low,
            Friendship.user_b_id == high,
            Friendship.status == "ACCEPTED",
        ).with_for_update()
    )
    if row is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Amizade não encontrada.")
    row.status = "REMOVED"
    row.responded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _friendship_response(db, row, actor_id)


def get_privacy_settings(db: Session, user_id: int):
    settings = db.get(UserPrivacySettings, user_id)
    if settings is None:
        return {"allow_messages_from_strangers": False, "allow_friend_requests": True}
    return {
        "allow_messages_from_strangers": settings.allow_messages_from_strangers,
        "allow_friend_requests": settings.allow_friend_requests,
    }


def update_privacy_settings(db: Session, user_id: int, changes: dict):
    db.scalar(select(User).where(User.id == user_id).with_for_update())
    settings = db.get(UserPrivacySettings, user_id)
    if settings is None:
        settings = UserPrivacySettings(user_id=user_id)
        db.add(settings)
    for key, value in changes.items():
        setattr(settings, key, value)
    db.commit()
    db.refresh(settings)
    # Retorna diretamente os valores do objeto já refreshado — sem releitura.
    return {
        "allow_messages_from_strangers": settings.allow_messages_from_strangers,
        "allow_friend_requests": settings.allow_friend_requests,
    }

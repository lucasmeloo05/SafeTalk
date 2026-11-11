
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fastapi import HTTPException, status

from app.models import (
    Block,
    Conversation,
    ConversationParticipant,
    Friendship,
    User,
    UserPrivacySettings,
)


def create_or_get_direct_conversation(
    db: Session,
    current_user: User,
    recipient_id: int,
) -> Conversation:
    if current_user.id == recipient_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Você não pode criar uma conversa consigo mesmo.",
        )

    recipient = db.get(User, recipient_id)

    if recipient is None or not recipient.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado.",
        )

    # Verifica se existe bloqueio em qualquer direção.
    block_exists = db.scalar(
        select(Block.id).where(
            or_(
                and_(
                    Block.blocker_id == current_user.id,
                    Block.blocked_id == recipient_id,
                ),
                and_(
                    Block.blocker_id == recipient_id,
                    Block.blocked_id == current_user.id,
                ),
            )
        )
    )

    if block_exists is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Não é possível iniciar uma conversa com este usuário.",
        )

    # Normaliza os IDs para consultar a amizade.
    user_a_id = min(current_user.id, recipient_id)
    user_b_id = max(current_user.id, recipient_id)

    friendship = db.scalar(
        select(Friendship).where(
            Friendship.user_a_id == user_a_id,
            Friendship.user_b_id == user_b_id,
            Friendship.status == "ACCEPTED",
        )
    )

    # Usuários que não são amigos dependem da configuração
    # de privacidade do destinatário.
    if friendship is None:
        privacy_settings = db.get(
            UserPrivacySettings,
            recipient_id,
        )

        if (
            privacy_settings is None
            or not privacy_settings.allow_messages_from_strangers
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Este usuário não permite mensagens "
                    "de pessoas que não são amigas."
                ),
            )

    # Verifica se já existe uma conversa entre os usuários.
    existing_conversation = db.scalar(
        select(Conversation).where(
            Conversation.type == "DIRECT",
            Conversation.user_a_id == user_a_id,
            Conversation.user_b_id == user_b_id,
        )
    )

    if existing_conversation is not None:
        return existing_conversation

    # Cria a conversa individual.
    conversation = Conversation(
        type="DIRECT",
        user_a_id=user_a_id,
        user_b_id=user_b_id,
        created_by=current_user.id,
    )

    try:
        db.add(conversation)
        db.flush()

        # Registra os dois usuários como participantes ativos.
        participants = [
            ConversationParticipant(
                conversation_id=conversation.id,
                user_id=current_user.id,
                role="MEMBER",
                status="ACTIVE",
            ),
            ConversationParticipant(
                conversation_id=conversation.id,
                user_id=recipient_id,
                role="MEMBER",
                status="ACTIVE",
            ),
        ]

        db.add_all(participants)
        db.commit()
        db.refresh(conversation)

        return conversation

    except IntegrityError:
        db.rollback()

        # Outra requisição pode ter criado a conversa
        # simultaneamente. Nesse caso, recuperamos a existente.
        existing_conversation = db.scalar(
            select(Conversation).where(
                Conversation.type == "DIRECT",
                Conversation.user_a_id == user_a_id,
                Conversation.user_b_id == user_b_id,
            )
        )

        if existing_conversation is not None:
            return existing_conversation

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não foi possível criar a conversa.",
        )

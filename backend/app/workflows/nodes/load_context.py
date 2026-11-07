from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.db.repositories.conversation_repo import ConversationRepository
from app.services.conversation_recent_cache import ConversationRecentCache
from app.services.active_session_service import mark_active_session
from app.workflows.rag_state import ChatContextMessage, RAGState
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


async def load_context(
    state: RAGState, session: AsyncSession, user_id: UUID
) -> RAGState:
    limit = settings.chat_history_window * 2
    cache = ConversationRecentCache()
    try:
        cached = await cache.get(user_id, state["conversation_id"])
    except Exception:
        # Redis 只是缓存，故障时回源数据库。
        logger.warning(
            "recent conversation cache read failed: conversation_id=%s",
            state["conversation_id"],
            exc_info=True,
        )
        cached = None

    if cached is not None:
        await mark_active_session(user_id, state["conversation_id"])
        return {"chat_history": cached}

    repo = ConversationRepository(session)

    history = await repo.recent_messages(
        state["conversation_id"],  # type: ignore
        limit=limit,  # type: ignore
    )

    try:
        await cache.replace(user_id, state["conversation_id"], history)
    except Exception:
        # Redis 只是缓存，数据库回源结果仍可继续用于本次问答。
        try:
            await cache.delete(user_id, state["conversation_id"])
        except Exception:
            logger.warning(
                "recent conversation stale cache cleanup failed: conversation_id=%s",
                state["conversation_id"],
                exc_info=True,
            )
        logger.warning(
            "recent conversation cache fill failed: conversation_id=%s",
            state["conversation_id"],
            exc_info=True,
        )
    await mark_active_session(user_id, state["conversation_id"])

    return {
        "chat_history": [
            ChatContextMessage(role=message.role, content=message.content)
            for message in history
        ]
    }

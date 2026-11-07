"""活跃会话 Redis 标记。"""

from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis

logger = get_logger(__name__)


def _active_session_key(user_id: UUID, conversation_id: UUID) -> str:
    return f"rag:active_session:{user_id}:{conversation_id}"


async def mark_active_session(user_id: UUID, conversation_id: UUID) -> None:
    """标记会话活跃，并在无新活动 30 分钟后自动过期。"""
    try:
        await get_redis().set(
            _active_session_key(user_id, conversation_id),
            "1",
            ex=settings.active_session_ttl_seconds,
        )
    except Exception:
        logger.warning("failed to mark active session", exc_info=True)


async def clear_active_session(user_id: UUID, conversation_id: UUID) -> None:
    try:
        await get_redis().delete(_active_session_key(user_id, conversation_id))
    except Exception:
        logger.warning("failed to clear active session", exc_info=True)

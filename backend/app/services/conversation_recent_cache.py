"""活跃会话最近消息缓存。数据库仍是唯一权威来源。"""

import json
from collections.abc import Sequence
from datetime import timezone
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.db.models import Message, MessageRole
from app.workflows.rag_state import ChatContextMessage

logger = get_logger(__name__)

_REPLACE_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current then
  local ok, data = pcall(cjson.decode, current)
  if ok and data['version'] and data['version'] >= ARGV[1] then
    redis.call('EXPIRE', KEYS[1], ARGV[2])
    return 0
  end
end
redis.call('SET', KEYS[1], ARGV[3], 'EX', ARGV[2])
return 1
"""


def _cache_key(user_id: UUID, conversation_id: UUID) -> str:
    return f"rag:conversation:recent:{user_id}:{conversation_id}"


def _version(message: Message) -> str:
    created_at = message.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return f"{created_at.isoformat()}|{message.id}"


def _payload(messages: Sequence[Message]) -> tuple[str, str]:
    version = _version(messages[-1]) if messages else ""
    payload = {
        "version": version,
        "messages": [
            {
                "role": (
                    message.role.value
                    if isinstance(message.role, MessageRole)
                    else message.role
                ),
                "content": message.content,
            }
            for message in messages
        ],
    }
    return version, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class ConversationRecentCache:
    def __init__(self) -> None:
        self.redis = get_redis()

    async def get(
        self, user_id: UUID, conversation_id: UUID
    ) -> list[ChatContextMessage] | None:
        key = _cache_key(user_id, conversation_id)
        raw = await self.redis.get(key)
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict) or not isinstance(
                payload.get("version"), str
            ):
                raise ValueError("version must be a string")
            messages = payload["messages"]
            if not isinstance(messages, list):
                raise ValueError("messages must be a list")
            if any(
                not isinstance(item, dict)
                or not isinstance(item.get("role"), str)
                or not isinstance(item.get("content"), str)
                for item in messages
            ):
                raise ValueError("invalid cached message")
            result = [
                ChatContextMessage(
                    role=MessageRole(item["role"]), content=item["content"]
                )
                for item in messages
            ]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("recent conversation cache is invalid: key=%s", key)
            await self.redis.delete(key)
            return None
        await self.redis.expire(key, settings.conversation_recent_cache_ttl_seconds)
        return result

    async def replace(
        self,
        user_id: UUID,
        conversation_id: UUID,
        messages: Sequence[Message],
    ) -> None:
        version, payload = _payload(messages)
        await self.redis.eval(
            _REPLACE_SCRIPT,
            1,
            _cache_key(user_id, conversation_id),
            version,
            settings.conversation_recent_cache_ttl_seconds,
            payload,
        )

    async def delete(self, user_id: UUID, conversation_id: UUID) -> None:
        await self.redis.delete(_cache_key(user_id, conversation_id))

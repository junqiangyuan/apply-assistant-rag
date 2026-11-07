import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.core.config import settings
from app.db.models import Message, MessageRole
from app.services.conversation_recent_cache import ConversationRecentCache


class FakeRedis:
    def __init__(self, value: str | None = None) -> None:
        self.value = value
        self.expire_calls: list[tuple[str, int]] = []
        self.deleted: list[str] = []
        self.eval_calls: list[tuple[object, ...]] = []

    async def get(self, key: str) -> str | None:
        return self.value

    async def expire(self, key: str, seconds: int) -> None:
        self.expire_calls.append((key, seconds))

    async def delete(self, key: str) -> None:
        self.deleted.append(key)

    async def eval(self, *args: object) -> None:
        self.eval_calls.append(args)


def _message(role: MessageRole, content: str) -> Message:
    return Message(
        id=uuid4(),
        conversation_id=uuid4(),
        role=role,
        content=content,
        created_at=datetime.now(timezone.utc),
    )


def test_cache_hit_returns_context_and_refreshes_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    value = json.dumps({"version": "v1", "messages": [{"role": "user", "content": "你好"}]})
    redis = FakeRedis(value)
    monkeypatch.setattr("app.services.conversation_recent_cache.get_redis", lambda: redis)

    user_id = UUID("11111111-1111-1111-1111-111111111111")
    conversation_id = UUID("22222222-2222-2222-2222-222222222222")
    result = asyncio.run(ConversationRecentCache().get(user_id, conversation_id))

    assert result is not None
    assert result[0].role is MessageRole.USER
    assert result[0].content == "你好"
    assert redis.expire_calls == [
        (
            "rag:conversation:recent:11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
            settings.conversation_recent_cache_ttl_seconds,
        )
    ]


def test_invalid_cache_is_deleted_and_misses(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis("not-json")
    monkeypatch.setattr("app.services.conversation_recent_cache.get_redis", lambda: redis)

    result = asyncio.run(ConversationRecentCache().get(UUID(int=1), UUID(int=2)))

    assert result is None
    assert redis.deleted == [
        "rag:conversation:recent:00000000-0000-0000-0000-000000000001:00000000-0000-0000-0000-000000000002"
    ]


def test_replace_uses_atomic_versioned_write(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr("app.services.conversation_recent_cache.get_redis", lambda: redis)
    messages = [_message(MessageRole.USER, "你好")]

    asyncio.run(ConversationRecentCache().replace(UUID(int=1), UUID(int=2), messages))

    assert len(redis.eval_calls) == 1
    assert redis.eval_calls[0][1] == 1
    assert redis.eval_calls[0][4] == settings.conversation_recent_cache_ttl_seconds


def test_replace_accepts_string_role_from_database(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr("app.services.conversation_recent_cache.get_redis", lambda: redis)
    messages = [_message("user", "数据库消息")]  # type: ignore[arg-type]

    asyncio.run(ConversationRecentCache().replace(UUID(int=1), UUID(int=2), messages))

    payload = json.loads(redis.eval_calls[0][5])
    assert payload["messages"] == [{"role": "user", "content": "数据库消息"}]

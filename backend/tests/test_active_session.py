from uuid import UUID
import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services.active_session_service import mark_active_session


def test_mark_active_session_sets_30_minute_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = AsyncMock()
    monkeypatch.setattr(
        "app.services.active_session_service.get_redis", lambda: redis
    )

    user_id = UUID("11111111-1111-1111-1111-111111111111")
    conversation_id = UUID("22222222-2222-2222-2222-222222222222")

    asyncio.run(mark_active_session(user_id, conversation_id))

    redis.set.assert_awaited_once_with(
        "rag:active_session:11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        "1",
        ex=1800,
    )

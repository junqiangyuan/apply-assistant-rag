import asyncio
import importlib
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.db.models import MessageRole
from app.workflows.nodes.load_context import load_context
from app.workflows.rag_state import ChatContextMessage

load_context_module = importlib.import_module("app.workflows.nodes.load_context")


def test_load_context_prefers_recent_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    cached = [ChatContextMessage(MessageRole.USER, "缓存消息")]

    class Cache:
        async def get(self, user_id: UUID, conversation_id: UUID):
            return cached

    monkeypatch.setattr(load_context_module, "ConversationRecentCache", Cache)
    monkeypatch.setattr(
        load_context_module,
        "mark_active_session",
        lambda *_: asyncio.sleep(0),
    )

    session = SimpleNamespace()
    state = {"conversation_id": UUID(int=1), "question": "问题"}
    result = asyncio.run(load_context(state, session, UUID(int=2)))

    assert result == {"chat_history": cached}


def test_load_context_falls_back_to_database_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    message = SimpleNamespace(role=MessageRole.ASSISTANT, content="数据库消息")

    class Repo:
        def __init__(self, session):
            pass

        async def recent_messages(self, conversation_id, limit):
            assert limit == 10
            return [message]

    class Cache:
        def __init__(self):
            self.replaced = None

        async def get(self, user_id, conversation_id):
            return None

        async def replace(self, user_id, conversation_id, messages):
            self.replaced = messages

    cache = Cache()
    monkeypatch.setattr(load_context_module, "ConversationRepository", Repo)
    monkeypatch.setattr(load_context_module, "ConversationRecentCache", lambda: cache)
    monkeypatch.setattr(
        load_context_module,
        "mark_active_session",
        lambda *_: asyncio.sleep(0),
    )

    result = asyncio.run(
        load_context(
            {"conversation_id": UUID(int=1), "question": "问题"},
            SimpleNamespace(),
            UUID(int=2),
        )
    )

    assert result["chat_history"] == [
        ChatContextMessage(MessageRole.ASSISTANT, "数据库消息")
    ]
    assert cache.replaced == [message]

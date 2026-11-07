import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.services.chat_service as chat_module
from app.core.config import settings
from app.llm.prompts import REFUSAL_ANSWER
from app.services.chat_service import ChatService


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def rollback(self) -> None:
        return None


class _Graph:
    async def ainvoke(self, state):
        # 走图内拒答，避免真正调用 LLM；本测试只关心缓存是否被查 / 写
        return {"refused": True, "answer": REFUSAL_ANSWER, "query": state["question"]}


def _run(monkeypatch, history: list) -> list[str]:
    lookups: list[str] = []

    async def fake_lookup(self, question, permissions):
        lookups.append(question)
        return None, [0.1]

    async def fake_load_context(state, session, user_id):
        return {"chat_history": history}

    async def noop(*args, **kwargs):
        return None

    async def fake_persist_user(self, state, session, user_id):
        state["user_message_id"] = uuid4()

    async def fake_persist_assistant(self, state, session, *, user_id, verify_result):
        state["assistant_message_id"] = uuid4()

    monkeypatch.setattr(settings, "semantic_cache_enabled", True)
    monkeypatch.setattr(ChatService, "get_conversation", noop)
    monkeypatch.setattr(ChatService, "_try_cache_lookup", fake_lookup)
    monkeypatch.setattr(ChatService, "_persist_user_message", fake_persist_user)
    monkeypatch.setattr(ChatService, "_persist_assistant_message", fake_persist_assistant)
    monkeypatch.setattr(chat_module, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(chat_module, "load_context", fake_load_context)
    monkeypatch.setattr(chat_module, "get_rag_graph", lambda: _Graph())
    monkeypatch.setattr(chat_module, "compute_user_permission_tags", lambda user: ["public"])

    async def consume():
        service = ChatService(session=None)  # type: ignore[arg-type]
        user = SimpleNamespace(id=uuid4())
        return [e["event"] async for e in service.stream_answer(uuid4(), "那 MSDS 呢？", current_user=user)]

    events = asyncio.run(consume())
    assert events[-1] == "message_end", events
    return lookups


def test_follow_up_with_history_skips_semantic_cache(monkeypatch) -> None:
    history = [SimpleNamespace(role="user", content="北岸理工 MSCS 的雅思要求？")]
    assert _run(monkeypatch, history) == []


def test_first_turn_uses_semantic_cache(monkeypatch) -> None:
    assert _run(monkeypatch, []) == ["那 MSDS 呢？"]

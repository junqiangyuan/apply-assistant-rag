import asyncio
from uuid import uuid4

from app.core.config import settings
from app.llm.prompts import REFUSAL_ANSWER, build_answer_messages, is_refusal_answer
from app.retrieval.vector_retriever import RetrievedChunk
from app.workflows.nodes.judge_context import judge_context
from app.workflows.nodes.rerank import rerank


def _chunk(vector_score: float | None = 0.7, rerank_score: float | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_name="doc.md",
        content="内容",
        page_no=None,
        section_path=None,
        score=0.01,
        vector_score=vector_score,
        rerank_score=rerank_score,
    )


def test_rerank_disabled_still_truncates_to_top_k(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rerank_enabled", False)
    monkeypatch.setattr(settings, "retrieval_top_k", 5)
    chunks = [_chunk() for _ in range(20)]

    result = asyncio.run(rerank({"query": "q", "retrieved_chunks": chunks}))

    assert result["retrieved_chunks"] == chunks[:5]


def test_judge_without_rerank_uses_vector_threshold(monkeypatch) -> None:
    monkeypatch.setattr(settings, "retrieval_min_score", 0.6)
    monkeypatch.setattr(settings, "rerank_min_score", 0.3)

    low = asyncio.run(judge_context({"retrieved_chunks": [_chunk(vector_score=0.45)]}))
    high = asyncio.run(judge_context({"retrieved_chunks": [_chunk(vector_score=0.65)]}))

    assert low["context_is_enough"] is False
    assert high["context_is_enough"] is True


def test_judge_with_rerank_uses_rerank_threshold(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rerank_min_score", 0.3)
    chunks = [_chunk(vector_score=0.9, rerank_score=0.1)]

    assert asyncio.run(judge_context({"retrieved_chunks": chunks}))["context_is_enough"] is False


def test_is_refusal_answer_matches_unified_and_legacy_text() -> None:
    assert is_refusal_answer(REFUSAL_ANSWER)
    assert is_refusal_answer(f"  “{REFUSAL_ANSWER}”\n")
    assert is_refusal_answer("抱歉，知识库中没有找到相关信息。")
    assert not is_refusal_answer("MSCS 要求 GPA 不低于 3.3 [1]。")
    assert not is_refusal_answer(f"{REFUSAL_ANSWER} 不过北岸理工要求雅思 7.0 [1]。")
    assert not is_refusal_answer("")


def test_answer_prompt_instructs_unified_refusal_text() -> None:
    messages = build_answer_messages("哈佛的雅思要求？", [_chunk()], [])
    assert REFUSAL_ANSWER in messages[0].content

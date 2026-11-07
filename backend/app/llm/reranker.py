import dataclasses
from typing import Any

import httpx
from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.retrieval.vector_retriever import RetrievedChunk
from langsmith import traceable

logger = get_logger(__name__)


class Reranker:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=settings.rerank_timeout)
        return self._client

    @traceable(name="Reranker.rerank", run_type="tool")
    async def rerank(
        self, query: str, candidates: list[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        if len(candidates) <= 1:
            return candidates

        api_key = settings.effective_rerank_api_key
        if not api_key:
            raise ConfigurationError("Rerank API key 未配置")

        try:
            scores = await self._fetch_scores(query, candidates, api_key)
        except Exception:
            logger.exception("rerank 调用失败，降级为不重排: query=%r", query)
            return candidates

        ranked = [
            dataclasses.replace(chunk, rerank_score=score)
            for chunk, score in zip(candidates, scores, strict=False)
        ]
        ranked.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        return ranked

    async def _fetch_scores(
        self, query: str, candidates: list[RetrievedChunk], api_key: str
    ) -> list[float]:
        payload: dict[str, Any] = {
            "model": settings.rerank_model,
            "query": query,
            "documents": [c.content for c in candidates],
            "top_n": len(candidates),
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        client = self._get_client()
        response = await client.post(
            settings.rerank_base_url, json=payload, headers=headers
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results") or []
        if not isinstance(results, list) or len(results) == 0:
            raise ValueError(f"rerank 响应缺少 resulits:{data!r}")

        scores: list[float] = [0.0] * len(candidates)
        for item in results:
            idx = item.get("index")
            score = item.get("relevance_score")
            if not isinstance(idx, int) or not isinstance(score, int | float):
                continue
            if 0 <= idx < len(scores):
                scores[idx] = float(score)
        return scores


_reranker: Reranker | None = None


def get_reranker() -> Reranker:
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker

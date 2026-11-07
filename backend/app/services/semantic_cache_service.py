import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache

from app.core.config import settings
from app.core.logging import get_logger
from redisvl.extensions.cache.llm import SemanticCache
from redisvl.query.filter import Tag
from redisvl.utils.vectorize import CustomTextVectorizer

_CACHE_NAME = "rag_semantic_chache"
_SCOPE_FIELD = "permission_scope"


def _scope_key(permission_scope: list[str]) -> str:
    """权限集合序列化成 集合相等的可比较TAG值，严格控制回答权限
    避免缓存非相同权限回答
    Args:
        permission_scope (list[str]): _description_

    Returns:
        str: _description_
    """
    canonical = "\x00".join(sorted(permission_scope))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _stub_embed(text: str, **_: object) -> list[float]:
    return [0.0] * settings.embedding_dim


logger = get_logger(__name__)


@dataclass(frozen=True)
class CacheAnswer:
    answer: str
    citations: list[dict]
    cached_question: str


class SemanticCacheService:
    def __init__(self) -> None:
        self._cache = SemanticCache(
            name=_CACHE_NAME,
            redis_url=settings.redis_url,
            distance_threshold=1.0 - settings.semantic_cache_min_similarity,
            ttl=settings.semantic_cache_ttl_seconds,
            vectorizer=CustomTextVectorizer(_stub_embed),
            filterable_fields=[{"name": _SCOPE_FIELD, "type": "tag"}],
            overwrite=False,
        )

    async def lookup(
        self,
        query_embedding: list[float],
        permission_scope: list[str],
    ) -> CacheAnswer | None:
        scope = _scope_key(permission_scope)
        try:
            hits = await self._cache.acheck(
                vector=query_embedding,
                filter_expression=Tag(_SCOPE_FIELD) == scope,
                num_results=1,
                return_fields=["prompt", "response", "metadata"],
            )
        except Exception:
            logger.exception("semantic cache lookup failed,treat as miss")
            return None

        if not hits:
            return None

        hit = hits[0]
        metadata = hit.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}
        return CacheAnswer(
            answer=hit.get("response", ""),
            citations=metadata.get("citations", []),
            cached_question=hit.get("prompt", ""),
        )

    async def save(
        self,
        *,
        question: str,
        query_embedding: list[float],
        answer: str,
        citations: list[dict],
        permission_scope: list[str],
    ) -> None:
        try:
            await self._cache.astore(
                prompt=question,
                response=answer,
                vector=query_embedding,
                metadata={"citations": citations},
                filters={_SCOPE_FIELD: _scope_key(permission_scope)},
            )
        except Exception:
            logger.exception("semantic cache save failed,skip")


@lru_cache(maxsize=1)
def get_semantic_cache() -> SemanticCacheService:
    return SemanticCacheService()

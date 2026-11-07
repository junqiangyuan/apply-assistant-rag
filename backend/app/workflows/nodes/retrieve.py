from app.core.config import settings
from app.retrieval.vector_retriever import RetrievedChunk, VectorRetriever
from app.retrieval.hybrid_retriever import HybridRetriever
from app.workflows.rag_state import RAGState
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.logging import get_logger

logger = get_logger(__name__)


async def retrieve(state: RAGState) -> RAGState:
    retriever = HybridRetriever()
    recall_top_k = settings.retrieval_recall_top_k
    permissions = state.get("permissions")

    if state.get("route") == "multi_query" and state.get("multi_queries"):
        bundles: list[list[RetrievedChunk]] = []
        for sub_query in state["multi_queries"] or []:  # type: ignore
            bundles.append(
                await retriever.search(
                    sub_query,
                    recall_top_k=recall_top_k,
                    final_top_k=recall_top_k,
                    permission_tags=permissions,
                )
            )
        chunks = _merge_chunks(bundles, top_k=recall_top_k)
    else:
        chunks = await retriever.search(
            state["query"],  # type: ignore
            recall_top_k=recall_top_k,
            final_top_k=recall_top_k,  # type: ignore
            permission_tags=permissions,
        )  # type: ignore
    return {"retrieved_chunks": chunks}


def _should_refuse(chunks: list[RetrievedChunk]) -> bool:
    if not chunks:
        return True
    top = chunks[0]
    if top.vector_score is None:
        return True  # Top1 仅命中关键词路，缺乏语义作证
    return top.vector_score < settings.retrieval_min_score


def _merge_chunks(
    bundles: list[list[RetrievedChunk]], top_k: int
) -> list[RetrievedChunk]:
    """多路召回结果去重+ 取top-k

    同一个chunk 可能在多条子查询命中，保留最高得分，在按得分降序取top-k

    multi_query_coun * 单路召回时间 约增加 1s耗时，成本增加

    Args:
        bundles (list[list[RetrievedChunk]]): _description_
        top_k (int): _description_

    Returns:
        list[RetrievedChunk]: _description_
    """
    best: dict[str, RetrievedChunk] = {}
    for bundle in bundles:
        for chunk in bundle:
            key = str(chunk.chunk_id)
            prev = best.get(key)
            if prev is None or (chunk.rrf_score or 0.0) > (prev.rrf_score or 0.0):
                best[key] = chunk
    ranked = sorted(best.values(), key=lambda c: c.rrf_score or 0.0, reverse=True)
    return ranked[:top_k]

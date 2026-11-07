from app.core.config import settings
from app.llm.reranker import get_reranker
from app.workflows.rag_state import RAGState


async def rerank(state: RAGState) -> RAGState:
    chunks = state.get("retrieved_chunks", [])
    if not settings.rerank_enabled or len(chunks) <= 1:
        return {}

    reranked = await get_reranker().rerank(state["query"], chunks)  # type: ignore
    ## 召回可以多一些，最后排序阶段只保留最靠前的几条
    return {"retrieved_chunks": reranked[: settings.retrieval_top_k]}

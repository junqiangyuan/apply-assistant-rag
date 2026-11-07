from app.core.config import settings
from app.llm.reranker import get_reranker
from app.workflows.rag_state import RAGState


async def rerank(state: RAGState) -> RAGState:
    chunks = state.get("retrieved_chunks", [])
    if not settings.rerank_enabled or len(chunks) <= 1:
        # 召回阶段按 retrieval_recall_top_k 取了较多候选；不重排时也必须截到 top_k，
        # 否则全部召回结果都会进入生成上下文和引用列表
        return {"retrieved_chunks": chunks[: settings.retrieval_top_k]}

    reranked = await get_reranker().rerank(state["query"], chunks)  # type: ignore
    ## 召回可以多一些，最后排序阶段只保留最靠前的几条
    return {"retrieved_chunks": reranked[: settings.retrieval_top_k]}

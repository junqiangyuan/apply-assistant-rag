from app.core.config import settings
from app.workflows.rag_state import RAGState


async def judge_context(state: RAGState) -> RAGState:
    chunks = state.get("retrieved_chunks", [])
    if not chunks:
        return {"context_is_enough": False}

    top = chunks[0]
    if top.rerank_score is not None:
        is_enough = top.rerank_score >= settings.rerank_min_score
    elif top.vector_score is not None:
        # 未重排时只有向量相似度，必须用向量阈值；rerank_min_score 是另一种分数的刻度，
        # 拿来比较向量分数几乎永远成立，拒答就形同虚设
        is_enough = top.vector_score >= settings.retrieval_min_score
    else:
        is_enough = False
    return {"context_is_enough": is_enough}

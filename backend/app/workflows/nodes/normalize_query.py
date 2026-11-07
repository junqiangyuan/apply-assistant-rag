from app.llm.query_rewriter import get_query_rewriter
from app.workflows.rag_state import RAGState


async def normalize_query(state: RAGState) -> RAGState:  # type: ignore
    history = state.get("chat_history", [])
    if not history:
        return {"query": state["question"]}  # type: ignore
    rewritten = await get_query_rewriter().contextualize(
        question=state["question"],  # type: ignore
        history=history,  # type: ignore
    )
    return {"query": rewritten}
from app.core.config import settings
from app.core.logging import get_logger
from app.workflows.nodes import (
    judge_context,
    normalize_query,
    observe_context,
    plan_retrieval,
    refuse,
    rerank,
    retrieve,
    route_query,
)
from app.workflows.rag_state import RAGState
from langgraph.graph import END, START, StateGraph

logger = get_logger(__name__)


def _after_plan(state: RAGState) -> str:
    if state.get("agent_steps"):
        last_action = state["agent_steps"][-1].get("action")  # type: ignore
        if last_action == "refuse":
            return "refuse"
    return "retrieve"


def _after_observe(state: RAGState) -> str:
    if not settings.agent_loop_enabled:
        return "rerank"
    if state.get("context_sufficient"):
        return "rerank"
    if state.get("retrieval_round", 0) >= settings.agent_max_rounds:
        return "rerank"
    return "plan"


def _after_judge(state: RAGState) -> str:
    if state.get("context_is_enough"):
        return "end"
    return "refuse"


def _build_graph():
    builder = StateGraph(RAGState)

    builder.add_node("normalize_query", normalize_query)
    builder.add_node("route_query", route_query)
    builder.add_node("plan_retrieval", plan_retrieval)
    builder.add_node("retrieve", retrieve)
    builder.add_node("observe_context", observe_context)
    builder.add_node("rerank", rerank)
    builder.add_node("refuse", refuse)
    builder.add_node("judge_context", judge_context)

    builder.add_edge(START, "normalize_query")
    builder.add_edge("normalize_query", "route_query")
    builder.add_edge("route_query", "plan_retrieval")
    builder.add_conditional_edges(
        "plan_retrieval", _after_plan, {"retrieve": "retrieve", "refuse": "refuse"}
    )
    builder.add_edge("retrieve", "observe_context")
    builder.add_conditional_edges(
        "observe_context",
        _after_observe,
        {"plan": "plan_retrieval", "rerank": "rerank"},
    )
    builder.add_edge("rerank", "judge_context")
    builder.add_conditional_edges(
        "judge_context",
        _after_judge,
        {"end": END, "refuse": "refuse"},
    )
    builder.add_edge("refuse", END)

    return builder.compile()


_rag_graph = _build_graph()


def get_rag_graph():
    return _rag_graph


##./.venv/bin/python -c 'from app.workflows.graph import get_rag_graph; print(get_rag_graph().get_graph(xray=True).draw_mermaid())

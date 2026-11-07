from app.core.config import settings
from app.llm.agent_planner import get_agent_planner
from app.llm.query_rewriter import get_query_rewriter
from app.workflows.rag_state import QueryRoute, RAGState


async def plan_retrieval(state: RAGState) -> RAGState:
    steps = list(state.get("agent_steps", []))
    current_route: QueryRoute = state.get("route", "original")
    current_query = state.get("query") or state["question"]  # type: ignore
    if not steps:
        steps.append(
            {
                "round": 1,
                "action": "initial",
                "reason": "首轮检索沿用 route_query_决策",
                "route": current_route,
                "query": current_query,
            }
        )
        return {"agent_steps": steps}

    decision = await get_agent_planner().plan(
        question=state["query"],  # type: ignore
        current_query=current_query,
        current_route=current_route,
        previous_steps=steps,
    )

    update: RAGState = {}
    new_route = current_route
    new_query = current_query

    if decision.action == "rewrite_query" and decision.new_query:
        new_query = decision.new_query
        new_route = "original"
        update["query"] = new_query
        update["route"] = new_route
        update["rewritten_query"] = None
        update["hyde_answer"] = None
        update["multi_queries"] = None
    elif decision.action == "switch_route" and decision.new_route:
        # QueryRewriter 补齐路由的目标，避免只换标签不换行为
        rewriter = get_query_rewriter()
        result = await rewriter.apply_route(
            question=state["question"],  # type: ignore
            route=decision.new_route,
            multi_query_count=settings.multi_query_count,
        )
        new_route = result.route
        new_query = result.query
        update["route"] = new_route
        update["query"] = new_query
        update["rewritten_query"] = result.rewritten_query
        update["hyde_answer"] = result.hyde_answer
        update["multi_queries"] = result.multi_queries
    steps.append(
        {
            "round": len(steps) + 1,
            "action": decision.action,
            "reason": decision.reason,
            "route": new_route,
            "query": new_query,
        }
    )
    update["agent_steps"] = steps
    # 增加统一 refuse节点，无须其他节点处理
    return update

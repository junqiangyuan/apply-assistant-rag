import asyncio
from types import SimpleNamespace

import app.sql_agent.pipeline_demo as demo
from app.sql_agent.pipeline_demo import (
    METRIC_DOCUMENT_NAME,
    QueryQuad,
    SCHEMA,
    _after_parse,
    _metric_documents,
    build_pipeline,
)


def test_query_quad_and_schema_use_fully_qualified_tables() -> None:
    query = QueryQuad(metrics=["overdue_rate"], dimensions=["member_unit"], time_range="last_month")
    assert query.metrics == ["overdue_rate"]
    assert SCHEMA["metrics"]["overdue_rate"]["table"] == "nl2sql_demo.loan_records"


def test_empty_quad_routes_to_clarify() -> None:
    assert _after_parse({"parsed_query": QueryQuad()}) == "clarify"


def test_langgraph_has_seven_business_nodes() -> None:
    names = set(build_pipeline().get_graph().nodes)
    assert {"query_parse", "clarify", "semantic_match", "generate_sql", "validate_sql", "execute", "explain"} <= names


def test_metric_document_has_one_self_contained_chunk_per_yaml_metric() -> None:
    chunks = _metric_documents()
    assert len(chunks) == len(SCHEMA["metrics"])
    assert "指标键：overdue_rate" in chunks[0].page_content
    assert "别名：贷款逾期率、逾期率、超期比例、逾期多少" in chunks[0].page_content
    assert "业务含义：超过30天逾期贷款笔数占快照日贷款总笔数比例。" in chunks[0].page_content


def test_query_parse_only_retrieves_top3_metric_candidates(monkeypatch) -> None:
    captured = {}

    class Retriever:
        async def search(self, query, **kwargs):
            captured.update(kwargs)
            return [
                SimpleNamespace(content="指标键：overdue_rate\n指标名称：贷款逾期率"),
                SimpleNamespace(content="指标键：loan_balance\n指标名称：贷款余额"),
            ]

    class Model:
        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _prompt):
            return QueryQuad(metrics=["overdue_rate"])

    monkeypatch.setattr(demo, "HybridRetriever", Retriever)
    monkeypatch.setattr(demo, "get_chat_model", lambda: Model())
    state = asyncio.run(demo._query_parse({"question": "逾期多少"}))

    assert captured["final_top_k"] == 3
    assert captured["document_names"] == [METRIC_DOCUMENT_NAME]
    assert state["metric_candidates"] == ["overdue_rate", "loan_balance"]

"""PostgreSQL + Knowledge Base + LLM quadruple extraction demo."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

import yaml
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.core.config import settings
from app.db.models import Document, DocumentChunk, DocumentStatus
from app.db.repositories.chunk_repo import DocumentChunkRepository
from app.db.session import AsyncSessionLocal
from app.ingestion.embedder import get_embeddings
from app.llm.models import get_chat_model
from app.retrieval.hybrid_retriever import HybridRetriever
from app.sql_agent.sql_validator import validate_sql_ast

DEMO_SCHEMA = "nl2sql_demo"
SCHEMA_DOCUMENT_NAME = "nl2sql_demo_schema.yaml"
SCHEMA_PERMISSION = ["nl2sql-demo"]
SNAPSHOT_DATE = "2026-08-31"
SNAPSHOT = date(2026, 8, 31)
SCHEMA_FILE = Path(__file__).with_name(SCHEMA_DOCUMENT_NAME)
METRIC_DOCUMENT_NAME = "nl2sql_demo_metrics.yaml"

def _load_schema() -> dict[str, Any]:
    """严格加载语义层唯一事实源。"""
    loaded = yaml.safe_load(SCHEMA_FILE.read_text(encoding="utf-8")) or {}
    if not loaded.get("metrics") or not loaded.get("tables"):
        raise ValueError(f"语义层 YAML 缺少 metrics 或 tables：{SCHEMA_FILE}")
    return loaded


SCHEMA = _load_schema()


def _metric_documents() -> list[Any]:
    """把 YAML 指标转换成“一指标一 chunk”的自包含检索文本。"""
    from langchain_core.documents import Document as LCDocument

    chunks = []
    for index, (key, cfg) in enumerate(SCHEMA["metrics"].items()):
        content = (
            f"指标键：{key}\n"
            f"指标名称：{cfg.get('name', key)}\n"
            f"别名：{'、'.join(cfg.get('aliases', []))}\n"
            f"业务含义：{cfg.get('description', '')}"
        )
        chunks.append(
            LCDocument(
                page_content=content,
                metadata={
                    "source": METRIC_DOCUMENT_NAME,
                    "metric_key": key,
                    "chunk_index": index,
                    "chunk_hash": hashlib.md5(content.encode()).hexdigest(),
                },
            )
        )
    return chunks


class Filter(BaseModel):
    field: str
    operator: str = "="
    value: str


class QueryQuad(BaseModel):
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    time_range: str = ""


class PipelineState(TypedDict, total=False):
    question: str
    parsed_query: QueryQuad
    metric_candidates: list[str]
    schema_context: str
    matched_config: dict[str, Any] | None
    generated_sql: str
    sql_generation_mode: str
    validation_passed: bool
    validation_error: str
    parse_error: str
    retry_count: int
    clarify_count: int
    query_result: list[dict[str, Any]]
    explanation: str
    explain_mode: str
    llm_calls: int
    llm_calls_by_node: dict[str, int]
    skipped_nodes: list[str]
    node_trace: list[str]
    refused: bool
    refusal_reason: str


def _trace(s: PipelineState, node: str) -> None:
    s.setdefault("node_trace", []).append(node)


def _llm(s: PipelineState, node: str) -> None:
    s["llm_calls"] = s.get("llm_calls", 0) + 1
    calls = s.setdefault("llm_calls_by_node", {})
    calls[node] = calls.get(node, 0) + 1


async def _search(
    q: str, top_k: int = 4, *, document_names: list[str] | None = None
) -> str:
    hits = await HybridRetriever().search(
        q,
        recall_top_k=10,
        final_top_k=top_k,
        permission_tags=SCHEMA_PERMISSION,
        document_names=document_names or [SCHEMA_DOCUMENT_NAME],
    )
    return "\n\n---\n\n".join(h.content for h in hits)


async def _query_parse(s: PipelineState) -> PipelineState:
    _trace(s, "query_parse")
    hits = await HybridRetriever().search(
        s["question"],
        recall_top_k=10,
        final_top_k=3,
        permission_tags=SCHEMA_PERMISSION,
        document_names=[METRIC_DOCUMENT_NAME],
    )
    context = "\n\n---\n\n".join(h.content for h in hits)
    candidates = []
    for hit in hits:
        match = re.search(r"指标键：([A-Za-z0-9_]+)", hit.content)
        if match and match.group(1) not in candidates:
            candidates.append(match.group(1))
    prompt = f"提取指标、维度、过滤条件、时间范围四元组，只选候选指标，无法确定时 metrics 为空。候选 Top3：{candidates}\n参考：{context}\n问题：{s['question']}"
    try:
        model = get_chat_model()
        try:
            result = await model.with_structured_output(QueryQuad).ainvoke(prompt)
        except Exception:
            # 部分 OpenAI 兼容服务暂不支持 response_format；仍使用真实模型，
            # 退回严格 JSON 提示并由 Pydantic 校验，而不是规则解析。
            response = await model.ainvoke(
                prompt + "\n请只输出 JSON 对象，不要 Markdown。"
            )
            raw = (
                response.content
                if isinstance(response.content, str)
                else str(response.content)
            )
            raw = re.sub(
                r"^```(?:json)?\\s*|\\s*```$", "", raw.strip(), flags=re.IGNORECASE
            )
            result = QueryQuad.model_validate_json(raw)
    except Exception as exc:
        s["parse_error"] = f"四元组解析失败：{exc.__class__.__name__}"
        s["parsed_query"] = QueryQuad()
        return s
    _llm(s, "query_parse")
    s["metric_candidates"] = candidates
    s["parsed_query"] = result
    return s


def _after_parse(s: PipelineState) -> str:
    return (
        "clarify"
        if not s.get("parsed_query", QueryQuad()).metrics
        else "semantic_match"
    )


async def _clarify(s: PipelineState) -> PipelineState:
    _trace(s, "clarify")
    from langgraph.types import interrupt
    approved = interrupt("指标不明确或未配置?")
    s["clarify_count"] = s.get("clarify_count", 0) + 1
    s["refused"] = True
    s["refusal_reason"] = "指标不明确或未配置，澄清后安全拒绝执行。"
    return s


async def _semantic_match(s: PipelineState) -> PipelineState:
    _trace(s, "semantic_match")
    q = s["parsed_query"]
    if len(q.metrics) != 1:
        return s
    config = SCHEMA["metrics"].get(q.metrics[0])
    s["matched_config"] = config
    if config is None:
        return s
    invalid = [d for d in q.dimensions if d not in config["dimensions"]]
    if invalid:
        s["refused"] = True
        s["refusal_reason"] = f"维度不在白名单：{invalid}"
        return s
    select = ", ".join(q.dimensions + [f"{config['formula']} AS {config['alias']}"])
    group = f" GROUP BY {', '.join(q.dimensions)}" if q.dimensions else ""
    order = f" ORDER BY {config['alias']} DESC" if q.dimensions else ""
    s["generated_sql"] = (
        f"SELECT {select} FROM {config['table']} WHERE {config['filter'].format(snapshot_date=SNAPSHOT_DATE)}{group}{order}"
    )
    s["sql_generation_mode"] = "semantic_python"
    s.setdefault("skipped_nodes", []).append("generate_sql")
    return s


def _after_match(s: PipelineState) -> str:
    if s.get("refused"):
        return "explain"
    return "validate" if s.get("matched_config") else "generate"


async def _generate_sql(s: PipelineState) -> PipelineState:
    _trace(s, "generate_sql")
    s["schema_context"] = await _search(s["question"], 6)
    r = await get_chat_model().ainvoke(
        f"根据 Schema 只输出 PostgreSQL SELECT SQL。Schema：{s['schema_context']}\n问题：{s['question']}"
    )
    _llm(s, "generate_sql")
    s["generated_sql"] = (
        (r.content if isinstance(r.content, str) else str(r.content)).strip().strip("`")
    )
    s["sql_generation_mode"] = "llm_schema"
    return s


async def _validate(s: PipelineState) -> PipelineState:
    _trace(s, "validate_sql")
    r = validate_sql_ast(s.get("generated_sql", ""))
    s["validation_passed"] = r.valid
    if r.valid:
        s["generated_sql"] = r.normalized_sql or s["generated_sql"]
    else:
        s["validation_error"] = r.message
    return s


async def _execute(s: PipelineState) -> PipelineState:
    _trace(s, "execute")
    async with AsyncSessionLocal() as session:
        async with session.begin():
            conn = await session.connection()
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            await conn.execute(text(f"EXPLAIN {s['generated_sql']}"))
            rows = (await session.execute(text(s["generated_sql"]))).mappings().all()
    s["query_result"] = [dict(r) for r in rows]
    return s


async def _explain(s: PipelineState) -> PipelineState:
    _trace(s, "explain")
    if s.get("refused"):
        s["explanation"] = s["refusal_reason"]
        s["explain_mode"] = "refusal"
        return s
    r = await get_chat_model().ainvoke(
        "用简洁中文解释查询结果："
        + json.dumps(s.get("query_result", []), ensure_ascii=False, default=str)
    )
    _llm(s, "explain")
    s["explanation"] = r.content if isinstance(r.content, str) else str(r.content)
    s["explain_mode"] = "llm"
    return s


def build_pipeline():
    b = StateGraph(PipelineState)
    for n, f in {
        "query_parse": _query_parse,
        "clarify": _clarify,
        "semantic_match": _semantic_match,
        "generate_sql": _generate_sql,
        "validate_sql": _validate,
        "execute": _execute,
        "explain": _explain,
    }.items():
        b.add_node(n, f)
    b.add_edge(START, "query_parse")
    b.add_conditional_edges(
        "query_parse",
        _after_parse,
        {"clarify": "clarify", "semantic_match": "semantic_match"},
    )
    b.add_edge("clarify", "explain")
    b.add_conditional_edges(
        "semantic_match",
        _after_match,
        {"validate": "validate_sql", "generate": "generate_sql", "explain": "explain"},
    )
    b.add_edge("generate_sql", "validate_sql")
    b.add_conditional_edges(
        "validate_sql",
        lambda s: "execute" if s.get("validation_passed") else "explain",
        {"execute": "execute", "explain": "explain"},
    )
    b.add_edge("execute", "explain")
    b.add_edge("explain", END)
    return b.compile()


async def run_pipeline_async(question: str) -> PipelineState:
    return await build_pipeline().ainvoke(
        {"question": question, "clarify_count": 0, "retry_count": 0}
    )


async def initialize_demo_database() -> None:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(text(f"CREATE SCHEMA IF NOT EXISTS {DEMO_SCHEMA}"))
            await s.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {DEMO_SCHEMA}.loan_records (loan_id TEXT PRIMARY KEY, member_unit TEXT NOT NULL, balance NUMERIC NOT NULL, overdue_days INTEGER NOT NULL, snapshot_date DATE NOT NULL)"
                )
            )
            await s.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {DEMO_SCHEMA}.repayment_plans (repayment_id TEXT PRIMARY KEY, loan_id TEXT NOT NULL, due_date DATE NOT NULL, paid_date DATE, amount NUMERIC NOT NULL)"
                )
            )
            for row in [
                ("L1", "华中公司", 100000, 45),
                ("L2", "华中公司", 80000, 0),
                ("L3", "华南公司", 120000, 60),
                ("L4", "华南公司", 50000, 10),
            ]:
                await s.execute(
                    text(
                        f"INSERT INTO {DEMO_SCHEMA}.loan_records VALUES (:id,:unit,:balance,:days,:snapshot) ON CONFLICT (loan_id) DO UPDATE SET member_unit=EXCLUDED.member_unit,balance=EXCLUDED.balance,overdue_days=EXCLUDED.overdue_days,snapshot_date=EXCLUDED.snapshot_date"
                    ),
                    dict(zip(("id", "unit", "balance", "days"), row))
                    | {"snapshot": SNAPSHOT},
                )
            for row in [
                ("R1", "L1", "2026-08-10", "2026-08-09", 20000),
                ("R2", "L1", "2026-08-20", None, 15000),
                ("R3", "L2", "2026-08-15", "2026-08-14", 10000),
                ("R4", "L3", "2026-08-12", "2026-08-12", 25000),
            ]:
                values = dict(zip(("id", "loan", "due", "paid", "amount"), row))
                values["due"] = date.fromisoformat(values["due"])
                values["paid"] = (
                    date.fromisoformat(values["paid"]) if values["paid"] else None
                )
                await s.execute(
                    text(
                        f"INSERT INTO {DEMO_SCHEMA}.repayment_plans VALUES (:id,:loan,:due,:paid,:amount) ON CONFLICT (repayment_id) DO UPDATE SET loan_id=EXCLUDED.loan_id,due_date=EXCLUDED.due_date,paid_date=EXCLUDED.paid_date,amount=EXCLUDED.amount"
                    ),
                    values,
                )


async def generate_schema_yaml() -> Path:
    async with AsyncSessionLocal() as s:
        for full, cfg in SCHEMA["tables"].items():
            schema, table = full.split(".", 1)
            rows = (
                await s.execute(
                    text(
                        "SELECT column_name,data_type FROM information_schema.columns WHERE table_schema=:schema AND table_name=:table ORDER BY ordinal_position"
                    ),
                    {"schema": schema, "table": table},
                )
            ).all()
            if not rows:
                raise RuntimeError(f"测试表不存在：{full}")
            descriptions = {
                "loan_id": "贷款唯一标识",
                "member_unit": "成员单位名称",
                "balance": "未偿贷款本金余额",
                "overdue_days": "逾期天数",
                "snapshot_date": "状态快照日期",
                "repayment_id": "还款计划唯一标识",
                "due_date": "计划还款日期",
                "paid_date": "实际还款日期，空表示未还",
                "amount": "计划还款金额",
            }
            cfg["fields"] = [
                {"name": n, "type": t, "description": descriptions.get(n, n)}
                for n, t in rows
            ]
    SCHEMA_FILE.write_text(
        yaml.safe_dump(SCHEMA, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return SCHEMA_FILE


async def import_schema_document() -> None:
    if not SCHEMA_FILE.exists():
        await generate_schema_yaml()
    if not settings.embedding_api_key:
        raise RuntimeError("EMBEDDING_API_KEY 未配置")
    content = SCHEMA_FILE.read_text(encoding="utf-8")
    from langchain_core.documents import Document as LCDocument
    from app.ingestion.splitter import split

    chunks = split(
        [LCDocument(page_content=content, metadata={"source": SCHEMA_DOCUMENT_NAME})]
    )
    metric_chunks = _metric_documents()
    all_chunks = chunks + metric_chunks
    vectors = await get_embeddings().aembed_documents(
        [chunk.page_content for chunk in all_chunks]
    )
    documents = [
        (
            SCHEMA_DOCUMENT_NAME,
            content,
            chunks,
            vectors[: len(chunks)],
        ),
        (
            METRIC_DOCUMENT_NAME,
            "\n\n".join(chunk.page_content for chunk in metric_chunks),
            metric_chunks,
            vectors[len(chunks) :],
        ),
    ]
    async with AsyncSessionLocal() as s:
        async with s.begin():
            # 同名文档替换，避免旧 YAML 版本继续被检索到。
            old = (
                await s.execute(
                    select(Document).where(
                        Document.name.in_([SCHEMA_DOCUMENT_NAME, METRIC_DOCUMENT_NAME])
                    )
                )
            ).scalars().all()
            for d in old:
                await s.delete(d)
            await s.flush()
            repo = DocumentChunkRepository(s)
            for name, doc_content, doc_chunks, doc_vectors in documents:
                d = Document(
                    id=uuid4(),
                    name=name,
                    file_hash=hashlib.sha256(doc_content.encode()).hexdigest(),
                    mime_type="application/yaml",
                    size=len(doc_content.encode()),
                    storage_provider="local",
                    cos_bucket="local",
                    cos_object_key=name,
                    cos_region="local",
                    status=DocumentStatus.READY,
                    permission_tags=SCHEMA_PERMISSION,
                )
                s.add(d)
                await s.flush()
                await repo.bulk_add(
                    [
                        DocumentChunk(
                            document_id=d.id,
                            content=chunk.page_content,
                            embedding=vector,
                            chunk_index=chunk.metadata["chunk_index"],
                            chunk_hash=chunk.metadata["chunk_hash"],
                            extra_metadata=chunk.metadata,
                        )
                        for chunk, vector in zip(doc_chunks, doc_vectors, strict=True)
                    ]
                )


async def main(a: argparse.Namespace) -> None:
    if a.init_db:
        await initialize_demo_database()
    if a.generate_schema:
        print((await generate_schema_yaml()).read_text(encoding="utf-8"))
    if a.import_schema:
        await import_schema_document()
    print(build_pipeline().get_graph(xray=True).draw_mermaid())
    if not any((a.init_db, a.generate_schema, a.import_schema)):
        for q in (
            "上个月贷款逾期率按成员单位拆一下",
            "上个月各成员单位贷款余额",
            "各成员单位贷款和还款次数对比",
            "利率",
        ):
            s = await run_pipeline_async(q)
            print(
                f"\n>>> {q}\n节点：{' -> '.join(s.get('node_trace', []))}\nSQL模式：{s.get('sql_generation_mode', '未生成')}\nLLM：{s.get('llm_calls_by_node', {})}\nSQL：{s.get('generated_sql', '')}\n结果：{s.get('explanation', '')}"
            )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--init-db", action="store_true")
    p.add_argument("--generate-schema", action="store_true")
    p.add_argument("--import-schema", action="store_true")
    asyncio.run(main(p.parse_args()))

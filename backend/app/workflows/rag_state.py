from dataclasses import dataclass
from typing import Literal, TypedDict
from uuid import UUID

from app.db.models import MessageRole
from app.retrieval.vector_retriever import RetrievedChunk


@dataclass(frozen=True)
class ChatContextMessage:
    role: MessageRole
    content: str

QueryRoute = Literal["original", "rewrite", "hyde", "multi_query"]


class RAGState(TypedDict, total=False):
    # 输入
    conversation_id: UUID
    question: str

    # load_context
    chat_history: list[ChatContextMessage]

    # normalize_query 删除
    query: str

    # route_query output
    route: QueryRoute
    rewritten_query: str | None  # 改写结果
    hyde_answer: str | None  # 假设答案
    multi_queries: list[str] | None  # 补充问题

    retrieved_chunks: list[RetrievedChunk]
    refused: bool

    # 执行步骤
    agent_steps: list[dict]
    # 检索次数
    retrieval_round: int
    # 上下文是否足够
    context_sufficient: bool

    # rerank 后基于 Top1 score 的拒答闸门
    # False 时图走向 refuse 节点；True 时图走向 END
    context_is_enough: bool

    answer: str

    user_message_id: UUID
    assistant_message_id: UUID
    # LangSmith trace_id
    trace_id: str | None
    permissions: list[str]

import json
from dataclasses import dataclass

from app.core.logging import get_logger
from app.llm.models import get_chat_model
from app.llm.prompts import build_verify_answer_messages, format_context
from app.retrieval.vector_retriever import RetrievedChunk

logger = get_logger(__name__)


@dataclass(frozen=True)
class VerifyResult:
    verified: bool
    reason: str


class AnswerVerifier:
    async def verify(
        self, question: str, answer: str, chunks: list[RetrievedChunk]
    ) -> VerifyResult:
        if not chunks or not answer.strip():
            return VerifyResult(verified=True, reason="")

        messages = build_verify_answer_messages(
            question=question, answer=answer, chunks_text=format_context(chunks)
        )
        try:
            response = await get_chat_model().ainvoke(messages)
            raw = _extract_text(response.content).strip()
            return _parse_result(raw)
        except Exception:
            logger.exception(
                "answer verify 调用失败，降级 verified=True: question=%r", question
            )
            return VerifyResult(verified=True, reason="verifier_exception")


_verifier: AnswerVerifier | None = None


def get_answer_verifier() -> AnswerVerifier:
    global _verifier
    if _verifier is None:
        _verifier = AnswerVerifier()
    return _verifier


def _parse_result(raw: str) -> VerifyResult:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("answer verifier JSON 解析失败")
        return VerifyResult(verified=True, reason="verifier_parse_failed")
    verified_raw = data.get("verified")
    if not isinstance(verified_raw, bool):
        logger.warning("answer verifier 返回的verified 字段非布尔")
        return VerifyResult(verified=True, reason="verifier_invalid_verified")
    reason = str(data.get("reason") or "").strip()
    return VerifyResult(verified=verified_raw, reason=reason)


def _extract_text(content: str | list[str | dict]) -> str:
    """兼容 langchain ChatModel 的 content 联合类型（参考 generate.py 同款处理）。"""
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))

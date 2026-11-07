import asyncio
import warnings
from dataclasses import dataclass

warnings.filterwarnings("ignore", category=DeprecationWarning, module="ragas")

from app.core.logging import get_logger
from app.ingestion.embedder import get_embeddings
from app.llm.models import get_chat_model
from ragas import evaluate
from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class RagasMetrics:
    faithfulness: float | None
    answer_relevancy: float | None
    context_precision: float | None
    context_recall: float | None


@dataclass(frozen=True)
class RagasSample:
    question: str
    answer: str
    retrieved_contexts: list[str]
    reference_answer: str


_METRICS = [faithfulness, answer_relevancy, context_precision, context_recall]


async def evaluate_batch(samples: list[RagasSample]) -> list[RagasMetrics]:
    if not samples:
        return []

    dataset = EvaluationDataset(
        samples=[
            SingleTurnSample(
                user_input=s.question,
                response=s.answer or " ",
                retrieved_contexts=s.retrieved_contexts or [""],
                reference=s.reference_answer or "",
            )
            for s in samples
        ]
    )

    try:
        results = await asyncio.to_thread(
            evaluate,
            dataset=dataset,
            metrics=_METRICS,
            llm=get_chat_model(),
            embeddings=get_embeddings(),
            raise_exceptions=False,
            show_progress=False,
        )
    except Exception:
        logger.exception("RAGAS evaluate 整批失败，返回 None 占位")
        return [_empty_metrics() for _ in samples]

    return _extract_metrics(results, expected=len(samples))


def _extract_metrics(result, expected: int) -> list[RagasMetrics]:
    rows = getattr(result, "scores", None) or []
    if len(rows) != expected:
        logger.warning(
            "RAGAS 返回行数 %d 与样本数 %d 不一致，按可用值对齐", len(rows), expected
        )

    metrics: list[RagasMetrics] = []
    for i in range(expected):
        row = rows[i] if i < len(rows) else {}
        metrics.append(
            RagasMetrics(
                faithfulness=_pick(row, "faithfulness"),
                answer_relevancy=_pick(row, "answer_relevancy"),
                context_precision=_pick(row, "context_precision"),
                context_recall=_pick(row, "context_recall"),
            )
        )
    return metrics


def _pick(row: dict, key: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    if as_float != as_float:  # NaN  # noqa: PLR0124
        return None
    return as_float


def _empty_metrics() -> RagasMetrics:
    return RagasMetrics(
        faithfulness=None,
        answer_relevancy=None,
        context_precision=None,
        context_recall=None,
    )

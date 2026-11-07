import json
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import NotFoundError, ValidationError

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    question: str
    expected_answer: str
    expected_document_names: list[str]
    expected_keywords: list[str]
    should_refuse: bool
    tags: list[str]


def list_datasets() -> list[tuple[str, int]]:
    if not DATASETS_DIR.exists():
        return []
    results: list[tuple[str, int]] = []
    for path in sorted(DATASETS_DIR.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as f:
            count = sum(1 for line in f if line.strip())
        results.append((path.stem, count))
    return results


def load_dataset(name: str) -> list[EvaluationCase]:
    path = DATASETS_DIR / f"{name}.jsonl"
    if not path.exists():
        raise NotFoundError(f"测评集不存在：{name}")

    cases: list[EvaluationCase] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    f"测评集 {name} 第 {line_no} 行 JSON 非法:{exc.msg}"
                ) from exc
            cases.append(_parse_case(data, line_no=line_no, dataset=name))
    return cases


def _parse_case(data: dict, *, line_no: int, dataset: str) -> EvaluationCase:
    try:
        return EvaluationCase(
            case_id=str(data["id"]),
            question=str(data["question"]),
            expected_answer=str(data.get("expected_answer", "")),
            expected_document_names=list(data.get("expected_document_names" or [])),  # noqa: SIM222
            expected_keywords=list(data.get("expected_keywords" or [])),  # noqa: SIM222
            should_refuse=bool(data.get("should_refuse" or False)),  # noqa: SIM222
            tags=list(data.get("tags" or [])),  # noqa: SIM222
        )
    except KeyError as exc:
        raise ValidationError(
            f"测评集 {dataset} 第 {line_no} 行缺失字段: {exc.msg}"
        ) from exc

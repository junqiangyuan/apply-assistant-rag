"""LLM SQL 的最小安全校验：AST 白名单 + PostgreSQL EXPLAIN。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import sqlglot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sqlglot import exp

logger = logging.getLogger(__name__)

MAX_SQL_LENGTH = 10_000
DEFAULT_DB_TIMEOUT_SECONDS = 5


class ReasonCode(StrEnum):
    EMPTY_SQL = "EMPTY_SQL"
    TOO_LONG = "TOO_LONG"
    MULTI_STATEMENT = "MULTI_STATEMENT"
    NOT_SELECT = "NOT_SELECT"
    PARSE_ERROR = "PARSE_ERROR"
    PARAMETERS_NOT_SUPPORTED = "PARAMETERS_NOT_SUPPORTED"
    DB_VALIDATION_ERROR = "DB_VALIDATION_ERROR"


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    normalized_sql: str | None
    original_sql: str
    reason_code: ReasonCode | None = None
    message: str = ""
    position: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "normalized_sql": self.normalized_sql,
            "original_sql": self.original_sql,
            "reason_code": self.reason_code.value if self.reason_code else None,
            "message": self.message,
            "position": self.position,
        }


def validate_sql_ast(sql: str, *, max_length: int = MAX_SQL_LENGTH) -> ValidationResult:
    """校验单条 PostgreSQL 只读查询并返回规范化 SQL。"""
    original = sql or ""
    if not original.strip():
        return _invalid(original, ReasonCode.EMPTY_SQL, "SQL 不能为空")
    if len(original) > max_length:
        return _invalid(original, ReasonCode.TOO_LONG, f"SQL 长度不能超过 {max_length} 个字符")

    try:
        statements = sqlglot.parse(original, read="postgres")
    except (sqlglot.errors.ParseError, ValueError) as exc:
        return _invalid(original, ReasonCode.PARSE_ERROR, f"SQL 解析失败：{_safe_error(exc)}")
    if len(statements) != 1:
        return _invalid(original, ReasonCode.MULTI_STATEMENT, "只允许一条 SQL 语句")

    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.Union)):
        return _invalid(original, ReasonCode.NOT_SELECT, "只允许 SELECT 查询")
    if any(isinstance(node, (exp.Placeholder, exp.Parameter)) for node in statement.walk()):
        return _invalid(original, ReasonCode.PARAMETERS_NOT_SUPPORTED, "暂不支持参数占位符")
    if any(
        isinstance(node, exp.Select)
        and (node.args.get("into") or node.args.get("locks"))
        for node in statement.walk()
    ):
        return _invalid(original, ReasonCode.NOT_SELECT, "不允许 SELECT INTO 或 FOR UPDATE/SHARE")
    if any(isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Command)) for node in statement.walk()):
        return _invalid(original, ReasonCode.NOT_SELECT, "只允许只读 SELECT 查询")

    return ValidationResult(
        True,
        statement.sql(dialect="postgres", comments=False),
        original,
        message="SQL 校验通过",
    )


async def validate_sql_readonly(
    connection: AsyncConnection,
    sql: str,
    *,
    max_length: int = MAX_SQL_LENGTH,
    timeout_seconds: float = DEFAULT_DB_TIMEOUT_SECONDS,
) -> ValidationResult:
    """先做 AST 校验，再在只读事务中执行 PostgreSQL EXPLAIN。"""
    ast_result = validate_sql_ast(sql, max_length=max_length)
    if not ast_result.valid:
        return ast_result

    async def explain() -> None:
        transaction = await connection.begin()
        try:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            await connection.execute(text(f"EXPLAIN {ast_result.normalized_sql}"))
        finally:
            await transaction.rollback()

    try:
        await asyncio.wait_for(explain(), timeout=timeout_seconds)
    except Exception as exc:  # 数据库错误对外统一脱敏
        logger.warning("SQL EXPLAIN 校验失败", exc_info=exc)
        return _invalid(ast_result.original_sql, ReasonCode.DB_VALIDATION_ERROR, "数据库只读校验失败")
    return ast_result


def _invalid(original: str, code: ReasonCode, message: str) -> ValidationResult:
    return ValidationResult(False, None, original, code, message)


def _safe_error(exc: Exception) -> str:
    return str(exc).splitlines()[0][:200]

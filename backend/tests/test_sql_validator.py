import asyncio
from unittest.mock import AsyncMock

import pytest

from app.sql_agent.sql_validator import ReasonCode, validate_sql_ast, validate_sql_readonly


@pytest.mark.parametrize(
    ("sql", "ok"),
    [
        ("SELECT 1", True),
        ("WITH x AS (SELECT 1) SELECT * FROM x", True),
        ("SELECT 1 UNION SELECT 2", True),
        ("SELECT * FROM t FOR UPDATE", False),
        ("SELECT * INTO t FROM source", False),
        ("INSERT INTO t VALUES (1)", False),
        ("SELECT 1; SELECT 2", False),
        ("SELECT :name", False),
        ("-- comment\nSELECT 1", True),
    ],
)
def test_validate_sql_ast(sql: str, ok: bool) -> None:
    result = validate_sql_ast(sql)
    assert result.valid is ok
    if not ok:
        assert result.reason_code is not None
    elif sql.startswith("--"):
        assert result.normalized_sql == "SELECT 1"


def test_validate_sql_ast_empty_and_too_long() -> None:
    assert validate_sql_ast(" ").reason_code == ReasonCode.EMPTY_SQL
    assert validate_sql_ast("x" * 10_001).reason_code == ReasonCode.TOO_LONG


def test_readonly_explain_order() -> None:
    connection = AsyncMock()
    transaction = AsyncMock()
    connection.begin.return_value = transaction

    result = asyncio.run(validate_sql_readonly(connection, "SELECT 1"))

    assert result.valid
    assert [call.args[0].text for call in connection.execute.await_args_list] == [
        "SET TRANSACTION READ ONLY",
        "EXPLAIN SELECT 1",
    ]
    transaction.rollback.assert_awaited_once()


def test_readonly_explain_failure_is_sanitized() -> None:
    connection = AsyncMock()
    transaction = AsyncMock()
    connection.begin.return_value = transaction
    connection.execute.side_effect = RuntimeError("postgres://secret-password")

    result = asyncio.run(validate_sql_readonly(connection, "SELECT 1"))

    assert not result.valid
    assert result.reason_code == ReasonCode.DB_VALIDATION_ERROR
    assert "secret-password" not in result.message
    transaction.rollback.assert_awaited_once()

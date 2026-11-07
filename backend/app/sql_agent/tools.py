"""SQL 相关工具：只读访问数据库，供 SQL Agent 使用。

参考 LangChain 官方 SQL Agent 教程的四个工具：
sql_db_list_tables / sql_db_schema / sql_db_query / sql_db_query_checker。
注意：这些工具是演示级封装，生产环境必须使用权限收窄的只读账号。
"""

from langchain.tools import tool

from app.sql_agent.sql_validator import validate_sql_ast

# ponytail: sqlite 内存库仅用于示例演示；接入真实库时把 _db 换成项目
# 现有的异步 engine（backend/app/db/session.py），并启用只读账号。
_db: "sqlite3.Connection | None" = None


def _get_db() -> "sqlite3.Connection":
    import sqlite3

    global _db
    if _db is None:
        _db = sqlite3.connect(":memory:", check_same_thread=False)
    return _db


@tool
def sql_db_list_tables() -> str:
    """输入为空字符串，输出为数据库中表的逗号分隔列表。"""
    cur = _get_db().cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall() if not row[0].startswith("sqlite_")]
    return ", ".join(tables)


@tool
def sql_db_schema(table_names: str) -> str:
    """输入为逗号分隔的表名列表，输出这些表的 schema 与示例行。

    先调用 sql_db_list_tables 确认表存在。
    示例输入：employees, orders
    """
    con = _get_db()
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    valid = {row[0] for row in cur.fetchall() if not row[0].startswith("sqlite_")}
    results = []
    for name in (t.strip() for t in table_names.split(",")):
        if not name:
            continue
        if name not in valid:
            results.append(f"错误：表 {name!r} 不存在")
            continue
        cur.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        row = cur.fetchone()
        if row:
            results.append(row[0])
            cur.execute(f'SELECT * FROM "{name}" LIMIT 3')
            rows = cur.fetchall()
            if rows:
                cols = [d[0] for d in cur.description]
                results.append(
                    f"/* {name} 表 3 行示例：\n"
                    + "\t".join(cols)
                    + "\n"
                    + "\n".join("\t".join(str(x) for x in r) for r in rows)
                    + "\n*/"
                )
    return "\n\n".join(results)


@tool
def sql_db_query(query: str) -> str:
    """输入为一条正确且详细的 SQL 查询，输出为数据库执行结果。

    查询错误时返回错误信息；请根据错误重写查询并重试。
    遇到 Unknown column 之类错误时，先用 sql_db_schema 查看正确字段。
    """
    validation = validate_sql_ast(query)
    if not validation.valid:
        return f"Error [{validation.reason_code}]: {validation.message}"
    con = _get_db()
    try:
        cur = con.cursor()
        cur.execute(validation.normalized_sql or query)
        return str(cur.fetchall())
    except Exception as e:
        return f"Error: {e}"


@tool
def sql_db_query_checker(query: str) -> str:
    """执行前校验 SQL，只返回可执行的规范化 SELECT。"""
    validation = validate_sql_ast(query)
    if not validation.valid:
        return f"Error [{validation.reason_code}]: {validation.message}"
    return validation.normalized_sql or query


SQL_TOOLS = [sql_db_list_tables, sql_db_schema, sql_db_query, sql_db_query_checker]

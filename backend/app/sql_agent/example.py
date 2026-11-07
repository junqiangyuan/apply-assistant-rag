"""SQL Agent 示例：使用内存 sqlite 库演示工具与 Agent 的完整行为。

运行：cd backend && uv run python -m app.sql_agent.example
"""

import asyncio
import sqlite3

from app.sql_agent.agent import build_sql_agent
from app.sql_agent.tools import SQL_TOOLS, _get_db

SEED = """
CREATE TABLE employees (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    department TEXT NOT NULL,
    salary INTEGER NOT NULL
);
INSERT INTO employees (name, department, salary) VALUES
    ('张三', '研发', 25000),
    ('李四', '研发', 22000),
    ('王五', '市场', 18000),
    ('赵六', '市场', 16000);
"""


def _seed() -> None:
    con = _get_db()
    con.executescript(SEED)
    con.commit()


async def main() -> None:
    _seed()
    print("== 可用工具 ==")
    for t in SQL_TOOLS:
        print(f"- {t.name}: {t.description.splitlines()[0]}")

    print("\n== 演示查询：各部门平均工资 ==")
    agent = build_sql_agent()
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "请按部门统计平均工资？"}]}
    )
    print(result["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())

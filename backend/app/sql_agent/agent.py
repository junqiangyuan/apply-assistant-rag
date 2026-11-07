"""SQL Agent：基于 LangChain create_agent，配合 SQL 工具回答数据库问题。"""

from langchain.agents import create_agent

from app.llm.models import get_chat_model
from app.sql_agent.tools import SQL_TOOLS

SYSTEM_PROMPT = """你是一个与 SQL 数据库交互的智能助手。
根据用户问题，先编写一条语法正确的 {dialect} 查询并执行，然后查看结果回答用户。

规则：
1. 除非用户明确指定条数，否则查询结果最多限制为 {top_k} 条。
2. 可以按相关列排序，返回最有意义的示例；不要查询整表所有列，只查问题相关列。
3. 执行查询前必须先调用 sql_db_query_checker 检查；执行出错就重写查询再试。
4. 禁止执行任何 DML 语句（INSERT、UPDATE、DELETE、DROP 等）。
5. 开始前必须先调用 sql_db_list_tables 查看有哪些表，不要跳过这一步。
6. 然后调用 sql_db_schema 查看最相关表的 schema。

回答格式：先给出 SQL 查询（markdown 代码块），再解释结果。"""


def build_sql_agent():
    """构建 SQL Agent。每次调用返回新实例，避免跨请求共享会话状态。"""
    return create_agent(
        get_chat_model(),
        SQL_TOOLS,
        system_prompt=SYSTEM_PROMPT.format(dialect="postgres", top_k=10),
    )

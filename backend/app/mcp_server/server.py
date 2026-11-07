from app.mcp_server.tools import register_tools
from mcp.server.mcpserver import MCPServer

knowledge_mcp = MCPServer(
    name="apply-assistant-rag",
    instructions=(
        "知识库工具集：先调 ask_knowledge_base 直接问答；"
        "调 list_documents / get_document_status /get_knowledge_base_stats 了解库内文档；"
        "管理员可调 upload_document 上传新文件。"
    ),
    # stateless_http=True,
    # json_response=True,
    # streamable_http_path="/",
)

register_tools(knowledge_mcp)
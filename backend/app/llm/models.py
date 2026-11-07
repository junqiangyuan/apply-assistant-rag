from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.tools.registry import ToolRegistry
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

_chat_model: BaseChatModel | None = None
_tool_chat_model: BaseChatModel | None = None


def get_chat_model() -> BaseChatModel:
    """返回流式 ChatOpenAI实例

    单例缓存：模型客户端持有httpx 连接池，避免反复创建浪费资源
    Returns:
        BaseChatModel: _description_
    """

    global _chat_model
    if _chat_model is not None:
        return _chat_model

    if not settings.chat_api_key:
        raise ConfigurationError("Chat API key 未配置")

    _chat_model = ChatOpenAI(
        model=settings.chat_model,
        api_key=settings.chat_api_key,  # type: ignore
        base_url=settings.chat_base_url,
        temperature=0,
        streaming=True,
    )
    return _chat_model


def get_chat_model_with_tools() -> BaseChatModel:
    """返回绑定集中注册工具的 chat_model 单例。"""

    global _tool_chat_model
    if _tool_chat_model is not None:
        return _tool_chat_model

    _tool_chat_model = get_chat_model().bind_tools(ToolRegistry().get_tools())
    return _tool_chat_model

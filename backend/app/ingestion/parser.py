import asyncio
import io

from app.core.exceptions import AppException
from app.core.logging import get_logger
from docling.datamodel.base_models import DocumentStream
from docling.document_converter import DocumentConverter
from langchain_core.documents import Document

logger = get_logger(__name__)


class DocumentParseError(AppException):
    code = "document_parse_error"
    message = "文档解析失败"
    http_status = 400


_converter: DocumentConverter | None = None


## 先定义内部方法，然后暴露外部异步方法
def _get_converter() -> DocumentConverter:
    global _converter
    if _converter is None:
        _converter = DocumentConverter()
    return _converter


def _convert_sync(filename: str, content: bytes) -> str:
    source = DocumentStream(name=filename, stream=io.BytesIO(content))
    result = _get_converter().convert(source)
    return result.document.export_to_markdown()


async def parse(filename: str, content: bytes) -> list[Document]:
    try:
        markdown = await asyncio.to_thread(_convert_sync, filename, content)
    except Exception as exc:
        logger.exception("docling parse failed:%s", filename)
        raise DocumentParseError(f"Docling 解析失败:{exc}") from exc

    if not markdown.strip():
        raise DocumentParseError("解析结果为空，文档可能损坏或不受支持")

    return [Document(page_content=markdown, metadata={"source": filename})]

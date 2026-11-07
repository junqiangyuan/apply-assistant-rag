import hashlib

from app.core.config import settings
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


def _build_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "?", "；", "，", " ", ""],
        length_function=len,
        is_separator_regex=False,
    )


def split(documents: list[Document]) -> list[Document]:
    splitter = _build_splitter()
    chunks = splitter.split_documents(documents)

    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index
        chunk.metadata["chunk_hash"] = hashlib.md5(
            chunk.page_content.encode("utf-8")
        ).hexdigest()

    return chunks

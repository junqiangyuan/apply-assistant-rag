"""文档切分。

Docling 输出的是 Markdown，按 Markdown 结构切分（`format=markdown` 的文档）：

1. 表格先转成"每行一条键值对"的文本。原始 Markdown 表格被字符切分器从行间切开后，
   后半截的行会丢掉表头，检索到也读不出"3.0 / 4.0"是哪一列；键值对让每一行自带字段名。
2. 按标题切成小节。文档标题下的一级小节（如"一、服务套餐""Q3"）各自成块，只把同一
   一级小节内的子节贪心打包到 chunk_size 以内；文档标题和顶部声明并入第一个小节。
   不跨一级小节打包，是因为把"套餐 / 客服 / 退费"塞进同一个 chunk 会稀释 embedding，
   实测相关问题的相似度从 0.68 掉到 0.57，跌破检索阈值。小节边界是天然的语义边界，
   一个问答或一个小节不会被从中间切断，也不会出现 chunk 末尾只挂着一个标题的情况。
3. 只有单个小节本身超过 chunk_size 时，才退回字符级递归切分，并给后续片段补上标题，
   避免片段脱离上下文。

其他来源（例如 SQL Agent 的 YAML schema）不带 `format=markdown`，保持原来的递归切分，
否则 YAML 注释 `# ...` 会被误认成标题。
"""

import hashlib
import re
from dataclasses import dataclass, field

from app.core.config import settings
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "?", "；", "，", " ", ""]
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_TABLE_DELIMITER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
_SECTION_PATH_MAX = 1024


def _build_splitter(chunk_size: int | None = None) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size or settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=_SEPARATORS,
        length_function=len,
        is_separator_regex=False,
    )


# ---------- 表格 → 键值对 ----------


def _split_cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [cell.strip().replace("\\|", "|") for cell in _CELL_SPLIT_RE.split(body)]


def _is_table_row(line: str) -> bool:
    return line.strip().startswith("|")


def _row_to_key_value(headers: list[str], cells: list[str]) -> str:
    pairs = []
    for index, value in enumerate(cells):
        if not value:
            continue
        key = headers[index] if index < len(headers) and headers[index] else f"列{index + 1}"
        pairs.append(f"{key}：{value}")
    return "- " + "；".join(pairs) if pairs else ""


def tables_to_key_value(markdown: str) -> str:
    """把 Markdown 表格的每个数据行转成 `- 表头1：值1；表头2：值2` 一行。"""
    lines = markdown.split("\n")
    output: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        is_table_start = (
            _is_table_row(line)
            and i + 1 < len(lines)
            and _TABLE_DELIMITER_RE.match(lines[i + 1]) is not None
        )
        if not is_table_start:
            output.append(line)
            i += 1
            continue

        headers = _split_cells(line)
        i += 2
        while i < len(lines) and _is_table_row(lines[i]):
            row = _row_to_key_value(headers, _split_cells(lines[i]))
            if row:
                output.append(row)
            i += 1
    return "\n".join(output)


# ---------- 按标题分节 ----------


@dataclass
class _Section:
    path: list[str]
    lines: list[str] = field(default_factory=list)
    has_body: bool = False
    # 标题嵌套深度（文档标题为 1，顶部无标题的前言为 0）；合并后取其中最浅的一级
    depth: int = 0

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


def _split_sections(markdown: str) -> list[_Section]:
    sections: list[_Section] = []
    stack: list[tuple[int, str]] = []
    current = _Section(path=[])
    in_code = False

    for line in markdown.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        match = None if in_code else _HEADING_RE.match(line)
        if match:
            if current.lines:
                sections.append(current)
            level, title = len(match.group(1)), match.group(2).strip()
            stack = [(lv, t) for lv, t in stack if lv < level] + [(level, title)]
            current = _Section(path=[t for _, t in stack], lines=[line], depth=len(stack))
            continue
        current.lines.append(line)
        if line.strip():
            current.has_body = True

    if current.lines:
        sections.append(current)
    return [s for s in sections if s.text]


def _attach_bare_headings(sections: list[_Section]) -> list[_Section]:
    """只有标题、没有正文的小节（如紧跟子标题的父标题）并入下一个小节，不能单独成为 chunk 的结尾。"""
    merged: list[_Section] = []
    pending: list[_Section] = []
    for section in sections:
        if not section.has_body:
            pending.append(section)
            continue
        if pending:
            section = _Section(
                path=section.path,
                lines=[ln for p in pending for ln in p.lines] + section.lines,
                has_body=True,
                depth=min(p.depth for p in [*pending, section]),
            )
            pending = []
        merged.append(section)
    if pending:
        if merged:
            merged[-1].lines.extend(ln for p in pending for ln in p.lines)
        else:
            merged.extend(pending)
    return merged


def _heading_prefix(section: _Section) -> str:
    headings = [ln for ln in section.lines if _HEADING_RE.match(ln)]
    return "\n".join(headings)


def _split_oversized(section: _Section, chunk_size: int) -> list[str]:
    prefix = _heading_prefix(section)
    budget = max(chunk_size - len(prefix) - 2, chunk_size // 2)
    pieces = _build_splitter(budget).split_text(section.text)
    return [
        piece if index == 0 or not prefix else f"{prefix}\n\n{piece}"
        for index, piece in enumerate(pieces)
    ]


def _format_path(path: list[str]) -> str | None:
    if not path:
        return None
    return " > ".join(path)[:_SECTION_PATH_MAX]


def _group_depth(sections: list[_Section]) -> int:
    """一级小节所在的深度：最浅一层只有一个标题时视为文档标题，取下一层。"""
    depths = [s.depth for s in sections if s.depth > 0]
    if not depths:
        return 1
    top = min(depths)
    if depths.count(top) == 1 and any(d > top for d in depths):
        return top + 1
    return top


def _split_markdown(document: Document, chunk_size: int) -> list[Document]:
    text = tables_to_key_value(document.page_content)
    sections = _attach_bare_headings(_split_sections(text))

    group_depth = _group_depth(sections)

    chunks: list[Document] = []
    buffer: list[str] = []
    buffer_path: list[str] = []
    # buffer 里是否已有一级小节的正文；只有文档标题 / 前言时不切块，留给下一个小节
    buffer_has_group = False

    def flush() -> None:
        nonlocal buffer_has_group
        if buffer:
            chunks.append(_make_doc(document, "\n\n".join(buffer), buffer_path))
            buffer.clear()
        buffer_has_group = False

    for section in sections:
        body = section.text
        is_preamble = section.depth < group_depth
        starts_group = not is_preamble and section.depth == group_depth
        if starts_group and buffer_has_group:
            flush()
        if len(body) > chunk_size:
            flush()
            for piece in _split_oversized(section, chunk_size):
                chunks.append(_make_doc(document, piece, section.path))
            continue
        joined_len = sum(len(b) for b in buffer) + 2 * len(buffer) + len(body)
        if buffer and joined_len > chunk_size:
            flush()
        if not buffer_has_group:
            buffer_path = section.path
        buffer.append(body)
        if not is_preamble:
            buffer_has_group = True
    flush()
    return chunks


def _make_doc(source: Document, content: str, path: list[str]) -> Document:
    metadata = dict(source.metadata)
    section_path = _format_path(path)
    if section_path:
        metadata["section_path"] = section_path
    return Document(page_content=content, metadata=metadata)


def split(documents: list[Document]) -> list[Document]:
    chunk_size = settings.chunk_size
    chunks: list[Document] = []
    for document in documents:
        if document.metadata.get("format") == "markdown":
            chunks.extend(_split_markdown(document, chunk_size))
        else:
            chunks.extend(_build_splitter().split_documents([document]))

    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index
        chunk.metadata["chunk_hash"] = hashlib.md5(
            chunk.page_content.encode("utf-8")
        ).hexdigest()

    return chunks

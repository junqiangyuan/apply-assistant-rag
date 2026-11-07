from langchain_core.documents import Document

from app.core.config import settings
from app.ingestion import splitter

TABLE_DOC = """## 枫原大学商学院 硕士项目申请要求

演示用虚构资料：以下内容均为虚构。

### 一、项目要求一览

| 项目                | 学制   | GPA 最低要求   | 工作经验          |
|---------------------|--------|----------------|-------------------|
| 金融硕士（MSF）     | 1 年   | 3.2 / 4.0      | 不要求            |
| 工商管理硕士（MBA） | 2 年   | 3.0 / 4.0      | 至少 3 年全职经验 |

### 二、面试

MSF 和 MBA 需要面试；MSM 不设面试。
"""


def _md(text: str) -> list[Document]:
    return [Document(page_content=text, metadata={"source": "t.md", "format": "markdown"})]


def test_table_rows_become_self_describing_key_values() -> None:
    text = splitter.tables_to_key_value(TABLE_DOC)

    assert "|" not in text
    assert (
        "- 项目：金融硕士（MSF）；学制：1 年；GPA 最低要求：3.2 / 4.0；工作经验：不要求"
        in text
    )
    assert (
        "- 项目：工商管理硕士（MBA）；学制：2 年；GPA 最低要求：3.0 / 4.0；"
        "工作经验：至少 3 年全职经验" in text
    )


def test_empty_cells_are_skipped_and_escaped_pipes_kept() -> None:
    text = splitter.tables_to_key_value("| a | b |\n|---|---|\n| x \\| y |  |\n")
    assert text.strip() == "- a：x | y"


def test_title_and_disclaimer_join_first_section_and_top_sections_split() -> None:
    chunks = splitter.split(_md(TABLE_DOC))

    assert len(chunks) == 2
    first = chunks[0].page_content
    assert first.startswith("## 枫原大学商学院")
    assert "演示用虚构资料" in first
    assert "项目：工商管理硕士（MBA）" in first
    assert "二、面试" not in first
    assert chunks[0].metadata["section_path"] == "枫原大学商学院 硕士项目申请要求 > 一、项目要求一览"
    assert chunks[1].page_content.startswith("### 二、面试")


def test_subsections_of_one_top_section_are_packed_together() -> None:
    doc = (
        "# 指南\n\n声明。\n\n## 三、要求\n\n### 3.1 GPA\n\nGPA 3.3。\n\n### 3.2 语言\n\n雅思 7.0。"
        "\n\n## 四、截止\n\n11 月 15 日。"
    )
    chunks = splitter.split(_md(doc))

    assert [c.page_content.split("\n")[0] for c in chunks] == ["# 指南", "## 四、截止"]
    assert "### 3.2 语言" in chunks[0].page_content


def test_sections_are_not_cut_and_no_chunk_ends_with_bare_heading(monkeypatch) -> None:
    monkeypatch.setattr(settings, "chunk_size", 120)
    qa = "\n\n".join(
        f"### Q{i}：问题{i}？\n\n" + f"答案{i}。" * 12 for i in range(1, 5)
    )
    doc = "# FAQ\n\n## 一、分组\n\n" + qa

    chunks = splitter.split(_md(doc))

    for chunk in chunks:
        last_line = chunk.page_content.strip().split("\n")[-1]
        assert not last_line.startswith("#"), chunk.page_content
    for i in range(1, 5):
        holders = [c for c in chunks if f"### Q{i}：" in c.page_content]
        assert len(holders) == 1
        assert holders[0].page_content.count(f"答案{i}。") == 12
    # 只有标题的父节并入下一个小节
    assert chunks[0].page_content.startswith("# FAQ\n\n## 一、分组\n\n### Q1")
    assert chunks[0].metadata["section_path"] == "FAQ > 一、分组 > Q1：问题1？"


def test_oversized_section_pieces_carry_heading(monkeypatch) -> None:
    monkeypatch.setattr(settings, "chunk_size", 80)
    monkeypatch.setattr(settings, "chunk_overlap", 0)
    body = "\n".join(f"第{i}条规定内容比较长需要单独成行。" for i in range(10))
    chunks = splitter.split(_md(f"## 长小节\n\n{body}"))

    assert len(chunks) > 1
    assert all(c.page_content.startswith("## 长小节") for c in chunks)
    assert all(c.metadata["section_path"] == "长小节" for c in chunks)


def test_non_markdown_source_keeps_plain_recursive_split() -> None:
    yaml_text = "# comment line\nmetrics:\n  a: 1\n"
    chunks = splitter.split([Document(page_content=yaml_text, metadata={"source": "s.yaml"})])

    assert [c.page_content for c in chunks] == [yaml_text.strip()]
    assert "section_path" not in chunks[0].metadata


def test_chunk_index_and_hash_assigned() -> None:
    chunks = splitter.split(_md(TABLE_DOC))
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))
    assert all(len(c.metadata["chunk_hash"]) == 32 for c in chunks)

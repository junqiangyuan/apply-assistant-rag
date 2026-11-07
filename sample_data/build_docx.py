"""生成演示用 Word 文档：枫原大学商学院硕士申请要求。

用 .docx + 表格的形式，演示文档解析链路对 Word 表格的处理
（表格按行转成键值对自然语言再入库）。

运行：cd backend && uv run python ../sample_data/build_docx.py
"""

from pathlib import Path

from docx import Document

OUT = Path(__file__).parent / "docs" / "枫原大学_商学院硕士申请要求.docx"

doc = Document()
doc.add_heading("枫原大学商学院 硕士项目申请要求（2027 秋季入学）", level=1)
doc.add_paragraph(
    "演示用虚构资料：枫原大学（Maplefield University）及本文所有项目、分数线、"
    "日期和费用均为虚构，仅用于演示 RAG 检索与问答，不代表任何真实院校的要求。"
)

doc.add_heading("一、项目要求一览", level=2)
rows = [
    ("项目", "学制", "GPA 最低要求", "雅思要求", "GMAT / GRE", "工作经验", "申请截止日期"),
    ("金融硕士（MSF）", "1 年", "3.2 / 4.0", "总分 7.0，单项 6.5", "GMAT 650 或 GRE 320", "不要求", "1 月 10 日"),
    ("市场营销硕士（MSM）", "1 年", "3.0 / 4.0", "总分 6.5，单项 6.0", "不要求", "不要求", "2 月 28 日"),
    ("工商管理硕士（MBA）", "2 年", "3.0 / 4.0", "总分 7.0，单项 6.5", "GMAT 600", "至少 3 年全职经验", "第一轮 12 月 1 日；第二轮 3 月 1 日"),
]
table = doc.add_table(rows=len(rows), cols=len(rows[0]))
table.style = "Table Grid"
for r, row in enumerate(rows):
    for c, value in enumerate(row):
        table.cell(r, c).text = value

doc.add_heading("二、面试", level=2)
doc.add_paragraph(
    "金融硕士（MSF）和 MBA 项目通过材料初审后，需参加 30 分钟的线上视频面试；"
    "市场营销硕士（MSM）不设面试。"
)

doc.add_heading("三、费用", level=2)
doc.add_paragraph("申请费：每个项目 120 美元，不可减免。")
doc.add_paragraph(
    "留位费：收到录取后须在 4 周内缴纳 2,000 美元留位费以确认入学，留位费不予退还。"
)

doc.add_heading("四、联系方式", level=2)
doc.add_paragraph("商学院招生办（虚构）邮箱：business-admissions@maplefield.example")

doc.save(OUT)
print(f"written: {OUT}")

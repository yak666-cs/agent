"""文件操作 Skill —— 纯提示词，无代码"""

from skills.base import BaseSkill, SkillMeta


class FileOpsSkill(BaseSkill):
    """指导 LLM 如何处理文件操作类的任务"""

    def __init__(self):
        super().__init__(SkillMeta(
            name="file_ops",
            description="文件读取、写入、查看",
            scenarios=["读文件", "写文件", "创建文件", "查看文件"],
        ))

    def get_prompt(self) -> str:
        return """
## Skill: 文件操作
当用户让你读文件时，直接用 read_file 工具把完整内容读出来，原文展示。
当用户让你写文件时，确认内容后用 write_file 工具执行。
当用户问"文件在哪"时，用 bash 执行 dir 命令。
如果路径不确定，先列目录再确认。

## Skill: 文档读取
当用户要求读取 PDF、Word (.docx)、Excel (.xlsx) 文件时，使用 read_document 工具。
不要尝试安装任何 Python 库（如 PyMuPDF、python-docx、openpyxl 等），这些库已预装。
不要尝试用 bash 或 python_repl 去解析文档，直接用 read_document 工具。
PDF 支持指定页范围（page_start / page_end），Excel 支持指定工作表（sheet_name）。
"""

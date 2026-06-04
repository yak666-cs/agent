"""
读取文档工具 —— PDF、Word、Excel
不依赖外部命令，纯 Python 解析。
"""

import os
from tools.base import BaseTool, ToolMeta, Permission
from tools.path_util import resolve_path


class ReadDocumentTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(
            name="read_document",
            description="读取 PDF、Word (.docx)、Excel (.xlsx) 文档内容。PDF 支持按页范围提取，Excel 支持指定工作表。",
            permission=Permission.READ_ONLY,
            requires_confirmation=False,
            timeout_seconds=30.0,
            tags=["file", "document", "pdf", "word", "excel"],
        ))

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文档路径，支持 .pdf / .docx / .xlsx"
                },
                "page_start": {
                    "type": "integer",
                    "description": "PDF 起始页码（从 1 开始），不指定则读取全部"
                },
                "page_end": {
                    "type": "integer",
                    "description": "PDF 结束页码（包含），不指定则读取到末尾"
                },
                "sheet_name": {
                    "type": "string",
                    "description": "Excel 工作表名称，不指定则读取所有工作表"
                },
            },
            "required": ["file_path"],
        }

    async def execute(self, file_path: str, page_start: int = None, page_end: int = None, sheet_name: str = None) -> str:
        full_path = resolve_path(file_path)
        if not os.path.exists(full_path):
            return f"(错误) 文件不存在: {file_path}"

        ext = os.path.splitext(full_path)[1].lower()

        try:
            if ext == ".pdf":
                return self._read_pdf(full_path, page_start, page_end)
            elif ext == ".docx":
                return self._read_docx(full_path)
            elif ext in (".xlsx", ".xls"):
                return self._read_xlsx(full_path, sheet_name)
            else:
                return f"(错误) 不支持的文件格式: {ext}，仅支持 .pdf / .docx / .xlsx"
        except ImportError as e:
            return f"(错误) 缺少依赖库: {e}，请安装对应的 Python 包"
        except Exception as e:
            return f"(错误) 读取失败: {e}"

    def _read_pdf(self, path: str, page_start: int = None, page_end: int = None) -> str:
        import fitz
        doc = fitz.open(path)
        total = len(doc)

        start = max(1, page_start or 1) - 1
        end = min(total, page_end or total)

        parts = [f"(PDF 文档: {os.path.basename(path)}, 共 {total} 页, 显示第 {start+1}-{end} 页)"]
        for i in range(start, end):
            page = doc[i]
            text = page.get_text().strip()
            if text:
                parts.append(f"\n--- 第 {i+1} 页 ---\n{text}")
            else:
                parts.append(f"\n--- 第 {i+1} 页 (无文本内容，可能为图片扫描页) ---")

        doc.close()
        return "\n".join(parts)

    def _read_docx(self, path: str) -> str:
        from docx import Document
        doc = Document(path)
        lines = [f"(Word 文档: {os.path.basename(path)})"]
        for para in doc.paragraphs:
            if para.text.strip():
                lines.append(para.text)
        return "\n".join(lines) if len(lines) > 1 else "(文档内容为空)"

    def _read_xlsx(self, path: str, sheet_name: str = None) -> str:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

        if sheet_name:
            if sheet_name not in wb.sheetnames:
                return f"(错误) 工作表 '{sheet_name}' 不存在，可用工作表: {', '.join(wb.sheetnames)}"
            sheets = [sheet_name]
        else:
            sheets = wb.sheetnames

        parts = [f"(Excel 文档: {os.path.basename(path)}, 共 {len(wb.sheetnames)} 个工作表)"]
        for name in sheets:
            ws = wb[name]
            parts.append(f"\n--- 工作表: {name} ({ws.max_row} 行 x {ws.max_column} 列) ---")
            for row in ws.iter_rows(values_only=True):
                row_vals = [str(v) if v is not None else "" for v in row]
                line = "\t".join(row_vals)
                if line.strip():
                    parts.append(line)

        wb.close()
        return "\n".join(parts) if len(parts) > 1 else "(文档内容为空)"

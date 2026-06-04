import io
from tools.base import BaseTool, ToolMeta, Permission


class PythonReplTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(
            name="python_repl",
            description="执行 Python 代码并返回输出。适用于：数学计算、数据处理、文本分析等。",
            permission=Permission.READ_ONLY,
            requires_confirmation=False,
            timeout_seconds=15.0,
            tags=["code", "python"],
        ))

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python 代码。使用 print() 输出结果。"
                },
            },
            "required": ["code"],
        }

    async def execute(self, code: str) -> str:
        safe_builtins = {
            "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
            "enumerate": enumerate, "float": float, "int": int, "len": len,
            "list": list, "max": max, "min": min, "print": print, "range": range,
            "round": round, "sorted": sorted, "str": str, "sum": sum,
            "tuple": tuple, "type": type, "zip": zip,
            "True": True, "False": False, "None": None,
        }
        try:
            local_ns = {}
            exec(code, {"__builtins__": safe_builtins, "__name__": "__main__"}, local_ns)
            results = [f"{k} = {v!r}" for k, v in local_ns.items() if not k.startswith("_")]
            return "\n".join(results) if results else "(代码执行完成，无显式输出)"
        except SyntaxError as e:
            return f"(语法错误) {e}"
        except Exception as e:
            return f"(执行错误) {type(e).__name__}: {e}"

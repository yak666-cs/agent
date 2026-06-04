# Agent Loop Lab

基于 [Agent Loop Lab](https://aglab.funfun.zone/) 题目，用 **DeepSeek V4-Flash** 构建的 Agent，支持自主调用工具完成任务。

## 5 秒启动

```powershell
cd agent-loop-lab
.\python main.py --simple
```

需要先设置 `DEEPSEEK_API_KEY`，有两种方式：

```powershell
# 方式一：临时设置
set DEEPSEEK_API_KEY=sk-xxx

# 方式二：复制 .env.example 为 .env，填入 key（自动加载）
copy .env.example .env
```

没 API Key？去 https://platform.deepseek.com/api_keys 注册就有免费额度。

## 两种启动方式

| 方式 | 命令 | 说明 |
|------|------|------|
| **CLI 学习模式** | `.\python main.py --simple` | 逐轮展示工具调用过程 |
| **Web 版** | `.\python web_app.py` | 浏览器打开 http://127.0.0.1:8000 |

也可以用 `run.bat` 双击启动学习模式。

---

## 项目结构

```
agent-loop-lab/
│
├── tools/                     ◄── Tool：可执行代码
│   ├── base.py                    BaseTool 基类 + 权限等级
│   ├── registry.py                tool_registry 注册中心
│   ├── selector.py                ToolSelector 意图筛选
│   ├── executor.py                ToolExecutor 超时/截断/异常
│   ├── path_util.py               路径解析
│   └── builtin/
│       ├── bash.py                执行系统命令
│       ├── file_reader.py         读取文件
│       ├── file_writer.py         写入文件
│       ├── file_deleter.py        删除文件  ← 新增
│       ├── web_search.py          搜索（占位）
│       └── python_repl.py         Python REPL
│
├── skills/                     ◄── Skill：纯提示词（无代码）
│   ├── base.py                    只有 get_prompt()
│   ├── manager.py                 skill_manager 管理注册
│   └── builtin/
│       ├── system_debug.py        "系统问题用 bash 查"
│       ├── file_ops.py            "读文件时直接展示内容"
│       ├── file_manage.py         "删文件时直接调工具" ← 新增
│       └── data_analysis.py       "计算用 python_repl"
│
├── agent/                      ◄── Agent 核心
│   ├── loop.py                    核心循环（Message → LLM → Tool → Message...）
│   ├── llm.py                     DeepSeek API 调用
│   ├── context.py                 上下文管理 + System Prompt 组装
│   └── types.py                   数据类型定义
│
├── harness/                    ◄── 工程化
│   ├── resilience.py              重试 + 熔断
│   └── observability.py           Token 统计 + 成本
│
├── static/index.html            Web 前端
├── main.py                      CLI 入口
├── web_app.py                   Web 入口
├── python.bat                   让 .\python 指向 Python 3.12
└── run.bat                      双击启动学习模式
```

---

## Tool 和 Skill 的区别

```
Tool：可执行代码，LLM 通过 tool_call 选中它来干活
      └── 例：BashTool.execute("dir") → 真正跑命令

Skill：纯提示词，注入 System Prompt 指导 LLM 行为
      └── 例："删文件时直接调 file_deleter，不要问"
```

| | Tool | Skill |
|--|------|-------|
| 有什么 | name + description + 参数定义 + execute() 代码 | 只有 name + get_prompt() 文本 |
| 怎么起作用 | LLM 调用它执行 | 注入 System Prompt 影响 LLM 思考 |
| 加一个需要 | 写 Python 类继承 BaseTool | 写 Python 类继承 BaseSkill |
| 注册方式 | `tool_registry.register(MyTool())` | `skill_manager.register(MySkill())` |

---

## 添加新能力（两步）

**第一步：写 Tool（真正的执行逻辑）**

```python
# tools/builtin/my_tool.py
from tools.base import BaseTool, ToolMeta, Permission

class MyTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(
            name="my_tool",
            description="描述给 LLM 看",
            permission=Permission.READ_ONLY,
        ))
    def parameters_schema(self):
        return {"type": "object", "properties": {...}}
    async def execute(self, **kwargs) -> str:
        # 真正干活的代码
        return "结果"
```

**第二步：写 Skill（指导 LLM 怎么用）**

```python
# skills/builtin/my_skill.py
from skills.base import BaseSkill, SkillMeta

class MySkill(BaseSkill):
    def get_prompt(self):
        return "## Skill: 当用户说X时，你先用Y工具，再用Z工具..."
```

**第三步：注册**

```python
# main.py
tool_registry.register(MyTool())     # ← 加这行
skill_manager.register(MySkill())    # ← 加这行
```

---

## 问题排查

| 现象 | 原因 |
|------|------|
| `python` 命令找不到 | 用 `.\python` 代替，或双击 `run.bat` |
| API 报错 401 | DEEPSEEK_API_KEY 没设置或填错了 |
| API 报错 402 | DeepSeek 账户余额不足 |
| Agent 不调工具只说话 | 任务太简单，LLM 觉得不需要工具 |
| Agent 问"确认吗"不执行 | 修改 `agent/context.py` 里的规则，要求直接调 |
| 文件删不了 | CLI 模式会弹确认，Web 模式禁止删除 |

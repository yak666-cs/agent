# KAI AGENT — Agent Loop Lab

基于 DeepSeek LLM 的桌面 AI 助手，支持 **CLI / Web / 原生桌面窗口** 三种运行形态。核心架构复刻 Claude Code 的 Agent Loop 模式。

---

## 目录结构

```
agent-loop-lab/
├── agent/                   # 核心引擎
│   ├── loop.py              # AgentLoop 主循环
│   ├── types.py             # 数据类型: Message, ToolCall, ToolResult, AgentState
│   ├── context.py           # ContextManager — 上下文工程(滑动窗口/摘要/相关性裁剪)
│   ├── llm.py               # LLMClient — OpenAI 兼容客户端(默认 DeepSeek)
│   └── subagent.py          # SubagentManager — 子任务分解与并发调度
├── tools/                   # 工具层(可执行代码)
│   ├── base.py              # BaseTool 抽象基类
│   ├── registry.py          # ToolRegistry 单例注册中心
│   ├── selector.py          # ToolSelector — 工具列表传给 LLM
│   ├── executor.py          # ToolExecutor — 执行边界(超时/截断/沙箱/缓存)
│   ├── cache.py             # ResultCache — 工具结果缓存(TTL)
│   ├── prompt_cache.py      # PromptCache — 分层提示词缓存(L1内存+L2磁盘)
│   ├── sandbox.py           # Sandbox — 策略沙箱(文件/命令/资源三级)
│   ├── path_util.py         # 路径解析工具
│   └── builtin/             # 内建工具
│       ├── bash.py          # 执行终端命令
│       ├── file_reader.py   # 读取文件(支持行号范围)
│       ├── file_writer.py   # 写入/创建文件
│       ├── file_deleter.py  # 删除文件
│       ├── web_search.py    # 互联网搜索(百度+Bing)
│       ├── python_repl.py   # 安全 Python REPL
│       ├── system_info.py   # 系统概况(CPU/内存/磁盘/网络)
│       ├── process_manager.py # 进程管理
│       ├── read_document.py # 读 PDF/Word/Excel
│       ├── memory_tool.py   # 长期记忆读写
│       ├── ip_geolocation.py# IP 地理定位
│       └── subagent_tool.py # 子Agent 委派工具
├── skills/                  # 技能层(纯提示词)
│   ├── base.py              # BaseSkill 抽象基类
│   ├── manager.py           # SkillManager — 拼接提示词注入 System Prompt
│   └── builtin/
│       ├── system_debug.py  # 系统排查
│       ├── file_ops.py      # 文件操作
│       ├── data_analysis.py # 数据分析
│       ├── file_manage.py   # 文件管理(删除)
│       └── memory.py        # 长期记忆
├── harness/                 # 工程化模块
│   ├── observability.py     # AgentObserver + SessionMetrics + 成本估算(CNY)
│   ├── auth.py              # 用户认证(注册/登录/Token/PBKDF2)
│   └── resilience.py        # CircuitBreaker + RetryConfig + 指数退避
├── memory/
│   ├── __init__.py          # MemoryStore — 长期记忆(SQLite)
│   └── conversation_store.py# ConversationStore — 会话历史(SQLite)
├── static/
│   └── index.html           # 前端单页应用(SSE + 认证 + 文件上传)
├── main.py                  # CLI 入口
├── web_app.py               # Web 版(FastAPI + SSE, 端口8000)
├── KAI_AGENT.py             # 桌面版(pywebview + 托盘, 端口8765)
├── mobile/
│   └── main.py              # Kivy/Android 移动端
├── tests/                   # 测试
├── tests_plan/              # 测试计划(pytest conftest)
├── requirements.txt         # 依赖
└── CLAUDE.md                # 本文件
```

---

## 三种运行入口

| 入口 | 命令 | 端口 | 沙箱 | 工具数 | 技能数 |
|------|------|------|------|--------|--------|
| CLI | `python main.py` | — | PERMISSIVE | 7 | 4 |
| Web | `python web_app.py` | 8000 | RESTRICTIVE | 6 | 4 |
| 桌面 | `python KAI_AGENT.py` | 8765 | RESTRICTIVE(可调) | 11 | 5 |

- 桌面版双击 `KAI_AGENT.bat` / `KAI_AGENT.vbs` 启动，支持系统托盘
- 所有入口自动加载 `.env` 文件

---

## 环境变量

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key(首选) | — |
| `LLM_API_KEY` | 通用 LLM Key(备选) | — |
| `OPENAI_API_KEY` | OpenAI Key(兜底) | — |
| `LLM_BASE_URL` | API 地址 | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 模型名 | `deepseek-v4-flash` |
| `KAI_AGENT_PORT` | 桌面版端口 | 8765 |
| `KAI_MEMORY_PATH` | SQLite 目录 | `data/memory/` |
| `KAI_CACHE_DIR` | L2 缓存目录 | `.kai_cache` |
| `HTTP_PROXY` / `HTTPS_PROXY` | 代理 | — |

**.env 文件编码为 UTF-8**，Windows 中文系统默认 GBK，打开时必须指定 `encoding="utf-8"`。

---

## 核心架构

### AgentLoop (`agent/loop.py`)
主循环：用户消息 → LLM 推理 → 工具调用(并行) → LLM 再推理 → 最终回复
- `max_turns=15`, `max_consecutive_errors=3`
- 内建 CircuitBreaker + RetryConfig
- 响应缓存(30s TTL, 消息 hash)
- 支持 `cancel()` 中断
- 5 个观察者钩子: `on_turn_start/end`, `on_tool_call/result`, `on_llm_response`
- 致命错误类型(AUTH, BAD_REQUEST, CONTEXT_LENGTH) 直接返回

### ContextManager (`agent/context.py`)
三种上下文工程策略(全部启用):
1. **滑动窗口** — 保留最近 40 条消息
2. **历史摘要** — 旧 USER→ASSISTANT 轮次压缩为 `[历史摘要]`
3. **相关性裁剪** — 按用户问题关键词过滤无关消息
- System Prompt 始终保留在最前面
- `repair_tool_pairs()` 修复残缺 tool_call↔tool_result 配对
- `compression_log` 记录每次压缩操作

### Tool 与 Skill 分离
- **Tool**: 有 `execute()` 代码，是"能力"
- **Skill**: 只有 `get_prompt()` 文本，是"知识/规则"，注入 System Prompt

### Sandbox (`tools/sandbox.py`)
三级安全边界：文件系统 / 命令 / 资源
- RESTRICTIVE: 白名单模式，仅允许放行命令
- PERMISSIVE: 黑名单模式，默认放行
- 可通过 API(`/api/sandbox/config`) 运行时调整

### CircuitBreaker (`harness/resilience.py`)
CLOSED → OPEN → HALF_OPEN 状态机
- `failure_threshold=3`, `cooldown_seconds=30s`
- 每次 LLM 调用前检查 `allow_request()`

---

## 11 个注册工具

| 工具名 | 超时 | 缓存TTL | 权限 | 功能 |
|--------|------|---------|------|------|
| `bash` | 60s | — | SHELL | 执行终端命令 |
| `read_file` | 10s | 10s | READ_ONLY | 读文件(支持行号范围) |
| `write_file` | 15s | — | READ_WRITE | 写文件 |
| `file_deleter` | 10s | — | DESTRUCTIVE | 删文件(不删目录) |
| `web_search` | 15s | 60s | NETWORK | 百度+Bing 搜索 |
| `python_repl` | 15s | — | READ_ONLY | 受限 Python 执行 |
| `system_info` | 15s | 3s | READ_ONLY | 系统概况 |
| `process_manager` | 15s | 2s | SHELL | 进程管理 |
| `read_document` | 30s | — | READ_ONLY | PDF/Word/Excel 文本提取 |
| `memory` | 5s | — | READ_WRITE | 长期记忆 save/recall/search/forget |
| `ip_geolocation` | 10s | 300s | READ_ONLY | IP 定位(中国用 cip.cc) |
| `subagent_delegate` | 300s | — | READ_ONLY | 子任务分解+并发执行 |

注: `subagent_delegate` 在 `main.py` 和 `web_app.py` 中通过 `SubagentDelegateTool` 动态注册(非内置)。

---

## 5 个注册技能

| 技能 | 触发场景 |
|------|---------|
| `system_debug` | CPU/内存/磁盘/端口/进程排查 |
| `file_ops` | 文件读写/文档读取 |
| `data_analysis` | 计算/统计/数据分析 |
| `file_manage` | 删除文件相关操作 |
| `memory` | 长期记忆(记住/回忆) |

---

## 数据库

所有 SQLite 文件存储在 `KAI_MEMORY_PATH` 目录 (`check_same_thread=False`):

| 文件 | 管理类 | 表 |
|------|--------|-----|
| `kai_memory.db` | `MemoryStore` | `memories`(key, type, content, tags) |
| `conversations.db` | `ConversationStore` | `sessions` + `messages`(含 tool_data JSON) |
| `auth.db` | `AuthStore` | `users`(username, password_hash, token) |

---

## 前端要点

- 纯 HTML+CSS+JS 单页应用，通过 SSE 接收流式事件
- 认证: PBKDF2 密码哈希 + Bearer Token 存在 localStorage
- 会话管理: 多标签页，消息持久化到 conversation_store
- 支持文件上传(60+ 扩展名)，自动解析 PDF/Word/Excel
- Markdown 简易渲染器(非 marked.js，内建实现)
- 首次启动弹出登录/注册模态框

---

## 重要设计决策

1. `.env` 必须用 `encoding="utf-8"` 打开，否则 Windows 中文系统崩溃
2. 桌面版 pywebview 使用 `url` 而非 `html` 参数加载，避免 about:blank 跨域问题
3. 工具调用使用 `asyncio.gather` 并行执行
4. 成本估算基于 DeepSeek 官方定价(CNY)，在 `harness/observability.py` 中定义
5. IP 定位中国用 `cip.cc`，国外回退 `ipinfo.io`
6. 子代理中禁止递归调用 `subagent_delegate`
7. 前端所有 `fetch()` 使用 `authFetch()` 包装自动加 Authorization 头
8. 页面所有文字可选中复制(无 `user-select: none`)

---

## 子代理（Subagent）使用规则

项目在 `.claude/agents/` 中定义了以下子代理，遇到匹配场景时**必须自动使用**：

| 子代理 | 触发条件 | 模型 |
|--------|---------|------|
| `code-auditor` | 用户要求审计、审查项目、分析代码质量 | sonnet |
| `security-reviewer` | 涉及安全审查、密码、认证、注入风险 | haiku |
| `test-analyzer` | 用户要求检查测试、覆盖率、测试质量 | haiku |
| `task-planner` | 复杂多步骤需求，需要先规划再执行 | sonnet |
| `code-explorer` | 快速搜索代码、查找文件定义、理解结构 | haiku |

**规则：**
1. 多步骤的复杂任务，先 spawn `task-planner` 做分解规划
2. 可并行的子任务通过 `General-purpose agent` 并行执行
3. 审计/审查类任务必须使用专用子代理，不要自己串行做
4. 每个子代理完成后汇总结果，不要在一个子代理里做所有事

## 常见操作

```bash
python main.py                           # CLI 模式
python web_app.py                        # Web 模式(自动打开浏览器)
python KAI_AGENT.py                      # 桌面应用
pytest tests/ -v && pytest tests_plan/ -v  # 运行测试
find . -name "*.py" | xargs wc -l       # 统计代码行数
```

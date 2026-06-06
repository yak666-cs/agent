# KAI AGENT

基于 DeepSeek V4-Flash 的桌面 AI 智能体，可自主调用工具完成系统任务。
支持多会话管理、长期记忆、上下文工程、容错熔断、安全沙箱、子 Agent 分派等生产级特性。

## 快速启动

```powershell
cd agent-loop-lab

# 1. 设置 API Key
copy .env.example .env
# 编辑 .env，填入你的 DeepSeek API Key

# 2. 桌面应用（推荐）
python KAI_AGENT.py

# 3. 或 CLI 学习模式
python main.py --simple
```

没 API Key？去 https://platform.deepseek.com/api_keys 注册就有免费额度。

## 功能概览

### 12 个内置工具

| Tool | 说明 | 权限 |
|------|------|------|
| `bash` | 执行终端命令 | SHELL |
| `read_file` | 读取文件内容（支持行号范围） | READ_ONLY |
| `write_file` | 写入/创建文件 | READ_WRITE |
| `file_deleter` | 删除文件 | DESTRUCTIVE |
| `web_search` | 搜索互联网（百度 + Bing） | NETWORK |
| `python_repl` | 执行 Python 代码 | READ_ONLY |
| `system_info` | 一键获取系统概况（CPU/内存/磁盘/网络） | READ_ONLY |
| `process_manager` | 查看/管理进程（list/info/kill） | SHELL |
| `read_document` | 读取 PDF / Word / Excel 文档 | READ_ONLY |
| `memory` | 长期记忆读写（save/recall/search/list/forget） | READ_WRITE |
| `ip_geolocation` | IP 地理定位 | READ_ONLY |
| `subagent_delegate` | 子任务分解+并发执行 | READ_ONLY |

### 长期记忆

Agent 具备两层记忆系统：

**1. 事实记忆（MemoryStore）** — 你告诉 Agent 的信息
- `memory` 工具的 `save` / `recall` / `search` 操作
- Agent 每次对话开始时自动检索相关记忆注入上下文
- 存储在 `F:\KAI_AGENT\memory\kai_memory.db`

**2. 对话记忆（ConversationStore）** — 完整的聊天历史
- 每次对话自动持久化到 SQLite
- 重启后自动加载历史会话和消息
- 多标签页管理，支持切换/重命名/删除
- 存储在 `F:\KAI_AGENT\memory\conversations.db`

### 性能优化

- **工具结果缓存** — `system_info`（3s）、`process_manager`（2s）、`read_file`（10s）、`web_search`（60s）的结果在 TTL 内直接复用
- **LLM 响应缓存** — 30 秒内相同请求跳过 API 调用，零延迟零 token
- **Prompt Cache 分层缓存** — L1 内存（30s）+ L2 磁盘（5min），缓存命中统计

### 工程化特性

#### Resilience（容错）

| 机制 | 说明 | 配置 |
|------|------|------|
| **指数退避重试** | LLM 调用失败后 1s → 2s → 4s 递增等待 | `max_retries=2, base_delay=1.0` |
| **熔断器** | 连续 N 次失败 → 暂停 30s → 半开探测 → 恢复或继续熔断 | `failure_threshold=5, cooldown=30s` |
| **优雅降级** | 工具执行失败 → 错误信息回传 LLM 自行调整；熔断时跳过 LLM 调用直接报错 | 自动 |

#### Sandbox（安全沙箱）

三层安全边界，可配置严格/宽松模式：

| 边界 | 说明 |
|------|------|
| **文件系统** | 路径白名单（如 `~/Desktop/*`）+ 敏感路径黑名单（`.env`、`.ssh`、Windows 系统目录） |
| **命令执行** | 破坏性命令黑名单（`rm -rf /`、`format`、`shutdown`）、严格模式禁止高危操作（`sudo`、`curl -O`） |
| **资源限制** | 输出行数上限（5000）、字符数上限（50000） |

#### Auth（用户认证）

基于 Token 认证 + PBKDF2-SHA256 密码哈希：

| 功能 | 说明 |
|------|------|
| **注册** | 用户名 + 密码，密码经 600K 轮 PBKDF2 哈希 |
| **登录** | 验证密码，返回 64 字符随机 Token |
| **鉴权** | FastAPI `get_current_user()` 从 Bearer Token 提取用户 |
| **登出** | 清除 Token，强制重新登录 |

#### Observability（可观测性）

| 功能 | 说明 |
|------|------|
| **Token 统计** | 每次 LLM 请求的输入/输出 token 累计追踪 |
| **成本估算** | 按模型定价表（DeepSeek/GPT/Claude）自动换算人民币 |
| **性能指标** | 每轮耗时、工具执行耗时、LLM 延迟 |
| **日志持久化** | 会话结束后自动保存 JSON 到 `logs/`，支持 `to_file()` / `from_file()` 恢复 |

```python
# 使用示例
observer = AgentObserver(model="deepseek-v4-flash")
agent.register_observer(observer)  # 一键挂载所有钩子
# 会话结束后:
path = observer.metrics.to_file()
print(observer.metrics.summary())
```

#### Subagents（子 Agent 分派）

将复杂任务自动分解为多个子任务，支持三种执行模式：

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| **并行** | 所有子任务同时执行 | 独立子任务（查 CPU + 查内存 + 查磁盘） |
| **串行** | 前序结果传递给后续 | 有依赖关系（先写文件 → 再统计字数） |
| **混合** | 依赖图并发调度 | 一部分子任务并行、另一部分按依赖顺序（先并行收集数据 → 再串行分析 → 最后生成报告） |

```python
# 使用示例
manager = SubagentManager(llm=llm, tool_registry=tool_registry, ...)
result = await manager.run("分析系统性能并生成报告")
```

#### Prompt Cache（提示词缓存）

| 级别 | 实现 | TTL | 说明 |
|------|------|-----|------|
| L1 内存 | `dict` | 30s | 进程内极速缓存 |
| L2 磁盘 | `.kai_cache/*.json` | 5min | 跨进程持久化 |
| System Prompt 缓存 | 专用 key 前缀 | - | 稳定不变的部分单独缓存 |

```python
from tools.prompt_cache import prompt_cache
key = prompt_cache.make_key(messages, tools)
cached = prompt_cache.get(key)  # 自动查 L1 → L2
prompt_cache.set(key, content, tool_calls, finish_reason)
print(prompt_cache.stats.summary())  # 缓存命中统计
```

## 三种启动方式

| 方式 | 命令 | 端口 | 沙箱模式 | 工具数 |
|------|------|------|----------|--------|
| **桌面应用** | `python KAI_AGENT.py` | 8765 | RESTRICTIVE（可调） | 12 |
| **Web 版** | `python web_app.py` | 8000 | RESTRICTIVE | 12 |
| **CLI 模式** | `python main.py` | — | PERMISSIVE | 12 |

桌面应用特性：
- 原生 Windows 窗口（Edge Chromium 渲染）
- 多会话标签页管理
- 文件拖拽上传（自动解析 PDF/Word/Excel）
- 系统托盘，支持最小化隐藏
- 会话历史持久化

## 项目结构

```
agent-loop-lab/
│
├── KAI_AGENT.py                ◄── 桌面应用入口（FastAPI + pywebview）
├── main.py                     ◄── CLI 入口
├── web_app.py                  ◄── Web 版入口
│
├── agent/                      ◄── Agent 核心
│   ├── loop.py                    核心循环（Message → LLM → Tool → Message...）
│   ├── llm.py                     DeepSeek API 调用（OpenAI 兼容格式）
│   ├── context.py                 上下文工程（滑动窗口/历史摘要/相关性裁剪/配对修复）
│   ├── subagent.py                子 Agent 分派与多角色协作（并行/串行/混合依赖图）
│   └── types.py                   数据类型定义（Message/ToolCall/ToolResult/AgentState）
│
├── tools/                       ◄── 工具层（可执行代码）
│   ├── base.py                     BaseTool 基类 + 权限等级（READ_ONLY → DESTRUCTIVE）
│   ├── registry.py                 tool_registry 单例注册中心
│   ├── selector.py                 ToolSelector 工具选择（top_k 限制）
│   ├── executor.py                 ToolExecutor（超时控制/输出截断/沙箱集成/结果缓存）
│   ├── cache.py                    工具结果缓存（TTL 内存缓存）
│   ├── prompt_cache.py             分层 Prompt 缓存（L1 内存 30s + L2 磁盘 5min）
│   ├── sandbox.py                  策略沙箱（文件系统/命令/资源三层安全边界）
│   ├── path_util.py                路径解析（桌面别名展开）
│   └── builtin/
│       ├── bash.py                 执行系统命令
│       ├── file_reader.py          读取文件（支持行号范围）
│       ├── file_writer.py          写入/创建文件
│       ├── file_deleter.py         删除文件
│       ├── web_search.py           搜索互联网（百度 + Bing）
│       ├── python_repl.py          安全 Python REPL
│       ├── system_info.py          系统概况（CPU/内存/磁盘/网络）
│       ├── process_manager.py      进程管理（list/info/kill）
│       ├── read_document.py        文档读取（PDF/Word/Excel 文本提取）
│       ├── memory_tool.py          长期记忆读写（save/recall/search/forget）
│       ├── ip_geolocation.py       IP 地理定位（cip.cc/ipinfo.io）
│       └── subagent_tool.py        子 Agent 委派工具
│
├── skills/                      ◄── 技能层（纯提示词，注入 System Prompt）
│   ├── base.py                     BaseSkill 抽象基类
│   ├── manager.py                  SkillManager 单例（拼接提示词注入）
│   └── builtin/
│       ├── system_debug.py         系统排查指导
│       ├── file_ops.py             文件操作指导
│       ├── file_manage.py          文件管理指导（删除相关）
│       ├── data_analysis.py        数据分析指导
│       └── memory.py               长期记忆使用指导
│
├── memory/                      ◄── 持久化存储（SQLite）
│   ├── __init__.py                  MemoryStore（事实记忆：key-value + LIKE 搜索）
│   └── conversation_store.py        ConversationStore（会话历史：sessions + messages）
│
├── harness/                     ◄── 工程化支撑
│   ├── resilience.py               熔断器（CLOSED→OPEN→HALF_OPEN）+ 指数退避重试
│   ├── observability.py            AgentObserver + SessionMetrics + 成本估算（CNY）
│   └── auth.py                     用户认证（PBKDF2 + Token + FastAPI 依赖注入）
│
├── mobile/
│   └── main.py                  ◄── Kivy/Android 移动端
│
├── static/
│   └── index.html               ◄── 前端单页应用（SSE + 认证 + 文件上传 + 沙箱设置）
│
├── tests/                       ◄── 已有测试（agent/resilience/subagent）
├── tests_plan/                  ◄── 完整测试计划（8 模块 164 项测试）
│
├── .env                          ◄── API Key 配置
├── .env.example                  ◄── 配置模板
├── pyproject.toml                ◄── 项目元数据
└── requirements.txt              ◄── 依赖清单
```

## 添加新能力

三步添加一个新工具：

**1. 写 Tool（执行逻辑）**

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
        return "结果"
```

**2. 可选：写 Skill（指导 LLM 怎么用）**

```python
# skills/builtin/my_skill.py
from skills.base import BaseSkill, SkillMeta

class MySkill(BaseSkill):
    def get_prompt(self):
        return "## Skill: 当用户说X时，你先用Y工具..."
```

**3. 注册**

```python
# KAI_AGENT.py（或 main.py）的 _register_all() 函数中
tool_registry.register(MyTool())
skill_manager.register(MySkill())
```

## 缓存机制

| 级别 | 实现 | TTL | 作用 |
|------|------|-----|------|
| 工具结果 | `tools/cache.py` | 2-60s | 同参数重复调用直接返回 |
| LLM 响应 | `agent/loop.py` | 30s | 完全相同请求跳过 API |
| Prompt L1 | `tools/prompt_cache.py` | 30s | 进程内内存缓存 |
| Prompt L2 | `tools/prompt_cache.py` | 5min | 磁盘持久化缓存 |

缓存自动生效，无需手动配置。

## 上下文工程

Agent 在 `agent/context.py` 中实现了三层上下文管理，确保长对话中 LLM 窗口不被撑爆，同时尽可能保留有价值的信息：

| 策略 | 参数 | 说明 |
|------|------|------|
| **滑动窗口** | `window_size=N` | 限制消息条数，超出时从最旧开始丢弃。确保 ASSISTANT(tool_calls) ↔ TOOL 配对不被破坏 |
| **历史摘要** | `enable_summary=True` | 超预算时，把最早一轮对话压缩成 `[历史摘要]` 格式，代替直接删除 |
| **相关性裁剪** | `enable_relevance=True` | 只保留内容包含当前问题关键词的消息（自动提取英文词如 CPU、API），最后 2 条始终保留 |

三者可组合使用。裁剪优先级：滑动窗口 → 预算裁剪（摘要） → 相关性过滤。

```python
# 使用示例
ctx = ContextManager(
    window_size=20,
    enable_summary=True,
    enable_relevance=True,
)
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | - |
| `LLM_API_KEY` | 通用 API Key（备选） | - |
| `LLM_BASE_URL` | API 地址 | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 模型名 | `deepseek-v4-flash` |
| `KAI_MEMORY_PATH` | 记忆数据库目录 | `F:\KAI_AGENT\memory` |
| `KAI_AGENT_PORT` | Web 服务端口 | `8765` |

## 问题排查

| 现象 | 原因 |
|------|------|
| API 报错 401 | DEEPSEEK_API_KEY 没设置或填错了 |
| API 报错 402 | DeepSeek 账户余额不足 |
| Agent 连续 3 次调用失败 | API Key 失效，检查 .env 中的 key |
| Agent 不调工具只说话 | 任务太简单，LLM 觉得不需要工具 |
| 文件删不了 | 桌面应用模式下禁止删除文件 |
| bash 命令报安全限制 | 命令不在白名单中，桌面模式受限 |
| 沙箱报错 | 点击前端 🔒 沙箱按钮切换模式或调整白名单 |

## 运行测试

```bash
cd agent-loop-lab

# 运行原有测试
pytest tests/ -v

# 运行完整 8 模块 164 项测试
PYTHONPATH=. python -m pytest tests_plan/ -v

# 运行单个模块
PYTHONPATH=. python -m pytest tests_plan/test_sandbox.py -v
```

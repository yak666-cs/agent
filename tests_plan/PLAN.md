# KAI Agent 测试计划

## 概述

覆盖 8 个核心模块，总计 57+ 个测试场景。

| 模块 | 测试文件 | 场景数 | 优先级 |
|------|---------|--------|--------|
| Memory | `test_memory.py` | 8 | P0-P2 |
| Skills/Multi-tool | `test_skills_multi_tool.py` | 10 | P0-P2 |
| Resilience | `test_resilience.py` | 12 | P0-P2 |
| Sandbox | `test_sandbox.py` | 11 | P0-P2 |
| Prompt Cache | `test_prompt_cache.py` | 8 | P0-P2 |
| Context Engineering | `test_context_engineering.py` | 11 | P0-P2 |
| Observability | `test_observability.py` | 6 | P0-P2 |
| Subagents | `test_subagent.py` | 8 | P0-P2 |

## 运行方式

```bash
# 安装依赖
pip install -e .
pip install pytest pytest-asyncio

# 运行全部测试
pytest tests_plan/ -v

# 运行单个模块
pytest tests_plan/test_memory.py -v
```

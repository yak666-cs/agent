# -*- coding: utf-8 -*-
test_info = {
    "tests/test_agent.py": {"modules": ["agent/context.py", "agent/types.py", "tools/base.py", "tools/executor.py", "tools/registry.py", "tools/selector.py"], "tests": 9},
    "tests/test_resilience.py": {"modules": ["agent/context.py", "agent/llm.py", "agent/loop.py", "agent/types.py"], "tests": 3},
    "tests/test_subagent.py": {"modules": ["agent/subagent.py"], "tests": 4},
    "tests_plan/test_context_engineering.py": {"modules": ["agent/context.py"], "tests": 18},
    "tests_plan/test_memory.py": {"modules": ["memory/conversation_store.py"], "tests": 20},
    "tests_plan/test_observability.py": {"modules": ["harness/observability.py"], "tests": 26},
    "tests_plan/test_prompt_cache.py": {"modules": ["tools/prompt_cache.py"], "tests": 17},
    "tests_plan/test_resilience.py": {"modules": ["harness/resilience.py", "agent/loop.py", "agent/llm.py", "agent/context.py"], "tests": 20},
    "tests_plan/test_sandbox.py": {"modules": ["tools/sandbox.py"], "tests": 33},
    "tests_plan/test_skills_multi_tool.py": {"modules": ["tools/base.py", "tools/registry.py", "tools/selector.py", "tools/executor.py", "skills/manager.py", "skills/base.py"], "tests": 20},
    "tests_plan/test_subagent.py": {"modules": ["agent/subagent.py"], "tests": 18},
}

covered = set()
for k, v in test_info.items():
    for m in v["modules"]:
        covered.add(m)

all_mods = [
    "agent/loop.py", "agent/types.py", "agent/context.py", "agent/llm.py", "agent/subagent.py",
    "tools/base.py", "tools/registry.py", "tools/selector.py", "tools/executor.py", "tools/cache.py", "tools/prompt_cache.py", "tools/sandbox.py", "tools/path_util.py",
    "tools/builtin/bash.py", "tools/builtin/file_deleter.py", "tools/builtin/file_reader.py", "tools/builtin/file_writer.py", "tools/builtin/ip_geolocation.py", "tools/builtin/memory_tool.py", "tools/builtin/process_manager.py", "tools/builtin/python_repl.py", "tools/builtin/read_document.py", "tools/builtin/subagent_tool.py", "tools/builtin/system_info.py", "tools/builtin/web_search.py",
    "skills/base.py", "skills/manager.py",
    "skills/builtin/data_analysis.py", "skills/builtin/file_manage.py", "skills/builtin/file_ops.py", "skills/builtin/memory.py", "skills/builtin/subagent_delegation.py", "skills/builtin/system_debug.py", "skills/builtin/task_planning.py",
    "harness/observability.py", "harness/auth.py", "harness/resilience.py",
    "memory/conversation_store.py"
]

missing = [m for m in all_mods if m not in covered]
total_tests = sum(v["tests"] for v in test_info.values())

print("=" * 60)
print("Test File Summary")
print("=" * 60)
for tf in sorted(test_info.keys()):
    info = test_info[tf]
    print("  " + tf)
    print("     Test functions: %d" % info["tests"])
    print("     Covers: %s" % ", ".join(info["modules"]))
    print()

print("  Total test files: %d" % len(test_info))
print("  Total test functions: %d" % total_tests)

print()
print("=" * 60)
print("MISSING modules (no test coverage)")
print("=" * 60)
for m in sorted(missing):
    print("  X " + m)

print()
print("=" * 60)
print("COVERED modules")
print("=" * 60)
for m in sorted(all_mods):
    if m in covered:
        print("  V " + m)

groups = {
    "agent": ["loop.py", "types.py", "context.py", "llm.py", "subagent.py"],
    "tools": ["base.py", "registry.py", "selector.py", "executor.py", "cache.py", "prompt_cache.py", "sandbox.py", "path_util.py"],
    "tools/builtin": ["bash.py", "file_deleter.py", "file_reader.py", "file_writer.py", "ip_geolocation.py", "memory_tool.py", "process_manager.py", "python_repl.py", "read_document.py", "subagent_tool.py", "system_info.py", "web_search.py"],
    "skills": ["base.py", "manager.py"],
    "skills/builtin": ["data_analysis.py", "file_manage.py", "file_ops.py", "memory.py", "subagent_delegation.py", "system_debug.py", "task_planning.py"],
    "harness": ["observability.py", "auth.py", "resilience.py"],
    "memory": ["conversation_store.py"]
}

print()
print("=" * 60)
print("Coverage by Package")
print("=" * 60)
for pkg, files in sorted(groups.items()):
    cnt = 0
    miss = []
    for f in files:
        key = "%s/%s" % (pkg, f)
        if key in covered:
            cnt += 1
        else:
            miss.append(f)
    print("  %s/  (%d/%d)" % (pkg, cnt, len(files)))
    if miss:
        print("     Missing: %s" % ", ".join(miss))
    print()

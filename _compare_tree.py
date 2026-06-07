# -*- coding: utf-8 -*-
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 从 CLAUDE.md 目录树提取的路径
doc_dirs = {'agent', 'tools', 'tools/builtin', 'skills', 'skills/builtin', 'harness', 'memory', 'static', 'mobile', 'tests', 'tests_plan'}

doc_files = {
    'agent/loop.py', 'agent/types.py', 'agent/context.py', 'agent/llm.py', 'agent/subagent.py',
    'tools/base.py', 'tools/registry.py', 'tools/selector.py', 'tools/executor.py',
    'tools/cache.py', 'tools/prompt_cache.py', 'tools/sandbox.py', 'tools/path_util.py',
    'tools/builtin/bash.py', 'tools/builtin/file_reader.py', 'tools/builtin/file_writer.py',
    'tools/builtin/file_deleter.py', 'tools/builtin/web_search.py', 'tools/builtin/python_repl.py',
    'tools/builtin/system_info.py', 'tools/builtin/process_manager.py', 'tools/builtin/read_document.py',
    'tools/builtin/memory_tool.py', 'tools/builtin/ip_geolocation.py', 'tools/builtin/subagent_tool.py',
    'skills/base.py', 'skills/manager.py',
    'skills/builtin/system_debug.py', 'skills/builtin/file_ops.py',
    'skills/builtin/data_analysis.py', 'skills/builtin/file_manage.py', 'skills/builtin/memory.py',
    'harness/observability.py', 'harness/auth.py', 'harness/resilience.py',
    'memory/__init__.py', 'memory/conversation_store.py',
    'static/index.html', 'main.py', 'web_app.py', 'KAI_AGENT.py', 'mobile/main.py',
    'requirements.txt', 'CLAUDE.md',
}

# 实际存在的目录（从 dir 输出中提取）
actual_dirs = {
    '.claude', '.claude/agents', '.git', '.github', '.kai_cache',
    '.pytest_cache', 'agent', 'data', 'harness', 'memory', 'mobile',
    'resume_render', 'skills', 'static', 'tests', 'tests_plan', 'tools',
    'uploads', '__pycache__',
}

# 实际存在的文件（从 dir 输出中提取）
actual_files = {
    '.env', '.env.example', '.gitignore', 'baidu_weather.html', 'bash.exe.stackdump',
    'bing_full.html', 'bing_weather.html', 'buildozer.spec', 'build_resume_docx.py',
    'check_api.py', 'CLAUDE.md', 'convert_icon.py', 'create_shortcut.vbs',
    'debug_log.txt', 'exercises.md', 'generate_icon.py', 'job_pdf_extract.txt',
    'KAI_AGENT.bat', 'kai_agent.ico', 'KAI_AGENT.py', 'KAI_AGENT.vbs', 'kai_server.log',
    'main.py', 'patch_obs_js.py', 'patch_obs_js2.py', 'processes.csv', 'pyproject.toml',
    'python.bat', 'README.md', 'refresh_shortcut.vbs', 'requirements.txt',
    'resume.pdf', 'resume_docx_textboxes.txt', 'resume_pdf_extract.txt',
    'run.bat', 'start.bat', 'startup_log.txt', 'temp_procs.txt', 'thesis_extract.txt',
    'TOOL_ROADMAP.md', 'web_app.py', '_analyze.py', '_test_context.py',
    '.claude/agents/code-auditor.md', '.claude/agents/code-explorer.md',
    '.claude/agents/security-reviewer.md', '.claude/agents/task-planner.md',
    '.claude/agents/test-analyzer.md',
}

print('=' * 65)
print(' 1. CLAUDE.md 声称存在但实际不存在的')
print('=' * 65)

missing_dirs = doc_dirs - actual_dirs
if missing_dirs:
    for d in sorted(missing_dirs):
        print(f'  [MISS DIR]  {d}/')
else:
    print('  (无缺失目录)')

missing_files = doc_files - actual_files
if missing_files:
    for f in sorted(missing_files):
        print(f'  [MISS FILE] {f}')
else:
    print('  (无缺失文件)')

print()
print('=' * 65)
print(' 2. 实际存在但 CLAUDE.md 未提及的')
print('=' * 65)

extra_dirs = actual_dirs - doc_dirs
if extra_dirs:
    for d in sorted(extra_dirs):
        print(f'  [EXTRA DIR]  {d}/')
else:
    print('  (无多余目录)')

extra_files = actual_files - doc_files
if extra_files:
    for f in sorted(extra_files):
        print(f'  [EXTRA FILE] {f}')
else:
    print('  (无多余文件)')

print()
print('=' * 65)
print(' 3. 重点文件专项检查')
print('=' * 65)
targets = ['static/index.html', '.env.example', 'requirements.txt', 'pyproject.toml']
for name in targets:
    status = 'EXISTS' if name in actual_files else 'NOT FOUND'
    print(f'  [{status:>9}] {name}')

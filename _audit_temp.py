# -*- coding: utf-8 -*-
import os, ast
from collections import defaultdict

root = r'C:\Users\DYK\Desktop\agent\agent-loop-lab'
file_stats = []
all_py_files = []

for dirpath, dirnames, filenames in os.walk(root):
    parts = dirpath.split(os.sep)
    skip = False
    for p in parts:
        if p.startswith('.') and p not in ['.']:
            skip = True
            break
        if p in ('__pycache__', '.git', '.pytest_cache', '.kai_cache', '.github'):
            skip = True
            break
    if skip:
        continue
    for f in filenames:
        if f.endswith('.py'):
            all_py_files.append(os.path.join(dirpath, f))

for fp in all_py_files:
    rel = os.path.relpath(fp, root).replace('\\', '/')
    module = 'other'
    if rel.startswith('agent/'): module = 'agent'
    elif rel.startswith('tools/'): module = 'tools'
    elif rel.startswith('harness/'): module = 'harness'
    elif rel.startswith('memory/'): module = 'memory'
    elif rel.startswith('skills/'): module = 'skills'
    elif '/' not in rel: module = 'root_py'
    
    lines = 0; classes = 0; functions = 0
    try:
        with open(fp, 'r', encoding='utf-8') as fh:
            content = fh.read()
        lines = content.count('\n')
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef): classes += 1
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): functions += 1
    except:
        pass
    file_stats.append({'path': rel, 'module': module, 'lines': lines, 'classes': classes, 'functions': functions})

by_module = defaultdict(list)
for s in file_stats:
    by_module[s['module']].append(s)

print('=== 各模块统计 ===')
for mod in ['agent', 'tools', 'harness', 'memory', 'skills', 'root_py', 'other']:
    files = sorted(by_module[mod], key=lambda x: x['lines'], reverse=True)
    tl = sum(f['lines'] for f in files)
    tc = sum(f['classes'] for f in files)
    tf = sum(f['functions'] for f in files)
    print(f'\n模块: {mod} ({len(files)}个文件, {tl}行, {tc}类, {tf}函数)')
    for f in files:
        print(f'  {f["path"]:45s} {f["lines"]:5d}行  {f["classes"]}类  {f["functions"]}函数')

print('\n\n=== TOP 10 最大文件 ===')
sorted_all = sorted(file_stats, key=lambda x: x['lines'], reverse=True)
for i, f in enumerate(sorted_all[:10], 1):
    print(f'{i:2d}. {f["path"]:50s} {f["lines"]:5d}行  {f["classes"]}类  {f["functions"]}函数  [{f["module"]}]')

print(f'\n总计: {len(file_stats)} 个 .py 文件, {sum(f["lines"] for f in file_stats)} 行代码')

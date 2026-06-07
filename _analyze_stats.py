#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""项目 .py 文件统计脚本"""
import ast
import os

ROOT = r"C:\Users\DYK\Desktop\agent\agent-loop-lab"

def get_all_py_files(root):
    result = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 跳过 venv、.git 等目录
        skip_dirs = {'venv', '.git', '__pycache__', '.idea', 'node_modules'}
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for f in filenames:
            if f.endswith('.py'):
                result.append(os.path.join(dirpath, f))
    return result

def parse_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        try:
            with open(filepath, 'r', encoding='gbk') as f:
                content = f.read()
        except Exception as e:
            return 0, 0, 0, str(e)
    except Exception as e:
        return 0, 0, 0, str(e)
    
    lines = content.count('\n')
    if not content.endswith('\n'):
        lines += 1
    
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return lines, 0, 0, f"SyntaxError: {e}"
    
    classes = sum(1 for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
    functions = sum(1 for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return lines, classes, functions, None

def classify(relpath):
    """将相对路径归类到分组"""
    if relpath.startswith('agent/'):
        return 'agent/（含子模块）'
    elif relpath.startswith('tools/'):
        return 'tools/（含 builtin/ 子目录）'
    elif relpath.startswith('harness/'):
        return 'harness/'
    elif relpath.startswith('memory/'):
        return 'memory/'
    elif relpath.startswith('skills/'):
        return 'skills/（含 builtin/ 子目录）'
    elif '/' not in relpath:
        return '根目录 .py 文件'
    else:
        return '其他目录'

all_files = get_all_py_files(ROOT)

groups = {}
for fp in all_files:
    rel = os.path.relpath(fp, ROOT).replace('\\', '/')
    grp = classify(rel)
    if grp not in groups:
        groups[grp] = []
    groups[grp].append((rel, fp))

# 打印结果
print("=" * 80)
print("📊 项目代码统计报告 - agent-loop-lab")
print("=" * 80)

grand_lines = 0
grand_classes = 0
grand_funcs = 0
grand_files = 0
all_stats = []  # (rel, lines)

for grp_name in sorted(groups.keys()):
    file_list = groups[grp_name]
    file_list.sort(key=lambda x: x[0])
    g_lines = 0
    g_classes = 0
    g_funcs = 0
    
    print(f"\n{'─' * 60}")
    print(f"📁 模块: {grp_name} ({len(file_list)} 个文件)")
    print(f"{'─' * 60}")
    
    for rel, fp in file_list:
        lines, classes, funcs, err = parse_file(fp)
        if err:
            print(f"  ❌ {rel:50s} 错误: {err}")
        else:
            print(f"  📄 {rel:50s} 行数:{lines:>5}  类:{classes:>2}  函数:{funcs:>3}")
        g_lines += lines
        g_classes += classes
        g_funcs += funcs
        all_stats.append((rel, lines))
    
    print(f"  {'─' * 60}")
    print(f"  📌 小计: 文件={len(file_list)}, 行数={g_lines}, 类={g_classes}, 函数={g_funcs}")
    
    grand_lines += g_lines
    grand_classes += g_classes
    grand_funcs += g_funcs
    grand_files += len(file_list)

print(f"\n{'=' * 60}")
print(f"🏁 总计: 文件={grand_files}, 总行数={grand_lines}, 总类数={grand_classes}, 总函数数={grand_funcs}")
print(f"{'=' * 60}")

# 前10大文件
print(f"\n{'=' * 60}")
print(f"🏆 按行数排序的前 10 个最大文件")
print(f"{'=' * 60}")
all_stats.sort(key=lambda x: x[1], reverse=True)
for i, (rel, lines) in enumerate(all_stats[:10], 1):
    print(f"  {i:>2}. {rel:55s} {lines:>5} 行")

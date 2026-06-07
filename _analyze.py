import os, sys

root = r'C:\Users\DYK\Desktop\agent\agent-loop-lab'

all_files = []
for dirpath, dirnames, filenames in os.walk(root):
    rel = os.path.relpath(dirpath, root)
    parts = rel.split(os.sep)
    if any(p.startswith('test') or p == 'tests' or p == 'tests_plan' for p in parts):
        continue
    for f in filenames:
        if f.endswith('.py') and not f.startswith('test'):
            full = os.path.join(dirpath, f)
            all_files.append(full)

print(f'共 {len(all_files)} 个待分析文件\n')

def get_module(filepath):
    rel = os.path.relpath(filepath, root)
    parts = rel.split(os.sep)
    if len(parts) == 1:
        return '根目录'
    return parts[0]

groups = {}
for f in all_files:
    mod = get_module(f)
    groups.setdefault(mod, []).append(f)

file_stats = []
for f in all_files:
    with open(f, 'r', encoding='utf-8', errors='ignore') as fh:
        lines = fh.readlines()
    total_lines = len(lines)
    class_count = sum(1 for l in lines if l.strip().startswith('class '))
    def_count = sum(1 for l in lines if l.strip().startswith('def '))
    rel = os.path.relpath(f, root)
    file_stats.append((rel, total_lines, class_count, def_count))

mod_summary = {}
for mod, flist in groups.items():
    total_files = len(flist)
    total_lines = 0
    total_classes = 0
    total_funcs = 0
    for f in flist:
        rel = os.path.relpath(f, root)
        for rel2, tl, cc, dc in file_stats:
            if rel2 == rel:
                total_lines += tl
                total_classes += cc
                total_funcs += dc
                break
    mod_summary[mod] = (total_files, total_lines, total_classes, total_funcs)

mod_order = ['agent', 'tools', 'harness', 'memory', 'skills', 'mobile', '根目录']
mod_summary_sorted = [(m, mod_summary[m]) for m in mod_order if m in mod_summary]

print('=' * 80)
print(f'{"模块统计总表":^80}')
print('=' * 80)
print(f'{"模块":<12} {"文件数":>6} {"总行数":>10} {"总类数":>8} {"总函数数":>10}')
print('-' * 50)
for mod, (fc, tl, cc, dc) in mod_summary_sorted:
    print(f'{mod:<12} {fc:>6} {tl:>10} {cc:>8} {dc:>10}')
print('-' * 50)
total_f = sum(v[0] for v in mod_summary.values())
total_l = sum(v[1] for v in mod_summary.values())
total_c = sum(v[2] for v in mod_summary.values())
total_d = sum(v[3] for v in mod_summary.values())
print(f'{"总计":<12} {total_f:>6} {total_l:>10} {total_c:>8} {total_d:>10}')

print()
print('=' * 80)
print(f'{"Top 10 最大文件":^80}')
print('=' * 80)
print(f'{"文件路径":<60} {"行数":>6} {"类":>4} {"函数":>6}')
print('-' * 80)
file_stats_sorted = sorted(file_stats, key=lambda x: x[1], reverse=True)
for rel, tl, cc, dc in file_stats_sorted[:10]:
    print(f'{rel:<60} {tl:>6} {cc:>4} {dc:>6}')

print()
print('=' * 80)
print(f'{"每个文件详细统计":^80}')
print('=' * 80)
print(f'{"文件路径":<65} {"行数":>6} {"类":>4} {"函数":>6}')
print('-' * 85)
file_stats_sorted2 = sorted(file_stats, key=lambda x: x[1], reverse=True)
for rel, tl, cc, dc in file_stats_sorted2:
    print(f'{rel:<65} {tl:>6} {cc:>4} {dc:>6}')

#!/usr/bin/env python3
# rebuild_index.py — 重建 _index/meta.jsonl 和 _index/by_branch.jsonl
#
# 设计:
#   · 扫所有 memory/**/*.md(排除 _index/ INDEX.md MEMORY.md backup-*)
#   · 提取 frontmatter(支持顶层 type 和 metadata.type 两种格式)
#   · 保留 last_access / decay / status(从旧 meta.jsonl 读),不重置
#   · 文件不在旧索引 → last_access=mtime,decay=0,status=active
#   · 文件在旧索引但本次扫描丢失 → 不保留(memory 被删/移)
#
# 用法:
#   python3 ~/.claude/bin/rebuild_index.py [<mem_root>]
#   省略 mem_root 时默认 ~/.claude/projects/<cwd-slug>/memory/
#
# harness:
#   · tmpfile + rename 原子写
#   · 重跑幂等(LRU 数据保留 → 第二次跑结果跟第一次一致)

import os
import re
import sys
import json
import tempfile
from datetime import datetime, timezone
from collections import OrderedDict


def parse_frontmatter(path):
    """提取 frontmatter 的 name / description / type。

    支持两种格式:
      ① 顶层:`type: xxx`
      ② 嵌套:`metadata:\n  type: xxx`
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read(8192)
    except Exception as e:
        return {'name': '', 'description': '', 'type': '', '_error': str(e)}

    m = re.match(r'^---\n(.+?)\n---', content, re.DOTALL)
    if not m:
        return {'name': '', 'description': '', 'type': ''}

    fm_block = m.group(1)
    out = {'name': '', 'description': '', 'type': ''}

    for key in ('name', 'description'):
        km = re.search(rf'^{key}:\s*(.*)$', fm_block, re.MULTILINE)
        if km:
            v = km.group(1).strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            elif v.startswith("'") and v.endswith("'"):
                v = v[1:-1]
            out[key] = v

    nested = re.search(r'^metadata:\s*\n((?:\s+\w+:.*\n?)+)', fm_block, re.MULTILINE)
    if nested:
        type_match = re.search(r'^\s+type:\s*(\S+)', nested.group(1), re.MULTILINE)
        if type_match:
            out['type'] = type_match.group(1).strip()
    if not out['type']:
        type_match = re.search(r'^type:\s*(\S+)', fm_block, re.MULTILINE)
        if type_match:
            out['type'] = type_match.group(1).strip()

    return out


def infer_type_from_path(rel_path):
    """frontmatter 缺 type 时,从路径推断兜底。"""
    if rel_path.startswith('feedback/'):  return 'feedback'
    if rel_path.startswith('reference/'): return 'reference'
    if rel_path.startswith('user/'):      return 'user'
    if rel_path.startswith('global/'):    return 'global'
    if '/branches/' in rel_path:          return 'branch'
    if rel_path.startswith('projects/'):  return 'project'
    return ''


def infer_project_branch(rel_path):
    """从路径推断 project 和 branch 字段。"""
    parts = rel_path.split('/')
    project, branch = '', ''
    if parts[0] == 'projects' and len(parts) >= 2:
        project = parts[1]
        if 'branches' in parts:
            idx = parts.index('branches')
            if idx + 1 < len(parts):
                branch_slug = parts[idx+1].replace('.md', '')
                # feat_0602_example_feature → feat/<date>/example-feature
                m = re.match(r'^(feat|bugfix|hotfix|fix)_(\d{4})_(.+)$', branch_slug)
                if m:
                    branch = f"{m.group(1)}/{m.group(2)}/{m.group(3).replace('_','-')}"
                else:
                    branch = branch_slug.replace('_', '/')
    return project, branch


def mtime_iso(p):
    return datetime.fromtimestamp(os.path.getmtime(p), tz=timezone.utc).isoformat().replace('+00:00', 'Z')


def load_old_index(idx_path):
    """读旧 meta.jsonl,返回 {path: record} dict,用于保留 last_access/decay/status。"""
    old = {}
    if not os.path.exists(idx_path):
        return old
    with open(idx_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                r = json.loads(line)
                old[r['path']] = r
            except json.JSONDecodeError:
                continue
    return old


def atomic_write(path, lines):
    """tmpfile + rename 原子写,符合 harness 原则。"""
    dir_ = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=dir_, prefix='.rebuild_', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            for line in lines:
                f.write(line + '\n')
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def main():
    if len(sys.argv) > 1:
        mem_root = sys.argv[1]
    else:
        cwd_slug = os.getcwd().replace('/', '-')
        mem_root = os.path.expanduser(f'~/.claude/projects/{cwd_slug}/memory')

    if not os.path.isdir(mem_root):
        print(f'❌ memory 根目录不存在: {mem_root}', file=sys.stderr)
        sys.exit(1)

    idx_dir = os.path.join(mem_root, '_index')
    os.makedirs(idx_dir, exist_ok=True)
    meta_path = os.path.join(idx_dir, 'meta.jsonl')
    branch_path = os.path.join(idx_dir, 'by_branch.jsonl')

    old_meta = load_old_index(meta_path)
    print(f'  · 读旧 meta.jsonl: {len(old_meta)} 条')

    records = []
    branch_records = []
    stats = {'scanned': 0, 'reused_last_access': 0, 'new_last_access': 0, 'fm_warnings': []}

    for root, dirs, files in os.walk(mem_root):
        dirs[:] = [d for d in dirs if not d.startswith('_') and not d.startswith('backup-') and not d.startswith('.')]
        for fname in files:
            if not fname.endswith('.md'): continue
            if fname in ('INDEX.md', 'MEMORY.md'): continue

            full = os.path.join(root, fname)
            rel = os.path.relpath(full, mem_root)
            stats['scanned'] += 1

            fm = parse_frontmatter(full)
            if not fm.get('name') or not fm.get('description'):
                stats['fm_warnings'].append(rel)

            ftype = fm.get('type') or infer_type_from_path(rel)
            project, branch = infer_project_branch(rel)

            # 保留 LRU 字段
            old = old_meta.get(rel, {})
            last_access = old.get('last_access') or mtime_iso(full)
            decay = old.get('decay', 0)
            status = old.get('status', 'active')
            if old:
                stats['reused_last_access'] += 1
            else:
                stats['new_last_access'] += 1

            record = OrderedDict([
                ('path', rel),
                ('type', ftype),
                ('project', project),
                ('branch', branch),
                ('name', fm.get('name', '')),
                ('description', fm.get('description', '')),
                ('status', status),
                ('last_access', last_access),
                ('decay', decay),
                ('size', os.path.getsize(full)),
            ])
            records.append(record)

            if branch:
                branch_records.append(OrderedDict([
                    ('project', project),
                    ('branch', branch),
                    ('memory', rel),
                ]))

    # 排序保证 idempotent
    records.sort(key=lambda x: x['path'])
    branch_records.sort(key=lambda x: (x['project'], x['branch']))

    atomic_write(meta_path, [json.dumps(r, ensure_ascii=False) for r in records])
    atomic_write(branch_path, [json.dumps(r, ensure_ascii=False) for r in branch_records])

    print(f'  · 扫描 .md: {stats["scanned"]} 条')
    print(f'  · 保留 last_access(LRU 不重置): {stats["reused_last_access"]} 条')
    print(f'  · 新 last_access(用 mtime 兜底): {stats["new_last_access"]} 条')
    print(f'  · 写 meta.jsonl: {len(records)} 行')
    print(f'  · 写 by_branch.jsonl: {len(branch_records)} 行')

    if stats['fm_warnings']:
        print(f'  ⚠️ {len(stats["fm_warnings"])} 条 frontmatter 不全(name/description 缺):')
        for w in stats['fm_warnings'][:5]:
            print(f'      {w}')
        if len(stats['fm_warnings']) > 5:
            print(f'      ... 还有 {len(stats["fm_warnings"])-5} 条')

    print(f'✅ rebuild 完成: {meta_path}')


if __name__ == '__main__':
    main()

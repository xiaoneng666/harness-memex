#!/usr/bin/env python3
# update_index_md.py — 从 meta.jsonl 自动重写 INDEX.md 的 AUTO 标记区块
#
# 设计:
#   · 只重写 INDEX.md 里用 <!-- AUTO:START <name> --> ... <!-- AUTO:END <name> --> 包起来的区块
#   · 其它内容(目录树、LRU 表、自定义说明)完全保留
#   · 标记缺失/损坏 → 直接 abort 不写,LLM 排查(harness 不破坏旧)
#
# 默认重写 3 个区块:
#   · project-table  — projects/* 的项目速查表
#   · feedback-list  — feedback/*.md 的速查链接(用 · 分隔)
#   · reference-list — reference/*.md 的速查链接
#
# 用法:
#   python3 ~/.claude/bin/update_index_md.py [<mem_root>]
#
# harness:
#   · tempfile + rename 原子写
#   · 幂等(同输入同输出)
#   · 缺标记区块 → 直接 raise SystemExit(1) 不写半个

import os
import re
import sys
import json
import tempfile
from collections import defaultdict, OrderedDict


def load_meta(mem_root):
    idx = os.path.join(mem_root, '_index', 'meta.jsonl')
    if not os.path.exists(idx):
        print(f'❌ {idx} 不存在 — 先跑 rebuild_index.py', file=sys.stderr)
        sys.exit(1)
    records = []
    with open(idx, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f'❌ meta.jsonl 损坏:{e}', file=sys.stderr)
                sys.exit(1)
    return records


def slug_from_path(rel_path):
    return os.path.splitext(os.path.basename(rel_path))[0]


def short_desc(record, max_chars=80):
    d = (record.get('description') or '').strip()
    if not d:
        return record.get('name') or slug_from_path(record['path'])
    if len(d) > max_chars:
        d = d[:max_chars].rstrip() + '...'
    return d


def render_project_table(records):
    """按 (project, sub-service, branches?) 分组。

    分组规则:
      · projects/<biz>/<file>.md            → 组 "<biz>"
      · projects/<biz>/<sub>/<file>.md       → 组 "<biz> / <sub>"
      · projects/<biz>/<sub>/branches/<x>.md → 组 "<biz> / <sub> / branches"
      · global/*.md                          → 组 "global"
    """
    groups = OrderedDict()
    for r in records:
        p = r['path']
        if p.startswith('global/'):
            key = 'global'
        elif p.startswith('projects/'):
            parts = p.split('/')
            biz = parts[1]
            if len(parts) == 3:
                key = biz
            elif len(parts) == 4:
                key = f'{biz} / {parts[2]}'
            elif len(parts) == 5 and parts[3] == 'branches':
                key = f'{biz} / {parts[2]} / branches'
            else:
                key = biz
        else:
            continue
        groups.setdefault(key, []).append(r)

    lines = ['| 项目 | 关键文档 |', '|---|---|']
    for key, recs in groups.items():
        def sort_key(r):
            slug = slug_from_path(r['path'])
            priority = 0
            if slug in ('overview', 'iterations_index', 'README'):
                priority = -2
            elif slug in ('history',):
                priority = -1
            return (priority, slug)
        recs.sort(key=sort_key)

        items = []
        for r in recs:
            slug = slug_from_path(r['path'])
            if 'branches' in r['path']:
                display = r.get('branch') or slug.replace('_', '/')
                items.append(f'[`{display}`]({r["path"]})')
            else:
                desc = short_desc(r, 60) if r.get('description') else ''
                if desc and desc != slug:
                    items.append(f'[`{slug}`]({r["path"]}) — {desc}')
                else:
                    items.append(f'[`{slug}`]({r["path"]})')

        lines.append(f'| **{key}** | {" · ".join(items)} |')

    return '\n'.join(lines)


def render_feedback_list(records):
    feedbacks = sorted(
        [r for r in records if r['type'] == 'feedback'],
        key=lambda r: r['path']
    )
    items = [f'[`{slug_from_path(r["path"])}`]({r["path"]})' for r in feedbacks]
    return ' · '.join(items)


def render_reference_list(records):
    refs = sorted(
        [r for r in records if r['type'] == 'reference'],
        key=lambda r: r['path']
    )
    items = []
    for r in refs:
        slug = slug_from_path(r['path'])
        desc = short_desc(r, 50) if r.get('description') else ''
        if desc:
            items.append(f'[`{slug}`]({r["path"]}) — {desc}')
        else:
            items.append(f'[`{slug}`]({r["path"]})')
    return ' · '.join(items)


def replace_block(content, block_name, new_inner):
    pattern = re.compile(
        r'(<!-- AUTO:START ' + re.escape(block_name) + r' -->\n'
        r'(?:<!--[^>]*-->\n)?)'
        r'(.*?)'
        r'(\n<!-- AUTO:END ' + re.escape(block_name) + r' -->)',
        re.DOTALL
    )
    m = pattern.search(content)
    if not m:
        raise ValueError(f'缺 AUTO:START/END {block_name} 标记对')
    return content[:m.start()] + m.group(1) + new_inner + m.group(3) + content[m.end():]


def atomic_write(path, content):
    dir_ = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=dir_, prefix='.update_index_md_', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main():
    if len(sys.argv) > 1:
        mem_root = sys.argv[1]
    else:
        cwd_slug = os.getcwd().replace('/', '-')
        mem_root = os.path.expanduser(f'~/.claude/projects/{cwd_slug}/memory')

    index_path = os.path.join(mem_root, 'INDEX.md')
    if not os.path.exists(index_path):
        print(f'❌ {index_path} 不存在', file=sys.stderr)
        sys.exit(1)

    with open(index_path, 'r', encoding='utf-8') as f:
        content = f.read()

    records = load_meta(mem_root)
    print(f'  · 读 meta.jsonl: {len(records)} 条')

    new_blocks = {
        'project-table': '\n' + render_project_table(records) + '\n',
        'feedback-list': '\n' + render_feedback_list(records) + '\n',
        'reference-list': '\n' + render_reference_list(records) + '\n',
    }

    new_content = content
    for name, inner in new_blocks.items():
        try:
            new_content = replace_block(new_content, name, inner)
            print(f'  ✓ 重写 {name}')
        except ValueError as e:
            print(f'❌ {e} — abort,不写 INDEX.md', file=sys.stderr)
            sys.exit(1)

    if new_content == content:
        print('  · INDEX.md 内容无变化,不写')
        return

    atomic_write(index_path, new_content)
    print(f'✅ 重写完成: {index_path}')


if __name__ == '__main__':
    main()

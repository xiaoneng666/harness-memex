#!/usr/bin/env python3
# lru_compact.py — LRU 周扫工具(MEMORY_SPEC.md § 三)
#
# 设计:
#   30d 周期 × 3 次压缩 + 候选删除,共 4 阶段。
#   工具只标候选 + 列清单,**压缩内容由 LLM 写**(见 spec § 三.A)。
#   分支删除(本地+远程都查不到) → status=dormant 进 LRU(spec § 三.B)。
#
# 用法:
#   # 默认扫 cwd 对应 mem_root,列待压缩/候选删除清单
#   python3 ~/.claude/bin/lru_compact.py [<mem_root>]
#
#   # LLM 压缩完一条后,标 decay(单条增量更新 meta.jsonl)
#   python3 ~/.claude/bin/lru_compact.py --mark <rel_path> <new_decay> [<mem_root>]
#
#   # 锁定某条永不淘汰(status=pinned)/ 解锁(回 active)
#   python3 ~/.claude/bin/lru_compact.py --pin <rel_path> [<mem_root>]
#   python3 ~/.claude/bin/lru_compact.py --unpin <rel_path> [<mem_root>]
#
#   # 检测分支删除(对 type=branch 的 memory 跑 git;查不到 → status=dormant)
#   python3 ~/.claude/bin/lru_compact.py --detect-deleted-branches <repo_path> [<mem_root>]
#
# 自定义周期:export MEMEX_LRU_PERIOD_DAYS=30
#
# harness:
#   · 不动文件内容(LLM 干压缩);只动 meta.jsonl 的 decay/status 字段
#   · tmpfile + rename 原子写
#   · 幂等

import os
import re
import sys
import json
import tempfile
import subprocess
from datetime import datetime, timezone, timedelta

PERIOD_DAYS = int(os.environ.get('MEMEX_LRU_PERIOD_DAYS', '30'))


def now_utc():
    return datetime.now(timezone.utc)


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except Exception:
        return None


def load_meta(idx_path):
    records = []
    if not os.path.exists(idx_path):
        return records
    with open(idx_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def atomic_write_jsonl(path, records):
    dir_ = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=dir_, prefix='.lru_', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp): os.unlink(tmp)
        raise


def days_since(last_access_str):
    la = parse_iso(last_access_str)
    if not la:
        return 99999
    return (now_utc() - la).total_seconds() / 86400


def categorize(rec):
    """按 (status, last_access, decay) 返回 stage。

    stage:
      'active'                — 30d 内有 access,不动
      'pinned'                — status=pinned,用户显式锁,永不淘汰
      'pending_compact_1'     — decay=0, 30d+ 未 access → 待第 1 次压缩
      'pending_compact_2'     — decay=1, 30d+ 未 access → 待第 2 次压缩
      'pending_compact_3'     — decay=2, 30d+ 未 access → 待第 3 次压缩
      'pending_delete'        — decay=3, 30d+ 未 access → 标 candidate_to_delete
      'awaiting_user_authorize_delete' — status=candidate_to_delete → 等用户授权
    """
    status = rec.get('status', 'active')
    if status == 'candidate_to_delete':
        return 'awaiting_user_authorize_delete'
    if status == 'pinned':
        return 'pinned'

    days = days_since(rec.get('last_access'))
    if days < PERIOD_DAYS:
        return 'active'

    decay = rec.get('decay', 0)
    if decay == 0: return 'pending_compact_1'
    if decay == 1: return 'pending_compact_2'
    if decay == 2: return 'pending_compact_3'
    if decay >= 3: return 'pending_delete'
    return 'active'


def fmt_size(b):
    if b < 1024: return f'{b}B'
    if b < 1024*1024: return f'{b/1024:.1f}KB'
    return f'{b/1024/1024:.1f}MB'


def cmd_scan(mem_root, quiet=False):
    idx = os.path.join(mem_root, '_index', 'meta.jsonl')
    if not os.path.exists(idx):
        if quiet:
            return  # hook 静默
        print(f'❌ meta.jsonl 不存在: {idx} — 先跑 rebuild_index.py', file=sys.stderr)
        sys.exit(1)

    records = load_meta(idx)
    buckets = {
        'pending_compact_1': [],
        'pending_compact_2': [],
        'pending_compact_3': [],
        'pending_delete': [],
        'awaiting_user_authorize_delete': [],
    }
    for r in records:
        stage = categorize(r)
        if stage in buckets:
            buckets[stage].append(r)

    # --quiet 模式:hook 用,只输出 key:N 行
    if quiet:
        print(f"compact_1:{len(buckets['pending_compact_1'])}")
        print(f"compact_2:{len(buckets['pending_compact_2'])}")
        print(f"compact_3:{len(buckets['pending_compact_3'])}")
        print(f"pending_delete:{len(buckets['pending_delete'])}")
        print(f"awaiting_delete:{len(buckets['awaiting_user_authorize_delete'])}")
        return

    print(f'# LRU 周扫报告 — {mem_root}')
    print(f'# 周期 {PERIOD_DAYS}d × 3 次压缩 + 候选删除,见 ~/.claude/MEMORY_SPEC.md § 三')
    print(f'# 扫描时间: {now_utc().isoformat()}')
    print(f'# 总 memory 条目: {len(records)}')
    print()

    targets = {
        'pending_compact_1': (f'待第 1 次压缩 (decay 0→1, {PERIOD_DAYS}d 未 access)', '≤ 2KB · 保留 Why/决策/状态/链接'),
        'pending_compact_2': (f'待第 2 次压缩 (decay 1→2, {PERIOD_DAYS*2}d 未 access)', '≤ 800B · 1-2 段核心 + 链接'),
        'pending_compact_3': (f'待第 3 次压缩 (decay 2→3, {PERIOD_DAYS*3}d 未 access)', '≤ 300B · 1-3 句精华 + 链接'),
        'pending_delete': (f'待标 candidate_to_delete (decay=3, {PERIOD_DAYS*4}d 未 access)', '通知用户授权删除'),
        'awaiting_user_authorize_delete': ('等用户授权删除 (status=candidate_to_delete)', '用户输入"删"指令才 rm'),
    }
    total_pending = 0
    for stage, (label, action) in targets.items():
        items = buckets[stage]
        if not items: continue
        total_pending += len(items)
        print(f'## {label} — {len(items)} 条')
        print(f'   动作: {action}')
        for r in items:
            days = int(days_since(r.get('last_access')))
            print(f'   · {r["path"]}  ({fmt_size(r.get("size", 0))}, {days}d 未 access)')
            if r.get('description'):
                d = r['description']
                if len(d) > 70: d = d[:70] + '...'
                print(f'       {d}')
        print()

    if total_pending == 0:
        print('✅ 无待压缩 / 候选删除 — 全部 active 或 pinned')
        return

    print('---')
    print('压缩流程(LLM 决策):见 ~/.claude/MEMORY_SPEC.md § 三.A')
    print('压缩完一条后跑(省 mem_root 默认当前 cwd):')
    print('  python3 ~/.claude/bin/lru_compact.py --mark <rel_path> <new_decay>')
    print('锁某条永不淘汰(开发中分支等):')
    print('  python3 ~/.claude/bin/lru_compact.py --pin <rel_path>')
    print('真删一条(必须 status=candidate_to_delete + last_access ≥ 60d):')
    print('  python3 ~/.claude/bin/lru_compact.py --rm <rel_path>')


def cmd_rm(rel_path, mem_root, force=False):
    """显式删除一条 memory(带安全闸门 + 软删 _trash/)。

    安全闸门:
      1. status 必须是 candidate_to_delete(除非 --force)
      2. last_access 必须 ≥ 60 天前(防误删活跃)
      3. 删之前 dump 前 10 行 + metadata 让用户确认
      4. 软删:mv 到 _trash/<UTC>_<basename>(30d 后真清,P1 待做)
      5. 从 meta.jsonl + by_branch.jsonl 移除
    """
    import shutil
    idx = os.path.join(mem_root, '_index', 'meta.jsonl')
    by_branch = os.path.join(mem_root, '_index', 'by_branch.jsonl')
    records = load_meta(idx)

    target = None
    for r in records:
        if r.get('path') == rel_path:
            target = r
            break
    if not target:
        print(f'❌ {rel_path} 不在 meta.jsonl 里', file=sys.stderr)
        sys.exit(1)

    # 闸门 1: status
    if target.get('status') != 'candidate_to_delete' and not force:
        print(f'❌ {rel_path} status={target.get("status")},不是 candidate_to_delete', file=sys.stderr)
        print('   只有状态为 candidate_to_delete 的才能 rm。先跑 LRU 流程让它进入候选,', file=sys.stderr)
        print('   或加 --force 强制(危险)。', file=sys.stderr)
        sys.exit(2)

    # 闸门 2: last_access ≥ 60d
    days = days_since(target.get('last_access'))
    if days < 60 and not force:
        print(f'❌ {rel_path} 仅 {int(days)}d 未 access(< 60d),refuse 删除(防误删活跃)', file=sys.stderr)
        print('   加 --force 强制(危险)。', file=sys.stderr)
        sys.exit(2)

    full = os.path.join(mem_root, rel_path)
    if not os.path.exists(full):
        print(f'⚠️ 源文件 {full} 已不存在,直接清索引', file=sys.stderr)
    else:
        # 闸门 3: dump 前 10 行
        print(f'# 即将删除: {rel_path}')
        print(f'#   status: {target.get("status")}, last_access: {target.get("last_access")}, size: {target.get("size")}B, decay: {target.get("decay")}')
        print(f'#   description: {target.get("description", "")}')
        print('# 内容前 10 行:')
        try:
            with open(full, 'r', encoding='utf-8') as f:
                for i, line in enumerate(f):
                    if i >= 10: break
                    print(f'#   {line.rstrip()}')
        except Exception as e:
            print(f'#   (无法读取: {e})')

        # 闸门 4: 软删到 _trash/
        trash = os.path.join(mem_root, '_trash')
        os.makedirs(trash, exist_ok=True)
        timestamp = now_utc().strftime('%Y%m%dT%H%M%SZ')
        basename = os.path.basename(rel_path)
        trash_path = os.path.join(trash, f'{timestamp}_{basename}')
        shutil.move(full, trash_path)
        print(f'✓ 软删 → {trash_path}(30d 后真清)')

    # 闸门 5: 移除索引
    records = [r for r in records if r.get('path') != rel_path]
    atomic_write_jsonl(idx, records)

    # by_branch.jsonl 同步
    if os.path.exists(by_branch):
        with open(by_branch, 'r', encoding='utf-8') as f:
            br = [json.loads(l) for l in f if l.strip()]
        br = [r for r in br if r.get('memory') != rel_path]
        atomic_write_jsonl(by_branch, br)

    print(f'✓ 从索引移除: {rel_path}')


def cmd_mark(rel_path, new_decay, mem_root):
    idx = os.path.join(mem_root, '_index', 'meta.jsonl')
    records = load_meta(idx)
    found = False
    new_decay = int(new_decay)
    for r in records:
        if r.get('path') == rel_path:
            r['decay'] = new_decay
            r['status'] = 'dormant' if new_decay > 0 else 'active'
            full = os.path.join(mem_root, rel_path)
            if os.path.exists(full):
                r['size'] = os.path.getsize(full)
            found = True
            break

    if not found:
        print(f'❌ {rel_path} 不在 meta.jsonl 里', file=sys.stderr)
        sys.exit(1)

    atomic_write_jsonl(idx, records)
    print(f'✓ 标记 {rel_path}: decay={new_decay}, status={r["status"]}, size={r.get("size")}')


def cmd_pin(rel_path, mem_root, unpin=False):
    idx = os.path.join(mem_root, '_index', 'meta.jsonl')
    records = load_meta(idx)
    target = 'active' if unpin else 'pinned'
    found = False
    for r in records:
        if r.get('path') == rel_path:
            r['status'] = target
            found = True
            break
    if not found:
        print(f'❌ {rel_path} 不在 meta.jsonl 里', file=sys.stderr)
        sys.exit(1)
    atomic_write_jsonl(idx, records)
    print(f'✓ {rel_path}: status={target}')


def cmd_detect_deleted_branches(repo_path, mem_root):
    if not os.path.isdir(os.path.join(repo_path, '.git')):
        print(f'❌ {repo_path} 不是 git 仓库根', file=sys.stderr)
        sys.exit(1)

    idx = os.path.join(mem_root, '_index', 'meta.jsonl')
    records = load_meta(idx)

    try:
        local = subprocess.check_output(
            ['git', '-C', repo_path, 'for-each-ref', '--format=%(refname:short)', 'refs/heads/'],
            stderr=subprocess.DEVNULL, text=True
        ).strip().split('\n')
        remote = subprocess.check_output(
            ['git', '-C', repo_path, 'for-each-ref', '--format=%(refname:short)', 'refs/remotes/'],
            stderr=subprocess.DEVNULL, text=True
        ).strip().split('\n')
    except subprocess.CalledProcessError as e:
        print(f'❌ git 调用失败: {e}', file=sys.stderr)
        sys.exit(1)

    remote_clean = {b.split('/', 1)[1] if '/' in b else b for b in remote if b}
    local_set = set(local)
    alive = local_set | remote_clean

    changed = 0
    deleted_list = []
    for r in records:
        if r.get('type') != 'branch': continue
        branch = r.get('branch', '')
        if not branch: continue
        if branch in alive: continue
        if r.get('status') != 'dormant':
            r['status'] = 'dormant'
            changed += 1
            deleted_list.append((branch, r['path']))

    if changed:
        atomic_write_jsonl(idx, records)
        print(f'✓ {changed} 条 branch memory 标 dormant (分支已删):')
        for b, p in deleted_list:
            print(f'   · {b}  → {p}')
        print()
        print('这些 memory 现在进 LRU 流程:下次扫 30d+ 未 access 触发压缩。')
    else:
        print('✓ 所有 branch memory 对应分支仍存活,无需 demote')


def main():
    args = sys.argv[1:]
    cwd_slug = os.getcwd().replace('/', '-')
    default_mem_root = os.path.expanduser(f'~/.claude/projects/{cwd_slug}/memory')

    if args and args[0] == '--mark':
        if len(args) < 3:
            print('用法: --mark <rel_path> <new_decay> [<mem_root>]', file=sys.stderr)
            sys.exit(1)
        cmd_mark(args[1], args[2], args[3] if len(args) > 3 else default_mem_root)
        return

    if args and args[0] in ('--pin', '--unpin'):
        if len(args) < 2:
            print('用法: --pin <rel_path> [<mem_root>] / --unpin <rel_path> [<mem_root>]', file=sys.stderr)
            sys.exit(1)
        cmd_pin(args[1], args[2] if len(args) > 2 else default_mem_root, unpin=(args[0] == '--unpin'))
        return

    if args and args[0] == '--quiet':
        mem_root = args[1] if len(args) > 1 else default_mem_root
        cmd_scan(mem_root, quiet=True)
        return

    if args and args[0] == '--rm':
        if len(args) < 2:
            print('用法: --rm <rel_path> [<mem_root>] [--force]', file=sys.stderr)
            sys.exit(1)
        rel = args[1]
        force = '--force' in args[2:]
        rest = [a for a in args[2:] if a != '--force']
        mem_root = rest[0] if rest else default_mem_root
        cmd_rm(rel, mem_root, force=force)
        return

    if args and args[0] == '--detect-deleted-branches':
        if len(args) < 2:
            print('用法: --detect-deleted-branches <repo_path> [<mem_root>]', file=sys.stderr)
            sys.exit(1)
        cmd_detect_deleted_branches(args[1], args[2] if len(args) > 2 else default_mem_root)
        return

    mem_root = args[0] if args else default_mem_root
    if not os.path.isdir(mem_root):
        print(f'❌ mem_root 不存在: {mem_root}', file=sys.stderr)
        sys.exit(1)
    cmd_scan(mem_root)


if __name__ == '__main__':
    main()

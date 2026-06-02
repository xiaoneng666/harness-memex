#!/usr/bin/env python3
"""merge_settings.py — 把 Memex hook 注册合并进现有 settings.json

设计:
  · 读现有 settings.json + memex-hooks.json
  · 按 command 字符串去重:已存在的不重复加
  · 保留现有所有非 memex 配置
  · 用 tmpfile + os.replace 原子写

用法:
  python3 merge_settings.py <target_settings.json> <memex-hooks.json>
"""

import json
import os
import sys
import tempfile


def main():
    if len(sys.argv) != 3:
        print('用法: python3 merge_settings.py <target> <snippet>', file=sys.stderr)
        sys.exit(1)

    target_path = sys.argv[1]
    snippet_path = sys.argv[2]

    with open(target_path, 'r', encoding='utf-8') as f:
        target = json.load(f)
    with open(snippet_path, 'r', encoding='utf-8') as f:
        snippet = json.load(f)

    target.setdefault('hooks', {})
    snippet_hooks = snippet.get('hooks', {})

    total_added = 0
    for event, configs in snippet_hooks.items():
        target['hooks'].setdefault(event, [])
        for cfg in configs:
            if not cfg.get('hooks'):
                continue
            cmd = cfg['hooks'][0].get('command', '')
            # 已存在(按 command 字符串)→ 跳过
            exists = False
            for existing in target['hooks'][event]:
                if not existing.get('hooks'):
                    continue
                ec = existing['hooks'][0].get('command', '')
                if ec == cmd:
                    exists = True
                    break
            if not exists:
                target['hooks'][event].append(cfg)
                total_added += 1
                print(f'  + {event}: {cmd[:60]}...' if len(cmd) > 60 else f'  + {event}: {cmd}')

    # 原子写
    dir_ = os.path.dirname(target_path) or '.'
    fd, tmp = tempfile.mkstemp(dir=dir_, prefix='.settings_', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(target, f, indent=2, ensure_ascii=False)
            f.write('\n')
        os.replace(tmp, target_path)
        print(f'  ✓ 新加 {total_added} 个 hook 注册')
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


if __name__ == '__main__':
    main()

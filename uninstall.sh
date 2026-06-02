#!/bin/bash
# harness-memex uninstall — 卸载 hooks + 工具,保留 memory 数据
#
# 做的事:
#   1. 从 ~/.claude/settings.json 移除 memex hook 注册(原文件备份)
#   2. 删 ~/.claude/hooks/{5 件套}.sh 和 ~/.claude/bin/{3 工具}.py
#   3. 保留 ~/.claude/MEMORY_SPEC.md 和 INDEX_TEMPLATE.md(参考价值)
#   4. **保留所有 ~/.claude/projects/*/memory/**(你的工作面不丢)

set -e

DOTCLAUDE="$HOME/.claude"
HOOKS_DIR="$DOTCLAUDE/hooks"
BIN_DIR="$DOTCLAUDE/bin"
SETTINGS="$DOTCLAUDE/settings.json"

C_OK="\033[32m✓\033[0m"
C_WARN="\033[33m⚠\033[0m"

MEMEX_HOOKS="session-bootstrap.sh pre-read-memory-bump.sh check-protected-branch.sh pre-edit-branch-notice.sh post-write-memory-sync.sh"
MEMEX_BINS="rebuild_index.py update_index_md.py lru_compact.py"

echo "╭─────────────────────────────────────────╮"
echo "│  harness-memex uninstall                "
echo "├─────────────────────────────────────────┤"
echo "│  会删:                                   "
echo "│    · 5 个 hook 脚本                       "
echo "│    · 3 个 python 工具                     "
echo "│    · settings.json 里的 hook 注册         "
echo "│  会保留:                                  "
echo "│    · MEMORY_SPEC.md / INDEX_TEMPLATE.md  "
echo "│    · 所有 memory 数据(projects/*/memory)"
echo "╰─────────────────────────────────────────╯"
echo
read -p "确认卸载? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "取消"
  exit 0
fi

echo
echo "[1/3] 删 hook 脚本"
for f in $MEMEX_HOOKS; do
  tgt="$HOOKS_DIR/$f"
  if [ -e "$tgt" ]; then
    rm "$tgt"
    printf "  $C_OK 删 %s\n" "$f"
  fi
done

echo
echo "[2/3] 删 python 工具"
for f in $MEMEX_BINS; do
  tgt="$BIN_DIR/$f"
  if [ -e "$tgt" ]; then
    rm "$tgt"
    printf "  $C_OK 删 %s\n" "$f"
  fi
done

echo
echo "[3/3] 清 settings.json"
if [ -f "$SETTINGS" ]; then
  backup="${SETTINGS}.memex-uninstall-backup-$(date +%Y%m%d-%H%M%S)"
  cp "$SETTINGS" "$backup"
  python3 - "$SETTINGS" <<'PYEOF'
import json, sys
target = sys.argv[1]
with open(target) as f:
    cfg = json.load(f)
removed = 0
for event in list(cfg.get('hooks', {}).keys()):
    new_list = []
    for entry in cfg['hooks'][event]:
        keep = True
        for h in entry.get('hooks', []):
            cmd = h.get('command', '')
            if 'session-bootstrap.sh' in cmd or 'pre-read-memory-bump.sh' in cmd \
               or 'check-protected-branch.sh' in cmd or 'pre-edit-branch-notice.sh' in cmd \
               or 'post-write-memory-sync.sh' in cmd:
                keep = False
                removed += 1
                break
        if keep:
            new_list.append(entry)
    cfg['hooks'][event] = new_list
with open(target, 'w') as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
    f.write('\n')
print(f"  ✓ 移除 {removed} 个 memex hook 注册")
PYEOF
  printf "  $C_OK 备份: %s\n" "$backup"
fi

echo
echo "🗑️  卸载完成"
echo
echo "你的 memory 数据保留在: $DOTCLAUDE/projects/*/memory/"
echo "想恢复? 重跑 ./install.sh 即可。"

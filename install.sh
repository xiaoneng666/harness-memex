#!/bin/bash
# Memex install — 傻瓜式安装
#
# 做的事:
#   1. 依赖检查(jq / python3 / git)
#   2. 复制 hooks → ~/.claude/hooks/(不覆盖已有,只问)
#   3. 复制 bin   → ~/.claude/bin/(同上)
#   4. 复制 MEMORY_SPEC + INDEX_TEMPLATE → ~/.claude/(不覆盖)
#   5. 合并 hook 注册进 ~/.claude/settings.json(自动备份)
#   6. chmod +x 所有脚本
#
# 安全设计:
#   - 不静默覆盖任何现有文件
#   - settings.json 改前必备份
#   - 失败立即退,提示原因

set -e

SRC="$(cd "$(dirname "$0")" && pwd)"
DOTCLAUDE="$HOME/.claude"
HOOKS_DIR="$DOTCLAUDE/hooks"
BIN_DIR="$DOTCLAUDE/bin"
SETTINGS="$DOTCLAUDE/settings.json"

C_OK="\033[32m✓\033[0m"
C_WARN="\033[33m⚠\033[0m"
C_ERR="\033[31m✗\033[0m"

echo "╭─────────────────────────────────────────╮"
echo "│  Memex — Persistent memory for Claude   │"
echo "│  Installing to $DOTCLAUDE                "
echo "╰─────────────────────────────────────────╯"
echo

# ───── 1. 依赖检查 ─────
echo "[1/6] 检查依赖..."
need_cmd() {
  if command -v "$1" >/dev/null 2>&1; then
    printf "  $C_OK %s — %s\n" "$1" "$(command -v "$1")"
  else
    printf "  $C_ERR 缺少 %s\n" "$1"
    case "$1" in
      jq) echo "      装法: brew install jq  (macOS) / apt install jq (Linux)" ;;
      python3) echo "      装法: brew install python3 / apt install python3" ;;
      git) echo "      装法: brew install git / apt install git" ;;
    esac
    exit 1
  fi
}
need_cmd jq
need_cmd python3
need_cmd git

# ───── 2. ~/.claude/ 存在性 ─────
if [ ! -d "$DOTCLAUDE" ]; then
  printf "  $C_WARN ~/.claude 不存在,先建出来\n"
  mkdir -p "$DOTCLAUDE"
fi

# ───── 3. 复制 hooks ─────
echo
echo "[2/6] 安装 hooks → $HOOKS_DIR"
mkdir -p "$HOOKS_DIR"
copied=0; skipped=0
for f in "$SRC"/hooks/*.sh; do
  bn=$(basename "$f")
  tgt="$HOOKS_DIR/$bn"
  if [ -e "$tgt" ]; then
    if cmp -s "$f" "$tgt"; then
      printf "  $C_OK %s 已是最新,跳过\n" "$bn"
    else
      printf "  $C_WARN %s 已存在且内容不同,跳过(手动 diff: diff %s %s)\n" "$bn" "$f" "$tgt"
    fi
    skipped=$((skipped+1))
  else
    cp "$f" "$tgt"
    chmod +x "$tgt"
    printf "  $C_OK %s\n" "$bn"
    copied=$((copied+1))
  fi
done
echo "  小结: 安装 $copied · 跳过 $skipped"

# ───── 4. 复制 bin ─────
echo
echo "[3/6] 安装 bin → $BIN_DIR"
mkdir -p "$BIN_DIR"
copied=0; skipped=0
for f in "$SRC"/bin/*.py; do
  bn=$(basename "$f")
  tgt="$BIN_DIR/$bn"
  if [ -e "$tgt" ]; then
    if cmp -s "$f" "$tgt"; then
      printf "  $C_OK %s 已是最新\n" "$bn"
    else
      printf "  $C_WARN %s 已存在且内容不同,跳过\n" "$bn"
    fi
    skipped=$((skipped+1))
  else
    cp "$f" "$tgt"
    chmod +x "$tgt"
    printf "  $C_OK %s\n" "$bn"
    copied=$((copied+1))
  fi
done
echo "  小结: 安装 $copied · 跳过 $skipped"

# ───── 5. 复制 MEMORY_SPEC + INDEX templates (v0.2) ─────
echo
echo "[4/6] 安装 spec + templates → $DOTCLAUDE"
for f in MEMORY_SPEC.md MEMEX_GLOBAL_INDEX_TEMPLATE.md MEMEX_PROJECT_INDEX_TEMPLATE.md; do
  src="$SRC/templates/$f"
  tgt="$DOTCLAUDE/$f"
  if [ ! -f "$src" ]; then
    printf "  $C_WARN %s 在 templates/ 下不存在,跳过\n" "$f"
    continue
  fi
  if [ -e "$tgt" ]; then
    printf "  $C_WARN %s 已存在,保留(手动 diff: diff %s %s)\n" "$f" "$src" "$tgt"
  else
    cp "$src" "$tgt"
    printf "  $C_OK %s\n" "$f"
  fi
done

# ───── 6. 合并 settings.json ─────
echo
echo "[5/6] 合并 hook 配置 → $SETTINGS"
if [ ! -f "$SETTINGS" ]; then
  cp "$SRC/templates/settings.starter.json" "$SETTINGS"
  printf "  $C_OK 新建 $SETTINGS\n"
else
  backup="${SETTINGS}.memex-backup-$(date +%Y%m%d-%H%M%S)"
  cp "$SETTINGS" "$backup"
  python3 "$SRC/install/merge_settings.py" "$SETTINGS" "$SRC/templates/memex-hooks.json"
  printf "  $C_OK 合并完成(备份: %s)\n" "$backup"
fi

# ───── 7. 完成提示 ─────
echo
echo "[6/6] 验证"
if jq -e '.hooks.PreToolUse[].hooks[].command | select(test("memex|session-bootstrap"))' "$SETTINGS" >/dev/null 2>&1; then
  printf "  $C_OK settings.json 已含 memex hook 注册\n"
else
  printf "  $C_WARN 没在 settings.json 找到 memex hook,可能需要手动检查\n"
fi

echo
echo "╭─────────────────────────────────────────╮"
echo "│  🎉 安装完成                              "
echo "├─────────────────────────────────────────┤"
echo "│  1. 重启 Claude Code                     "
echo "│  2. 任意 cwd 启动,跑一个 bash            "
echo "│  3. 检查工作面:                          "
echo "│     ls ~/.claude/projects/\$(pwd|sed 's#/#-#g')/memory/  "
echo "│                                          "
echo "│  自定义保护分支:                          "
echo "│     export MEMEX_PROTECTED_BRANCHES=\"main master develop staging\"  "
echo "│                                          "
echo "│  详细文档:./docs/                        "
echo "╰─────────────────────────────────────────╯"

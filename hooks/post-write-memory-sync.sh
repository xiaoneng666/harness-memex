#!/bin/bash
# post-write-memory-sync.sh — PostToolUse(Write|Edit|MultiEdit)  (Memex v0.2)
#
# 当 LLM Write/Edit 到 ~/.claude/memex/**/*.md 后,自动跑 rebuild_index +
# update_index_md。无需手动维护索引。
#
# 不监控旧 ~/.claude/projects/<cwd>/memory/ — 那里走 Claude Code 原生写,不归我们管。

input=$(cat)
fpath=$(printf '%s' "$input" | jq -r '.tool_response.filePath // .tool_input.file_path // ""' 2>/dev/null)

# 只对 memex 池里的 .md 起作用
case "$fpath" in
  "$HOME/.claude/memex/"*.md|"$HOME/.claude/memex/"*/*.md) : ;;
  *) exit 0 ;;
esac

# 跳过 INDEX.md / _index/*(自身就是工具产物)
case "$fpath" in
  */INDEX.md|*/_index/*) exit 0 ;;
esac

PYTHON3=$(command -v python3 2>/dev/null || echo /usr/bin/python3)
REBUILD="$HOME/.claude/bin/rebuild_index.py"
UPDATE_IDX="$HOME/.claude/bin/update_index_md.py"
MEMEX="$HOME/.claude/memex"

[ -f "$REBUILD" ] || exit 0

echo "[$(date -u +%FT%TZ)] post-write-memory-sync: $fpath" >&2

"$PYTHON3" "$REBUILD" --memex "$MEMEX" 2>&1 | tail -5 >&2
rc=${PIPESTATUS[0]}

if [ "$rc" = "0" ] && [ -f "$UPDATE_IDX" ]; then
  # 只更新受影响的 INDEX.md
  # 判断 project_key:看 fpath 是否在 projects/<key>/ 下
  rel="${fpath#$MEMEX/}"
  case "$rel" in
    projects/*)
      key=$(echo "$rel" | cut -d/ -f2)
      "$PYTHON3" "$UPDATE_IDX" --memex "$MEMEX" --project "$key" 2>&1 | tail -3 >&2
      ;;
    global/*)
      "$PYTHON3" "$UPDATE_IDX" --memex "$MEMEX" --global 2>&1 | tail -3 >&2
      ;;
  esac
fi

if [ "$rc" != "0" ]; then
  ctx="⚠️ Memex post-write-memory-sync 失败(rebuild_index exit=${rc})。
刚 Write 的 ${fpath} 可能未入索引。
fallback: python3 ~/.claude/bin/rebuild_index.py"
  jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$c}}'
fi

exit 0

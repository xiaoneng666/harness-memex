#!/bin/bash
# post-write-memory-sync.sh — PostToolUse(Write|Edit|MultiEdit) hook
#
# 当 LLM Write/Edit/MultiEdit 到 memory/**/*.md 后,自动增量同步进
# _index/meta.jsonl 和 _index/by_branch.jsonl(若是 branch 类)。
# 无需手动跑 rebuild_index。
#
# 保留原条目的 last_access / decay / status;新文件 last_access=mtime,decay=0,status=active。
# rebuild_index 失败 → 用 hookSpecificOutput.additionalContext 抛错给 LLM(不只是 stderr)。

input=$(cat)
fpath=$(printf '%s' "$input" | jq -r '.tool_response.filePath // .tool_input.file_path // ""' 2>/dev/null)

case "$fpath" in
  *"/.claude/projects/"*"/memory/"*".md") : ;;
  *) exit 0 ;;
esac

case "$fpath" in
  */memory/INDEX.md|*/memory/MEMORY.md|*/_index/*) exit 0 ;;
esac

mem_root="${fpath%/memory/*}/memory"
[ -d "$mem_root" ] || exit 0

PYTHON3=$(command -v python3 2>/dev/null || echo /usr/bin/python3)
REBUILD="$HOME/.claude/bin/rebuild_index.py"
[ -f "$REBUILD" ] || exit 0

echo "[$(date -u +%FT%TZ)] post-write-memory-sync: $fpath" >&2
"$PYTHON3" "$REBUILD" "$mem_root" 2>&1 | grep -E '✅|❌|⚠️|扫描' | head -5 >&2
rc=${PIPESTATUS[0]}

if [ "$rc" != "0" ]; then
  ctx="⚠️ Memex post-write-memory-sync 失败(rebuild_index exit=${rc})。
刚 Write 的 ${fpath} 可能未入索引。
fallback: python3 ~/.claude/bin/rebuild_index.py ${mem_root}"
  jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$c}}'
fi

exit 0

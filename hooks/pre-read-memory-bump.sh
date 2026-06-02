#!/bin/bash
# pre-read-memory-bump.sh — PreToolUse(Read) hook
#
# 每次 LLM Read memory/**/*.md 时,更新 _index/meta.jsonl 那一行的 last_access。
# 让 LRU 决策反映访问热度(对 read-heavy 的 feedback/reference 至关重要 —
# 否则 mtime 不动会被误判为僵尸,详见 MEMORY_SPEC.md § 三)。
#
# tmpfile + mv 原子;jq 流式过滤,只改命中行;失败永远 exit 0 不阻断 Read。

input=$(cat)
fpath=$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""' 2>/dev/null)

case "$fpath" in
  *"/.claude/projects/"*"/memory/"*".md") : ;;
  *) exit 0 ;;
esac

# 反推 memory 根目录 + 相对路径
mem_root="${fpath%/memory/*}/memory"
rel="${fpath#${mem_root}/}"

idx="$mem_root/_index/meta.jsonl"
[ -f "$idx" ] || exit 0

now=$(date -u +%FT%TZ)
tmp=$(mktemp "${idx}.XXXXXX" 2>/dev/null) || exit 0
if jq -c --arg p "$rel" --arg now "$now" \
    'if .path==$p then .last_access=$now else . end' \
    "$idx" > "$tmp" 2>/dev/null; then
  mv "$tmp" "$idx"
else
  rm -f "$tmp"
fi

exit 0

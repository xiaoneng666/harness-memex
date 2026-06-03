#!/bin/bash
# pre-read-memory-bump.sh — PreToolUse(Read)  (Memex v0.2)
#
# 每次 Read ~/.claude/memex/**/*.md 时更新 _index/meta.jsonl 的 last_access。
# 让 LRU 反映访问热度(read-heavy 的 feedback/reference 不被误杀)。

input=$(cat)
fpath=$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""' 2>/dev/null)

# 只对 memex 池起作用
case "$fpath" in
  "$HOME/.claude/memex/"*.md) : ;;
  *) exit 0 ;;
esac
# 跳 _index/INDEX.md 本身
case "$fpath" in
  */_index/*|*/INDEX.md) exit 0 ;;
esac

MEMEX="$HOME/.claude/memex"
rel="${fpath#$MEMEX/}"
idx="$MEMEX/_index/meta.jsonl"
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

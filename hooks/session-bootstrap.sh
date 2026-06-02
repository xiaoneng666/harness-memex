#!/bin/bash
# session-bootstrap.sh — PreToolUse(any) hook
#
# 任何 cwd 第一次启动 Claude 时,自动建出 MEMORY_SPEC.md 定义的三层目录骨架
# + 初始化 INDEX.md + 跑 rebuild_index 扫已有 .md 入索引。
#
# 幂等状态机:
#   ① mem_root 不存在        → mkdir + 建骨架 + rebuild_index
#   ② _index/ 缺失           → 建骨架 + rebuild_index
#   ③ _index/ 在但 .md 漂移   → 增量 rebuild_index
#   ④ 全一致                  → exit 0
#
# 同一 session 只跑一次:/tmp/harness-memex-bootstrap-<sid>
# 失败永远 exit 0(不阻断 LLM);rebuild 失败时塞 ⚠️ 兜底 ctx 让 LLM 接管。

input=$(cat)
sid=$(printf '%s' "$input" | jq -r '.session_id // "nosess"' 2>/dev/null)
[ "$sid" = "nosess" ] && exit 0

marker="/tmp/harness-memex-bootstrap-${sid}"
[ -f "$marker" ] && exit 0
touch "$marker" 2>/dev/null

cwd=$(pwd)
cwd_slug=$(printf '%s' "$cwd" | sed 's#/#-#g')
mem_root="$HOME/.claude/projects/${cwd_slug}/memory"

PYTHON3=$(command -v python3 2>/dev/null || echo /usr/bin/python3)
REBUILD="$HOME/.claude/bin/rebuild_index.py"

need_bootstrap=0
need_reindex=0

if [ ! -d "$mem_root" ]; then
  need_bootstrap=1
  need_reindex=1
elif [ ! -d "$mem_root/_index" ]; then
  need_bootstrap=1
  need_reindex=1
else
  actual=$(find "$mem_root" -name '*.md' \
    -not -name 'INDEX.md' -not -name 'MEMORY.md' \
    -not -path '*/_index/*' -not -path '*/backup-*/*' \
    2>/dev/null | wc -l | tr -d ' ')
  meta="$mem_root/_index/meta.jsonl"
  indexed=0
  [ -f "$meta" ] && indexed=$(grep -c '^{' "$meta" 2>/dev/null || echo 0)
  if [ "$actual" != "$indexed" ]; then
    need_reindex=1
    echo "[$(date -u +%FT%TZ)] memory index drift: ${actual} .md vs ${indexed} indexed → reindexing" >&2
  fi
fi

[ $need_bootstrap -eq 0 ] && [ $need_reindex -eq 0 ] && exit 0

# ─── ① bootstrap 骨架 ───
if [ $need_bootstrap -eq 1 ]; then
  {
    echo "[$(date -u +%FT%TZ)] bootstrap memory skeleton at $mem_root" >&2
    mkdir -p \
      "$mem_root/_index" \
      "$mem_root/feedback" \
      "$mem_root/reference" \
      "$mem_root/user" \
      "$mem_root/global" \
      "$mem_root/projects" \
      || { echo "✗ mkdir failed" >&2; exit 0; }

    touch "$mem_root/_index/meta.jsonl" "$mem_root/_index/by_branch.jsonl"

    if [ -f "$HOME/.claude/INDEX_TEMPLATE.md" ] && [ ! -f "$mem_root/INDEX.md" ]; then
      cp "$HOME/.claude/INDEX_TEMPLATE.md" "$mem_root/INDEX.md"
    fi

    if [ ! -e "$mem_root/MEMORY.md" ] && [ -f "$mem_root/INDEX.md" ]; then
      (cd "$mem_root" && ln -s INDEX.md MEMORY.md)
    fi

    echo "✓ memory skeleton bootstrapped" >&2
  } 2>/dev/null
fi

# ─── ② rebuild_index(扫已有 .md 入索引,LRU 字段保留)───
reindex_rc=0
if [ $need_reindex -eq 1 ] && [ -f "$REBUILD" ]; then
  echo "[$(date -u +%FT%TZ)] auto rebuild_index for $mem_root" >&2
  "$PYTHON3" "$REBUILD" "$mem_root" 2>&1 | head -10 >&2
  reindex_rc=${PIPESTATUS[0]}
fi

# ─── ③ ctx 注入(含失败兜底)───
if [ "$reindex_rc" != "0" ] && [ $need_reindex -eq 1 ]; then
  ctx="⚠️ Memex bootstrap 跑了,但 rebuild_index 失败(exit=${reindex_rc})。
${mem_root}/_index/meta.jsonl 可能不全。
fallback: python3 ~/.claude/bin/rebuild_index.py ${mem_root}"
elif [ $need_bootstrap -eq 1 ]; then
  ctx="✨ 本 cwd memory 工作面已按 ~/.claude/MEMORY_SPEC.md 初始化(三层目录 + 索引扫好)。先看 ${mem_root}/INDEX.md。"
elif [ $need_reindex -eq 1 ]; then
  ctx="🔄 检测到 memory 索引漂移,已自动增量 rebuild_index。详情:${mem_root}/_index/meta.jsonl"
else
  exit 0
fi

jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
exit 0

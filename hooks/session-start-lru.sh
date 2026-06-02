#!/bin/bash
# session-start-lru.sh — SessionStart hook
#
# 每次 Claude session 启动时主动跑 LRU 扫,若有候选 → 塞 ctx 给 LLM,
# 让 LLM 决定是否当场压缩。无候选 → 静默(不刷屏)。
#
# 性能:lru_compact.py 在 N=100 时 < 50ms,SessionStart 时长可控。

input=$(cat)
sid=$(printf '%s' "$input" | jq -r '.session_id // "nosess"' 2>/dev/null)

# 同 session 只跑一次
marker="/tmp/memex-lru-${sid}"
[ -f "$marker" ] && exit 0
touch "$marker" 2>/dev/null

cwd=$(pwd)
cwd_slug=$(printf '%s' "$cwd" | sed 's#/#-#g')
mem_root="$HOME/.claude/projects/${cwd_slug}/memory"

# 没 mem_root → 没东西扫,静默(bootstrap 会建)
[ -d "$mem_root" ] || exit 0
[ -f "$mem_root/_index/meta.jsonl" ] || exit 0

PYTHON3=$(command -v python3 2>/dev/null || echo /usr/bin/python3)
LRU="$HOME/.claude/bin/lru_compact.py"
[ -f "$LRU" ] || exit 0

# 跑 --quiet 模式拿候选数量
report=$("$PYTHON3" "$LRU" --quiet "$mem_root" 2>/dev/null)

# 解析候选数(--quiet 输出格式:
#   compact_1: N
#   compact_2: N
#   compact_3: N
#   pending_delete: N
#   awaiting_delete: N
# )
total=$(echo "$report" | awk -F: 'NR<=5 {sum+=$2} END {print sum+0}')

# 无候选 → 静默
[ "$total" -eq 0 ] && exit 0

# 有候选 → 塞 ctx
c1=$(echo "$report" | awk -F: '$1=="compact_1"{print $2+0; exit}')
c2=$(echo "$report" | awk -F: '$1=="compact_2"{print $2+0; exit}')
c3=$(echo "$report" | awk -F: '$1=="compact_3"{print $2+0; exit}')
pd=$(echo "$report" | awk -F: '$1=="pending_delete"{print $2+0; exit}')
awd=$(echo "$report" | awk -F: '$1=="awaiting_delete"{print $2+0; exit}')

ctx="🔄 Memex LRU 周扫(自动,SessionStart 触发):

  · 待第 1 次压缩(30d+): ${c1:-0} 条
  · 待第 2 次压缩(60d+): ${c2:-0} 条
  · 待第 3 次压缩(90d+): ${c3:-0} 条
  · 待标候选删除(120d+): ${pd:-0} 条
  · 已待用户授权删除: ${awd:-0} 条

要不要现在处理? 详细清单:
  python3 ~/.claude/bin/lru_compact.py ${mem_root}

不处理也行,下次 session 启动再提醒。
(候选删除需显式跑 lru_compact.py --rm <path>,有 60d 防误删 + 软删 _trash/ 保险)"

jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$c}}'
exit 0

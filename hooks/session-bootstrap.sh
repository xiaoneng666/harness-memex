#!/bin/bash
# session-bootstrap.sh — PreToolUse(any) hook  (Memex v0.2)
#
# 薄壳脚本:复杂逻辑全在 ~/.claude/bin/update_memex_bridge.py。
# 这里只做去重 marker + 调 Python + 解析输出 + 塞 ctx。
#
# 失败永远 exit 0(不阻断 LLM)。

input=$(cat)
sid=$(printf '%s' "$input" | jq -r '.session_id // "nosess"' 2>/dev/null)
[ "$sid" = "nosess" ] && exit 0

cwd=$(pwd)
cwd_slug=$(printf '%s' "$cwd" | sed 's#/#-#g')
marker="/tmp/memex-bootstrap-${sid}-${cwd_slug}"
[ -f "$marker" ] && exit 0
touch "$marker" 2>/dev/null

PYTHON3=$(command -v python3 2>/dev/null || echo /usr/bin/python3)
BRIDGE_PY="$HOME/.claude/bin/update_memex_bridge.py"
REBUILD="$HOME/.claude/bin/rebuild_index.py"
UPDATE_IDX="$HOME/.claude/bin/update_index_md.py"
MEMEX="$HOME/.claude/memex"

[ -f "$BRIDGE_PY" ] || exit 0

# 调 Python 干所有重活,拿 JSON 结果
result=$("$PYTHON3" "$BRIDGE_PY" --cwd "$cwd" --memex "$MEMEX" 2>/dev/null)
[ -z "$result" ] && exit 0

bootstrap=$(printf '%s' "$result" | jq -r '.bootstrap // false' 2>/dev/null)
new_projects=$(printf '%s' "$result" | jq -r '.new_projects // 0' 2>/dev/null)
discovered=$(printf '%s' "$result" | jq -r '.discovered_repos // 0' 2>/dev/null)
action=$(printf '%s' "$result" | jq -r '.bridge_action // ""' 2>/dev/null)

# 新发现 project → 跑 rebuild 让索引同步
if [ "$bootstrap" = "true" ] || [ "$new_projects" != "0" ]; then
  "$PYTHON3" "$REBUILD" --memex "$MEMEX" >/dev/null 2>&1
  "$PYTHON3" "$UPDATE_IDX" --memex "$MEMEX" >/dev/null 2>&1
fi

# ctx 注入
if [ "$bootstrap" = "true" ]; then
  ctx="✨ Memex v0.2 初始化完成 (~/.claude/memex/)。识别到本 cwd 下 ${discovered} 个 git repo。
INDEX 已搭桥到 ~/.claude/projects/${cwd_slug}/memory/MEMORY.md(${action})。"
  jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
elif [ "$new_projects" != "0" ]; then
  ctx="✨ Memex 识别到 ${new_projects} 个新 project 并已建骨架 + 挂 @import。"
  jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
fi

exit 0

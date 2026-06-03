#!/bin/bash
# pre-edit-branch-notice.sh — PreToolUse(Edit|Write|MultiEdit)  (Memex v0.2)
#
# 每 session 每分支首次编辑代码文件时,把对应的 (project_key, branch) memory
# 路径塞 ctx,让 LLM 写代码前 Read 一下。
#
# 去重:同 session 同 project_key 同 branch 只提示一次。

input=$(cat)
sid=$(printf '%s' "$input" | jq -r '.session_id // "nosess"' 2>/dev/null)
fpath=$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""' 2>/dev/null)

# Early return:Write memory / spec / template 自身 → 静默
case "$fpath" in
  "$HOME/.claude/memex/"*) exit 0 ;;
  "$HOME/.claude/projects/"*"/memory/"*) exit 0 ;;
  "$HOME/.claude/MEMORY_SPEC.md"|"$HOME/.claude/"*"_TEMPLATE.md") exit 0 ;;
esac

# 反推 git 仓库:用 file 所在目录的 toplevel
if [ -n "$fpath" ]; then
  git_dir=$(dirname "$fpath")
else
  git_dir="."
fi

repo_root=$(git -C "$git_dir" rev-parse --show-toplevel 2>/dev/null)
branch=$(git -C "$git_dir" rev-parse --abbrev-ref HEAD 2>/dev/null)

# 拿不到 → 静默
[ -z "$repo_root" ] && exit 0
[ -z "$branch" ] && exit 0

PYTHON3=$(command -v python3 2>/dev/null || echo /usr/bin/python3)
DERIVE_KEY="$HOME/.claude/bin/derive_project_key.py"
MEMEX="$HOME/.claude/memex"

info=$("$PYTHON3" "$DERIVE_KEY" "$repo_root" 2>/dev/null)
project_key=$(printf '%s' "$info" | jq -r '.key // ""' 2>/dev/null)
[ -z "$project_key" ] || [ "$project_key" = "null" ] && exit 0
display=$(printf '%s' "$info" | jq -r '.display_name // ""' 2>/dev/null)

# 去重 marker(slug 化分支名)
slug=$(printf '%s' "$branch" | sed 's#[/-]#_#g')
marker="/tmp/memex-pre-edit-${sid}-${project_key}-${slug}"
[ -f "$marker" ] && exit 0
touch "$marker" 2>/dev/null

# 保护分支预警
DEFAULT_PROTECTED="main master develop production staging"
PROTECTED_BRANCHES="${MEMEX_PROTECTED_BRANCHES:-$DEFAULT_PROTECTED}"
is_protected() {
  local b="$1"
  for p in $PROTECTED_BRANCHES; do
    [ "$b" = "$p" ] && return 0
  done
  return 1
}

if is_protected "$branch"; then
  ctx="⚠️ ${display}: 正在保护分支 [${branch}] 编辑文件 — 一般不该直接改主干,确认是否该先切 feat/bugfix。"
  jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
  exit 0
fi

# 查 branches.jsonl(O(1))
memfile=""
idx="$MEMEX/_index/branches.jsonl"
if [ -f "$idx" ]; then
  rel=$(jq -r --arg k "$project_key" --arg b "$slug" \
        'select(.project_key==$k and .branch_slug==$b) | .memory_path' \
        "$idx" 2>/dev/null | head -1)
  if [ -n "$rel" ] && [ -f "$MEMEX/$rel" ]; then
    memfile="$MEMEX/$rel"
  fi
fi
# fallback glob
[ -z "$memfile" ] && memfile=$(ls "$MEMEX/projects/$project_key/branches/${slug}.md" 2>/dev/null | head -1)

project_index="$MEMEX/projects/$project_key/INDEX.md"

if [ -n "$memfile" ]; then
  ctx="开改核实 · ${display} · 当前分支: ${branch}

并行 Read(同回合发,把项目共享 + 分支层一次拉齐):"
  [ -f "$project_index" ] && ctx="$ctx
  · ${project_index}(项目共享层:overview / feedback / reference)"
  ctx="$ctx
  · ${memfile}(本分支 memory:进度 / 决策 / 踩坑)"
else
  suggested="$MEMEX/projects/$project_key/branches/${slug}.md"
  ctx="开改核实 · ${display} · 当前分支: ${branch}
⚠️ 本分支暂无 memory。建议路径: ${suggested}

先 Read project INDEX 把项目共享层拉齐:"
  [ -f "$project_index" ] && ctx="$ctx
  · ${project_index}"
  ctx="$ctx

按 spec § 五 自决策:长期分支建议立档,临时分支可跳。"
fi

# 后台 touch:更新 projects.jsonl.last_access,让下次 session bootstrap 把本 project 加进 bridge
BRIDGE_PY="$HOME/.claude/bin/update_memex_bridge.py"
if [ -f "$BRIDGE_PY" ]; then
  "$PYTHON3" "$BRIDGE_PY" --touch "$project_key" --repo "$repo_root" >/dev/null 2>&1 &
fi

jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
exit 0

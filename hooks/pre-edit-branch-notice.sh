#!/bin/bash
# pre-edit-branch-notice.sh — PreToolUse(Edit|Write|MultiEdit) hook
#
# 每 session 每分支首次编辑文件时,把「当前分支 + 对应 memory 文件」注入 ctx,
# 让 LLM 写代码前意识到在哪个分支、本分支本来该干啥。
#
# 去重:同 session 同分支只提示一次。切换分支(slug 变)重提一次。
# 自定义保护分支:export MEMEX_PROTECTED_BRANCHES="main master develop staging"

input=$(cat)
sid=$(printf '%s' "$input" | jq -r '.session_id // "nosess"' 2>/dev/null)

# 从 file_path 反推 git 仓库(支持 monorepo 子项目)
fpath=$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""' 2>/dev/null)
if [ -n "$fpath" ]; then
  git_dir=$(dirname "$fpath")
else
  git_dir="."
fi
branch=$(git -C "$git_dir" rev-parse --abbrev-ref HEAD 2>/dev/null)

# ─── 保护分支列表 ───
DEFAULT_PROTECTED="main develop production staging"
PROTECTED_BRANCHES="${MEMEX_PROTECTED_BRANCHES:-$DEFAULT_PROTECTED}"

is_protected() {
  local b="$1"
  for p in $PROTECTED_BRANCHES; do
    [ "$b" = "$p" ] && return 0
  done
  return 1
}

if [ -z "$branch" ]; then
  # 兜底:file 在常见 project 路径下但 git 不识别 → 提醒 LLM 接管
  case "$fpath" in
    */project/*|*/projects/*|*/code/*|*/workspace/*|*/repos/*)
      ctx="⚠️ 编辑 ${fpath} 但 hook 没识别 git 分支(cwd 和 file dirname 都不在 git 仓库下)。
按 ~/.claude/MEMORY_SPEC.md § 四+九 自决策:
1) 自己 git -C \$(dirname ${fpath}) rev-parse 拿分支
2) 看本 cwd by_branch.jsonl 是否有对应 memory
3) 若是长期工作分支,改动前考虑建/更新 memory"
      jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
      ;;
  esac
  exit 0
fi

slug=$(printf '%s' "$branch" | sed 's#[/-]#_#g')
marker="/tmp/harness-memex-br-${sid}-${slug}"
[ -f "$marker" ] && exit 0
touch "$marker" 2>/dev/null

if is_protected "$branch"; then
  ctx="⚠️ 正在保护分支 [${branch}] 上编辑文件 — 改动一般不该直接落主干,确认是否该先切 feat/bugfix 分支。"
else
  cwd_slug=$(pwd | sed 's#/#-#g')
  mem_root="$HOME/.claude/projects/${cwd_slug}/memory"
  memfile=""
  if [ -d "$mem_root" ]; then
    idx="$mem_root/_index/by_branch.jsonl"
    if [ -f "$idx" ]; then
      rel=$(jq -r --arg b "$branch" 'select(.branch==$b) | .memory' "$idx" 2>/dev/null | head -1)
      if [ -n "$rel" ] && [ -f "$mem_root/$rel" ]; then
        memfile="$mem_root/$rel"
      fi
    fi
    [ -z "$memfile" ] && memfile=$(ls "$mem_root"/projects/*/*/branches/"${slug}".md 2>/dev/null | head -1)
    [ -z "$memfile" ] && memfile=$(ls "$mem_root"/projects/*/branches/"${slug}".md 2>/dev/null | head -1)
  fi

  if [ -n "$memfile" ]; then
    ctx="开改核实 · 当前分支: ${branch} · 本分支记忆: ${memfile}

开改前先 Read 此文件,确认本次改动属于该分支 + 了解前面已做到哪一步。"
  else
    ctx="开改核实 · 当前分支: ${branch} · ⚠️ 本分支暂无 memory 文件

按 ~/.claude/MEMORY_SPEC.md § 四 自决策:是否需要立档(长期工作分支建议立、临时分支可跳)。"
  fi
fi

jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
exit 0

#!/bin/bash
# post-checkout-handoff.sh — PostToolUse(Bash) hook  (Memex v0.2)
#
# 切分支(git checkout / switch)成功后,塞 ctx 让 LLM 并行:
#   · Write a-memory(收档 from)
#   · Read  b-memory(启档 to)
#
# v0.2 关键变化:不再按 cwd 查找 memory,改按 (project_key, branch) 查
# ~/.claude/memex/_index/branches.jsonl(O(1) jq filter)。
#
# 流程:
#   1. 解析 git checkout 命令拿 git working dir
#   2. git rev-parse 拿 from / to branch
#   3. git -C <dir> repo_root → derive_project_key.py 拿 project_key
#   4. jq branches.jsonl 查 (key, from) / (key, to) → memory 文件
#   5. 塞 ctx
#
# hook 只支持 `cd <path>` / `git -C <path>` 两种最简形式(spec § 七)。

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)
exit_code=$(printf '%s' "$input" | jq -r '.tool_response.exitCode // .tool_response.exit_code // 0' 2>/dev/null)

[ "$exit_code" != "0" ] && exit 0

# 是 git checkout/switch 才处理
cmd_n="$cmd"
case "$cmd_n" in
  *"git -C "*)
    cmd_n=$(printf '%s' "$cmd_n" | sed -E 's/git[[:space:]]+-C[[:space:]]+[^[:space:]]+[[:space:]]+/git /g')
    ;;
esac
case "$cmd_n" in
  *"git checkout "*|*"git switch "*) : ;;
  *) exit 0 ;;
esac

PYTHON3=$(command -v python3 2>/dev/null || echo /usr/bin/python3)
DERIVE_KEY="$HOME/.claude/bin/derive_project_key.py"
MEMEX="$HOME/.claude/memex"

# 解析 git working dir(spec § 七 两种最简形式)
resolve_git_dir() {
  local c="$1"
  local trimmed="${c#"${c%%[![:space:]]*}"}"
  local p
  case "$trimmed" in
    "git -C "*)
      p=$(printf '%s' "$trimmed" | sed -E 's/^git[[:space:]]+-C[[:space:]]+([^[:space:]]+).*$/\1/' | head -1)
      ;;
    "cd "*)
      p=$(printf '%s' "$trimmed" | sed -E 's/^cd[[:space:]]+([^[:space:];&]+).*$/\1/' | head -1)
      ;;
    *)
      echo "."; return ;;
  esac
  case "$p" in
    "~/"*) p="${HOME}/${p#"~/"}" ;;
    "~")   p="${HOME}" ;;
  esac
  echo "$p"
}

git_dir=$(resolve_git_dir "$cmd")

# 拿 from / to
to_branch=$(git -C "$git_dir" rev-parse --abbrev-ref HEAD 2>/dev/null)
from_branch=$(git -C "$git_dir" rev-parse --abbrev-ref '@{-1}' 2>/dev/null)

if [ -z "$to_branch" ]; then
  ctx="⚠️ git checkout 成功但 hook 没识别 git 仓库(git_dir=${git_dir})。
按 ~/.claude/MEMORY_SPEC.md § 五+十 自决策:拿当前分支,查 ~/.claude/memex/_index/branches.jsonl 看是否有对应 memory。"
  jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$c}}'
  exit 0
fi

# 同分支 → 静默
[ -n "$from_branch" ] && [ "$from_branch" = "$to_branch" ] && exit 0

# 拿 project_key
info=$("$PYTHON3" "$DERIVE_KEY" "$git_dir" 2>/dev/null)
project_key=$(printf '%s' "$info" | jq -r '.key // ""' 2>/dev/null)
display=$(printf '%s' "$info" | jq -r '.display_name // ""' 2>/dev/null)

if [ -z "$project_key" ] || [ "$project_key" = "null" ]; then
  ctx="⚠️ git checkout 成功(${from_branch:-?} → ${to_branch}),但 derive_project_key 失败(git_dir=${git_dir})。
按 spec § 三 自决策:看是否要建 memory。"
  jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$c}}'
  exit 0
fi

# 工具:从 branch 名转 slug
slug_branch() {
  printf '%s' "$1" | sed 's#[/-]#_#g'
}

# 工具:查 branches.jsonl(O(1) jq filter)
lookup_branch_memory() {
  local key="$1" branch="$2"
  local idx="$MEMEX/_index/branches.jsonl"
  [ -f "$idx" ] || return
  local slug
  slug=$(slug_branch "$branch")
  local rel
  rel=$(jq -r --arg k "$key" --arg b "$slug" \
        'select(.project_key==$k and .branch_slug==$b) | .memory_path' \
        "$idx" 2>/dev/null | head -1)
  if [ -n "$rel" ] && [ -f "$MEMEX/$rel" ]; then
    echo "$MEMEX/$rel"
    return
  fi
  # fallback glob
  ls "$MEMEX/projects/$key/branches/${slug}.md" 2>/dev/null | head -1
}

# 建议路径(若 from 没 memory,给出推荐路径)
suggest_branch_memory_path() {
  local key="$1" branch="$2"
  local slug
  slug=$(slug_branch "$branch")
  echo "$MEMEX/projects/$key/branches/${slug}.md"
}

from_mem=$(lookup_branch_memory "$project_key" "$from_branch")
to_mem=$(lookup_branch_memory "$project_key" "$to_branch")

DEFAULT_PROTECTED="main master develop production staging"
PROTECTED_BRANCHES="${MEMEX_PROTECTED_BRANCHES:-$DEFAULT_PROTECTED}"
is_protected() {
  local b="$1"
  for p in $PROTECTED_BRANCHES; do
    [ "$b" = "$p" ] && return 0
  done
  return 1
}

project_index="$MEMEX/projects/$project_key/INDEX.md"

ctx="🔄 切分支完成(${display}): ${from_branch:-?} → ${to_branch}

立刻并行处理(无依赖,可同时发):"

# A. 读 project INDEX(总是,把项目共享层一次拉齐:overview / 项目 feedback / 项目 reference 都在里面链接)
if [ -f "$project_index" ]; then
  ctx="$ctx
  · Read ${project_index}:加载 ${display} 项目共享层(overview / 长期决策 / 项目专属 feedback / reference)"
fi

# B. 写 from(收档)
if [ -n "$from_mem" ]; then
  ctx="$ctx
  · Write ${from_mem}:总结本次会话以来在 ${from_branch} 的关键改动 / 状态 / 思路 / 进度"
elif [ -n "$from_branch" ] && ! is_protected "$from_branch"; then
  suggested=$(suggest_branch_memory_path "$project_key" "$from_branch")
  ctx="$ctx
  · Write ${suggested}(自建):若 ${from_branch} 有会话改动,frontmatter + 摘要 / 进度;不重要可跳"
fi

# C. 读 to(启档)
if [ -n "$to_mem" ]; then
  ctx="$ctx
  · Read ${to_mem}:加载 ${to_branch} 分支记忆(进度 / 决策 / 踩坑)"
else
  ctx="$ctx
  · ${to_branch} 分支无 memory(看上面 INDEX 的分支列表确认,再决定是否立档)"
fi

ctx="$ctx

(三步互不依赖,**同回合并行发**最高效 — 把项目共享层 + 分支层一次拉齐)

想看更多?按需查:
  · python3 ~/.claude/bin/memex_query.py --project ${project_key}
  · python3 ~/.claude/bin/memex_query.py --feedback --project-filter ${project_key}
  · python3 ~/.claude/bin/memex_query.py --grep <term>"

# 后台 touch:更新 projects.jsonl.last_access,让下次 session bootstrap 把本 project 加进 bridge
BRIDGE_PY="$HOME/.claude/bin/update_memex_bridge.py"
if [ -f "$BRIDGE_PY" ]; then
  "$PYTHON3" "$BRIDGE_PY" --touch "$project_key" --repo "$git_dir" >/dev/null 2>&1 &
fi

jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$c}}'
exit 0

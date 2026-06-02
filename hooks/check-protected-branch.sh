#!/bin/bash
# check-protected-branch.sh — PreToolUse(Bash) hook
#
# 拦三类 git 命令:
#   ① git commit / git push:
#       · 保护分支(可配 MEMEX_PROTECTED_BRANCHES) → block(exit 2)
#       · 功能分支 → 放行 + 注入本分支 memory ctx
#   ② git checkout / git switch:
#       · 不拦,做收档(当前)+ 启档(目标)提示;目标 memory 内容前 200 行注入 ctx
#   ③ 其它 git / 非 git → 静默放行
#
# 自定义保护分支:export MEMEX_PROTECTED_BRANCHES="main master develop staging"
#
# 设计原则:
#   · 脚本只支持两种最简 shell 形式:`cd <path>; git ...` / `git -C <path> ...`
#   · 复杂 shell(pushd / 别名 / subshell)一律 silent degrade + 塞 ⚠️ 兜底 ctx
#   · 失败永远 exit 0(除了拦保护分支故意 exit 2)

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)

# ─── 保护分支列表(env var > default)───
DEFAULT_PROTECTED="main develop production staging"
PROTECTED_BRANCHES="${MEMEX_PROTECTED_BRANCHES:-$DEFAULT_PROTECTED}"

is_protected() {
  local b="$1"
  for p in $PROTECTED_BRANCHES; do
    [ "$b" = "$p" ] && return 0
  done
  return 1
}

# ─── 从 cmd 解析 git working dir(支持 monorepo 子项目)───
# 只支持两种最简形式;其它一律返回 "." 让 git 自己上溯找 .git
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
      echo "."
      return
      ;;
  esac
  # 展开 ~ 为 $HOME(否则 git -C 不识别字面 ~)
  # 注意:${p#~/} 里的 ~ 会被 bash 展开成 $HOME;必须双引号让它字面
  case "$p" in
    "~/"*) p="${HOME}/${p#"~/"}" ;;
    "~")   p="${HOME}" ;;
  esac
  echo "$p"
}

# ─── 只查当前 cwd 对应的 mem_root(防跨 cwd 同名分支串,见 spec § 九)───
lookup_branch_memory() {
  local branch="$1"
  local cwd_slug
  cwd_slug=$(pwd | sed 's#/#-#g')
  local mem_root="$HOME/.claude/projects/${cwd_slug}/memory"
  [ -d "$mem_root" ] || return 0

  local idx="$mem_root/_index/by_branch.jsonl"
  if [ -f "$idx" ]; then
    local rel
    rel=$(jq -r --arg b "$branch" 'select(.branch==$b) | .memory' "$idx" 2>/dev/null | head -1)
    if [ -n "$rel" ] && [ -f "$mem_root/$rel" ]; then
      echo "$mem_root/$rel"
      return 0
    fi
  fi

  # fallback:本 cwd glob(不跨 cwd)
  local slug
  slug=$(printf '%s' "$branch" | sed 's#[/-]#_#g')
  ls "$mem_root"/projects/*/*/branches/"${slug}".md 2>/dev/null | head -1
  ls "$mem_root"/projects/*/branches/"${slug}".md 2>/dev/null | head -1
}

# Normalize:把 "git -C <path>" 改成 "git",让外层 case 子串匹配
cmd_n="$cmd"
case "$cmd_n" in
  *"git -C "*)
    cmd_n=$(printf '%s' "$cmd_n" | sed -E 's/git[[:space:]]+-C[[:space:]]+[^[:space:]]+[[:space:]]+/git /g')
    ;;
esac

case "$cmd_n" in
  # ─── git commit / push ───
  *"git commit"*|*"git push"*)
    git_dir=$(resolve_git_dir "$cmd")
    branch=$(git -C "$git_dir" rev-parse --abbrev-ref HEAD 2>/dev/null)
    if [ -z "$branch" ]; then
      ctx="⚠️ 检测到 commit/push 但 hook 没识别 git 分支(尝试 git_dir=${git_dir})。
按 ~/.claude/MEMORY_SPEC.md § 四+九 自决策:
1) 自己 git rev-parse / git status 拿当前分支
2) 若是保护分支(${PROTECTED_BRANCHES})→ 停下来,切 feat/bugfix 分支
3) 功能分支再看 memory 是否要追加本次改动"
      jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
      exit 0
    fi

    if is_protected "$branch"; then
      echo "❌ 当前在保护分支 [$branch],禁止直接 commit/push。" >&2
      echo "   功能分支:git checkout -b feat/$(date +%m%d)/<name>" >&2
      echo "   修复分支:git checkout -b bugfix/$(date +%m%d)/<name>" >&2
      exit 2
    fi

    memfile=$(lookup_branch_memory "$branch")
    if [ -n "$memfile" ]; then
      ctx="提交核实 · 当前分支: ${branch} · 本分支记忆: ${memfile}

按 ~/.claude/MEMORY_SPEC.md § 四 自决策:是否需要 commit 后把本次关键改动追加进 memory(看会话上下文,只记主要的)。"
    else
      ctx="提交核实 · 当前分支: ${branch} · ⚠️ 无对应分支记忆

按 ~/.claude/MEMORY_SPEC.md § 四 自决策:是否需要立档(长期工作分支建议立、临时分支可跳)。"
    fi
    echo "✓ 提交落在分支: ${branch}"
    jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
    exit 0
    ;;

  # git checkout / switch 移到 hooks/post-checkout-handoff.sh(PostToolUse Bash)
  # 原因:PreToolUse 时工具未执行,a 分支会话尚未"封档",ctx 太早不准。
  # PostToolUse 时已切完,from/to 明确,LLM 可并行 Write a + Read b。
esac
exit 0

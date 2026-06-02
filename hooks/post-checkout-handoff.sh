#!/bin/bash
# post-checkout-handoff.sh — PostToolUse(Bash) hook
#
# 切分支完成后(Bash 工具执行成功之后)触发,塞 ctx 让 LLM 主动并行:
#   1. Write a-memory(总结刚才在 from 分支的会话改动)
#   2. Read b-memory(加载 to 分支上下文)
#
# 用 `@{-1}` 拿 git 内置的"前一个 HEAD"分支名,不依赖 reflog 解析。
#
# 设计:
#   · hook 只塞事实(from/to/path),不替 LLM 决策
#   · PostToolUse 时工具已成功,from/to 已确定
#   · Write a + Read b 互相无依赖,LLM 可并行发出

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)
exit_code=$(printf '%s' "$input" | jq -r '.tool_response.exitCode // .tool_response.exit_code // 0' 2>/dev/null)

# Bash 执行失败 → 没切成功 → 不处理
[ "$exit_code" != "0" ] && exit 0

# 解析 cmd 看是不是 git checkout/switch
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

# 从 cmd 解析 git working dir(同 spec § 七 两种最简形式)
resolve_git_dir() {
  local c="$1"
  local trimmed="${c#"${c%%[![:space:]]*}"}"
  case "$trimmed" in
    "git -C "*)
      printf '%s' "$trimmed" | sed -E 's/^git[[:space:]]+-C[[:space:]]+([^[:space:]]+).*$/\1/'
      return
      ;;
    "cd "*)
      printf '%s' "$trimmed" | sed -E 's/^cd[[:space:]]+([^[:space:];&]+).*$/\1/'
      return
      ;;
  esac
  echo "."
}

git_dir=$(resolve_git_dir "$cmd")

# 现在的分支(to)和前一个 HEAD(from)
to_branch=$(git -C "$git_dir" rev-parse --abbrev-ref HEAD 2>/dev/null)
from_branch=$(git -C "$git_dir" rev-parse --abbrev-ref '@{-1}' 2>/dev/null)

# 拿不到分支 → 兜底 ctx,让 LLM 接管
if [ -z "$to_branch" ]; then
  ctx="⚠️ git checkout 执行成功,但 hook 没识别 git 仓库(git_dir=${git_dir})。
按 ~/.claude/MEMORY_SPEC.md § 四+九 自决策:
1) 自己拿当前分支
2) 看是否要写前一分支 memory + 读当前分支 memory"
  jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$c}}'
  exit 0
fi

# 同分支(可能是 git checkout 文件不是分支)→ 静默
[ -n "$from_branch" ] && [ "$from_branch" = "$to_branch" ] && exit 0

# 查 from/to 的 memory 路径
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
  local slug
  slug=$(printf '%s' "$branch" | sed 's#[/-]#_#g')
  ls "$mem_root"/projects/*/*/branches/"${slug}".md 2>/dev/null | head -1
  ls "$mem_root"/projects/*/branches/"${slug}".md 2>/dev/null | head -1
}

# 推荐的 a-memory 写入路径(若不存在,LLM 按这个模板建)
suggest_branch_memory_path() {
  local branch="$1"
  local cwd_slug
  cwd_slug=$(pwd | sed 's#/#-#g')
  local mem_root="$HOME/.claude/projects/${cwd_slug}/memory"
  local slug
  slug=$(printf '%s' "$branch" | sed 's#[/-]#_#g')
  echo "$mem_root/projects/<biz>/branches/${slug}.md"
}

from_mem=$(lookup_branch_memory "$from_branch")
to_mem=$(lookup_branch_memory "$to_branch")

# 构建 ctx:塞事实 + 给出明确并行指令
ctx="🔄 切分支完成: ${from_branch:-?} → ${to_branch}

立刻并行处理(无依赖,可同时发):"

# A. 写 from(收档)
if [ -n "$from_mem" ]; then
  ctx="$ctx
  · Write ${from_mem}:总结本次会话以来在 ${from_branch} 的关键改动 / 状态 / 思路 / 进度"
else
  if [ -n "$from_branch" ]; then
    case "$from_branch" in
      main|master|develop|production) : ;;  # 保护分支不强求建
      *)
        suggested=$(suggest_branch_memory_path "$from_branch")
        ctx="$ctx
  · Write ${suggested}(自建一份):若 ${from_branch} 有会话改动,frontmatter + 摘要 / 进度;不重要可跳"
        ;;
    esac
  fi
fi

# B. 读 to(启档)
if [ -n "$to_mem" ]; then
  ctx="$ctx
  · Read ${to_mem}:加载 ${to_branch} 上下文(进度 / 决策 / 踩坑)"
else
  ctx="$ctx
  · Read ~/.claude/projects/$(pwd | sed 's#/#-#g')/memory/INDEX.md:看 ${to_branch} 是否要立档(项目速查段 + by_branch.jsonl 没命中)"
fi

ctx="$ctx

(两步互不依赖,**同一回合并行发**最高效)"

jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$c}}'
exit 0

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
DEFAULT_PROTECTED="main master develop production"
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

  # ─── git checkout / switch ─── 不拦,做收档+启档
  *"git checkout "*|*"git switch "*)
    git_dir=$(resolve_git_dir "$cmd")
    cur=$(git -C "$git_dir" rev-parse --abbrev-ref HEAD 2>/dev/null)
    [ -z "$cur" ] && exit 0  # 不在 git 仓库

    trimmed="${cmd_n#"${cmd_n%%[![:space:]]*}"}"
    case "$trimmed" in
      "cd "*)
        trimmed=$(printf '%s' "$trimmed" | sed -E 's/^cd[[:space:]]+[^[:space:];&]+[[:space:]]*(&&|;)[[:space:]]*//')
        ;;
    esac

    target=""
    case "$trimmed" in
      "git checkout "*|"git switch "*)
        first_cmd=$(printf '%s' "$trimmed" | sed -E 's/[[:space:]]*(&&|;|\|).*$//')
        target=$(printf '%s' "$first_cmd" \
          | sed -E 's/^git (checkout|switch)[[:space:]]+//' \
          | tr ' ' '\n' \
          | grep -vE '^-' \
          | grep -vE '^$' \
          | head -1)
        ;;
      *) exit 0 ;;
    esac

    # 目标参数像文件路径 → 不是切分支,放行
    if printf '%s' "$target" | grep -qE '^\./|\.[a-zA-Z][a-zA-Z0-9]{0,5}$'; then
      exit 0
    fi
    if [ -z "$target" ]; then
      case "$trimmed" in
        "git checkout "*|"git switch "*)
          ctx="⚠️ 检测到 git checkout/switch 但 hook 没识别 target 分支(可能复杂 cmd 格式)。
当前分支: ${cur}。按 ~/.claude/MEMORY_SPEC.md § 四+九 自决策:
1) 切换前是否要追加本次改动进 ${cur} 的 memory(若有)
2) 自己看 target 是什么,有无对应 memory 可 Read"
          jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
          ;;
      esac
      exit 0
    fi
    [ "$target" = "$cur" ] && exit 0

    # 收档当前 + 启档目标
    ctx="🔄 切分支 ${cur} → ${target}"

    cur_mem=$(lookup_branch_memory "$cur")
    if [ -n "$cur_mem" ]; then
      ctx="$ctx\n\n【收档 · 当前分支 ${cur}】memory: ${cur_mem}\n切换前请把本次会话以来的关键改动/状态/思路/进度补进该文件(只记主要的)。"
    else
      if ! is_protected "$cur"; then
        ctx="$ctx\n\n【收档 · 当前分支 ${cur}】⚠️ 无 memory 文件,若是重要分支建议先建一份(只记主要的)。"
      fi
    fi

    tgt_mem=$(lookup_branch_memory "$target")
    if [ -n "$tgt_mem" ]; then
      tgt_content=$(cat "$tgt_mem" 2>/dev/null | head -200)
      ctx="$ctx\n\n【启档 · 目标分支 ${target}】memory: ${tgt_mem}\n\n--- 内容(前 200 行)---\n${tgt_content}"
    else
      ctx="$ctx\n\n【启档 · 目标分支 ${target}】暂无 memory 文件;若是已有工作的分支,切完后读读 INDEX.md。"
    fi

    jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
    exit 0
    ;;
esac
exit 0

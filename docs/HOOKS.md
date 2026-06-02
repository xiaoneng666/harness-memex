# Hooks 详解

5 个 hook,event listener 模式。装到 `~/.claude/hooks/` 后,通过 `~/.claude/settings.json` 注册到 Claude Code 的 PreToolUse/PostToolUse 事件。

## hook 通用约定

- 所有 hook 都是 bash 脚本
- 输入:Claude Code 的工具调用 JSON 从 stdin 传入
- 输出:hookSpecificOutput.additionalContext 注入 LLM 上下文(可选)
- 失败永远 `exit 0`(silent degrade)— 除了保护分支拦截故意 `exit 2`(block)
- 错误同时到 stderr(可观测)+ ⚠️ ctx(LLM 接管)

---

## 1. session-bootstrap.sh

**触发**:`PreToolUse` matcher=`*`(任何工具首次调用)

**作用**:
- 新 cwd 第一次启动 Claude → 自动建 memory 骨架(三层目录 + 空 jsonl + INDEX 模板)
- 检测 `.md` 数 vs jsonl 行数漂移 → 自动增量 rebuild_index
- 同 session 只跑一次(`/tmp/harness-memex-bootstrap-<sid>` 去重)

**注入 ctx**:
- bootstrap 成功:`✨ 本 cwd memory 工作面已初始化`
- 漂移 reindex:`🔄 检测到索引漂移,已自动 rebuild`
- rebuild 失败:`⚠️ rebuild_index 失败(exit=N),fallback 手动跑`

---

## 2. pre-read-memory-bump.sh

**触发**:`PreToolUse` matcher=`Read`

**作用**:
- Claude Read `memory/**/*.md` 文件时,更新 `_index/meta.jsonl` 中对应条目的 `last_access`
- 防 LRU 误杀 read-heavy 的 feedback / reference(它们不被 Write,但被频繁 Read)

**实现**:
```bash
jq -c --arg p "$rel" --arg now "$now" \
    'if .path==$p then .last_access=$now else . end' \
    "$idx" > "$tmp" && mv "$tmp" "$idx"
```

**注入 ctx**:无(静默更新)

---

## 3. check-protected-branch.sh

**触发**:`PreToolUse` matcher=`Bash`

**作用**(3 种):

### 3a. git commit / git push
- 如果分支 ∈ `MEMEX_PROTECTED_BRANCHES`(默认 `main master develop production`)→ **exit 2 拦截**
- 功能分支 → 注入"本分支 memory 路径 + 提示自决策是否写 memory"

### 3b. git checkout / git switch
- 不拦
- 收档:列出**当前分支** memory 路径,让 LLM 提醒用户补本次改动
- 启档:把**目标分支** memory 内容前 200 行直接注入 ctx

### 3c. 其它 git / 非 git
- 静默放行

**shell cmd 解析**(只支持两种最简):
- `cd <path> && git ...` → resolve_git_dir 取 path
- `git -C <path> ...` → resolve_git_dir 取 path
- 其它复杂格式(pushd / subshell / 别名)→ resolve_git_dir 返回 `.`(Claude cwd),git rev-parse 上溯找 .git

**自定义保护分支**:
```bash
export MEMEX_PROTECTED_BRANCHES="main master develop staging production release"
```

**兜底 ctx**:
- commit/push 拿不到分支 → `⚠️ 没识别 git 分支,你自己确认是否保护分支`
- checkout/switch 解析 target 失败 → `⚠️ 没识别 target,你自己看 memory`

---

## 4. pre-edit-branch-notice.sh

**触发**:`PreToolUse` matcher=`Edit|Write|MultiEdit`

**作用**:
- 每个 session 在每个分支**首次** Edit/Write 文件时,把"当前分支 + 对应 memory 路径"注入 ctx
- 让 LLM 写代码前意识到分支,防写错分支

**去重**:`/tmp/harness-memex-br-<sid>-<slug>` 标记,同 session 同分支只提示一次

**git 仓库识别**:
- 从 `tool_input.file_path` 反推:`dirname $fpath` 当 git -C 路径
- git 自动上溯找 .git,支持 monorepo 子项目

**兜底 ctx**:
- file 在 `*/project/* | */code/* | */workspace/*` 但 git 不识别 → `⚠️ 没识别分支,你自己拿`

---

## 5. post-write-memory-sync.sh

**触发**:`PostToolUse` matcher=`Write|Edit|MultiEdit`

**作用**:
- Claude 写 `memory/**/*.md` 后(新 file 或改 file)→ 自动跑 `rebuild_index.py` 增量同步进 jsonl
- 保留旧条目的 `last_access` / `decay` / `status`
- 新 file 默认 `last_access=mtime, decay=0, status=active`

**排除**:INDEX.md / MEMORY.md / `_index/*` 不处理(它们不入 jsonl)

**兜底 ctx**:
- rebuild_index 失败 → `⚠️ post-write-memory-sync 失败,fallback 手动跑 rebuild_index.py`

---

## settings.json 注册片段

`install.sh` 用 `merge_settings.py` 合并 `templates/memex-hooks.json` 到 `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "*",                   "hooks": [{"type":"command","command":"bash ~/.claude/hooks/session-bootstrap.sh"}] },
      { "matcher": "Read",                "hooks": [{"type":"command","command":"bash ~/.claude/hooks/pre-read-memory-bump.sh"}] },
      { "matcher": "Bash",                "hooks": [{"type":"command","command":"bash ~/.claude/hooks/check-protected-branch.sh"}] },
      { "matcher": "Edit|Write|MultiEdit","hooks": [{"type":"command","command":"bash ~/.claude/hooks/pre-edit-branch-notice.sh"}] }
    ],
    "PostToolUse": [
      { "matcher": "Write|Edit|MultiEdit","hooks": [{"type":"command","command":"bash ~/.claude/hooks/post-write-memory-sync.sh"}] }
    ]
  }
}
```

## 调试 hook

```bash
# 临时禁用所有 memex hook
mv ~/.claude/hooks ~/.claude/hooks.disabled

# 单独测某个 hook(模拟 stdin)
echo '{"tool_input":{"command":"git checkout feat/X"}}' | bash ~/.claude/hooks/check-protected-branch.sh

# 看 hook stderr
# Claude Code 把 hook stderr 显示在 Bash 工具的 error 输出里
```

## 加新 hook

1. 在 `hooks/` 加 `<your-hook>.sh`(参考现有结构)
2. 在 `templates/memex-hooks.json` 加注册片段
3. 跑 `install.sh` 或手动合并到 `~/.claude/settings.json`
4. 在 `docs/HOOKS.md` 加说明
5. 提 PR

# Hooks 详解(v0.2)

7 个 hook,event listener 模式。装到 `~/.claude/hooks/` 后,通过 `~/.claude/settings.json` 注册到 Claude Code 的 `SessionStart` / `PreToolUse` / `PostToolUse` 事件。

## hook 通用约定

- 所有 hook 都是 bash 脚本
- 输入:Claude Code 的工具调用 JSON 从 stdin 传入
- 输出:`hookSpecificOutput.additionalContext` 注入 LLM 上下文(可选)
- 失败永远 `exit 0`(silent degrade) — 除了保护分支拦截故意 `exit 2`(block)
- 错误同时到 stderr(可观测)+ ⚠️ ctx(LLM 接管)

---

## 1. session-bootstrap.sh

**触发**:`PreToolUse` matcher=`*`(任何工具首次调用)

**作用**(v0.2.1):
- 调 `~/.claude/bin/update_memex_bridge.py`,做以下 5 件:
  - 确保 `~/.claude/memex/` 骨架(`_index/`、`global/`、`projects/`)
  - 扫 cwd 子目录(深度 ≤ 4)所有 `.git` → derive_project_key → 建项目骨架
  - upsert `projects.jsonl`
  - 在 `~/.claude/projects/<cwd-slug>/memory/MEMORY.md` 末尾幂等替换 `<!-- memex:bridge -->` 区块。**@import 范围**:`global/INDEX.md` + cwd-discovered 有内容项目 + `last_access < MEMEX_RECENT_DAYS`(默认 30d)有内容项目
  - 在 `~/.claude/CLAUDE.md` 末尾幂等维护 `<!-- memex:catalog -->` 块,@import 全局 INDEX(用户级,任何 cwd 都加载)— 永久 opt-out:`touch ~/.claude/memex/.no_catalog` 或 `export MEMEX_NO_CATALOG=1`
- 新项目识别后自动跑 `rebuild_index.py` + `update_index_md.py`
- 同 session 同 cwd 只跑一次(`/tmp/memex-bootstrap-<sid>-<cwd_slug>` 去重)

**注入 ctx**:
- bootstrap 成功:`✨ Memex v0.2.1 初始化完成 (~/.claude/memex/)。识别到本 cwd 下 N 个 git repo。INDEX 已搭桥...`
- 新发现 project:`✨ Memex 识别到 N 个新 project 并已建骨架 + 挂 @import`

---

## 2. pre-read-memory-bump.sh

**触发**:`PreToolUse` matcher=`Read`

**作用**:
- Claude Read `~/.claude/memex/**/*.md` 文件时,更新 `_index/meta.jsonl` 中对应条目的 `last_access`
- 防 LRU 误杀 read-heavy 的 feedback / reference(它们不被 Write,但被频繁 Read)
- 跳 `_index/*` 和 `INDEX.md`(自身是工具产物)

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

**作用**:
- 拦 `git commit` / `git push` 到保护分支(默认 `main master develop production`,可改 `MEMEX_PROTECTED_BRANCHES` env var)→ **exit 2 block**
- 功能分支 → 放行 + 注入"本分支 memory 路径 + 提示自决策是否写 memory"
- 其它 git / 非 git → 静默放行

**shell cmd 解析**(spec § 七 两种最简):
- `cd <path> && git ...` → resolve_git_dir 取 path
- `git -C <path> ...` → resolve_git_dir 取 path
- 其它复杂格式 → 返回 `.`(Claude cwd),git rev-parse 上溯找 .git

**自定义保护分支**:
```bash
export MEMEX_PROTECTED_BRANCHES="main master develop staging production release"
```

---

## 4. pre-edit-branch-notice.sh

**触发**:`PreToolUse` matcher=`Edit|Write|MultiEdit`

**作用**(v0.2.1):
- 每 session 每 `(project_key, branch)` 首次 Edit/Write 业务代码时,**塞 ctx 同时给两份路径**:
  - `project INDEX` 路径(项目共享层:overview / 项目 feedback / 项目 reference)
  - 本分支 memory 路径
- 反推流程:`file_path` → `dirname` → `git -C <dir> rev-parse --show-toplevel` → `derive_project_key.py` → `branches.jsonl` O(1) 查找
- 跳过 Write 自身 memex 文件 / spec / 模板
- **后台 lazy bridge**:跑 `update_memex_bridge.py --touch <key> --repo <path>` 异步 bump `projects.jsonl.last_access`(下次 session bootstrap 把本 project 加进 bridge)

**去重**:`/tmp/memex-pre-edit-<sid>-<project_key>-<branch_slug>` 标记,同 session 同 project 同分支只提示一次。

**保护分支**:在保护分支编辑 → 警告 `⚠️ 正在保护分支 [X] 编辑文件 — 一般不该直接改主干`。

---

## 5. post-checkout-handoff.sh

**触发**:`PostToolUse` matcher=`Bash`

**作用**(v0.2.1):
- Bash 执行成功且 cmd 是 `git checkout` / `git switch` → 塞 ctx 让 LLM **同回合并行发 3 个 tool call**:
  - `Read <project_index>`:项目共享层(overview / feedback / reference)— **总是**
  - `Write <from-memory>`:总结当前会话以来在 from 分支的关键改动
  - `Read <to-memory>`:加载 to 分支记忆(进度 / 决策 / 踩坑)
- 路径解析:`resolve_git_dir` → `derive_project_key` → `branches.jsonl[project_key, branch_slug]` O(1) 查找
- **后台 lazy bridge**:跑 `update_memex_bridge.py --touch <key> --repo <path>` 异步 bump `projects.jsonl.last_access`

**from / to 解析**:
```bash
to_branch=$(git -C "$git_dir" rev-parse --abbrev-ref HEAD)
from_branch=$(git -C "$git_dir" rev-parse --abbrev-ref '@{-1}')
```

`@{-1}` 是 git 内置的"前一个 HEAD",不依赖 reflog 解析。

**兜底**:`from` 是保护分支 → 不推荐建 from 收档;`to` 无 memory → 提示从已 Read 的项目 INDEX 看分支列表确认是否立档。

---

## 6. post-write-memory-sync.sh

**触发**:`PostToolUse` matcher=`Write|Edit|MultiEdit`

**作用**(v0.2):
- Claude 写 `~/.claude/memex/**/*.md` 后 → 自动跑 `rebuild_index.py` 全量重建 3 个 jsonl + 跑 `update_index_md.py` 刷新对应 INDEX.md
- 路径在 `projects/<key>/` 下 → 只刷该项目 INDEX
- 路径在 `global/` 下 → 只刷 global/INDEX
- 排除 INDEX.md / `_index/*`(自身是产物)

**兜底**:rebuild 失败 → `⚠️ post-write 失败 (exit=N),fallback: rebuild_index.py`

---

## 7. session-start-lru.sh

**触发**:`SessionStart` matcher=`*`(v0.2 新增,原 v0.1 是手动跑 lru_compact.py)

**作用**:
- 启动时调 `lru_compact.py --quiet --memex ~/.claude/memex` 拿候选数
- 有候选 → 塞 ctx 让 LLM 自决策是否当场压缩:
  ```
  🔄 Memex LRU 周扫(SessionStart 触发):
    · 待第 1 次压缩(30d+): N 条
    · 待第 2 次压缩(60d+): N 条
    ...
  要不要现在处理? 详细清单: python3 ~/.claude/bin/lru_compact.py
  ```
- 无候选 → 静默 exit 0

**性能**:`lru_compact.py --quiet` 在 N=1000 时 < 100ms,SessionStart 时长可控。

---

## settings.json 注册片段

`install.sh` 用 `merge_settings.py` 合并 `templates/memex-hooks.json` 到 `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      { "matcher": "*",                   "hooks": [{"type":"command","command":"bash \"$HOME/.claude/hooks/session-start-lru.sh\""}] }
    ],
    "PreToolUse": [
      { "matcher": "*",                   "hooks": [{"type":"command","command":"bash \"$HOME/.claude/hooks/session-bootstrap.sh\""}] },
      { "matcher": "Read",                "hooks": [{"type":"command","command":"bash \"$HOME/.claude/hooks/pre-read-memory-bump.sh\""}] },
      { "matcher": "Bash",                "hooks": [{"type":"command","command":"bash \"$HOME/.claude/hooks/check-protected-branch.sh\""}] },
      { "matcher": "Edit|Write|MultiEdit","hooks": [{"type":"command","command":"bash \"$HOME/.claude/hooks/pre-edit-branch-notice.sh\""}] }
    ],
    "PostToolUse": [
      { "matcher": "Bash",                "hooks": [{"type":"command","command":"bash \"$HOME/.claude/hooks/post-checkout-handoff.sh\""}] },
      { "matcher": "Write|Edit|MultiEdit","hooks": [{"type":"command","command":"bash \"$HOME/.claude/hooks/post-write-memory-sync.sh\""}] }
    ]
  }
}
```

## 调试 hook

**关键**:macOS bash 可能启了 `xpg_echo`,会把字面 `\n` 解成真换行,破坏 JSON 测试输出。**用 `printf '%s'` 替代 `echo`**:

```bash
# 临时禁用所有 memex hook
mv ~/.claude/hooks ~/.claude/hooks.disabled

# 单独测某个 hook(用 printf,不用 echo!)
printf '%s' '{"tool_input":{"command":"git -C ~/repo checkout feat/X"},"tool_response":{"exitCode":0}}' \
  | bash ~/.claude/hooks/post-checkout-handoff.sh \
  | jq -r '.hookSpecificOutput.additionalContext'

# 看 hook stderr
# Claude Code 把 hook stderr 显示在 Bash 工具的 error 输出里
```

## 加新 hook

1. 在 `hooks/` 加 `<your-hook>.sh`(参考现有结构)
2. 在 `templates/memex-hooks.json` 加注册片段
3. 跑 `install.sh` 或手动合并到 `~/.claude/settings.json`
4. 在 `docs/HOOKS.md` 加说明
5. 提 PR
